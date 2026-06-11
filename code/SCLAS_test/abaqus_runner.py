#!/usr/bin/env python3
"""
SCLAS Abaqus backend runner template.

Run with normal Python for a fast placeholder result:
    python abaqus_runner.py input_data.json

Run inside Abaqus/CAE to convert the GUI mesh contract into Abaqus files:
    abaqus cae noGUI=abaqus_runner.py -- input_data.json

The Abaqus path creates a mesh scaffold from the GUI geometry/mesh settings,
writes a CAE database and an input deck, then still writes the lightweight
result CSV so the GUI can load something immediately.
"""

import csv
import json
import math
import os
import re
import sys
from datetime import datetime


def path_text(path):
    return os.fspath(path) if hasattr(os, "fspath") else str(path)


def timestamp_seconds():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_payload(path):
    with open(path_text(path), "r") as f:
        return json.load(f)


def write_json(path, data):
    with open(path_text(path), "w") as f:
        json.dump(data, f, indent=4)


def write_result_csv(path, curvature, moment_kn_m):
    with open(path_text(path), "w") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["curvature_1_per_m", "moment_kn_m"])
        for k, m in zip(curvature, moment_kn_m):
            writer.writerow(["{0:.12g}".format(k), "{0:.12g}".format(m)])


def hysteresis_loss(curvature, moment_kn_m):
    if len(curvature) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(curvature)):
        total += 0.5 * (moment_kn_m[i] + moment_kn_m[i - 1]) * (curvature[i] - curvature[i - 1])
    return abs(total)


def enabled_assessment_names(payload):
    enabled = payload.get("study_scope", {}).get("enabled_assessments", {})
    return [key for key, is_enabled in enabled.items() if is_enabled]


def build_backend_readiness(payload, source, mesh_status):
    enabled = set(enabled_assessment_names(payload))
    mesh_state = mesh_status.get("status", "not_attempted") if isinstance(mesh_status, dict) else "not_attempted"
    real_abaqus_mesh = mesh_state == "abaqus_mesh_created"
    return {
        "bending_stick_slip": {
            "requested": "bending_stick_slip" in enabled,
            "status": "placeholder_curve",
            "next_step": "replace proxy curve with Abaqus cyclic bending solve and ODB extraction",
        },
        "contact_friction": {
            "requested": bool(enabled),
            "status": "mesh_scaffold_only" if real_abaqus_mesh else "manifest_only",
            "next_step": "define normal/tangential contact pairs and friction sensitivity sweeps",
        },
        "torsion": {
            "requested": "torsion" in enabled,
            "status": "proxy_metric_only",
            "next_step": "add twist-controlled Abaqus load case and report torsional stiffness",
        },
        "tension_bending_coupling": {
            "requested": "tension_bending_coupling" in enabled,
            "status": "proxy_metric_only",
            "next_step": "add axial preload sweep before cyclic bending",
        },
        "compression_bird_caging": {
            "requested": "compression_bird_caging" in enabled,
            "status": "proxy_metric_only",
            "next_step": "add radial compression or pressure sweep and instability indicator",
        },
        "pressure_effect": {
            "requested": "pressure_effect" in enabled,
            "status": "proxy_metric_only",
            "next_step": "calibrate pressure-dependent contact and stiffness softening",
        },
        "source": source,
    }


def parse_input_path(argv):
    candidates = [arg for arg in argv[1:] if arg != "--" and not arg.startswith("-")]
    return candidates[-1] if candidates else "input_data.json"


def safe_name(text, limit=38):
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    return (cleaned or "SCLAS")[:limit]


def abaqus_available():
    try:
        import abaqus  # noqa: F401
        import abaqusConstants  # noqa: F401
        return True
    except Exception:
        return False


