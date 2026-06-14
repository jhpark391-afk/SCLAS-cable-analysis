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
import traceback
from datetime import datetime


def path_text(path):
    return os.fspath(path) if hasattr(os, "fspath") else str(path)


def timestamp_seconds():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_payload(path):
    with open(path_text(path), "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    return json.loads(text)


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


def bool_from_payload(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def abaqus_available():
    try:
        import abaqus  # noqa: F401
        import abaqusConstants  # noqa: F401
        return True
    except Exception:
        return False


def contact_defaults_from_payload(payload):
    analysis = payload.get("analysis_conditions", {})
    numerical_model = payload.get("numerical_model", {})
    defaults = numerical_model.get("contact_interface_defaults", {})
    return {
        "normal": defaults.get("normal", "penalty_or_augmented_lagrange"),
        "tangential": defaults.get("tangential", "regularized_coulomb"),
        "friction_coefficient": defaults.get("friction_coefficient", analysis.get("friction_coefficient")),
        "residual_contact_pressure_mpa": defaults.get("residual_contact_pressure_mpa", analysis.get("residual_contact_pressure_mpa")),
        "regularization_beta": defaults.get("regularization_beta", analysis.get("contact_regularization_beta")),
    }


def contact_region_map():
    return {
        "inner_armour_helical_beams_or_surfaces": {
            "assembly_surface": "InnerArmourHelix_ContactSurface",
            "assembly_edge_set": "InnerArmourHelix_ContactEdges",
            "component": "InnerArmourHelix",
            "surface_kind": "beam_line",
        },
        "outer_armour_helical_beams_or_surfaces": {
            "assembly_surface": "OuterArmourHelix_ContactSurface",
            "assembly_edge_set": "OuterArmourHelix_ContactEdges",
            "component": "OuterArmourHelix",
            "surface_kind": "beam_line",
        },
        "inner_armour_layer": {
            "assembly_surface": "InnerArmourHelix_ContactSurface",
            "assembly_edge_set": "InnerArmourHelix_ContactEdges",
            "component": "InnerArmourHelix",
            "surface_kind": "beam_line",
        },
        "outer_armour_layer": {
            "assembly_surface": "OuterArmourHelix_ContactSurface",
            "assembly_edge_set": "OuterArmourHelix_ContactEdges",
            "component": "OuterArmourHelix",
            "surface_kind": "beam_line",
        },
        "inner_sheath_inner_surface": {
            "assembly_surface": "inner_sheath_inner_surface",
            "component": "InnerSheathEquivalent",
            "surface_kind": "solid_face",
        },
        "inner_sheath_outer_surface": {
            "assembly_surface": "inner_sheath_outer_surface",
            "component": "InnerSheathEquivalent",
            "surface_kind": "solid_face",
        },
        "bedding_inner_surface": {
            "assembly_surface": "bedding_inner_surface",
            "component": "BeddingEquivalent",
            "surface_kind": "solid_face",
        },
        "bedding_outer_surface": {
            "assembly_surface": "bedding_outer_surface",
            "component": "BeddingEquivalent",
            "surface_kind": "solid_face",
        },
        "outer_sheath_inner_surface": {
            "assembly_surface": "outer_sheath_inner_surface",
            "component": "OuterSheathEquivalent",
            "surface_kind": "solid_face",
        },
        "outer_sheath_outer_surface": {
            "assembly_surface": "outer_sheath_outer_surface",
            "component": "OuterSheathEquivalent",
            "surface_kind": "solid_face",
        },
    }


def contact_binding_scaffold(payload):
    conceptual_regions = contact_region_map()
    numerical_model = payload.get("numerical_model", {})
    bindings = []
    for interface in numerical_model.get("contact_interfaces", []):
        master = interface.get("master")
        slave = interface.get("slave")
        resolved_master = conceptual_regions.get(master)
        resolved_slave = conceptual_regions.get(slave)
        status = "resolved_scaffold_not_bound_to_pair" if resolved_master and resolved_slave else "declared_not_bound_to_interaction"
        bindings.append(
            {
                "name": interface.get("name"),
                "master": master,
                "slave": slave,
                "resolved_master": resolved_master,
                "resolved_slave": resolved_slave,
                "priority": interface.get("priority"),
                "contact_property": "SCLAS_RegularizedContact",
                "status": status,
                "next_step": "bind resolved assembly regions to explicit Abaqus pair interactions",
            }
        )
    return bindings


def write_mesh_manifest(
    path,
    payload,
    abaqus_created,
    files=None,
    error="",
    contact_property=None,
    contact_regions=None,
    contact_interactions=None,
    contact_pairs=None,
    contact_pair_keyword_adjustment=None,
    boundary_conditions=None,
    mesh_control_adjustments=None,
):
    geometry = payload.get("derived_geometry_mm", {})
    armour = payload.get("armour", {})
    analysis = payload.get("analysis_conditions", {})
    mesh_cfg = payload.get("mesh", {})
    numerical_model = payload.get("numerical_model", {})
    files = files or []
    contact_regions = contact_regions or []
    contact_region_status = "not_created"
    if contact_regions:
        contact_region_status = "created"
        for region in contact_regions:
            if region.get("status") != "created":
                contact_region_status = "partial"
                break
    contact_interactions = contact_interactions or []
    contact_interaction_status = "not_created"
    if contact_interactions:
        interaction_statuses = [str(interaction.get("status", "")) for interaction in contact_interactions]
        if all(status == "created" for status in interaction_statuses):
            contact_interaction_status = "created"
        elif all(status.startswith("skipped") for status in interaction_statuses):
            contact_interaction_status = "skipped"
        else:
            contact_interaction_status = "partial"
    contact_pairs = contact_pairs or []
    mesh_control_adjustments = mesh_control_adjustments or []
    contact_pair_status = "not_created"
    if contact_pairs:
        contact_pair_status = "created"
        for contact_pair in contact_pairs:
            if contact_pair.get("status") != "created":
                contact_pair_status = "partial"
                break
    boundary_conditions = boundary_conditions or {}
    boundary_condition_status = boundary_conditions.get("status", "not_created")
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
            "annular_partition_quadrants": bool_from_payload(mesh_cfg.get("annular_partition_quadrants"), True),
            "contact_regularization_beta": float(analysis.get("contact_regularization_beta", 0.001)),
        },
        "contact_interfaces": numerical_model.get("contact_interfaces", []),
        "contact_interface_defaults": contact_defaults_from_payload(payload),
        "contact_binding_scaffold": contact_binding_scaffold(payload),
        "contact_property_scaffold": contact_property or {
            "status": "not_created",
            "reason": "Abaqus API not available or mesh scaffold failed before contact property creation.",
            "next_step": "create assembly surfaces/sets and bind the declared contact interfaces to this property",
        },
        "contact_region_scaffold_status": contact_region_status,
        "contact_region_scaffold": contact_regions,
        "contact_interaction_scaffold_status": contact_interaction_status,
        "contact_interaction_scaffold": contact_interactions,
        "contact_pair_scaffold_status": contact_pair_status,
        "contact_pair_scaffold": contact_pairs,
        "contact_pair_keyword_adjustment": contact_pair_keyword_adjustment or {
            "status": "not_attempted",
            "reason": "Abaqus input deck was not generated or no contact pair keyword adjustment was requested.",
        },
        "mesh_control_adjustments": mesh_control_adjustments,
        "boundary_condition_scaffold_status": boundary_condition_status,
        "boundary_condition_scaffold": boundary_conditions,
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
                "name": "inner_sheath_equivalent_solid",
                "count": 1,
                "type": "annular_solid_cylinder",
                "inner_radius_mm": geometry.get("inner_sheath_inner_radius_mm"),
                "outer_radius_mm": geometry.get("inner_sheath_outer_radius_mm"),
                "interface_surfaces": ["inner_sheath_inner_surface", "inner_sheath_outer_surface"],
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
                "name": "bedding_equivalent_solid",
                "count": 1,
                "type": "annular_solid_cylinder",
                "inner_radius_mm": geometry.get("inner_armour_outer_radius_mm"),
                "outer_radius_mm": geometry.get("bedding_outer_radius_mm"),
                "interface_surfaces": ["bedding_inner_surface", "bedding_outer_surface"],
                "element_hint": mesh_cfg.get("requested_element_type", "C3D8R"),
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
                "type": "annular_solid_cylinder",
                "inner_radius_mm": geometry.get("outer_sheath_inner_radius_mm"),
                "outer_radius_mm": geometry.get("outer_sheath_outer_radius_mm"),
                "interface_surfaces": ["outer_sheath_inner_surface", "outer_sheath_outer_surface"],
                "element_hint": mesh_cfg.get("requested_element_type", "C3D8R"),
            },
        ],
        "limitations": [
            "This is an Abaqus mesh scaffold, not the final contact-calibrated bending model.",
            "Layer solids are equivalent annular visual/mesh bodies; contact calibration and full pair definitions remain backend work.",
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


def create_contact_property_scaffold(model, payload):
    import abaqusConstants as ac

    defaults = contact_defaults_from_payload(payload)
    numerical_model = payload.get("numerical_model", {})
    friction = defaults.get("friction_coefficient")
    beta = defaults.get("regularization_beta")
    residual_pressure = defaults.get("residual_contact_pressure_mpa")
    try:
        friction = float(friction)
    except Exception:
        friction = 0.22
    try:
        beta = float(beta)
    except Exception:
        beta = 0.001
    try:
        residual_pressure = float(residual_pressure)
    except Exception:
        residual_pressure = 0.0

    prop_name = "SCLAS_RegularizedContact"
    contact_info = {
        "status": "created",
        "property_name": prop_name,
        "normal_behavior": defaults.get("normal"),
        "tangential_behavior": defaults.get("tangential"),
        "friction_coefficient": friction,
        "regularization_beta": beta,
        "residual_contact_pressure_mpa": residual_pressure,
        "declared_interfaces": numerical_model.get("contact_interfaces", []),
        "interaction_pair_status": "property_only_surface_pairs_pending",
        "warnings": [],
    }

    prop = model.ContactProperty(prop_name)
    try:
        prop.NormalBehavior(
            pressureOverclosure=getattr(ac, "HARD"),
            allowSeparation=getattr(ac, "ON"),
            constraintEnforcementMethod=getattr(ac, "DEFAULT"),
        )
    except Exception as exc:
        contact_info["warnings"].append("NormalBehavior default call failed: {0}".format(exc))
        try:
            prop.NormalBehavior(pressureOverclosure=getattr(ac, "HARD"), allowSeparation=getattr(ac, "ON"))
        except Exception as inner_exc:
            contact_info["warnings"].append("NormalBehavior fallback failed: {0}".format(inner_exc))
            contact_info["status"] = "created_without_normal_behavior"

    try:
        prop.TangentialBehavior(
            formulation=getattr(ac, "PENALTY"),
            directionality=getattr(ac, "ISOTROPIC"),
            slipRateDependency=getattr(ac, "OFF"),
            pressureDependency=getattr(ac, "OFF"),
            temperatureDependency=getattr(ac, "OFF"),
            dependencies=0,
            table=((friction,),),
            shearStressLimit=None,
            maximumElasticSlip=getattr(ac, "FRACTION"),
            fraction=beta,
            elasticSlipStiffness=None,
        )
    except Exception as exc:
        contact_info["warnings"].append("TangentialBehavior regularized call failed: {0}".format(exc))
        try:
            prop.TangentialBehavior(formulation=getattr(ac, "PENALTY"), table=((friction,),))
        except Exception as inner_exc:
            contact_info["warnings"].append("TangentialBehavior fallback failed: {0}".format(inner_exc))
            contact_info["status"] = "created_without_tangential_behavior"

    return contact_info


def build_abaqus_mesh_model(payload, job_dir):
    """Create a CAE mesh scaffold when this script is executed by Abaqus/CAE."""
    from abaqus import mdb
    from abaqusConstants import (
        ANALYSIS,
        B31,
        CARTESIAN,
        DEFORMABLE_BODY,
        DURING_ANALYSIS,
        HEX,
        IMPRINT,
        N1_COSINES,
        OFF,
        ON,
        STANDARD,
        SWEEP,
        THREE_D,
        XZPLANE,
        YZPLANE,
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
    annular_partition_quadrants = bool_from_payload(mesh_cfg.get("annular_partition_quadrants"), True)
    model_name = safe_name(payload.get("metadata", {}).get("job_id", "SCLAS_CableMesh"), 32)
    job_name = safe_name(model_name + "_mesh", 32)

    try:
        model_names = list(mdb.models.keys())
    except Exception:
        model_names = []
    if model_name in model_names:
        model_name = safe_name(model_name + "_" + datetime.now().strftime("%H%M%S"), 32)
        job_name = safe_name(model_name + "_mesh", 32)
    model = mdb.Model(name=model_name)
    assembly = model.rootAssembly
    assembly.DatumCsysByDefault(CARTESIAN)

    def make_material_section(section_name, mat_info):
        mat_name = safe_name(section_name + "_" + mat_info["name"] + "_mat")
        material = model.Material(name=mat_name)
        material.Elastic(table=((mat_info["elastic_modulus_mpa"], mat_info["poisson_ratio"]),))
        material.Density(table=((mat_info["density"],),))
        model.HomogeneousSolidSection(name=section_name, material=mat_name, thickness=None)
        return section_name

    steel = material_by_name(payload, "Armour", 210.0, 0.30, 7850.0)
    copper = material_by_name(payload, "Copper", 108.0, 0.33, 8960.0)
    sheath = material_by_name(payload, "Sheath", 1.4, 0.45, 1300.0)
    core_section = make_material_section("CoreSolidSection", copper)
    inner_sheath_section = make_material_section("InnerSheathSection", sheath)
    bedding_section = make_material_section("BeddingSection", sheath)
    outer_sheath_section = make_material_section("OuterSheathSection", sheath)

    steel_mat = model.Material(name="ArmourSteel_mat")
    steel_mat.Elastic(table=((steel["elastic_modulus_mpa"], steel["poisson_ratio"]),))
    steel_mat.Density(table=((steel["density"],),))
    contact_property = create_contact_property_scaffold(model, payload)
    contact_regions = []
    solid_end_face_specs = []
    end_coupling_node_specs = []

    def append_contact_region(record, created_count, expected_count):
        if created_count >= expected_count:
            record["status"] = "created"
        elif created_count > 0:
            record["status"] = "partial"
        else:
            record["status"] = "failed"
        contact_regions.append(record)

    def end_node_labels(part, z_value):
        tolerance = max(1.0e-6 * max(length, 1.0), 1.0e-5)
        labels = []
        try:
            for node in part.nodes:
                if abs(float(node.coordinates[2]) - z_value) <= tolerance:
                    labels.append(int(node.label))
        except Exception:
            labels = []
        return labels

    def append_end_coupling_node_spec(component_name, instance_name, left_node_labels=None, right_node_labels=None):
        end_coupling_node_specs.append(
            {
                "component": component_name,
                "assembly_instance": instance_name,
                "left_node_labels": left_node_labels or [],
                "right_node_labels": right_node_labels or [],
            }
        )

    def append_solid_end_face_spec(component_name, instance_name, left_probe, right_probe, left_node_labels=None, right_node_labels=None):
        solid_end_face_specs.append(
            {
                "component": component_name,
                "assembly_instance": instance_name,
                "left_probe": left_probe,
                "right_probe": right_probe,
                "left_node_labels": left_node_labels or [],
                "right_node_labels": right_node_labels or [],
            }
        )
        append_end_coupling_node_spec(component_name, instance_name, left_node_labels, right_node_labels)

    def region_sequence(found):
        try:
            len(found)
            return found
        except Exception:
            return (found,)

    def find_regions_at(container, probes):
        clean_probes = [probe for probe in probes if probe]
        if not clean_probes:
            return ()
        try:
            if len(clean_probes) == 1:
                return region_sequence(container.findAt((clean_probes[0],)))
            return container.findAt(*tuple((probe,) for probe in clean_probes))
        except Exception:
            found_regions = []
            seen = set()
            for probe in clean_probes:
                for region in region_sequence(container.findAt((probe,))):
                    try:
                        key = region.index
                    except Exception:
                        key = str(region)
                    if key in seen:
                        continue
                    seen.add(key)
                    found_regions.append(region)
            return tuple(found_regions)

    def find_faces_by_radius(container, radius):
        found_regions = []
        seen = set()
        tolerance = max(5.0e-2, abs(float(radius)) * 1.0e-4)
        for face in container:
            try:
                points = face.pointOn
            except Exception:
                points = []
            for point in points:
                if len(point) < 2:
                    continue
                point_radius = math.hypot(float(point[0]), float(point[1]))
                if abs(point_radius - float(radius)) > tolerance:
                    continue
                try:
                    key = face.index
                except Exception:
                    key = str(face)
                if key not in seen:
                    seen.add(key)
                    found_regions.append(face)
                break
        return tuple(found_regions)

    def find_layer_faces(container, spec, probes_key, probe_key):
        faces = find_regions_at(container, spec.get(probes_key) or [spec.get(probe_key)])
        if faces:
            return faces
        radius = spec.get("radius_mm")
        if radius is not None:
            faces = find_faces_by_radius(container, radius)
            if faces:
                return faces
        return ()

    def create_solid_contact_regions(part, inst, component_name, surface_specs=None):
        surface_specs = surface_specs or []
        record = {
            "component": component_name,
            "region_type": "solid_face_surface",
            "part": part.name,
            "assembly_instance": inst.name,
            "part_face_set": "ContactFaces",
            "part_surface": "ContactSurface",
            "assembly_face_set": component_name + "_ContactFaces",
            "assembly_surface": component_name + "_ContactSurface",
            "interface_surfaces": [],
            "created_regions": [],
            "warnings": [],
            "notes": [
                "ContactSurface uses all faces; named layer surfaces are created from radius-based face probes when available."
            ],
        }
        created = 0
        expected = 4 + 4 * len(surface_specs)
        try:
            part.Set(faces=part.faces[:], name=record["part_face_set"])
            record["created_regions"].append("part_face_set")
            created += 1
        except Exception as exc:
            record["warnings"].append("part face set failed: {0}".format(exc))
        try:
            part.Surface(side1Faces=part.faces[:], name=record["part_surface"])
            record["created_regions"].append("part_surface")
            created += 1
        except Exception as exc:
            record["warnings"].append("part surface failed: {0}".format(exc))
        try:
            assembly.Set(faces=inst.faces[:], name=record["assembly_face_set"])
            record["created_regions"].append("assembly_face_set")
            created += 1
        except Exception as exc:
            record["warnings"].append("assembly face set failed: {0}".format(exc))
        try:
            assembly.Surface(side1Faces=inst.faces[:], name=record["assembly_surface"])
            record["created_regions"].append("assembly_surface")
            created += 1
        except Exception as exc:
            record["warnings"].append("assembly surface failed: {0}".format(exc))

        for spec in surface_specs:
            spec_status = {
                "label": spec.get("label"),
                "radius_mm": spec.get("radius_mm"),
                "part_face_set": spec.get("part_face_set"),
                "part_surface": spec.get("part_surface"),
                "assembly_face_set": spec.get("assembly_face_set"),
                "assembly_surface": spec.get("assembly_surface"),
                "created_regions": [],
                "warnings": [],
            }
            try:
                part_faces = find_layer_faces(part.faces, spec, "part_probes", "part_probe")
                spec_status["part_face_count"] = len(part_faces)
                if not part_faces:
                    raise RuntimeError("no part faces found at radius {0}".format(spec.get("radius_mm")))
                part.Set(faces=part_faces, name=spec.get("part_face_set"))
                spec_status["created_regions"].append("part_face_set")
                created += 1
            except Exception as exc:
                spec_status["warnings"].append("part named face set failed: {0}".format(exc))
            try:
                part_faces = find_layer_faces(part.faces, spec, "part_probes", "part_probe")
                spec_status["part_surface_face_count"] = len(part_faces)
                if not part_faces:
                    raise RuntimeError("no part surface faces found at radius {0}".format(spec.get("radius_mm")))
                part.Surface(side1Faces=part_faces, name=spec.get("part_surface"))
                spec_status["created_regions"].append("part_surface")
                created += 1
            except Exception as exc:
                spec_status["warnings"].append("part named surface failed: {0}".format(exc))
            try:
                assembly_faces = find_layer_faces(inst.faces, spec, "assembly_probes", "assembly_probe")
                spec_status["assembly_face_count"] = len(assembly_faces)
                if not assembly_faces:
                    raise RuntimeError("no assembly faces found at radius {0}".format(spec.get("radius_mm")))
                assembly.Set(faces=assembly_faces, name=spec.get("assembly_face_set"))
                spec_status["created_regions"].append("assembly_face_set")
                created += 1
            except Exception as exc:
                spec_status["warnings"].append("assembly named face set failed: {0}".format(exc))
            try:
                assembly_faces = find_layer_faces(inst.faces, spec, "assembly_probes", "assembly_probe")
                spec_status["assembly_surface_face_count"] = len(assembly_faces)
                if not assembly_faces:
                    raise RuntimeError("no assembly surface faces found at radius {0}".format(spec.get("radius_mm")))
                assembly.Surface(side1Faces=assembly_faces, name=spec.get("assembly_surface"))
                spec_status["created_regions"].append("assembly_surface")
                created += 1
            except Exception as exc:
                spec_status["warnings"].append("assembly named surface failed: {0}".format(exc))
            if len(spec_status["created_regions"]) == 4:
                spec_status["status"] = "created"
            elif spec_status["created_regions"]:
                spec_status["status"] = "partial"
            else:
                spec_status["status"] = "failed"
            record["interface_surfaces"].append(spec_status)

        append_contact_region(record, created, expected)

    def create_beam_contact_regions(part, inst, component_name):
        record = {
            "component": component_name,
            "region_type": "beam_edge_set_and_surface",
            "part": part.name,
            "assembly_instance": inst.name,
            "part_edge_set": "ContactEdges",
            "assembly_edge_set": component_name + "_ContactEdges",
            "part_surface": "ContactSurface",
            "assembly_surface": component_name + "_ContactSurface",
            "created_regions": [],
            "warnings": [],
            "notes": [
                "B31 armour scaffold exposes edge sets and attempts beam circumferential contact surfaces."
            ],
        }
        created = 0
        expected = 4
        try:
            part.Set(edges=part.edges[:], name=record["part_edge_set"])
            record["created_regions"].append("part_edge_set")
            created += 1
        except Exception as exc:
            record["warnings"].append("part edge set failed: {0}".format(exc))
        try:
            assembly.Set(edges=inst.edges[:], name=record["assembly_edge_set"])
            record["created_regions"].append("assembly_edge_set")
            created += 1
        except Exception as exc:
            record["warnings"].append("assembly edge set failed: {0}".format(exc))
        try:
            part.Surface(circumEdges=part.edges[:], name=record["part_surface"])
            record["created_regions"].append("part_surface")
            created += 1
        except Exception as exc:
            record["warnings"].append("part beam surface failed: {0}".format(exc))
        try:
            assembly.Surface(circumEdges=inst.edges[:], name=record["assembly_surface"])
            record["created_regions"].append("assembly_surface")
            created += 1
        except Exception as exc:
            record["warnings"].append("assembly beam surface failed: {0}".format(exc))
        append_contact_region(record, created, expected)

    def create_contact_interaction_scaffold(contact_property_record, explicit_pair_records=None):
        explicit_pair_records = explicit_pair_records or []
        record = {
            "name": "SCLAS_GeneralContact",
            "type": "ContactStd",
            "create_step": "Initial",
            "contact_property": "SCLAS_RegularizedContact",
            "assignment_scope": "GLOBAL_SELF",
            "status": "not_created",
            "created_regions": [],
            "warnings": [],
            "notes": [
                "General contact is an executable scaffold until explicit inner sheath and bedding surfaces exist.",
                "Declared interface names remain in contact_binding_scaffold for later pair-level binding.",
            ],
        }
        if not contact_property_record or contact_property_record.get("status") not in ("created", "partial"):
            record["status"] = "skipped"
            record["warnings"].append("contact property was not available")
            return record

        created_pair_names = [item.get("name") for item in explicit_pair_records if item.get("status") == "created"]
        if created_pair_names:
            skipped_pair_names = [item.get("name") for item in explicit_pair_records if item.get("status") != "created"]
            record["status"] = "skipped_explicit_pairs_active"
            record["assignment_scope"] = "explicit_pairs_only"
            record["created_explicit_pair_count"] = len(created_pair_names)
            record["skipped_explicit_pair_count"] = len(skipped_pair_names)
            record["created_explicit_pairs"] = created_pair_names
            record["skipped_explicit_pairs"] = skipped_pair_names
            record["notes"].append(
                "Skipped general contact because explicit contact pairs are active; this avoids Abaqus general-contact/contact-pair domain overlap warnings."
            )
            record["notes"].append(
                "Beam-to-beam armour cross-layer contact remains scaffold-only until a solid or supported surface representation is added."
            )
            return record

        try:
            import abaqusConstants as ac

            interaction = model.ContactStd(name=record["name"], createStepName=record["create_step"])
            record["created_regions"].append("interaction")
            try:
                interaction.includedPairs.setValuesInStep(stepName=record["create_step"], useAllstar=ON)
                record["created_regions"].append("included_pairs_allstar")
            except Exception as exc:
                record["warnings"].append("included pair assignment failed: {0}".format(exc))

            try:
                global_region = getattr(ac, "GLOBAL")
                self_region = getattr(ac, "SELF")
                interaction.contactPropertyAssignments.appendInStep(
                    stepName=record["create_step"],
                    assignments=((global_region, self_region, record["contact_property"]),),
                )
                record["created_regions"].append("global_self_property_assignment")
            except Exception as exc:
                record["warnings"].append("contact property assignment failed: {0}".format(exc))

            if "global_self_property_assignment" in record["created_regions"]:
                record["status"] = "created"
            else:
                record["status"] = "partial"
        except Exception as exc:
            record["status"] = "failed"
            record["warnings"].append("general contact creation failed: {0}".format(exc))
        return record

    def create_explicit_contact_pair_scaffold(contact_property_record):
        records = []
        bindings = contact_binding_scaffold(payload)
        for binding in bindings:
            pair_name = safe_name("Pair_" + str(binding.get("name", "contact")), 38)
            record = {
                "name": pair_name,
                "interface": binding.get("name"),
                "type": "SurfaceToSurfaceContactStd",
                "create_step": "Initial",
                "contact_property": "SCLAS_RegularizedContact",
                "master": binding.get("master"),
                "slave": binding.get("slave"),
                "resolved_master": binding.get("resolved_master"),
                "resolved_slave": binding.get("resolved_slave"),
                "status": "not_created",
                "created_regions": [],
                "warnings": [],
                "notes": [
                    "Explicit pair contact is a scaffold and may need beam/surface tuning before production solving."
                ],
            }
            records.append(record)
            if not contact_property_record or contact_property_record.get("status") not in ("created", "partial"):
                record["status"] = "skipped"
                record["warnings"].append("contact property was not available")
                continue

            master_surface = (binding.get("resolved_master") or {}).get("assembly_surface")
            slave_surface = (binding.get("resolved_slave") or {}).get("assembly_surface")
            master_kind = (binding.get("resolved_master") or {}).get("surface_kind")
            slave_kind = (binding.get("resolved_slave") or {}).get("surface_kind")
            record["master_surface"] = master_surface
            record["slave_surface"] = slave_surface
            record["master_surface_kind"] = master_kind
            record["slave_surface_kind"] = slave_kind
            if not master_surface or not slave_surface:
                record["status"] = "skipped"
                record["warnings"].append("resolved assembly surfaces are incomplete")
                continue
            if master_surface not in assembly.surfaces.keys():
                record["status"] = "skipped"
                record["warnings"].append("master surface not found: {0}".format(master_surface))
                continue
            if slave_surface not in assembly.surfaces.keys():
                record["status"] = "skipped"
                record["warnings"].append("slave surface not found: {0}".format(slave_surface))
                continue

            def remove_interaction_if_created(name):
                try:
                    if name in model.interactions.keys():
                        del model.interactions[name]
                except Exception:
                    pass

            def try_pair(name, master_region, slave_region, mode):
                import abaqusConstants as ac

                try:
                    if mode == "standard":
                        model.SurfaceToSurfaceContactStd(
                            name=name,
                            createStepName="Initial",
                            master=master_region,
                            slave=slave_region,
                            sliding=getattr(ac, "FINITE"),
                            interactionProperty="SCLAS_RegularizedContact",
                            thickness=ON,
                        )
                    else:
                        model.SurfaceToSurfaceContactStd(
                            name=name,
                            createStepName="Initial",
                            master=master_region,
                            slave=slave_region,
                            sliding=getattr(ac, "FINITE"),
                            interactionProperty="SCLAS_RegularizedContact",
                        )
                    return True, ""
                except Exception as exc:
                    remove_interaction_if_created(name)
                    return False, str(exc)

            master_region = assembly.surfaces[master_surface]
            slave_region = assembly.surfaces[slave_surface]
            master_is_beam = master_kind == "beam_line"
            slave_is_beam = slave_kind == "beam_line"
            if master_is_beam and slave_is_beam:
                record["status"] = "skipped"
                record["warnings"].append(
                    "both regions are B31 beam line surfaces; Abaqus/Standard cannot use line elements as an explicit contact-pair master surface"
                )
                record["notes"].append("Skipped explicit armour-armour pair; keep general contact scaffold until a solid/contact-surface armour representation is added.")
                continue

            if master_is_beam:
                record["notes"].append("Declared master is a B31 beam line surface; using swapped solver order so the solid face is master.")
                attempts = [
                    (safe_name(pair_name + "_SolidMaster", 38), slave_region, master_region, "standard", "solid_master_swapped_order"),
                    (safe_name(pair_name + "_SolidMaster", 38), slave_region, master_region, "minimal", "solid_master_swapped_order_minimal"),
                ]
            elif slave_is_beam:
                record["notes"].append("Declared slave is a B31 beam line surface; keeping declared order so the solid face remains master.")
                attempts = [
                    (pair_name, master_region, slave_region, "standard", "solid_master_declared_order"),
                    (pair_name, master_region, slave_region, "minimal", "solid_master_declared_order_minimal"),
                ]
            else:
                attempts = [
                    (pair_name, master_region, slave_region, "standard", "declared_order"),
                    (pair_name, master_region, slave_region, "minimal", "declared_order_minimal"),
                    (safe_name(pair_name + "_Swap", 38), slave_region, master_region, "standard", "swapped_order"),
                    (safe_name(pair_name + "_Swap", 38), slave_region, master_region, "minimal", "swapped_order_minimal"),
                ]
            for attempt_name, attempt_master, attempt_slave, mode, label in attempts:
                success, error = try_pair(attempt_name, attempt_master, attempt_slave, mode)
                if success:
                    record["status"] = "created"
                    record["name"] = attempt_name
                    record["created_regions"].append(label)
                    break
                record["warnings"].append("{0} failed: {1}".format(label, error))
            if record["status"] != "created":
                record["status"] = "failed"
        return records

    def create_boundary_condition_scaffold():
        output_intervals = int(analysis.get("abaqus_output_intervals", 4))
        if output_intervals < 2:
            output_intervals = 2
        if output_intervals > 100:
            output_intervals = 100
        curve_v0_mode = bool(analysis.get("abaqus_curve_v0", False))
        curve_endpoint_mode = bool(analysis.get("abaqus_curve_v0_endpoint", False))
        curve_endpoint_factor = float(analysis.get("abaqus_curve_v0_endpoint_factor", 1.0))
        multistep_smoke = bool(analysis.get("abaqus_multistep_smoke", False))
        default_path = [1.0, 0.0, -1.0, 0.0]
        if curve_v0_mode:
            scale = float(analysis.get("abaqus_curve_v0_curvature_scale", 0.25))
            default_path = [scale, 0.0, -scale, 0.0]
        raw_path = analysis.get("abaqus_curve_v0_path_factors", default_path)
        if not isinstance(raw_path, list):
            raw_path = default_path
        load_path_factors = []
        for factor in raw_path[:20]:
            try:
                load_path_factors.append(float(factor))
            except Exception:
                pass
        if len(load_path_factors) < 2:
            load_path_factors = default_path
        record = {
            "status": "not_created",
            "step": "SCLAS_CyclicBendingStep",
            "amplitude": "SCLAS_CyclicBendingAmplitude",
            "left_reference_point_set": "SCLAS_RP_LeftEnd",
            "right_reference_point_set": "SCLAS_RP_RightEnd",
            "left_end_face_set": "SCLAS_LeftEndFaces",
            "right_end_face_set": "SCLAS_RightEndFaces",
            "left_end_surface": "SCLAS_LeftEndSurface",
            "right_end_surface": "SCLAS_RightEndSurface",
            "target_curvature_1_per_m": float(analysis.get("max_curvature_1_per_m", 0.08)) * (curve_endpoint_factor if curve_endpoint_mode else 1.0),
            "effective_length_mm": length,
            "target_rotation_rad": float(analysis.get("max_curvature_1_per_m", 0.08)) * (curve_endpoint_factor if curve_endpoint_mode else 1.0) * (length / 1000.0),
            "output_intervals": output_intervals,
            "solver_increment_control": "abaqus_default",
            "multistep_smoke": multistep_smoke,
            "curve_v0_mode": curve_v0_mode,
            "curve_endpoint_mode": curve_endpoint_mode,
            "curve_endpoint_factor": curve_endpoint_factor,
            "load_path_factors": load_path_factors,
            "created_regions": [],
            "optional_created_regions": [],
            "warnings": [],
            "optional_warnings": [],
            "notes": [
                "Boundary conditions are a cyclic bending scaffold; right reference point outputs are requested for ODB moment-curvature extraction.",
                "Reference point cyclic rotation is mandatory for this scaffold; end-face coupling is attempted when supported.",
            ],
        }
        required_created = 0
        required_expected = 5
        optional_created = 0
        try:
            if multistep_smoke:
                step_sequence = []
                previous_step = "Initial"
                for index, amplitude_value in enumerate(load_path_factors):
                    if index == 0:
                        step_name = record["step"]
                    else:
                        step_name = safe_name(record["step"] + "_{0:02d}".format(index + 1), 38)
                    model.StaticStep(name=step_name, previous=previous_step, nlgeom=ON)
                    step_sequence.append(
                        {
                            "name": step_name,
                            "amplitude_factor": amplitude_value,
                            "target_rotation_rad": record["target_rotation_rad"] * amplitude_value,
                        }
                    )
                    previous_step = step_name
                record["step_sequence"] = step_sequence
                if curve_v0_mode:
                    record["created_regions"].append("curve_v0_multistep_path")
                else:
                    record["created_regions"].append("cyclic_bending_multistep_smoke")
            else:
                model.StaticStep(name=record["step"], previous="Initial", nlgeom=ON)
                record["created_regions"].append("cyclic_bending_step")
            required_created += 1
        except Exception as exc:
            record["warnings"].append("cyclic bending step failed: {0}".format(exc))

        try:
            import abaqusConstants as ac

            model.TabularAmplitude(
                name=record["amplitude"],
                timeSpan=getattr(ac, "STEP"),
                data=((0.0, 0.0), (0.25, 1.0), (0.5, 0.0), (0.75, -1.0), (1.0, 0.0)),
            )
            record["created_regions"].append("cyclic_amplitude")
            required_created += 1
        except Exception as exc:
            record["warnings"].append("cyclic amplitude failed: {0}".format(exc))

        try:
            left_rp = assembly.ReferencePoint(point=(0.0, 0.0, -0.5 * length))
            assembly.Set(referencePoints=(assembly.referencePoints[left_rp.id],), name=record["left_reference_point_set"])
            record["created_regions"].append("left_reference_point")
            required_created += 1
        except Exception as exc:
            record["warnings"].append("left reference point failed: {0}".format(exc))
        try:
            right_rp = assembly.ReferencePoint(point=(0.0, 0.0, 0.5 * length))
            assembly.Set(referencePoints=(assembly.referencePoints[right_rp.id],), name=record["right_reference_point_set"])
            record["created_regions"].append("right_reference_point")
            required_created += 1
        except Exception as exc:
            record["warnings"].append("right reference point failed: {0}".format(exc))

        left_faces = []
        right_faces = []
        for spec in solid_end_face_specs:
            try:
                inst = assembly.instances[spec["assembly_instance"]]
                for face in region_sequence(inst.faces.findAt((spec["left_probe"],))):
                    left_faces.append(face)
            except Exception as exc:
                record["warnings"].append("{0} left end face failed: {1}".format(spec["component"], exc))
            try:
                inst = assembly.instances[spec["assembly_instance"]]
                for face in region_sequence(inst.faces.findAt((spec["right_probe"],))):
                    right_faces.append(face)
            except Exception as exc:
                record["warnings"].append("{0} right end face failed: {1}".format(spec["component"], exc))
        record["left_end_face_count"] = len(left_faces)
        record["right_end_face_count"] = len(right_faces)

        try:
            assembly.Set(faces=tuple(left_faces), name=record["left_end_face_set"])
            record["optional_created_regions"].append("left_end_face_set")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("left end face set failed: {0}".format(exc))
        try:
            assembly.Set(faces=tuple(right_faces), name=record["right_end_face_set"])
            record["optional_created_regions"].append("right_end_face_set")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("right end face set failed: {0}".format(exc))

        try:
            assembly.Surface(side1Faces=tuple(left_faces), name=record["left_end_surface"])
            record["optional_created_regions"].append("left_end_surface")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("left end surface failed: {0}".format(exc))
        try:
            assembly.Surface(side1Faces=tuple(right_faces), name=record["right_end_surface"])
            record["optional_created_regions"].append("right_end_surface")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("right end surface failed: {0}".format(exc))

        try:
            import abaqusConstants as ac
            coupling_method_name = None
            for candidate in ["Coupling", "KinematicCoupling"]:
                if hasattr(model, candidate):
                    coupling_method_name = candidate
                    break
            record["available_constraint_methods"] = [
                candidate for candidate in ["Coupling", "KinematicCoupling", "MultipointConstraint", "Equation"] if hasattr(model, candidate)
            ]
            if not coupling_method_name:
                raise AttributeError("no Coupling/KinematicCoupling method on Abaqus model")

            left_surface_region = None
            right_surface_region = None
            if record["left_end_surface"] in assembly.surfaces.keys():
                left_surface_region = assembly.surfaces[record["left_end_surface"]]
            elif record["left_end_face_set"] in assembly.sets.keys():
                left_surface_region = assembly.sets[record["left_end_face_set"]]
            if record["right_end_surface"] in assembly.surfaces.keys():
                right_surface_region = assembly.surfaces[record["right_end_surface"]]
            elif record["right_end_face_set"] in assembly.sets.keys():
                right_surface_region = assembly.sets[record["right_end_face_set"]]
            if left_surface_region is None or right_surface_region is None:
                raise KeyError("end face regions were not available for coupling")

            coupling_method = getattr(model, coupling_method_name)
            coupling_method(
                name="SCLAS_LeftEnd_KinematicCoupling",
                controlPoint=assembly.sets[record["left_reference_point_set"]],
                surface=left_surface_region,
                influenceRadius=getattr(ac, "WHOLE_SURFACE"),
                couplingType=getattr(ac, "KINEMATIC"),
                localCsys=None,
                u1=ON,
                u2=ON,
                u3=ON,
                ur1=ON,
                ur2=ON,
                ur3=ON,
            )
            coupling_method(
                name="SCLAS_RightEnd_KinematicCoupling",
                controlPoint=assembly.sets[record["right_reference_point_set"]],
                surface=right_surface_region,
                influenceRadius=getattr(ac, "WHOLE_SURFACE"),
                couplingType=getattr(ac, "KINEMATIC"),
                localCsys=None,
                u1=ON,
                u2=ON,
                u3=ON,
                ur1=ON,
                ur2=ON,
                ur3=ON,
            )
            record["optional_created_regions"].append("end_couplings")
            record["coupling_method"] = coupling_method_name
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("end coupling pending: {0}".format(exc))

        try:
            model.EncastreBC(
                name="SCLAS_LeftEnd_Fixed",
                createStepName="Initial",
                region=assembly.sets[record["left_reference_point_set"]],
            )
            if multistep_smoke:
                model.DisplacementBC(
                    name="SCLAS_RightEnd_CyclicRotation",
                    createStepName=record["step"],
                    region=assembly.sets[record["right_reference_point_set"]],
                    u1=0.0,
                    u2=0.0,
                    u3=0.0,
                    ur1=0.0,
                    ur2=record["step_sequence"][0]["target_rotation_rad"],
                    ur3=0.0,
                )
                for step_item in record.get("step_sequence", [])[1:]:
                    model.boundaryConditions["SCLAS_RightEnd_CyclicRotation"].setValuesInStep(
                        stepName=step_item["name"],
                        ur2=step_item["target_rotation_rad"],
                    )
            else:
                if curve_endpoint_mode:
                    model.DisplacementBC(
                        name="SCLAS_RightEnd_CyclicRotation",
                        createStepName=record["step"],
                        region=assembly.sets[record["right_reference_point_set"]],
                        u1=0.0,
                        u2=0.0,
                        u3=0.0,
                        ur1=0.0,
                        ur2=record["target_rotation_rad"],
                        ur3=0.0,
                    )
                else:
                    model.DisplacementBC(
                        name="SCLAS_RightEnd_CyclicRotation",
                        createStepName=record["step"],
                        region=assembly.sets[record["right_reference_point_set"]],
                        u1=0.0,
                        u2=0.0,
                        u3=0.0,
                        ur1=0.0,
                        ur2=record["target_rotation_rad"],
                        ur3=0.0,
                        amplitude=record["amplitude"],
                    )
            record["created_regions"].append("reference_point_bcs")
            required_created += 1
        except Exception as exc:
            record["warnings"].append("reference point BCs failed: {0}".format(exc))

        try:
            try:
                model.FieldOutputRequest(
                    name="SCLAS_RP_FieldOutput",
                    createStepName=record["step"],
                    variables=("U", "UR", "RF", "RM"),
                    numIntervals=output_intervals,
                    timeMarks=OFF,
                )
                record["optional_created_regions"].append("rp_field_output_num_intervals")
            except TypeError:
                try:
                    model.FieldOutputRequest(
                        name="SCLAS_RP_FieldOutput",
                        createStepName=record["step"],
                        variables=("U", "UR", "RF", "RM"),
                        frequency=1,
                    )
                    record["optional_created_regions"].append("rp_field_output_frequency")
                    record["optional_warnings"].append("RP field output numIntervals option unavailable; used frequency=1")
                except TypeError:
                    model.FieldOutputRequest(
                        name="SCLAS_RP_FieldOutput",
                        createStepName=record["step"],
                        variables=("U", "UR", "RF", "RM"),
                    )
                    record["optional_created_regions"].append("rp_field_output_default")
                    record["optional_warnings"].append("RP field output interval/frequency options unavailable; used Abaqus default frequency")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("RP field output request failed: {0}".format(exc))

        try:
            try:
                model.HistoryOutputRequest(
                    name="SCLAS_RightRP_HistoryOutput",
                    createStepName=record["step"],
                    variables=("UR2", "RM2"),
                    region=assembly.sets[record["right_reference_point_set"]],
                    numIntervals=output_intervals,
                    timeMarks=OFF,
                )
                record["optional_created_regions"].append("right_rp_history_output_num_intervals")
            except TypeError:
                try:
                    model.HistoryOutputRequest(
                        name="SCLAS_RightRP_HistoryOutput",
                        createStepName=record["step"],
                        variables=("UR2", "RM2"),
                        region=assembly.sets[record["right_reference_point_set"]],
                        frequency=1,
                    )
                    record["optional_created_regions"].append("right_rp_history_output_frequency")
                    record["optional_warnings"].append("RP history output numIntervals option unavailable; used frequency=1")
                except TypeError:
                    model.HistoryOutputRequest(
                        name="SCLAS_RightRP_HistoryOutput",
                        createStepName=record["step"],
                        variables=("UR2", "RM2"),
                        region=assembly.sets[record["right_reference_point_set"]],
                    )
                    record["optional_created_regions"].append("right_rp_history_output_default")
                    record["optional_warnings"].append("RP history output interval/frequency options unavailable; used Abaqus default frequency")
            optional_created += 1
        except Exception as exc:
            record["optional_warnings"].append("RP history output request failed: {0}".format(exc))

        record["required_created_count"] = required_created
        record["required_expected_count"] = required_expected
        record["optional_created_count"] = optional_created
        if required_created >= required_expected and "end_couplings" in record["optional_created_regions"]:
            record["status"] = "created"
        elif required_created >= required_expected:
            record["status"] = "created_with_pending_end_coupling"
        elif required_created > 0:
            record["status"] = "partial"
        else:
            record["status"] = "failed"
        return record

    def format_keyword_labels(labels):
        lines = []
        labels = [str(label) for label in labels]
        for i in range(0, len(labels), 16):
            lines.append(", ".join(labels[i : i + 16]))
        return lines

    def inject_end_coupling_keyword_fallback(inp_path, boundary_record):
        fallback = {
            "status": "not_attempted",
            "inp_file": os.path.basename(inp_path),
            "left_node_surface": "SCLAS_LeftEndNodeSurface",
            "right_node_surface": "SCLAS_RightEndNodeSurface",
            "left_coupling": "SCLAS_LeftEnd_KeywordCoupling",
            "right_coupling": "SCLAS_RightEnd_KeywordCoupling",
            "left_node_set_count": 0,
            "right_node_set_count": 0,
            "warnings": [],
            "notes": [
                "Keyword fallback is injected into the generated .inp because Abaqus 2019 did not expose model.Coupling in noGUI."
            ],
        }
        if not os.path.exists(inp_path):
            fallback["status"] = "failed"
            fallback["warnings"].append("input file not found")
            return fallback

        left_surface_lines = []
        right_surface_lines = []
        assembly_block_lines = [
            "**",
            "** SCLAS Abaqus 2019 end-coupling keyword fallback",
            "** Assembly-scoped end node sets and node-based surfaces.",
        ]
        for spec in end_coupling_node_specs:
            component = safe_name(spec.get("component", "solid"), 24)
            instance_name = spec.get("assembly_instance")
            left_labels = spec.get("left_node_labels", [])
            right_labels = spec.get("right_node_labels", [])
            if left_labels:
                left_set = safe_name("SCLAS_LNodes_" + component, 38)
                assembly_block_lines.append("*Nset, nset={0}, instance={1}".format(left_set, instance_name))
                assembly_block_lines.extend(format_keyword_labels(left_labels))
                left_surface_lines.append("{0}, 1.".format(left_set))
                fallback["left_node_set_count"] += 1
            else:
                fallback["warnings"].append("{0} left end node labels were empty".format(component))
            if right_labels:
                right_set = safe_name("SCLAS_RNodes_" + component, 38)
                assembly_block_lines.append("*Nset, nset={0}, instance={1}".format(right_set, instance_name))
                assembly_block_lines.extend(format_keyword_labels(right_labels))
                right_surface_lines.append("{0}, 1.".format(right_set))
                fallback["right_node_set_count"] += 1
            else:
                fallback["warnings"].append("{0} right end node labels were empty".format(component))

        if not left_surface_lines or not right_surface_lines:
            fallback["status"] = "failed"
            fallback["warnings"].append("not enough node sets to define node-based end surfaces")
            return fallback

        assembly_block_lines.append("*Surface, type=NODE, name={0}".format(fallback["left_node_surface"]))
        assembly_block_lines.extend(left_surface_lines)
        assembly_block_lines.append("*Surface, type=NODE, name={0}".format(fallback["right_node_surface"]))
        assembly_block_lines.extend(right_surface_lines)
        coupling_block_lines = [
            "**",
            "** SCLAS Abaqus 2019 end-coupling keyword fallback constraints",
            "** Abaqus input processing requires *Coupling in assembly/instance/part scope.",
            "*Coupling, constraint name={0}, ref node={1}, surface={2}".format(
                fallback["left_coupling"],
                boundary_record.get("left_reference_point_set", "SCLAS_RP_LeftEnd"),
                fallback["left_node_surface"],
            ),
            "*Kinematic",
            "1, 6",
            "*Coupling, constraint name={0}, ref node={1}, surface={2}".format(
                fallback["right_coupling"],
                boundary_record.get("right_reference_point_set", "SCLAS_RP_RightEnd"),
                fallback["right_node_surface"],
            ),
            "*Kinematic",
            "1, 6",
            "** End SCLAS Abaqus 2019 end-coupling keyword fallback constraints",
            "**",
        ]
        assembly_block_lines.extend(coupling_block_lines)
        assembly_block_lines.append("** End SCLAS assembly-scoped end coupling fallback data")
        assembly_block_lines.append("**")

        try:
            with open(inp_path, "r") as f:
                lines = f.read().splitlines()
            insert_index = None
            for i, line in enumerate(lines):
                if line.strip().lower() == "*end assembly":
                    insert_index = i
                    break
            if insert_index is None:
                fallback["status"] = "failed"
                fallback["warnings"].append("*End Assembly marker not found")
                return fallback
            new_lines = lines[:insert_index] + assembly_block_lines + lines[insert_index:]
            with open(inp_path, "w") as f:
                f.write("\n".join(new_lines) + "\n")
            fallback["status"] = "injected"
            fallback["assembly_line_count"] = len(assembly_block_lines)
            fallback["coupling_line_count"] = len(coupling_block_lines)
        except Exception as exc:
            fallback["status"] = "failed"
            fallback["warnings"].append("keyword injection failed: {0}".format(exc))
        return fallback

    def inject_odb_output_keyword_fallback(inp_path, boundary_record):
        output_intervals = int(boundary_record.get("output_intervals", 4))
        if output_intervals < 2:
            output_intervals = 2
        if output_intervals > 100:
            output_intervals = 100
        right_set = boundary_record.get("right_reference_point_set", "SCLAS_RP_RightEnd")
        fallback = {
            "status": "not_attempted",
            "inp_file": os.path.basename(inp_path),
            "right_reference_point_set": right_set,
            "output_intervals": output_intervals,
            "warnings": [],
            "notes": [
                "Keyword fallback requests right-reference-point field/history output for ODB moment-curvature extraction without forcing solver increments."
            ],
        }
        if not os.path.exists(inp_path):
            fallback["status"] = "failed"
            fallback["warnings"].append("input file not found")
            return fallback

        output_lines = [
            "**",
            "** SCLAS ODB output keyword fallback",
            "** Request RP output frames without changing Abaqus solver increment controls.",
            "*Output, field, number interval={0}, time marks=NO".format(output_intervals),
            "*Node Output, nset={0}".format(right_set),
            "U, UR, RF, RM",
            "*Output, history, frequency=1",
            "*Node Output, nset={0}".format(right_set),
            "UR2, RM2",
            "** End SCLAS ODB output keyword fallback",
            "**",
        ]
        try:
            with open(inp_path, "r") as f:
                lines = f.read().splitlines()
            end_step_indices = []
            for i, line in enumerate(lines):
                if line.strip().lower() == "*end step":
                    end_step_indices.append(i)
            if not end_step_indices:
                fallback["status"] = "failed"
                fallback["warnings"].append("*End Step marker not found")
                return fallback
            end_step_lookup = {}
            for index in end_step_indices:
                end_step_lookup[index] = True
            new_lines = []
            injected_count = 0
            for i, line in enumerate(lines):
                if i in end_step_lookup:
                    new_lines.extend(output_lines)
                    injected_count += 1
                new_lines.append(line)
            with open(inp_path, "w") as f:
                f.write("\n".join(new_lines) + "\n")
            fallback["status"] = "injected"
            fallback["step_count"] = injected_count
            fallback["line_count"] = len(output_lines) * injected_count
        except Exception as exc:
            fallback["status"] = "failed"
            fallback["warnings"].append("keyword injection failed: {0}".format(exc))
        return fallback

    def adjust_beam_contact_pair_keywords(inp_path, contact_pair_records):
        adjustment = {
            "status": "not_attempted",
            "inp_file": os.path.basename(inp_path),
            "target_type": "NODE TO SURFACE",
            "adjusted_count": 0,
            "beam_surfaces": [],
            "warnings": [],
            "notes": [
                "Abaqus/Standard automatically falls back to node-to-surface for 3D beam/truss slave surfaces; this records that choice explicitly in the generated input deck."
            ],
        }
        if not os.path.exists(inp_path):
            adjustment["status"] = "failed"
            adjustment["warnings"].append("input file not found")
            return adjustment

        beam_surfaces = []
        for record in contact_pair_records or []:
            if record.get("status") != "created":
                continue
            for role in ["master", "slave"]:
                surface_name = record.get(role + "_surface")
                surface_kind = record.get(role + "_surface_kind")
                if surface_name and surface_kind == "beam_line":
                    beam_surfaces.append(str(surface_name))
        beam_surfaces = sorted(set(beam_surfaces))
        adjustment["beam_surfaces"] = beam_surfaces
        if not beam_surfaces:
            adjustment["status"] = "skipped"
            adjustment["warnings"].append("no created contact pairs reference beam-line surfaces")
            return adjustment

        try:
            with open(inp_path, "r") as f:
                lines = f.read().splitlines()
            new_lines = list(lines)
            adjusted_pairs = []
            lower_beam_surfaces = [item.lower() for item in beam_surfaces]
            for index, line in enumerate(lines):
                stripped = line.strip()
                if not stripped.lower().startswith("*contact pair"):
                    continue
                data_index = None
                for candidate in range(index + 1, min(index + 6, len(lines))):
                    candidate_text = lines[candidate].strip()
                    if not candidate_text or candidate_text.startswith("**"):
                        continue
                    if candidate_text.startswith("*"):
                        break
                    data_index = candidate
                    break
                if data_index is None:
                    continue
                data_lower = lines[data_index].lower()
                if not any(surface in data_lower for surface in lower_beam_surfaces):
                    continue
                if "surface to surface" in line.lower():
                    new_line = re.sub("type\\s*=\\s*SURFACE\\s+TO\\s+SURFACE", "type=NODE TO SURFACE", line, flags=re.IGNORECASE)
                elif "node to surface" in line.lower():
                    new_line = line
                else:
                    new_line = line.rstrip() + ", type=NODE TO SURFACE"
                if new_line != new_lines[index]:
                    new_lines[index] = new_line
                    adjusted_pairs.append(lines[data_index].strip())
            if adjusted_pairs:
                with open(inp_path, "w") as f:
                    f.write("\n".join(new_lines) + "\n")
                adjustment["status"] = "adjusted"
                adjustment["adjusted_count"] = len(adjusted_pairs)
                adjustment["adjusted_pairs"] = adjusted_pairs
            else:
                adjustment["status"] = "skipped"
                adjustment["warnings"].append("no matching surface-to-surface contact-pair keywords were found")
        except Exception as exc:
            adjustment["status"] = "failed"
            adjustment["warnings"].append("contact pair keyword adjustment failed: {0}".format(exc))
        return adjustment

    def elem_code_for_solid():
        import abaqusConstants as ac

        return getattr(ac, requested_elem, ac.C3D8R)

    mesh_control_adjustments = []

    def apply_annular_quadrant_partition(part, component_name):
        record = {
            "component": component_name,
            "annular_partition_quadrants": bool(annular_partition_quadrants),
            "partition_planes": [],
            "mesh_controls": [],
            "warnings": [],
        }
        if not annular_partition_quadrants:
            record["status"] = "skipped"
            record["reason"] = "mesh.annular_partition_quadrants is false"
            return record
        try:
            for plane_name, plane_value in [("XZPLANE", XZPLANE), ("YZPLANE", YZPLANE)]:
                datum = part.DatumPlaneByPrincipalPlane(principalPlane=plane_value, offset=0.0)
                part.PartitionCellByDatumPlane(datumPlane=part.datums[datum.id], cells=part.cells[:])
                record["partition_planes"].append(plane_name)
        except Exception as exc:
            record["warnings"].append("quadrant partition failed: {0}".format(exc))
        try:
            part.setMeshControls(regions=part.cells[:], elemShape=HEX, technique=SWEEP)
            record["mesh_controls"].append("HEX_SWEEP")
        except Exception as exc:
            record["warnings"].append("HEX/SWEEP mesh control failed: {0}".format(exc))
        if record["partition_planes"] and record["mesh_controls"]:
            record["status"] = "created"
        elif record["partition_planes"] or record["mesh_controls"]:
            record["status"] = "partial"
        else:
            record["status"] = "failed"
        return record

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
        create_solid_contact_regions(part, inst, name)
        append_solid_end_face_spec(
            name,
            inst.name,
            (offset[0], offset[1], -0.5 * length + offset[2]),
            (offset[0], offset[1], 0.5 * length + offset[2]),
            left_node_labels=end_node_labels(part, 0.0),
            right_node_labels=end_node_labels(part, length),
        )
        return part

    def layer_surface_specs(component_name, inner_radius, outer_radius, inner_surface, outer_surface):
        probe_degrees = [45.0, 135.0, 225.0, 315.0] if annular_partition_quadrants else [37.0]

        def layer_probes(radius, z_value):
            probes = []
            for angle_deg in probe_degrees:
                angle = math.radians(angle_deg)
                probes.append((radius * math.cos(angle), radius * math.sin(angle), z_value))
            return probes

        inner_probes = layer_probes(inner_radius, 0.5 * length)
        outer_probes = layer_probes(outer_radius, 0.5 * length)
        inner_assembly_probes = [(probe[0], probe[1], 0.0) for probe in inner_probes]
        outer_assembly_probes = [(probe[0], probe[1], 0.0) for probe in outer_probes]
        return [
            {
                "label": "inner",
                "radius_mm": inner_radius,
                "part_face_set": "InnerContactFaces",
                "part_surface": "InnerContactSurface",
                "assembly_face_set": inner_surface + "_faces",
                "assembly_surface": inner_surface,
                "part_probe": inner_probes[0],
                "part_probes": inner_probes,
                "assembly_probe": inner_assembly_probes[0],
                "assembly_probes": inner_assembly_probes,
            },
            {
                "label": "outer",
                "radius_mm": outer_radius,
                "part_face_set": "OuterContactFaces",
                "part_surface": "OuterContactSurface",
                "assembly_face_set": outer_surface + "_faces",
                "assembly_surface": outer_surface,
                "part_probe": outer_probes[0],
                "part_probes": outer_probes,
                "assembly_probe": outer_assembly_probes[0],
                "assembly_probes": outer_assembly_probes,
            },
        ]

    def create_annular_cylinder(name, inner_radius, outer_radius, section_name, seed_circ, inner_surface, outer_surface):
        if inner_radius <= 0.0 or outer_radius <= inner_radius:
            return create_solid_cylinder(name, outer_radius, section_name, seed_circ)

        sketch = model.ConstrainedSketch(name=name + "_sketch", sheetSize=max(10.0, outer_radius * 4.0))
        sketch.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(outer_radius, 0.0))
        sketch.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(inner_radius, 0.0))
        part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
        part.BaseSolidExtrude(sketch=sketch, depth=length)
        del model.sketches[sketch.name]
        mesh_control_adjustments.append(apply_annular_quadrant_partition(part, name))
        region = part.Set(cells=part.cells[:], name="AllCells")
        part.SectionAssignment(region=region, sectionName=section_name)
        size_axial = length / float(z_elem)
        size_circ = max(0.1, 2.0 * math.pi * outer_radius / float(seed_circ))
        size_radial = max(0.1, outer_radius - inner_radius)
        part.seedPart(size=max(0.1, min(size_axial, size_circ, size_radial)), deviationFactor=0.1, minSizeFactor=0.1)
        part.setElementType(regions=(part.cells[:],), elemTypes=(ElemType(elemCode=elem_code_for_solid(), elemLibrary=STANDARD),))
        part.generateMesh()
        inst = assembly.Instance(name=name + "_1", part=part, dependent=ON)
        inst.translate(vector=(0.0, 0.0, -0.5 * length))
        probe_angle = math.radians(53.0)
        mid_radius = 0.5 * (inner_radius + outer_radius)
        probe_x = mid_radius * math.cos(probe_angle)
        probe_y = mid_radius * math.sin(probe_angle)
        create_solid_contact_regions(
            part,
            inst,
            name,
            surface_specs=layer_surface_specs(name, inner_radius, outer_radius, inner_surface, outer_surface),
        )
        append_solid_end_face_spec(
            name,
            inst.name,
            (probe_x, probe_y, -0.5 * length),
            (probe_x, probe_y, 0.5 * length),
            left_node_labels=end_node_labels(part, 0.0),
            right_node_labels=end_node_labels(part, length),
        )
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
        inst = assembly.Instance(name=name + "_1", part=part, dependent=ON)
        create_beam_contact_regions(part, inst, name)
        append_end_coupling_node_spec(
            name,
            inst.name,
            left_node_labels=end_node_labels(part, -0.5 * length),
            right_node_labels=end_node_labels(part, 0.5 * length),
        )
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

    create_annular_cylinder(
        "InnerSheathEquivalent",
        float(geometry["inner_sheath_inner_radius_mm"]),
        float(geometry["inner_sheath_outer_radius_mm"]),
        inner_sheath_section,
        core_circ,
        "inner_sheath_inner_surface",
        "inner_sheath_outer_surface",
    )

    create_armour_layer(
        "InnerArmourHelix",
        float(armour["inner_wire_radius_mm"]),
        float(geometry["inner_armour_center_radius_mm"]),
        int(armour["inner_wire_count"]),
        float(armour["inner_lay_angle_deg"]),
        hand=1.0,
    )

    create_annular_cylinder(
        "BeddingEquivalent",
        float(geometry["inner_armour_outer_radius_mm"]),
        float(geometry["bedding_outer_radius_mm"]),
        bedding_section,
        core_circ,
        "bedding_inner_surface",
        "bedding_outer_surface",
    )

    create_armour_layer(
        "OuterArmourHelix",
        float(armour["outer_wire_radius_mm"]),
        float(geometry["outer_armour_center_radius_mm"]),
        int(armour["outer_wire_count"]),
        float(armour["outer_lay_angle_deg"]),
        hand=-1.0,
    )

    create_annular_cylinder(
        "OuterSheathEquivalent",
        float(geometry["outer_sheath_inner_radius_mm"]),
        float(geometry["outer_sheath_outer_radius_mm"]),
        outer_sheath_section,
        core_circ,
        "outer_sheath_inner_surface",
        "outer_sheath_outer_surface",
    )

    boundary_conditions = create_boundary_condition_scaffold()
    contact_pairs = create_explicit_contact_pair_scaffold(contact_property)
    contact_interactions = [create_contact_interaction_scaffold(contact_property, contact_pairs)]
    old_cwd = os.getcwd()
    os.chdir(str(job_dir))
    inp_path = os.path.join(path_text(job_dir), job_name + ".inp")
    try:
        mdb.Job(name=job_name, model=model_name, type=ANALYSIS, description="SCLAS GUI generated mesh scaffold")
        mdb.jobs[job_name].writeInput(consistencyChecking=OFF)
        contact_keyword_adjustment = adjust_beam_contact_pair_keywords(inp_path, contact_pairs)
        for contact_pair in contact_pairs:
            if contact_keyword_adjustment.get("status") == "adjusted" and contact_pair.get("status") == "created":
                contact_pair["input_deck_contact_pair_type"] = contact_keyword_adjustment.get("target_type")
        keyword_fallback = inject_end_coupling_keyword_fallback(inp_path, boundary_conditions)
        boundary_conditions["keyword_coupling_fallback"] = keyword_fallback
        if keyword_fallback.get("status") == "injected":
            if "inp_keyword_coupling_fallback" not in boundary_conditions.get("optional_created_regions", []):
                boundary_conditions.setdefault("optional_created_regions", []).append("inp_keyword_coupling_fallback")
            boundary_conditions["status"] = "created_with_keyword_coupling_fallback"
        else:
            boundary_conditions.setdefault("optional_warnings", []).append(
                "inp keyword coupling fallback {0}".format(keyword_fallback.get("status", "unknown"))
            )
        output_keyword_fallback = inject_odb_output_keyword_fallback(inp_path, boundary_conditions)
        boundary_conditions["keyword_output_fallback"] = output_keyword_fallback
        if output_keyword_fallback.get("status") == "injected":
            if "inp_keyword_output_fallback" not in boundary_conditions.get("optional_created_regions", []):
                boundary_conditions.setdefault("optional_created_regions", []).append("inp_keyword_output_fallback")
        else:
            boundary_conditions.setdefault("optional_warnings", []).append(
                "inp keyword output fallback {0}".format(output_keyword_fallback.get("status", "unknown"))
            )
        cae_path = os.path.join(path_text(job_dir), "sclas_mesh_model.cae")
        mdb.saveAs(pathName=str(cae_path))
    finally:
        os.chdir(old_cwd)

    files = [os.path.basename(path) for path in [cae_path, inp_path] if os.path.exists(path)]
    return {
        "job_name": job_name,
        "model_name": model_name,
        "files": files,
        "contact_property_scaffold": contact_property,
        "contact_region_scaffold": contact_regions,
        "contact_interaction_scaffold": contact_interactions,
        "contact_pair_scaffold": contact_pairs,
        "contact_pair_keyword_adjustment": contact_keyword_adjustment,
        "boundary_condition_scaffold": boundary_conditions,
        "mesh_control_adjustments": mesh_control_adjustments,
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
                contact_property=mesh_status.get("contact_property_scaffold"),
                contact_regions=mesh_status.get("contact_region_scaffold"),
                contact_interactions=mesh_status.get("contact_interaction_scaffold"),
                contact_pairs=mesh_status.get("contact_pair_scaffold"),
                contact_pair_keyword_adjustment=mesh_status.get("contact_pair_keyword_adjustment"),
                boundary_conditions=mesh_status.get("boundary_condition_scaffold"),
                mesh_control_adjustments=mesh_status.get("mesh_control_adjustments"),
            )
            print("Wrote Abaqus mesh scaffold: {0}".format(", ".join(mesh_status.get("files", []))))
        except Exception as exc:
            error_detail = "{0}\n{1}".format(str(exc), traceback.format_exc())
            mesh_status = {"status": "abaqus_mesh_failed", "error": str(exc)}
            write_mesh_manifest(os.path.join(job_dir, "abaqus_mesh_manifest.json"), payload, abaqus_created=False, error=error_detail)
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