def write_mesh_manifest(path, payload, abaqus_created, files=None, error=""):
    geometry = payload.get("derived_geometry_mm", {})
    armour = payload.get("armour", {})
    analysis = payload.get("analysis_conditions", {})
    mesh_cfg = payload.get("mesh", {})
    numerical_model = payload.get("numerical_model", {})
    files = files or []
    manifest = {
        "status": "abaqus_mesh_created" if abaqus_created else "mesh_request_only",
        "created_at": timestamp_seconds(),
        "abaqus_files": files,
        "error": error,
        "mesh_settings_from_gui": {
            "requested_element_type": mesh_cfg.get("requested_element_type", "C3D8R"),
            "model_strategy": mesh_cfg.get("model_strategy", "periodic_homogenized_cell"),
            "armour_model": mesh_cfg.get("armour_model", "beam_with_contact_surface"),
            "axial_divisions": int(mesh_cfg.get("axial_divisions", 40)),
            "core_circumferential_divisions": int(mesh_cfg.get("core_circumferential_divisions", 24)),
            "armour_circumferential_divisions": int(mesh_cfg.get("armour_circumferential_divisions", 8)),
            "contact_regularization_beta": float(analysis.get("contact_regularization_beta", 0.001)),
        },
        "contact_interfaces": numerical_model.get("contact_interfaces", []),
        "contact_interface_defaults": numerical_model.get("contact_interface_defaults", {
            "normal": "penalty_or_augmented_lagrange",
            "tangential": "regularized_coulomb",
            "friction_coefficient": analysis.get("friction_coefficient"),
            "residual_contact_pressure_mpa": analysis.get("residual_contact_pressure_mpa"),
            "regularization_beta": analysis.get("contact_regularization_beta"),
        }),
        "components": [
            {
                "name": "three_core_equivalent_solids",
                "count": 3,
                "type": "solid_cylinder",
                "radius_mm": geometry.get("core_outer_radius_mm"),
                "center_radius_mm": geometry.get("core_center_radius_mm"),
                "element_hint": mesh_cfg.get("requested_element_type", "C3D8R"),
            },
            {
                "name": "inner_armour_helical_beams",
                "count": armour.get("inner_wire_count"),
                "type": "beam_helix",
                "wire_radius_mm": armour.get("inner_wire_radius_mm"),
                "center_radius_mm": geometry.get("inner_armour_center_radius_mm"),
                "lay_angle_deg": armour.get("inner_lay_angle_deg"),
                "element_hint": "B31",
            },
            {
                "name": "outer_armour_helical_beams",
                "count": armour.get("outer_wire_count"),
                "type": "beam_helix",
                "wire_radius_mm": armour.get("outer_wire_radius_mm"),
                "center_radius_mm": geometry.get("outer_armour_center_radius_mm"),
                "lay_angle_deg": armour.get("outer_lay_angle_deg"),
                "element_hint": "B31",
            },
            {
                "name": "outer_sheath_equivalent_solid",
                "count": 1,
                "type": "solid_cylinder",
                "radius_mm": geometry.get("outer_sheath_outer_radius_mm"),
                "element_hint": mesh_cfg.get("requested_element_type", "C3D8R"),
            },
        ],
        "limitations": [
            "This is an Abaqus mesh scaffold, not the final contact-calibrated bending model.",
            "Solids are equivalent visual/mesh bodies; layer subtraction and full contact pairs remain backend work.",
            "Helical armour wires are represented as B31 beam paths unless the backend replaces them with solid wires.",
        ],
    }
    write_json(path, manifest)
    return manifest


def material_by_name(payload, needle, fallback_e=1.0, fallback_nu=0.3, fallback_density=1000.0):
    for item in payload.get("materials", []):
        if needle.lower() in item.get("name", "").lower():
            return {
                "name": safe_name(item.get("name", needle)),
                "elastic_modulus_mpa": float(item.get("elastic_modulus_GPa", fallback_e)) * 1000.0,
                "poisson_ratio": float(item.get("poisson_ratio", fallback_nu)),
                "density": float(item.get("density_kg_m3", fallback_density)),
            }
    return {
        "name": safe_name(needle),
        "elastic_modulus_mpa": fallback_e * 1000.0,
        "poisson_ratio": fallback_nu,
        "density": fallback_density,
    }


def build_abaqus_mesh_model(payload, job_dir):
    """Create a CAE mesh scaffold when this script is executed by Abaqus/CAE."""
    from abaqus import mdb
    from abaqusConstants import (
        ANALYSIS,
        B31,
        CARTESIAN,
        DEFORMABLE_BODY,
        DURING_ANALYSIS,
        IMPRINT,
        N1_COSINES,
        OFF,
        ON,
        STANDARD,
        THREE_D,
    )
    from mesh import ElemType

    geometry = payload["derived_geometry_mm"]
    armour = payload["armour"]
    analysis = payload["analysis_conditions"]
    mesh_cfg = payload["mesh"]

    length = float(analysis.get("effective_length_mm", 234.2))
    z_elem = max(2, int(mesh_cfg.get("axial_divisions", 40)))
    core_circ = max(4, int(mesh_cfg.get("core_circumferential_divisions", 24)))
    armour_circ = max(4, int(mesh_cfg.get("armour_circumferential_divisions", 8)))
    requested_elem = str(mesh_cfg.get("requested_element_type", "C3D8R")).upper()
    model_name = safe_name(payload.get("metadata", {}).get("job_id", "SCLAS_CableMesh"), 32)
    job_name = safe_name(model_name + "_mesh", 32)

    if "Model-1" in mdb.models and len(mdb.models) == 1:
        del mdb.models["Model-1"]
    if model_name in mdb.models:
        del mdb.models[model_name]
    model = mdb.Model(name=model_name)
    assembly = model.rootAssembly
    assembly.DatumCsysByDefault(CARTESIAN)

    def make_material_section(section_name, mat_info):
        mat_name = safe_name(mat_info["name"] + "_mat")
        material = model.Material(name=mat_name)
        material.Elastic(table=((mat_info["elastic_modulus_mpa"], mat_info["poisson_ratio"]),))
        material.Density(table=((mat_info["density"],),))
        model.HomogeneousSolidSection(name=section_name, material=mat_name, thickness=None)
        return section_name

    steel = material_by_name(payload, "Armour", 210.0, 0.30, 7850.0)
    copper = material_by_name(payload, "Copper", 108.0, 0.33, 8960.0)
    sheath = material_by_name(payload, "Sheath", 1.4, 0.45, 1300.0)
    core_section = make_material_section("CoreSolidSection", copper)
    sheath_section = make_material_section("OuterSheathSection", sheath)

    steel_mat = model.Material(name="ArmourSteel_mat")
    steel_mat.Elastic(table=((steel["elastic_modulus_mpa"], steel["poisson_ratio"]),))
    steel_mat.Density(table=((steel["density"],),))

    def elem_code_for_solid():
        import abaqusConstants as ac

        return getattr(ac, requested_elem, ac.C3D8R)

    def create_solid_cylinder(name, radius, section_name, seed_circ, offset=(0.0, 0.0, 0.0)):
        sketch = model.ConstrainedSketch(name=name + "_sketch", sheetSize=max(10.0, radius * 4.0))
        sketch.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(radius, 0.0))
        part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
        part.BaseSolidExtrude(sketch=sketch, depth=length)
        del model.sketches[sketch.name]
        region = part.Set(cells=part.cells[:], name="AllCells")
        part.SectionAssignment(region=region, sectionName=section_name)
        size_axial = length / float(z_elem)
        size_circ = max(0.1, 2.0 * math.pi * radius / float(seed_circ))
        part.seedPart(size=max(0.1, min(size_axial, size_circ)), deviationFactor=0.1, minSizeFactor=0.1)
        part.setElementType(regions=(part.cells[:],), elemTypes=(ElemType(elemCode=elem_code_for_solid(), elemLibrary=STANDARD),))
        part.generateMesh()
        inst = assembly.Instance(name=name + "_1", part=part, dependent=ON)
        inst.translate(vector=(offset[0], offset[1], -0.5 * length + offset[2]))
        return part

    def create_armour_layer(name, wire_radius, center_radius, count, lay_angle_deg, hand):
        profile_name = name + "_profile"
        section_name = name + "_BeamSection"
        model.CircularProfile(name=profile_name, r=wire_radius)
        model.BeamSection(
            name=section_name,
            integration=DURING_ANALYSIS,
            profile=profile_name,
            material="ArmourSteel_mat",
            poissonRatio=steel["poisson_ratio"],
        )
        part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
        segments = max(16, z_elem)
        angle_rad = math.radians(float(lay_angle_deg))
        angular_rate = hand * math.tan(angle_rad) / max(center_radius, 1.0e-6)
        wire_segments = []
        for i in range(int(count)):
            theta0 = 2.0 * math.pi * i / float(count)
            points = []
            for j in range(segments + 1):
                z = -0.5 * length + length * j / float(segments)
                theta = theta0 + angular_rate * (z + 0.5 * length)
                points.append((center_radius * math.cos(theta), center_radius * math.sin(theta), z))
            wire_segments.extend((points[j], points[j + 1]) for j in range(segments))
        part.WirePolyLine(points=tuple(wire_segments), mergeType=IMPRINT, meshable=ON)
        region = part.Set(edges=part.edges[:], name="AllEdges")
        part.SectionAssignment(region=region, sectionName=section_name)
        part.assignBeamSectionOrientation(region=region, method=N1_COSINES, n1=(0.0, 0.0, -1.0))
        part.seedPart(size=max(0.1, length / float(z_elem)), deviationFactor=0.1, minSizeFactor=0.1)
        part.setElementType(regions=(part.edges[:],), elemTypes=(ElemType(elemCode=B31, elemLibrary=STANDARD),))
        part.generateMesh()
        assembly.Instance(name=name + "_1", part=part, dependent=ON)
        return part

    core_radius = float(geometry["core_outer_radius_mm"])
    core_center = float(geometry["core_center_radius_mm"])
    for i in range(3):
        angle = math.radians(120.0 * i)
        create_solid_cylinder(
            "Core_%d" % (i + 1),
            core_radius,
            core_section,
            core_circ,
            offset=(core_center * math.cos(angle), core_center * math.sin(angle), 0.0),
        )

    create_solid_cylinder(
        "OuterSheathEquivalent",
        float(geometry["outer_sheath_outer_radius_mm"]),
        sheath_section,
        core_circ,
    )

    create_armour_layer(
        "InnerArmourHelix",
        float(armour["inner_wire_radius_mm"]),
        float(geometry["inner_armour_center_radius_mm"]),
        int(armour["inner_wire_count"]),
        float(armour["inner_lay_angle_deg"]),
        hand=1.0,
    )
    create_armour_layer(
        "OuterArmourHelix",
        float(armour["outer_wire_radius_mm"]),
        float(geometry["outer_armour_center_radius_mm"]),
        int(armour["outer_wire_count"]),
        float(armour["outer_lay_angle_deg"]),
        hand=-1.0,
    )

    model.StaticStep(name="MeshOnlyStep", previous="Initial")
    old_cwd = os.getcwd()
    os.chdir(str(job_dir))
    try:
        mdb.Job(name=job_name, model=model_name, type=ANALYSIS, description="SCLAS GUI generated mesh scaffold")
        mdb.jobs[job_name].writeInput(consistencyChecking=OFF)
        cae_path = os.path.join(path_text(job_dir), "sclas_mesh_model.cae")
        mdb.saveAs(pathName=str(cae_path))
    finally:
        os.chdir(old_cwd)

    inp_path = os.path.join(path_text(job_dir), job_name + ".inp")
    files = [os.path.basename(path) for path in [cae_path, inp_path] if os.path.exists(path)]
    return {
        "job_name": job_name,
        "model_name": model_name,
        "files": files,
        "node_element_note": "See generated .inp/.cae for Abaqus node and element counts.",
    }


def write_summary(path, source, payload, curvature, moment_kn_m, derived, mesh_status=None):
    mesh_status = mesh_status or {}
    max_abs = max([abs(x) for x in moment_kn_m] or [0.0])
    min_moment = min(moment_kn_m or [0.0])
    max_moment = max(moment_kn_m or [0.0])
    study_scope = payload.get("study_scope", {})
    summary = {
        "source": source,
        "status": "completed",
        "max_abs_moment_kn_m": max_abs,
        "min_moment_kn_m": min_moment,
        "max_moment_kn_m": max_moment,
        "hysteresis_loss_kj_per_m_proxy": hysteresis_loss(curvature, moment_kn_m),
        "num_points": len(moment_kn_m),
        "study_scope": study_scope,
        "mesh_status": mesh_status,
        "result_contract": {
            "csv_file": "result_data.csv",
            "required_columns": ["curvature_1_per_m", "moment_kn_m"],
            "summary_file": "result_summary.json",
            "primary_result": "bending moment-curvature loop",
        },
        "backend_readiness": build_backend_readiness(payload, source, mesh_status),
        "enabled_assessments": enabled_assessment_names(payload),
        "derived_placeholder_metrics": derived,
        "recommended_next_steps": [
            "open the generated .inp/.cae scaffold in Abaqus/CAE",
            "add contact/friction definitions and verify convergence",
            "replace the placeholder curve with ODB-extracted moment-curvature data",
            "promote proxy torsion, pressure, and bird-caging metrics to Abaqus load cases",
        ],
        "computed_at": timestamp_seconds(),
        "note": "Placeholder response curve. Abaqus mesh scaffold is generated when run inside Abaqus/CAE.",
    }
    write_json(path, summary)


def run_placeholder_solver(payload):
    if "analysis_conditions" in payload:
        analysis = payload["analysis_conditions"]
        equivalent = payload["equivalent_properties"]
        steps = int(analysis.get("solver_steps", 500))
        cycles = int(analysis.get("loading_cycles", 2))
        k_max = float(analysis["max_curvature_1_per_m"])
        twist_max = float(analysis.get("max_twist_rad_per_m", 0.05))
        axial_strain = float(analysis.get("max_axial_strain", 0.002))
        radial_compression = float(analysis.get("radial_compression_ratio", 0.015))
        residual_pressure = float(analysis.get("residual_contact_pressure_mpa", 0.3))
        beta = float(analysis.get("contact_regularization_beta", 0.001))
        friction = float(analysis["friction_coefficient"])
        pressure = float(analysis["hydrostatic_pressure_mpa"])
        ei_init = float(equivalent["core_equivalent_EI_N_m2"])
    else:
        steps = int(payload.get("solver_steps", 500))
        cycles = int(payload.get("cycles", 2))
        k_max = float(payload.get("curvature", 0.08))
        twist_max = float(payload.get("twist", 0.05))
        axial_strain = float(payload.get("axial_strain", 0.002))
        radial_compression = float(payload.get("radial_compression", 0.015))
        residual_pressure = float(payload.get("residual_contact_pressure", 0.3))
        beta = float(payload.get("contact_regularization_beta", 0.001))
        friction = float(payload.get("friction_coeff", payload.get("friction", 0.22)))
        pressure = float(payload.get("pressure", 40.0))
        ei_init = float(payload.get("core_equivalent_EI", 65.0))

    normal_force_factor = 1.0 + residual_pressure / 0.3 if residual_pressure > 0.0 else 1.0
    pressure_softening_factor = max(0.0, 1.0 - pressure / 250.0)
    ei_stick = ei_init * (1.0 + 0.15 * friction * normal_force_factor)
    ei_slip = ei_init * (0.28 + 0.10 * friction) * pressure_softening_factor
    m_yield_n_m = (ei_stick - ei_slip) * k_max * 0.45 * (1.0 + 2.2 * friction + residual_pressure / 0.3)

    curvature = []
    moment_kn_m = []
    z = 0.0
    previous_k = 0.0
    total_angle = 2.0 * math.pi * max(cycles, 1)

    for i in range(max(steps, 2)):
        t = total_angle * i / (max(steps, 2) - 1)
        k = k_max * math.sin(t)
        dk = k - previous_k
        sign = 1.0 if dk >= 0.0 else -1.0
        z += (1.0 - 0.55 * sign * z - 0.45 * abs(z)) * dk
        transition_sharpness = max(2.0, min(30.0, 0.012 / max(beta, 1.0e-6)))
        m_n_m = ei_slip * k + m_yield_n_m * math.tanh(transition_sharpness * z)
        curvature.append(k)
        moment_kn_m.append(m_n_m / 1000.0)
        previous_k = k

    axial_stiffness_proxy = max(ei_init * 42.0, 1.0)
    torsion_stiffness_proxy = ei_init * (0.18 + 0.04 * abs(twist_max))
    axial_torsion_coupling_proxy = axial_stiffness_proxy * 0.03 * math.sin(math.atan2(twist_max, 1.0))
    compression_softening = max(0.0, 1.0 - 0.25 * radial_compression - pressure / 400.0)
    derived = {
        "bending_stiffness_initial_N_m2": ei_init,
        "bending_stiffness_stick_proxy_N_m2": ei_stick,
        "bending_stiffness_slip_N_m2": ei_slip,
        "normal_force_factor_proxy": normal_force_factor,
        "contact_regularization_beta": beta,
        "axial_torsional_stiffness_matrix_proxy": {
            "EA_N": axial_stiffness_proxy * compression_softening,
            "GJ_N_m2": torsion_stiffness_proxy * compression_softening,
            "K_axial_torsion_N_m": axial_torsion_coupling_proxy,
            "K_torsion_axial_N_m": axial_torsion_coupling_proxy,
        },
        "torsion_proxy_N_m2": torsion_stiffness_proxy,
        "tension_bending_coupling_index": axial_strain * (1.0 + 1.5 * friction),
        "bird_caging_risk_index": radial_compression * (1.0 + pressure / 100.0),
        "pressure_softening_factor": pressure_softening_factor,
        "compression_softening_factor": compression_softening,
        "calibration_targets": [
            "slip-zone bending stiffness",
            "dissipated hysteresis energy",
            "stick-to-slip transition curvature",
        ],
    }
    return curvature, moment_kn_m, derived


def main(argv):
    input_path = parse_input_path(argv)
    if not os.path.exists(input_path):
        sys.stderr.write("input JSON not found: {0}\n".format(input_path))
        return 2

    payload = load_payload(input_path)
    job_dir = os.path.dirname(os.path.abspath(input_path))

    mesh_status = {"status": "not_attempted"}
    if abaqus_available():
        try:
            mesh_status = build_abaqus_mesh_model(payload, job_dir)
            write_mesh_manifest(
                os.path.join(job_dir, "abaqus_mesh_manifest.json"),
                payload,
                abaqus_created=True,
                files=mesh_status.get("files", []),
            )
            print("Wrote Abaqus mesh scaffold: {0}".format(", ".join(mesh_status.get("files", []))))
        except Exception as exc:
            mesh_status = {"status": "abaqus_mesh_failed", "error": str(exc)}
            write_mesh_manifest(os.path.join(job_dir, "abaqus_mesh_manifest.json"), payload, abaqus_created=False, error=str(exc))
            sys.stderr.write("Abaqus mesh scaffold failed: {0}\n".format(exc))
    else:
        write_mesh_manifest(os.path.join(job_dir, "abaqus_mesh_manifest.json"), payload, abaqus_created=False)
        mesh_status = {"status": "abaqus_api_not_available", "manifest": "abaqus_mesh_manifest.json"}
        print("Abaqus API not available; wrote abaqus_mesh_manifest.json only.")

    curvature, moment_kn_m, derived = run_placeholder_solver(payload)
    result_csv = os.path.join(job_dir, "result_data.csv")
    write_result_csv(result_csv, curvature, moment_kn_m)
    write_summary(os.path.join(job_dir, "result_summary.json"), "SCLAS_ABAQUS_MESH_BRIDGE", payload, curvature, moment_kn_m, derived, mesh_status)
    print("Wrote {0}".format(result_csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
