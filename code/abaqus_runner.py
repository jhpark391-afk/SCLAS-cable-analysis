import csv
import json
import os
import sys
import traceback
from datetime import datetime
from decimal import Decimal
from math import sqrt, asin, pi, tan

try:
    import importlib.util as importlib_util
except Exception:
    importlib_util = None

try:
    import imp as imp_loader
except Exception:
    imp_loader = None

try:
    from part import *
    from material import *
    from section import *
    from assembly import *
    from step import *
    from interaction import *
    from load import *
    from mesh import *
    from optimization import *
    from job import *
    from sketch import *
    from visualization import *
    from connectorBehavior import *
    ABAQUS_AVAILABLE = True
except Exception:
    ABAQUS_AVAILABLE = False


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
        for k, moment in zip(curvature, moment_kn_m):
            writer.writerow(["{0:.12g}".format(k), "{0:.12g}".format(moment)])


def merge_odb_extraction_summary(job_dir, extraction_summary):
    summary_path = os.path.join(path_text(job_dir), "result_summary.json")
    summary = {}
    if os.path.exists(summary_path):
        try:
            summary = load_payload(summary_path)
        except Exception:
            summary = {}
    summary["odb_extraction"] = extraction_summary
    if extraction_summary.get("status") != "extracted":
        summary.setdefault("source", "SCLAS_ABAQUS_RUNNER_PLACEHOLDER")
        summary["status"] = "odb_extraction_incomplete"
        summary["note"] = "Abaqus runner did not produce an ODB-backed result_data.csv."
    write_json(summary_path, summary)


def load_python_module_from_path(module_name, module_path):
    if importlib_util is not None:
        spec = importlib_util.spec_from_file_location(module_name, module_path)
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    if imp_loader is not None:
        return imp_loader.load_source(module_name, module_path)
    raise RuntimeError("No Python source module loader is available")


def run_odb_extraction(job_dir, odb_path, input_path):
    summary_path = os.path.join(path_text(job_dir), "odb_extraction_summary.json")
    if not os.path.exists(path_text(odb_path)):
        summary = {
            "status": "missing_odb",
            "reason": "Abaqus job completed but ODB file was not found.",
            "odb_path": path_text(odb_path),
            "created_at": timestamp_seconds(),
        }
        write_json(summary_path, summary)
        merge_odb_extraction_summary(job_dir, summary)
        return 1

    try:
        runner_path = __file__
    except NameError:
        runner_path = sys.argv[0] if sys.argv else os.getcwd()
    here = os.path.dirname(os.path.abspath(runner_path))
    candidates = [
        os.path.join(path_text(job_dir), "sclas_odb_extractor.py"),
        os.path.join(here, "sclas_odb_extractor.py"),
    ]
    extractor_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            extractor_path = candidate
            break
    if extractor_path is None:
        summary = {
            "status": "extractor_missing",
            "reason": "sclas_odb_extractor.py was not found in the job folder or runner folder.",
            "odb_path": path_text(odb_path),
            "created_at": timestamp_seconds(),
        }
        write_json(summary_path, summary)
        merge_odb_extraction_summary(job_dir, summary)
        return 1

    try:
        module = load_python_module_from_path("sclas_odb_extractor_runtime", extractor_path)
        return int(module.main([
            "sclas_odb_extractor.py",
            path_text(odb_path),
            "--job-dir",
            path_text(job_dir),
            "--input-data",
            path_text(input_path),
        ]))
    except Exception as exc:
        summary = {
            "status": "failed",
            "reason": str(exc),
            "traceback": traceback.format_exc(),
            "odb_path": path_text(odb_path),
            "created_at": timestamp_seconds(),
        }
        write_json(summary_path, summary)
        merge_odb_extraction_summary(job_dir, summary)
        return 1


def latest_reference_point_key(assembly):
    return sorted(assembly.referencePoints.keys())[-1]


def parse_input_path(argv):
    candidates = [arg for arg in argv[1:] if arg != "--" and not arg.startswith("-")]
    return candidates[-1] if candidates else "input_data.json"


def as_float(value, default):
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def as_int(value, default):
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def first_present(mapping, keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def normalize_solver_step(solver, step_name, alias_names, defaults):
    step = dict(solver.get(step_name, {}))
    step["initial_increment"] = as_float(
        first_present(step, ["initial_increment", "initialInc", "inInc"], first_present(solver, [alias_names[0]], defaults["initial_increment"])),
        defaults["initial_increment"],
    )
    step["minimum_increment"] = as_float(
        first_present(step, ["minimum_increment", "minimumInc", "minInc"], first_present(solver, [alias_names[1]], defaults["minimum_increment"])),
        defaults["minimum_increment"],
    )
    step["maximum_increment"] = as_float(
        first_present(step, ["maximum_increment", "maximumInc", "maxInc"], first_present(solver, [alias_names[2]], defaults["maximum_increment"])),
        defaults["maximum_increment"],
    )
    step["max_num_increments"] = as_int(
        first_present(step, ["max_num_increments", "maxNumInc", "maxNumIncrements"], first_present(solver, [alias_names[3]], defaults["max_num_increments"])),
        defaults["max_num_increments"],
    )
    return step


def mesh_basis_code(mesh, field_name):
    basis_by_field = mesh.get("mesh_input_basis_by_field", {})
    basis = str(basis_by_field.get(field_name, mesh.get("mesh_input_basis", "count"))).strip().lower()
    return 2 if basis == "size" else 1


def automatic_variable_map(data):
    geo = data.get("geometry_mm", {})
    dgeo = data.get("derived_geometry_mm", {})
    arm = data.get("armour", {})
    ac = data.get("analysis_conditions", {})
    solver = data.get("solver", {})
    mesh = data.get("mesh", {})
    pressure_step = solver.get("pressure_step", {})
    bending_step = solver.get("bending_step", {})
    filler_profile = mesh.get("filler_profile_divisions", {})
    return {
        "source": "input_data.json -> normalize_payload -> abaqus_runner.py",
        "Roc": as_float(geo.get("conductor_radius_mm"), 4.0),
        "RoI": as_float(geo.get("insulation_radius_mm"), 11.3),
        "RoC": as_float(geo.get("core_outer_radius_mm"), 15.3),
        "TIS": as_float(geo.get("inner_sheath_thickness_mm"), 4.5),
        "TOS": as_float(geo.get("outer_sheath_thickness_mm"), 4.5),
        "TB": as_float(geo.get("bedding_thickness_mm", dgeo.get("bedding_thickness_mm")), 0.6),
        "RoIA": as_float(arm.get("inner_wire_radius_mm"), 2.0),
        "RoOA": as_float(arm.get("outer_wire_radius_mm"), 2.0),
        "NoIA": as_int(arm.get("inner_wire_count_resolved", arm.get("inner_wire_count")), 55),
        "NoOA": as_int(arm.get("outer_wire_count_resolved", arm.get("outer_wire_count")), 63),
        "P": as_float(ac.get("external_pressure_mpa", ac.get("hydrostatic_pressure_mpa")), 0.3),
        "FrCo": as_float(ac.get("friction_coefficient"), 0.3),
        "BendFac": as_float(ac.get("max_curvature_1_per_m", ac.get("bend_factor")), 5.0e-5),
        "inIncP": as_float(pressure_step.get("initial_increment"), 1.0e-5),
        "minIncP": as_float(pressure_step.get("minimum_increment"), 1.0e-10),
        "maxIncP": as_float(pressure_step.get("maximum_increment"), 0.1),
        "maxNumIncP": as_int(pressure_step.get("max_num_increments"), 10000),
        "inIncB": as_float(bending_step.get("initial_increment"), 1.0e-5),
        "minIncB": as_float(bending_step.get("minimum_increment"), 1.0e-10),
        "maxIncB": as_float(bending_step.get("maximum_increment"), 0.05),
        "maxNumIncB": as_int(bending_step.get("max_num_increments"), 10000),
        "ZAD": as_int(mesh.get("axial_divisions"), 40),
        "ZADMeshType": mesh_basis_code(mesh, "axial_divisions"),
        "CCD": as_int(mesh.get("core_circumferential_divisions"), 20),
        "CCDMeshType": mesh_basis_code(mesh, "core_circumferential_divisions"),
        "BSCD": as_int(mesh.get("bedding_sheath_circumferential_divisions"), 64),
        "BSCDMeshType": mesh_basis_code(mesh, "bedding_sheath_circumferential_divisions"),
        "ACD": as_int(mesh.get("armour_circumferential_divisions"), 3),
        "ACDMeshType": mesh_basis_code(mesh, "armour_circumferential_divisions"),
        "FD1": as_int(filler_profile.get("short_line"), 2),
        "FD2": as_int(filler_profile.get("long_line"), 2),
        "FD3": as_int(filler_profile.get("short_arc"), 4),
        "FD4": as_int(filler_profile.get("long_arc"), 6),
        "CHA": as_float(arm.get("core_lay_angle_deg"), 9.0),
        "IAHA": as_float(arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")), -20.1),
        "OAHA": as_float(arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")), 19.6),
        "pitch_core": as_float(arm.get("core_pitch_mm", arm.get("core_pitch_length_mm")), 702.6),
        "pitch_inner": as_float(arm.get("inner_armour_pitch_mm", arm.get("inner_armour_pitch_length_mm")), -677.94737),
        "pitch_outer": as_float(arm.get("outer_armour_pitch_mm", arm.get("outer_armour_pitch_length_mm")), 776.55789),
        "Dep": as_float(ac.get("effective_length_mm", dgeo.get("effective_length_mm")), 234.2),
        "conStiff": as_float(ac.get("contact_stiffness_scale_factor", ac.get("conStiff")), 0.05),
        "CPU": as_int(solver.get("cpu_count", solver.get("CPU")), 12),
    }


def core_center_from_outer_radius(core_outer_radius):
    return round(2.0 * sqrt(3.0) * float(core_outer_radius) / 3.0, 5)


def auto_armour_count(wire_radius, center_radius):
    wire_radius = as_float(wire_radius, 0.0)
    center_radius = as_float(center_radius, 0.0)
    if wire_radius <= 0.0 or center_radius <= wire_radius:
        return 1
    ratio = min(0.999999, max(1.0e-9, wire_radius / center_radius))
    return max(1, int(pi / asin(ratio)))


def pitch_from_lay_angle(center_radius, lay_angle_deg, fallback, sign=1.0):
    angle_rad = as_float(lay_angle_deg, 0.0) * pi / 180.0
    tangent = tan(angle_rad)
    if abs(tangent) < 1.0e-9:
        return float(fallback)
    return sign * (2.0 * pi * as_float(center_radius, 0.0) / tangent)


def helix_pitch_length_system(coc, co_ia, co_oa, no_ia, no_oa, cha, iaha, oaha):
    def pitch(radius, angle_deg, fallback):
        tangent = tan(pi / 180 * as_float(angle_deg, 0.0))
        if abs(tangent) < 1.0e-12:
            return Decimal(str(fallback))
        return 2 * Decimal(pi) * Decimal(str(radius)) / Decimal(tangent)

    pitch_core = pitch(coc, cha, 702.6)
    pitch_inner = pitch(co_ia, iaha, -677.94737)
    pitch_outer = pitch(co_oa, oaha, 776.55789)
    no_ia_int = max(1, as_int(no_ia, 55))
    no_oa_int = max(1, as_int(no_oa, 63))
    no_ia_dec = Decimal(no_ia_int)
    no_oa_dec = Decimal(no_oa_int)
    armour_count_factor = Decimal((no_ia_int + no_oa_int) // 6)
    depth = float(
        pitch_core / Decimal(3)
        + armour_count_factor
        * (abs(pitch_inner) / Decimal(no_ia_dec) + abs(pitch_outer) / Decimal(no_oa_dec))
    ) / 3
    return {
        "pitch_core": pitch_core,
        "pitch_inner": pitch_inner,
        "pitch_outer": pitch_outer,
        "effective_length_mm": depth,
    }


def normalized_geometry(data):
    geo = data.get("geometry_mm", {})
    dgeo = data.get("derived_geometry_mm", {})
    arm = data.get("armour", {})

    roc = as_float(geo.get("core_outer_radius_mm", dgeo.get("core_outer_radius_mm")), 15.3)
    coc = core_center_from_outer_radius(roc)
    core_count = as_int(geo.get("core_count", dgeo.get("core_count")), 3)
    r_cond = as_float(geo.get("conductor_radius_mm"), 4.0)
    r_insu = as_float(geo.get("insulation_radius_mm"), 11.3)
    tis = as_float(geo.get("inner_sheath_thickness_mm"), 4.5)
    tos = as_float(geo.get("outer_sheath_thickness_mm"), 4.5)
    gap = as_float(geo.get("clearance_gap_mm"), 0.0)
    ria = as_float(arm.get("inner_wire_radius_mm", dgeo.get("inner_armour_wire_radius_mm")), 2.0)
    roa = as_float(arm.get("outer_wire_radius_mm", dgeo.get("outer_armour_wire_radius_mm")), 2.0)
    bedding = as_float(geo.get("bedding_thickness_mm", dgeo.get("bedding_thickness_mm")), 0.6)

    iris = roc + coc
    oris = iris + tis
    co_ia = oris + gap + ria
    irb = co_ia + ria
    orb = irb + bedding
    co_oa = orb + gap + roa
    iros = co_oa + roa
    oros = iros + tos

    inner_input = as_int(arm.get("inner_wire_count"), 0)
    outer_input = as_int(arm.get("outer_wire_count"), 0)
    inner_resolved = inner_input if inner_input > 0 else auto_armour_count(ria, co_ia)
    outer_resolved = outer_input if outer_input > 0 else auto_armour_count(roa, co_oa)

    return {
        "conductor_radius_mm": r_cond,
        "insulation_radius_mm": r_insu,
        "core_outer_radius_mm": roc,
        "core_count": core_count,
        "core_count_source": geo.get("core_count_source", dgeo.get("core_count_source", "GUI_default_or_user")),
        "core_center_radius_mm": coc,
        "core_center_radius_source": "auto_2sqrt3_over_3_times_core_outer_radius",
        "inner_sheath_inner_radius_mm": iris,
        "inner_sheath_outer_radius_mm": oris,
        "inner_armour_center_radius_mm": co_ia,
        "inner_armour_wire_radius_mm": ria,
        "inner_armour_outer_radius_mm": irb,
        "bedding_thickness_mm": bedding,
        "bedding_outer_radius_mm": orb,
        "outer_armour_center_radius_mm": co_oa,
        "outer_armour_wire_radius_mm": roa,
        "outer_sheath_inner_radius_mm": iros,
        "outer_sheath_outer_radius_mm": oros,
        "inner_armour_wire_count_input": inner_input,
        "outer_armour_wire_count_input": outer_input,
        "inner_armour_wire_count": inner_resolved,
        "outer_armour_wire_count": outer_resolved,
        "inner_armour_wire_count_source": "user" if inner_input > 0 else "auto_from_wire_radius_and_center_radius",
        "outer_armour_wire_count_source": "user" if outer_input > 0 else "auto_from_wire_radius_and_center_radius",
        "filler_count": 3,
        "filler_profile_scale": roc / 15.3,
    }


def normalize_payload(data):
    data = dict(data)
    geometry = normalized_geometry(data)
    geo = dict(data.get("geometry_mm", {}))
    geo.setdefault("conductor_radius_mm", geometry["conductor_radius_mm"])
    geo.setdefault("insulation_radius_mm", geometry["insulation_radius_mm"])
    geo["core_outer_radius_mm"] = geometry["core_outer_radius_mm"]
    geo["core_count"] = geometry["core_count"]
    geo["core_center_radius_mm"] = geometry["core_center_radius_mm"]
    geo.setdefault("inner_sheath_thickness_mm", 4.5)
    geo.setdefault("outer_sheath_thickness_mm", 4.5)
    geo.setdefault("bedding_thickness_mm", geometry["bedding_thickness_mm"])
    geo.setdefault("clearance_gap_mm", 0.0)
    data["geometry_mm"] = geo
    merged_dgeo = dict(data.get("derived_geometry_mm", {}))
    merged_dgeo.update(geometry)
    data["derived_geometry_mm"] = merged_dgeo

    arm = dict(data.get("armour", {}))
    arm.setdefault("inner_wire_radius_mm", geometry["inner_armour_wire_radius_mm"])
    arm.setdefault("outer_wire_radius_mm", geometry["outer_armour_wire_radius_mm"])
    arm.setdefault("inner_wire_count", geometry["inner_armour_wire_count_input"])
    arm.setdefault("outer_wire_count", geometry["outer_armour_wire_count_input"])
    arm.setdefault("core_lay_angle_deg", 9.0)
    arm.setdefault("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg", arm.get("lay_angle_deg", -20.1)))
    arm.setdefault("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg", arm.get("lay_angle_deg", 19.6)))
    pitch_system = helix_pitch_length_system(
        geometry["core_center_radius_mm"],
        geometry["inner_armour_center_radius_mm"],
        geometry["outer_armour_center_radius_mm"],
        geometry["inner_armour_wire_count"],
        geometry["outer_armour_wire_count"],
        arm.get("core_lay_angle_deg"),
        arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")),
        arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")),
    )
    core_pitch_signed = float(pitch_system["pitch_core"])
    inner_pitch_signed = float(pitch_system["pitch_inner"])
    outer_pitch_signed = float(pitch_system["pitch_outer"])
    core_pitch_length = abs(core_pitch_signed)
    inner_pitch_length = abs(inner_pitch_signed)
    outer_pitch_length = abs(outer_pitch_signed)
    arm["core_pitch_length_mm"] = core_pitch_length
    arm["inner_armour_pitch_length_mm"] = inner_pitch_length
    arm["outer_armour_pitch_length_mm"] = outer_pitch_length
    arm["core_pitch_mm"] = core_pitch_signed
    arm["inner_armour_pitch_mm"] = inner_pitch_signed
    arm["outer_armour_pitch_mm"] = outer_pitch_signed
    arm["pitch_formula_source"] = "automatic_py_angle_formula"
    arm["inner_wire_count_resolved"] = geometry["inner_armour_wire_count"]
    arm["outer_wire_count_resolved"] = geometry["outer_armour_wire_count"]
    data["armour"] = arm
    merged_dgeo["core_pitch_length_mm"] = core_pitch_length
    merged_dgeo["inner_armour_pitch_length_mm"] = inner_pitch_length
    merged_dgeo["outer_armour_pitch_length_mm"] = outer_pitch_length
    if isinstance(arm.get("pitch_period_design"), dict):
        merged_dgeo["pitch_period_design"] = arm["pitch_period_design"]
        merged_dgeo.setdefault("pitch_design_source", arm["pitch_period_design"].get("source"))
        merged_dgeo.setdefault("pitch_design_strategy", arm["pitch_period_design"].get("strategy"))
    merged_dgeo["effective_length_mm"] = float(pitch_system["effective_length_mm"])
    merged_dgeo["effective_length_source"] = "automatic_py_Dep_from_pitch_core_inner_outer"
    data["derived_geometry_mm"] = merged_dgeo

    mesh = dict(data.get("mesh", {}))
    mesh.setdefault("axial_divisions", mesh.get("ZAD", 40))
    mesh.setdefault("core_circumferential_divisions", mesh.get("CCD", 20))
    mesh.setdefault("bedding_sheath_circumferential_divisions", mesh.get("BSCD", 64))
    mesh.setdefault("armour_circumferential_divisions", mesh.get("ACD", 3))
    filler_profile = dict(mesh.get("filler_profile_divisions", {}))
    filler_profile.setdefault("short_line", mesh.get("FD1", 2))
    filler_profile.setdefault("long_line", mesh.get("FD2", 2))
    filler_profile.setdefault("short_arc", mesh.get("FD3", 4))
    filler_profile.setdefault("long_arc", mesh.get("FD4", 6))
    mesh["filler_profile_divisions"] = filler_profile
    basis_by_field = dict(mesh.get("mesh_input_basis_by_field", {}))
    mesh_controls = data.get("mesh_controls", {})
    if not basis_by_field and isinstance(mesh_controls, dict):
        basis_by_field = dict(mesh_controls.get("input_basis_by_field", {}))
    default_basis = str(mesh.get("mesh_input_basis", "count")).lower()
    for key in [
        "axial_divisions",
        "core_circumferential_divisions",
        "bedding_sheath_circumferential_divisions",
        "armour_circumferential_divisions",
        "filler_z_divisions",
    ]:
        basis_by_field.setdefault(key, default_basis)
    mesh["mesh_input_basis_by_field"] = basis_by_field
    mesh["mesh_type_codes"] = {
        "ZADMeshType": mesh_basis_code(mesh, "axial_divisions"),
        "CCDMeshType": mesh_basis_code(mesh, "core_circumferential_divisions"),
        "BSCDMeshType": mesh_basis_code(mesh, "bedding_sheath_circumferential_divisions"),
        "ACDMeshType": mesh_basis_code(mesh, "armour_circumferential_divisions"),
    }
    if mesh.get("filler_z_divisions_source") == "same_as_axial_divisions":
        mesh["filler_z_divisions"] = mesh["axial_divisions"]
        mesh["filler_divisions"] = mesh["axial_divisions"]
    else:
        mesh.setdefault("filler_z_divisions", mesh.get("filler_divisions", mesh.get("axial_divisions", 40)))
        mesh.setdefault("filler_divisions", mesh.get("filler_z_divisions", 40))
    mesh.setdefault("solid_element_type", mesh.get("requested_element_type", "C3D8"))
    mesh.setdefault("requested_element_type", mesh.get("solid_element_type", "C3D8"))
    mesh.setdefault("global_seed_size_mm", None)
    mesh.setdefault("contact_regularization_beta", 0.001)
    data["mesh"] = mesh

    ac = dict(data.get("analysis_conditions", {}))
    pressure = ac.get("external_pressure_mpa", ac.get("hydrostatic_pressure_mpa", ac.get("pressure_mpa", 0.3)))
    ac["external_pressure_mpa"] = as_float(pressure, 0.0)
    ac["hydrostatic_pressure_mpa"] = ac["external_pressure_mpa"]
    ac["pressure_mpa"] = ac["external_pressure_mpa"]
    ac.setdefault("effective_length_mm", merged_dgeo.get("effective_length_mm", 234.2))
    ac.setdefault("effective_length_source", merged_dgeo.get("effective_length_source", "core_pitch_length_mm_divided_by_core_count"))
    ac.setdefault("residual_contact_pressure_mpa", 0.3)
    ac.setdefault("friction_coefficient", ac.get("FrCo", 0.3))
    ac.setdefault("contact_stiffness_scale_factor", ac.get("conStiff", 0.05))
    ac.setdefault("conStiff", ac["contact_stiffness_scale_factor"])
    ac.setdefault("max_curvature_1_per_m", ac.get("bend_factor", ac.get("BendFac", 5.0e-5)))
    ac.setdefault("bend_factor", ac["max_curvature_1_per_m"])
    ac.setdefault("curve_factors", [-0.1, -0.05, 0.0, 0.05, 0.1])
    curve_factors = ac.get("curve_factors", [-0.1, -0.05, 0.0, 0.05, 0.1])
    if not isinstance(curve_factors, (list, tuple)):
        curve_factors = [curve_factors]
    ac["curve_factors"] = [as_float(factor, 0.0) for factor in curve_factors]
    ac.setdefault("loading_cycles", 1)
    ac.setdefault("solver_steps", 500)
    ac.setdefault("contact_regularization_beta", mesh.get("contact_regularization_beta", 0.001))
    data["analysis_conditions"] = ac

    solver = dict(data.get("solver", {}))
    pressure_step = normalize_solver_step(
        solver,
        "pressure_step",
        ["inIncP", "minIncP", "maxIncP", "maxNumIncP"],
        {
            "initial_increment": 1.0e-5,
            "minimum_increment": 1.0e-10,
            "maximum_increment": 0.1,
            "max_num_increments": 10000,
        },
    )
    bending_step = normalize_solver_step(
        solver,
        "bending_step",
        ["inIncB", "minIncB", "maxIncB", "maxNumIncB"],
        {
            "initial_increment": 1.0e-5,
            "minimum_increment": 1.0e-10,
            "maximum_increment": 0.05,
            "max_num_increments": 10000,
        },
    )
    solver["pressure_step"] = pressure_step
    solver["bending_step"] = bending_step
    solver.setdefault("initial_increment", bending_step["initial_increment"])
    solver.setdefault("minimum_increment", bending_step["minimum_increment"])
    solver.setdefault("maximum_increment", bending_step["maximum_increment"])
    solver.setdefault("max_num_increments", bending_step["max_num_increments"])
    solver.setdefault("step_time", 1.0)
    solver.setdefault("nlgeom", False)
    solver.setdefault("stabilization_enabled", True)
    solver.setdefault("stabilization_factor", 0.0002)
    solver["cpu_count"] = max(1, as_int(solver.get("cpu_count", solver.get("CPU")), 12))
    solver["CPU"] = solver["cpu_count"]
    data["solver"] = solver

    output = dict(data.get("output_requests", {}))
    field = output.get("field")
    if isinstance(field, dict):
        expanded = []
        if field.get("U_UR", True):
            expanded.extend(["U", "UR"])
        if field.get("RF_RM", True):
            expanded.extend(["RF", "RM"])
        for name in ["S", "CPRESS", "COPEN", "CSLIP", "CSHEAR", "CSTATUS"]:
            if field.get(name, name != "CSTATUS"):
                if name == "CSLIP":
                    expanded.extend(["CSLIP1", "CSLIP2"])
                elif name == "CSHEAR":
                    expanded.extend(["CSHEAR1", "CSHEAR2"])
                else:
                    expanded.append(name)
        output["field"] = expanded
    output.setdefault("field", ["U", "RF", "S", "CPRESS", "COPEN", "CSLIP1", "CSLIP2", "CSHEAR1", "CSHEAR2"])
    output.setdefault("history", ["UR2", "RM2"])
    data["output_requests"] = output

    data.setdefault("modeling", {"model_type": "full_3d", "model_label": "Full 3D"})
    return data


def enabled_assessment_names(payload):
    enabled = payload.get("study_scope", {}).get("enabled_assessments", {})
    return [key for key, is_enabled in enabled.items() if is_enabled]


def build_backend_readiness(payload, source, mesh_status):
    enabled = set(enabled_assessment_names(payload))
    return {
        "bending_stick_slip": {"requested": "bending_stick_slip" in enabled, "status": "placeholder_curve"},
        "contact_friction": {"requested": bool(enabled), "status": "manifest_only"},
        "torsion": {"requested": "torsion" in enabled, "status": "proxy_metric_only"},
        "tension_bending_coupling": {"requested": "tension_bending_coupling" in enabled, "status": "proxy_metric_only"},
        "compression_bird_caging": {"requested": "compression_bird_caging" in enabled, "status": "proxy_metric_only"},
        "pressure_effect": {"requested": "pressure_effect" in enabled, "status": "proxy_metric_only"},
        "source": source,
    }


def fallback_result_curve(data):
    ac = data["analysis_conditions"]
    steps = max(2, as_int(ac.get("solver_steps"), 500))
    kmax = as_float(ac.get("max_curvature_1_per_m"), 5.0e-5)
    friction = as_float(ac.get("friction_coefficient"), 0.3)
    pressure = as_float(ac.get("external_pressure_mpa"), 0.0)
    stiffness = 1.0 + 0.35 * friction + 0.002 * pressure
    curvature = []
    moment = []
    for i in range(steps):
        phase = float(i) / float(max(1, steps - 1))
        k = -kmax + 2.0 * kmax * phase
        curvature.append(k)
        moment.append(k * stiffness)
    return curvature, moment


def fallback_manifest(data):
    geom = data["derived_geometry_mm"]
    ac = data["analysis_conditions"]
    mesh = data["mesh"]
    arm = data.get("armour", {})
    period_design_payload = arm.get("pitch_period_design")
    if not isinstance(period_design_payload, dict):
        period_design_payload = geom.get("pitch_period_design", {})
    if not isinstance(period_design_payload, dict):
        period_design_payload = {}
    pitch_design = {
        "source": period_design_payload.get("source", "automatic_py_pitch_angle_Dep_formula"),
        "strategy": period_design_payload.get("strategy", "direct_angle_pitch_and_Dep_formula"),
        "core_lay_angle_deg": as_float(arm.get("core_lay_angle_deg"), 9.0),
        "inner_armour_lay_angle_deg": as_float(arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")), -20.1),
        "outer_armour_lay_angle_deg": as_float(arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")), 19.6),
        "core_pitch_mm": as_float(
            arm.get("core_pitch_mm", arm.get("core_pitch_length_mm")),
            pitch_from_lay_angle(geom["core_center_radius_mm"], arm.get("core_lay_angle_deg"), 702.6, sign=1.0),
        ),
        "inner_armour_pitch_mm": as_float(
            arm.get("inner_armour_pitch_mm"),
            -abs(as_float(
                arm.get("inner_armour_pitch_length_mm"),
                pitch_from_lay_angle(geom["inner_armour_center_radius_mm"], arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")), -677.94737, sign=-1.0),
            )),
        ),
        "outer_armour_pitch_mm": as_float(
            arm.get("outer_armour_pitch_mm", arm.get("outer_armour_pitch_length_mm")),
            pitch_from_lay_angle(geom["outer_armour_center_radius_mm"], arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")), 776.55789, sign=1.0),
        ),
        "effective_length_mm": as_float(ac.get("effective_length_mm"), geom.get("effective_length_mm", 234.2)),
        "effective_length_source": ac.get("effective_length_source", geom.get("effective_length_source", "automatic_py_Dep_from_pitch_core_inner_outer")),
        "period_multipliers": {
            "inner_armour": arm.get("inner_armour_period_multiplier"),
            "outer_armour": arm.get("outer_armour_period_multiplier"),
        },
        "pitch_period_design": period_design_payload,
    }
    defaults = {
        "normal": "penalty_or_augmented_lagrange",
        "tangential": "regularized_coulomb",
        "friction_coefficient": as_float(ac.get("friction_coefficient"), 0.3),
        "residual_contact_pressure_mpa": as_float(ac.get("residual_contact_pressure_mpa"), 0.3),
        "regularization_beta": as_float(ac.get("contact_regularization_beta", mesh.get("contact_regularization_beta")), 0.001),
    }
    bindings = []
    for name in [
        "inner_armour_to_inner_sheath",
        "inner_armour_to_bedding",
        "outer_armour_to_bedding",
        "outer_armour_to_outer_sheath",
        "armour_cross_layer_interaction",
    ]:
        bindings.append({"name": name, "status": "resolved_scaffold_not_bound_to_pair"})
    return {
        "status": "mesh_request_only",
        "created_at": timestamp_seconds(),
        "geometry_transform": geom,
        "automatic_variable_map": automatic_variable_map(data),
        "pitch_design": pitch_design,
        "mesh_settings_from_gui": mesh,
        "contact_interface_defaults": defaults,
        "contact_binding_scaffold": bindings,
        "contact_property_scaffold": {"status": "not_created"},
        "contact_region_scaffold_status": "not_created",
        "contact_interaction_scaffold_status": "not_created",
        "contact_pair_scaffold_status": "not_created",
        "boundary_condition_scaffold_status": "not_created",
        "equivalent_properties_from_gui": data.get("equivalent_properties", {}),
        "components": [
            {"name": "core_solids", "count": geom.get("core_count", 3), "current_backend_default": 3},
            {"name": "inner_sheath_equivalent_solid"},
            {"name": "filler_matrix_solids", "count": geom["filler_count"], "profile_scale": geom["filler_profile_scale"]},
            {"name": "bedding_equivalent_solid"},
            {"name": "outer_sheath_equivalent_solid"},
            {"name": "inner_armour_helical_beams", "count": geom["inner_armour_wire_count"]},
            {"name": "outer_armour_helical_beams", "count": geom["outer_armour_wire_count"]},
        ],
    }


def fallback_summary(data, mesh_status, curvature, moment_kn_m):
    enabled = enabled_assessment_names(data)
    return {
        "source": "SCLAS_ABAQUS_MESH_BRIDGE",
        "status": "mesh_request_only",
        "result_contract": {"required_columns": ["curvature_1_per_m", "moment_kn_m"]},
        "backend_readiness": build_backend_readiness(data, "SCLAS_ABAQUS_MESH_BRIDGE", mesh_status),
        "hysteresis_loss_kj_per_m_proxy": 0.0,
        "derived_placeholder_metrics": {
            "axial_torsional_stiffness_matrix_proxy": [[1.0, 0.0], [0.0, 1.0]],
            "calibration_targets": {
                "friction_coefficient": data["analysis_conditions"]["friction_coefficient"],
                "external_pressure_mpa": data["analysis_conditions"]["external_pressure_mpa"],
            },
            "pressure_softening_factor": 1.0,
            "bird_caging_risk_index": 0.0,
        },
        "enabled_assessments": enabled,
        "num_points": len(curvature),
        "mesh_status": mesh_status,
    }


def _as_float(value, default):
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _as_int(value, default):
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _mat_by_index_or_alias(materials, index, aliases):
    for item in materials:
        try:
            if int(item.get('index')) == int(index):
                return item
        except Exception:
            pass
    alias_text = [str(a).lower() for a in aliases]
    for item in materials:
        text = (str(item.get('name', '')) + ' ' + str(item.get('material', ''))).replace('_', ' ').lower()
        if any(alias in text for alias in alias_text):
            return item
    raise KeyError('Required material not found: index=%s aliases=%s' % (index, ','.join(aliases)))


def build_abaqus_model(data, job_dir):
    """Build and run the Abaqus model using the automatic.py body.

    Intended as a candidate for review only. Production code still lives in
    code/abaqus_runner.py.
    """
    geo = data.get('geometry_mm', {})
    dgeo = data.get('derived_geometry_mm', {})
    arm = data.get('armour', {})
    ac = data.get('analysis_conditions', {})
    sol = data.get('solver', {})
    msh = data.get('mesh', {})

    Roc  = Decimal(str(_as_float(geo.get('conductor_radius_mm', geo.get('Roc')), 4.0)))
    RoI  = Decimal(str(_as_float(geo.get('insulation_radius_mm', geo.get('RoI')), 11.3)))
    RoC  = Decimal(str(_as_float(geo.get('core_outer_radius_mm', geo.get('RoC')), 15.3)))
    TIS  = Decimal(str(_as_float(geo.get('inner_sheath_thickness_mm', geo.get('TIS')), 4.5)))
    TOS  = Decimal(str(_as_float(geo.get('outer_sheath_thickness_mm', geo.get('TOS')), 4.5)))
    RoIA = Decimal(str(_as_float(arm.get('inner_wire_radius_mm', arm.get('RoIA')), 2.0)))
    RoOA = Decimal(str(_as_float(arm.get('outer_wire_radius_mm', arm.get('RoOA')), 2.0)))
    TB   = Decimal(str(_as_float(dgeo.get('bedding_thickness_mm', geo.get('bedding_thickness_mm', geo.get('TB'))), 0.6)))

    CoC  = Decimal(round((2*sqrt(3)*float(RoC)/3), 5))
    IRIS = RoC + CoC
    ORIS = IRIS + TIS
    CoIA = RoIA + ORIS
    IRB  = CoIA + RoIA
    ORB  = IRB + TB
    CoOA = RoOA + ORB
    IROS = CoOA + RoOA
    OROS = IROS + TOS
    scale = RoC / Decimal('15.3')

    NoIA = _as_int(arm.get('inner_wire_count', arm.get('NoIA')), 55)
    NoOA = _as_int(arm.get('outer_wire_count', arm.get('NoOA')), 63)

    RAoIA = round(Decimal(360) / Decimal(NoIA), 5)
    RAoOA = round(Decimal(360) / Decimal(NoOA), 5)

    P = _as_float(ac.get('external_pressure_mpa', ac.get('hydrostatic_pressure_mpa', ac.get('P'))), 0.3)
    FrCo = _as_float(ac.get('friction_coefficient', ac.get('FrCo')), 0.2)
    BendFac = _as_float(ac.get('max_curvature_1_per_m', ac.get('bend_factor', ac.get('BendFac'))), 5e-05)

    pstep = sol.get('pressure_step', {}) if isinstance(sol.get('pressure_step', {}), dict) else {}
    bstep = sol.get('bending_step', {}) if isinstance(sol.get('bending_step', {}), dict) else {}
    inIncP = _as_float(pstep.get('initial_increment', sol.get('initial_increment', sol.get('inIncP'))), 1e-05)
    minIncP = _as_float(pstep.get('minimum_increment', sol.get('minimum_increment', sol.get('minIncP'))), 1e-10)
    maxIncP = _as_float(pstep.get('maximum_increment', sol.get('maximum_increment', sol.get('maxIncP'))), 0.1)
    maxNumIncP = _as_int(pstep.get('max_num_increments', sol.get('max_num_increments', sol.get('maxNumIncP'))), 10000)

    inIncB = _as_float(bstep.get('initial_increment', sol.get('initial_increment', sol.get('inIncB'))), 1e-05)
    minIncB = _as_float(bstep.get('minimum_increment', sol.get('minimum_increment', sol.get('minIncB'))), 1e-10)
    maxIncB = _as_float(bstep.get('maximum_increment', sol.get('maximum_increment', sol.get('maxIncB'))), 0.05)
    maxNumIncB = _as_int(bstep.get('max_num_increments', sol.get('max_num_increments', sol.get('maxNumIncB'))), 10000)

    ZAD = _as_int(msh.get('axial_divisions', msh.get('ZAD')), 40)
    ZADMeshType = _as_int(msh.get('ZADMeshType'), 1)
    CCD = _as_int(msh.get('core_circumferential_divisions', msh.get('CCD')), 20)
    BSCD = _as_int(msh.get('bedding_sheath_circumferential_divisions', msh.get('BSCD')), 64)
    ACD = _as_int(msh.get('armour_circumferential_divisions', msh.get('ACD')), 3)
    CCDMeshType = _as_int(msh.get('CCDMeshType'), 1)
    BSCDMeshType = _as_int(msh.get('BSCDMeshType'), 1)
    ACDMeshType = _as_int(msh.get('ACDMeshType'), 1)
    BSRD = _as_int(msh.get('BSRD'), 3)
    BSRDMeshType = _as_int(msh.get('BSRDMeshType'), 1)
    filler_profile = msh.get('filler_profile_divisions', {}) if isinstance(msh.get('filler_profile_divisions', {}), dict) else {}
    FD1 = _as_int(filler_profile.get('short_line', msh.get('FD1')), 2)
    FD2 = _as_int(filler_profile.get('long_line', msh.get('FD2')), 2)
    FD3 = _as_int(filler_profile.get('short_arc', msh.get('FD3')), 4)
    FD4 = _as_int(filler_profile.get('long_arc', msh.get('FD4')), 6)
    FDMeshType = _as_int(msh.get('FDMeshType'), 1)

    CHA = _as_float(arm.get('core_lay_angle_deg', arm.get('CHA')), 9.0)
    IAHA = _as_float(arm.get('inner_armour_lay_angle_deg', arm.get('inner_lay_angle_deg', arm.get('IAHA'))), -20.1)
    OAHA = _as_float(arm.get('outer_armour_lay_angle_deg', arm.get('outer_lay_angle_deg', arm.get('OAHA'))), 19.6)

    pitch_core = 2*Decimal(pi)* Decimal(CoC)/ Decimal(tan(pi/180*CHA))
    pitch_inner = 2*Decimal(pi)* Decimal(CoIA)/ Decimal(tan(pi/180*IAHA))
    pitch_outer = 2*Decimal(pi)* Decimal(CoOA)/ Decimal(tan(pi/180*OAHA))

    Dep = float(pitch_core/3 +
       Decimal((NoIA+NoOA)/6)*(abs(pitch_inner)/Decimal(NoIA) + abs(pitch_outer)/Decimal(NoOA)
        ))/3
    conStiff = _as_float(ac.get('contact_stiffness_scale_factor', ac.get('conStiff')), 0.05)
    CPU = _as_int(sol.get('cpu_count', sol.get('CPU')), 12)

    mat_data = data['materials']
    mat_map = {
        'Conductor':   (1, ['conductor', 'copper']),
        'Insulation':  (2, ['insulation', 'xlpe']),
        'CoreShield':  (3, ['core shield', 'coreshield']),
        'InnerSheath': (5, ['inner sheath', 'innersheath']),
        'InnerArmour': (6, ['inner armour', 'inner armor', 'steel', 'armour', 'armor']),
        'Bedding':     (7, ['bedding', 'pfr']),
        'OuterArmour': (8, ['outer armour', 'outer armor', 'steel', 'armour', 'armor']),
        'OuterSheath': (9, ['outer sheath', 'outersheath']),
        'Filler':      (4, ['filler', 'pp']),
    }

    old_cwd = os.getcwd()
    job_dir = os.path.abspath(str(job_dir))
    if not os.path.isdir(job_dir):
        os.makedirs(job_dir)
    os.chdir(job_dir)
    cae_path = os.path.join(job_dir, 'Cable_Bending.cae')
    try:
        mdb.Model(name='Model-1')
        m  = mdb.models['Model-1']
        ra = m.rootAssembly

        mat_data = data['materials']
        mat_map = {
            'Conductor':   1,
            'Insulation':  2,
            'CoreShield':  3,
            'InnerSheath': 5,
            'InnerArmour': 6,
            'Bedding':     7,
            'OuterArmour': 8,
            'OuterSheath': 9,
            'Filler':      4,
        }

        materials = []
        for name, idx in mat_map.items():
            mat = next(i for i in mat_data if i['index'] == idx)
            E  = mat['elastic_modulus_GPa'] * 1000
            nu = mat['poisson_ratio']
            materials.append((name, E, nu))

        for name, E, nu in materials:
            m.Material(name=name)
            m.materials[name].Elastic(table=((E, nu), ))
            m.HomogeneousSolidSection(material=name, name=name, thickness=None)

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+Roc)))
        m.Part(dimensionality=THREE_D, name='Conductor', type=DEFORMABLE_BODY)
        p = m.parts['Conductor']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_core), sketch=sk)
        p.Set(cells=p.cells[:], name='Conductor')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['Conductor'], sectionName='Conductor', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+RoI)))
        sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+Roc)))
        m.Part(dimensionality=THREE_D, name='Insulation', type=DEFORMABLE_BODY)
        p = m.parts['Insulation']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_core), sketch=sk)
        p.Set(cells=p.cells[:], name='Insulation')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['Insulation'], sectionName='Insulation', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+RoI)))
        sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(IRIS)))
        m.Part(dimensionality=THREE_D, name='CoreShield', type=DEFORMABLE_BODY)
        p = m.parts['CoreShield']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_core), sketch=sk)
        p.Set(cells=p.cells[:], name='CoreShield')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['CoreShield'], sectionName='CoreShield', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        for i in range(3):
            ra.Instance(dependent=ON, name='Conductor-%d' % (i+1), part=m.parts['Conductor'])
            ra.Instance(dependent=ON, name='Insulation-%d' % (i+1), part=m.parts['Insulation'])
            ra.Instance(dependent=ON, name='CoreShield-%d' % (i+1), part=m.parts['CoreShield'])
            ra.InstanceFromBooleanMerge(domain=GEOMETRY,
                instances=(ra.instances['CoreShield-%d' % (i+1)],
                           ra.instances['Insulation-%d' % (i+1)],
                           ra.instances['Conductor-%d' % (i+1)]),
                keepIntersections=ON, name='Core', originalInstances=SUPPRESS)

        p = m.parts['Core']
        if CCDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#29 ]', ), ), number=CCD)
        elif CCDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#29 ]', ), ), size=CCD)
        if ZADMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#40 ]', ), ), number=ZAD)
        elif ZADMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#40 ]', ), ), size=ZAD)
        p.setMeshControls(algorithm=MEDIAL_AXIS,
            regions=p.cells.getSequenceFromMask(('[#7 ]', ), ))

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()
        for i in range(3):
            ra.rotate(angle=120 * i, axisDirection=(0.0, 0.0, 1.0),
                axisPoint=(0.0, 0.0, 0.0), instanceList=('Core-%d' % (i+1),))

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IRIS)))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(ORIS)))
        m.Part(dimensionality=THREE_D, name='InnerSheath', type=DEFORMABLE_BODY)
        p = m.parts['InnerSheath']
        p.BaseSolidExtrude(depth=Dep, sketch=sk)
        p.Set(cells=p.cells[:], name='InnerSheath')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['InnerSheath'], sectionName='InnerSheath', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        datum_yz =p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
        datum_xz = p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
            datumPlane=p.datums[datum_yz.id])
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
            datumPlane=p.datums[datum_xz.id])
        if ZADMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=ZAD)
        elif ZADMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), size=ZAD)

        if BSCDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), number=int(BSCD/4))
        elif BSCDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), size=BSCD)






        if BSRDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2000000 ]', ), ), number=BSRD)
        elif BSRDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2000000 ]', ), ), size=BSRD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()

        ra.Instance(dependent=ON, name='InnerSheath', part=m.parts['InnerSheath'])

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.ArcByCenterEnds(center=(0.0, float(CoIA)),
            direction=COUNTERCLOCKWISE,
            point1=(0.0, float(IRB)),
            point2=(0.0, float(ORIS)))
        sk.ArcByCenterEnds(center=(0.0, float(CoIA)),
            direction=CLOCKWISE,
            point1=(0.0, float(IRB)),
            point2=(0.0, float(ORIS)))
        m.Part(dimensionality=THREE_D, name='InnerArmour', type=DEFORMABLE_BODY)
        p = m.parts['InnerArmour']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_inner), sketch=sk)
        p.Set(cells=p.cells[:], name='InnerArmour')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['InnerArmour'], sectionName='InnerArmour', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']


        p.Set(edges=mdb.models['Model-1'].parts['InnerArmour'].edges.getSequenceFromMask((
            '[#8 ]', ), ), name='IAL')
        p.Set(edges=mdb.models['Model-1'].parts['InnerArmour'].edges.getSequenceFromMask((
            '[#2 ]', ), ), name='IAO')

        if ACDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#11 ]', ), ), number=ACD)
        elif ACDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#11 ]', ), ), size=ACD)



        if ACDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), number=ZAD)
        elif ACDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), size=ZAD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()



        for i in range(NoIA):
            ra.Instance(dependent=ON, name='InnerArmour-%d' % (i+1), part=m.parts['InnerArmour'])
            ra.rotate(angle=float(RAoIA) * i, axisDirection=(0.0, 0.0, 1.0),
                axisPoint=(0.0, 0.0, 0.0), instanceList=('InnerArmour-%d' % (i+1),))

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IRB)))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(ORB)))
        m.Part(dimensionality=THREE_D, name='Bedding', type=DEFORMABLE_BODY)
        p = m.parts['Bedding']
        p.BaseSolidExtrude(depth=Dep, sketch=sk)
        p.Set(cells=p.cells[:], name='Bedding')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['Bedding'], sectionName='Bedding', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        datum_yz =p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
        datum_xz = p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
            datumPlane=p.datums[datum_yz.id])
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
            datumPlane=p.datums[datum_xz.id])
        if ZADMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=ZAD)
        elif ZADMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), size=ZAD)
        if BSCDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), number=int(BSCD/4))
        elif BSCDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), size=BSCD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()


        ra.Instance(dependent=ON, name='Bedding', part=m.parts['Bedding'])

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.ArcByCenterEnds(center=(0.0, float(CoOA)),
            direction=COUNTERCLOCKWISE,
            point1=(0.0, float(IROS)),
            point2=(0.0, float(ORB)))
        sk.ArcByCenterEnds(center=(0.0, float(CoOA)),
            direction=CLOCKWISE,
            point1=(0.0, float(IROS)),
            point2=(0.0, float(ORB)))
        m.Part(dimensionality=THREE_D, name='OuterArmour', type=DEFORMABLE_BODY)
        p = m.parts['OuterArmour']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_outer), sketch=sk)
        p.Set(cells=p.cells[:], name='OuterArmour')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['OuterArmour'], sectionName='OuterArmour', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        p.Set(edges=p.edges.getSequenceFromMask(('[#8 ]', ), ), name='OAL')
        p.Set(edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), name='OAO')

        if ACDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#11 ]', ), ), number=ACD)
        elif ACDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#11 ]', ), ), size=ACD)
        if ZADMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), number=ZAD)
        elif ZADMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), size=ZAD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()

        for i in range(NoOA):
            ra.Instance(dependent=ON, name='OuterArmour-%d' % (i+1), part=m.parts['OuterArmour'])
            ra.rotate(angle=float(RAoOA) * i, axisDirection=(0.0, 0.0, 1.0),
                axisPoint=(0.0, 0.0, 0.0), instanceList=('OuterArmour-%d' % (i+1),))

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IROS)))
        sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(OROS)))
        m.Part(dimensionality=THREE_D, name='OuterSheath', type=DEFORMABLE_BODY)
        p = m.parts['OuterSheath']
        p.BaseSolidExtrude(depth=Dep, pitch=0, sketch=sk)
        p.Set(cells=p.cells[:], name='OuterSheath')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['OuterSheath'], sectionName='OuterSheath', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        datum_yz =p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
        datum_xz = p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
            datumPlane=p.datums[datum_yz.id])
        p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
            datumPlane=p.datums[datum_xz.id])

        if ZADMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=ZAD)
        elif ZADMeshType == 1:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), size=ZAD)

        if BSCDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), number=int(BSCD/4))
        elif BSCDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#10500800 ]', ), ), size=BSCD)

        if BSRDMeshType == 1:    
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#80000 ]', ), ), number=BSRD)
        elif BSRDMeshType == 2: 
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#80000 ]', ), ), size=BSRD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()

        ra.Instance(dependent=ON, name='OuterSheath', part=m.parts['OuterSheath'])

        m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
        sk = m.sketches['__profile__']
        sk.Spot(point=(0.0, 0.0))

        sk.Line(point1=(-1.29772369663124 * float(scale), -15.0 * float(scale)),
            point2=(1.29772369679995 * float(scale), -15.0 * float(scale)))
        sk.Line(point1=(-15.0 * float(scale), -29.3567337128366 * float(scale)),
            point2=(-15.0 * float(scale), -24.1305185109377 * float(scale)))
        sk.Line(point1=(15.0 * float(scale), -29.3567337128366 * float(scale)),
            point2=(15.0 * float(scale), -24.1305185109377 * float(scale)))
        sk.ArcByCenterEnds(center=(-15.3000015266274 * float(scale), -8.83346 * float(scale)),
            direction=COUNTERCLOCKWISE,
            point1=(-15.0 * float(scale), -24.1305185109377 * float(scale)),
            point2=(-1.29772369663124 * float(scale), -15.0 * float(scale)))
        sk.ArcByCenterEnds(center=(15.3000015266274 * float(scale), -8.83346 * float(scale)),
            direction=CLOCKWISE,
            point1=(15.0 * float(scale), -24.1305185109377 * float(scale)),
            point2=(1.29772369679995 * float(scale), -15.0 * float(scale)))
        sk.ArcByCenterEnds(center=(0.0, 0.0),
            direction=COUNTERCLOCKWISE,
            point1=(-15.0 * float(scale), -29.3567337128366 * float(scale)),
            point2=(15.0 * float(scale), -29.3567337128366 * float(scale)))

        m.Part(dimensionality=THREE_D, name='Filler', type=DEFORMABLE_BODY)
        p = m.parts['Filler']
        p.BaseSolidExtrude(depth=Dep, pitch=float(pitch_core), sketch=sk)
        p.Set(cells=p.cells[:], name='Filler')
        p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
            region=p.sets['Filler'], sectionName='Filler', thicknessAssignment=FROM_SECTION)
        del m.sketches['__profile__']

        if FDMeshType == 1:
            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=FD1)

            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#a280 ]', ), ), number=FD2)

            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#30050 ]', ), ), number=FD3)

            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#1400 ]', ), ), number=FD4)

            p.seedEdgeByNumber(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#492a ]', ), ), number=ZAD)

        elif FDMeshType == 2:
            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), size=FD1)

            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#a280 ]', ), ), size=FD2)

            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#30050 ]', ), ), size=FD3)

            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#1400 ]', ), ), size=FD4)

            p.seedEdgeBySize(constraint=FINER,
                edges=p.edges.getSequenceFromMask(('[#492a ]', ), ), size=ZAD)

        p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
            secondOrderAccuracy=OFF, distortionControl=DEFAULT),
            ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
            regions=(p.cells[:], ))
        p.generateMesh()

        for i in range(3):
            ra.Instance(dependent=ON, name='Filler-%d' % (i+1), part=m.parts['Filler'])
            ra.rotate(angle=120 * i, axisDirection=(0.0, 0.0, 1.0),
                axisPoint=(0.0, 0.0, 0.0), instanceList=('Filler-%d' % (i+1),))

        ra.regenerate()

        all_instances = ['Core-1', 'Core-2', 'Core-3', 'InnerSheath', 'Bedding', 'OuterSheath']
        for i in range(NoIA):
            all_instances.append('InnerArmour-%d' % (i+1))
        for i in range(NoOA):
            all_instances.append('OuterArmour-%d' % (i+1))
        for i in range(3):
            all_instances.append('Filler-%d' % (i+1))


        m.parts['Bedding'].Surface(name='BeddingO', side1Faces=m.parts['Bedding'].faces.getSequenceFromMask(('[#12088 ]', ), ))
        m.parts['Bedding'].Surface(name='BeddingI', side1Faces=m.parts['Bedding'].faces.getSequenceFromMask(('[#28110 ]', ), ))
        m.parts['Core'].Surface(name='CO', side1Faces=m.parts['Core'].faces.getSequenceFromMask(('[#20 ]', ), ))
        m.parts['Filler'].Surface(name='FO', side1Faces=m.parts['Filler'].faces.getSequenceFromMask(('[#8 ]', ), ))
        m.parts['Filler'].Surface(name='FL', side1Faces=m.parts['Filler'].faces.getSequenceFromMask(('[#20 ]', ), ))
        m.parts['Filler'].Surface(name='FR', side1Faces=m.parts['Filler'].faces.getSequenceFromMask(('[#2 ]', ), ))
        m.parts['InnerArmour'].Surface(name='IAS', side1Faces=m.parts['InnerArmour'].faces.getSequenceFromMask(('[#1 ]', ), ))
        m.parts['InnerSheath'].Surface(name='ISO', side1Faces=m.parts['InnerSheath'].faces.getSequenceFromMask(('[#12088 ]', ), ))
        m.parts['InnerSheath'].Surface(name='IAI', side1Faces=m.parts['InnerSheath'].faces.getSequenceFromMask(('[#28110 ]', ), ))
        m.parts['OuterArmour'].Surface(name='OAS', side1Faces=m.parts['OuterArmour'].faces.getSequenceFromMask(('[#1 ]', ), ))
        m.parts['OuterSheath'].Surface(name='OSI', side1Faces=m.parts['OuterSheath'].faces.getSequenceFromMask(('[#28110 ]', ), ))
        ra.regenerate()

        m.ContactProperty('IntProp-1')
        m.interactionProperties['IntProp-1'].TangentialBehavior(
            dependencies=0, directionality=ISOTROPIC, elasticSlipStiffness=None,
            formulation=PENALTY, fraction=0.001, maximumElasticSlip=FRACTION,
            pressureDependency=OFF, shearStressLimit=None, slipRateDependency=OFF,
            table=((FrCo, ), ), temperatureDependency=OFF)




        m.interactionProperties['IntProp-1'].NormalBehavior(
            allowSeparation=ON, clearanceAtZeroContactPressure=0.0,
            constraintEnforcementMethod=PENALTY, contactStiffness=DEFAULT,
            contactStiffnessScaleFactor=conStiff, lowerQuadraticRatio=0.33333,
            pressureOverclosure=HARD, stiffnessBehavior=NONLINEAR, stiffnessRatio=0.01,
            upperQuadraticFactor=0.03)
        ra.regenerate()
        # --------------------------------------------------
        # Surface-to-edge contact interactions
        # Original-style contact definition
        # --------------------------------------------------

        # Inner Armour contacts
        for i in range(1, int(NoIA)+1):

            m.SurfaceToSurfaceContactStd(
                name='InnerSheath-InnerArmour-%d' % i,
                createStepName='Initial',
                master=ra.instances['InnerSheath'].surfaces['ISO'],
                slave=ra.instances['InnerArmour-%d' % i].sets['IAL'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=NODE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )

            m.SurfaceToSurfaceContactStd(
                name='Bedding-InnerArmour-%d' % i,
                createStepName='Initial',
                master=ra.instances['Bedding'].surfaces['BeddingI'],
                slave=ra.instances['InnerArmour-%d' % i].sets['IAO'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=NODE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )


        # Outer Armour contacts
        for i in range(1, int(NoOA)+1):

            m.SurfaceToSurfaceContactStd(
                name='Bedding-OuterArmour-%d' % i,
                createStepName='Initial',
                master=ra.instances['Bedding'].surfaces['BeddingO'],
                slave=ra.instances['OuterArmour-%d' % i].sets['OAL'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=NODE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )

            m.SurfaceToSurfaceContactStd(
                name='OuterSheath-OuterArmour-%d' % i,
                createStepName='Initial',
                master=ra.instances['OuterSheath'].surfaces['OSI'],
                slave=ra.instances['OuterArmour-%d' % i].sets['OAO'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=NODE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )
        # --------------------------------------------------
        # Core / Filler to InnerSheath contact interactions
        # Surface-to-surface contact definition
        # --------------------------------------------------

        # Core outer surface to InnerSheath inner surface
        for i in range(1, 4):

            m.SurfaceToSurfaceContactStd(
                name='InnerSheath-Core-%d' % i,
                createStepName='Initial',
                master=ra.instances['InnerSheath'].surfaces['IAI'],
                slave=ra.instances['Core-%d' % i].surfaces['CO'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=SURFACE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )


        # Filler outer curved surface to InnerSheath inner surface
        for i in range(1, 4):

            m.SurfaceToSurfaceContactStd(
                name='InnerSheath-FillerOuter-%d' % i,
                createStepName='Initial',
                master=ra.instances['InnerSheath'].surfaces['IAI'],
                slave=ra.instances['Filler-%d' % i].surfaces['FO'],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=SURFACE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )

        # --------------------------------------------------
        # Core to Filler side contact interactions
        # Surface-to-surface contact definition
        # --------------------------------------------------

        core_filler_pairs = (
            (1, 'FL', 2),
            (1, 'FR', 3),
            (2, 'FL', 3),
            (2, 'FR', 1),
            (3, 'FL', 1),
            (3, 'FR', 2),
        )

        for filler_id, filler_side, core_id in core_filler_pairs:

            m.SurfaceToSurfaceContactStd(
                name='Core-%d-Filler-%d-%s' % (core_id, filler_id, filler_side),
                createStepName='Initial',
                master=ra.instances['Core-%d' % core_id].surfaces['CO'],
                slave=ra.instances['Filler-%d' % filler_id].surfaces[filler_side],
                interactionProperty='IntProp-1',
                sliding=SMALL,
                enforcement=SURFACE_TO_SURFACE,
                adjustMethod=OVERCLOSED,
                initialClearance=OMIT,
                clearanceRegion=None,
                datumAxis=None,
                smooth=0.2,
                surfaceSmoothing=NONE,
                thickness=ON,
                tied=OFF
            )
        # --------------------------------------------------
        # Core to Core self-contact
        # Core-1, Core-2, Core-3 outer surfaces are combined
        # into one assembly-level surface.
        # --------------------------------------------------

        core_self_faces = None

        for i in range(1, 4):
            faces_i = ra.instances['Core-%d' % i].surfaces['CO'].faces
            core_self_faces = faces_i if core_self_faces is None else core_self_faces + faces_i

        ra.Surface(
            name='CoreSelfSurf',
            side1Faces=core_self_faces
        )

        m.SelfContactStd(
            name='Core-SelfContact',
            createStepName='Initial',
            surface=ra.surfaces['CoreSelfSurf'],
            interactionProperty='IntProp-1',
            thickness=ON
        )

        ra.regenerate()



        rp = ra.ReferencePoint(point=(float(OROS) + 30.0, 0.0, 0.0))
        ra.Set(name='RP', referencePoints=(ra.referencePoints[rp.id], ))

        left_nodes = None
        right_nodes = None

        tol = 1.0e-3
        box = 1.0e9
        dep_f = float(Dep)

        for inst_name in all_instances:
            inst = ra.instances[inst_name]

            nodes_right_i = inst.nodes.getByBoundingBox(
                xMin=-box,
                yMin=-box,
                zMin=-tol,
                xMax=box,
                yMax=box,
                zMax=tol
            )

            nodes_left_i = inst.nodes.getByBoundingBox(
                xMin=-box,
                yMin=-box,
                zMin=dep_f - tol,
                xMax=box,
                yMax=box,
                zMax=dep_f + tol
            )

            if len(nodes_right_i) > 0:
                right_nodes = nodes_right_i if right_nodes is None else right_nodes + nodes_right_i

            if len(nodes_left_i) > 0:
                left_nodes = nodes_left_i if left_nodes is None else left_nodes + nodes_left_i

        if right_nodes is None:
            raise ValueError('No nodes found at z = Dep for Right Surface Node Set.')

        if left_nodes is None:
            raise ValueError('No nodes found at z = 0 for Left Surface Node Set.')

        ra.Set(
            name='Left Surface Node Set',
            nodes=left_nodes
        )

        ra.Set(
            name='Right Surface Node Set',
            nodes=right_nodes
        )


        # --------------------------------------------------
        # Pair left and right nodes by closest x-y coordinates
        # --------------------------------------------------

        left_node_data = []
        right_node_data = []

        for node in ra.sets['Left Surface Node Set'].nodes:
            left_node_data.append((
                node.instanceName,
                node.label,
                node.coordinates[0],
                node.coordinates[1],
                node.coordinates[2]
            ))

        for node in ra.sets['Right Surface Node Set'].nodes:
            right_node_data.append((
                node.instanceName,
                node.label,
                node.coordinates[0],
                node.coordinates[1],
                node.coordinates[2]
            ))

        if len(left_node_data) == 0:
            raise ValueError('No left nodes found for pairing.')

        if len(right_node_data) == 0:
            raise ValueError('No right nodes found for pairing.')

        if len(left_node_data) != len(right_node_data):
            pass

        used_right = {}
        node_pairs = []

        for ldata in left_node_data:
            l_inst, l_label, lx, ly, lz = ldata

            best_j = None
            best_dist2 = None

            for j, rdata in enumerate(right_node_data):
                if j in used_right:
                    continue

                r_inst, r_label, rx, ry, rz = rdata

                dx = lx - rx
                dy = ly - ry
                dist2 = dx*dx + dy*dy

                if best_dist2 is None or dist2 < best_dist2:
                    best_dist2 = dist2
                    best_j = j

            if best_j is None:
                raise ValueError('No available right node found for pairing.')

            used_right[best_j] = True
            node_pairs.append((ldata, right_node_data[best_j], best_dist2))

        num_pairs = len(node_pairs)

        max_pair_dist = 0.0
        for pair in node_pairs:
            d = pair[2] ** 0.5
            if d > max_pair_dist:
                max_pair_dist = d

        # --------------------------------------------------
        # Create individual node sets for paired nodes
        # --------------------------------------------------

        for i, pair in enumerate(node_pairs):
            ldata, rdata, dist2 = pair

            l_inst_name, l_label, lx, ly, lz = ldata
            r_inst_name, r_label, rx, ry, rz = rdata

            l_inst = ra.instances[l_inst_name]
            r_inst = ra.instances[r_inst_name]

            l_nodes = l_inst.nodes.sequenceFromLabels((l_label,))
            r_nodes = r_inst.nodes.sequenceFromLabels((r_label,))

            left_set = 'Left Surface Node-%d' % (i + 1)
            right_set = 'Right Surface Node-%d' % (i + 1)

            if left_set in ra.sets.keys():
                del ra.sets[left_set]

            if right_set in ra.sets.keys():
                del ra.sets[right_set]

            ra.Set(name=left_set, nodes=l_nodes)
            ra.Set(name=right_set, nodes=r_nodes)

        for cname in m.constraints.keys():
            if cname.startswith('PBC '):
                del m.constraints[cname]


        for i in range(1, num_pairs + 1):

            left_set = 'Left Surface Node-%d' % i
            right_set = 'Right Surface Node-%d' % i

            left_node = ra.sets[left_set].nodes[0]
            right_node = ra.sets[right_set].nodes[0]

            y_left = left_node.coordinates[1]
            y_right = right_node.coordinates[1]
            y_avg = 0.5 * (y_left + y_right)

            m.Equation(name='PBC %d_1' % i, terms=((1.0, left_set, 1), (-1.0, right_set, 1)))
            m.Equation(name='PBC %d_2' % i, terms=((1.0, left_set, 2), (-1.0, right_set, 2), (float(-Dep * Dep / 2.0), 'RP', 1)))
            m.Equation(name='PBC %d_3' % i, terms=((1.0, left_set, 3), (-1.0, right_set, 3), (float(Dep) * y_avg, 'RP', 1)))

        m.StaticStep(adaptiveDampingRatio=0.05,
            continueDampingFactors=False, initialInc=inIncP, minInc=minIncP, maxInc=maxIncP, maxNumInc=
            maxNumIncP, matrixSolver=DIRECT_UNSYMMETRIC, name='Pressure', previous='Initial', stabilizationMagnitude=0.0002,
            stabilizationMethod=DISSIPATED_ENERGY_FRACTION)


        ra.Surface(name='Surf-3', side1Faces=
            ra.instances['OuterSheath'].faces.getSequenceFromMask(('[#12088 ]', ), ))

        m.Pressure(amplitude=UNSET, createStepName='Pressure',
            distributionType=UNIFORM, field='', magnitude=P, name='Load-1', region=
            ra.surfaces['Surf-3'])

        # --------------------------------------------------
        # Bending cycle steps
        # Pressure is applied in the Pressure step and remains active.
        # RP3 displacement controls bending curvature.
        # --------------------------------------------------

        m.StaticStep(
            adaptiveDampingRatio=0.05,
            continueDampingFactors=False,
            initialInc=inIncB,
            minInc=minIncB,
            maxInc=maxIncB,
            maxNumInc=maxNumIncB,
            matrixSolver=DIRECT_UNSYMMETRIC,
            name='Bending',
            previous='Pressure',
            stabilizationMagnitude=0.0002,
            stabilizationMethod=DISSIPATED_ENERGY_FRACTION
        )

        m.TabularAmplitude(data=((0.0, 0.0), (0.01, 0.078459), (
            0.02, 0.156434), (0.03, 0.233445), (0.04, 0.309017), (0.05, 0.382683), (
            0.06, 0.45399), (0.07, 0.522499), (0.08, 0.587785), (0.09, 0.649448), (0.1, 
            0.707107), (0.11, 0.760406), (0.12, 0.809017), (0.13, 0.85264), (0.14, 
            0.891007), (0.15, 0.92388), (0.16, 0.951057), (0.17, 0.97237), (0.18, 
            0.987688), (0.19, 0.996917), (0.2, 1.0), (0.21, 0.996917), (0.22, 
            0.987688), (0.23, 0.97237), (0.24, 0.951057), (0.25, 0.92388), (0.26, 
            0.891007), (0.27, 0.85264), (0.28, 0.809017), (0.29, 0.760406), (0.3, 
            0.707107), (0.31, 0.649448), (0.32, 0.587785), (0.33, 0.522499), (0.34, 
            0.45399), (0.35, 0.382683), (0.36, 0.309017), (0.37, 0.233445), (0.38, 
            0.156434), (0.39, 0.078459), (0.4, 0.0), (0.41, -0.078459), (0.42, 
            -0.156434), (0.43, -0.233445), (0.44, -0.309017), (0.45, -0.382683), (0.46, 
            -0.45399), (0.47, -0.522499), (0.48, -0.587785), (0.49, -0.649448), (0.5, 
            -0.707107), (0.51, -0.760406), (0.52, -0.809017), (0.53, -0.85264), (0.54, 
            -0.891007), (0.55, -0.92388), (0.56, -0.951057), (0.57, -0.97237), (0.58, 
            -0.987688), (0.59, -0.996917), (0.6, -1.0), (0.61, -0.996917), (0.62, 
            -0.987688), (0.63, -0.97237), (0.64, -0.951057), (0.65, -0.92388), (0.66, 
            -0.891007), (0.67, -0.85264), (0.68, -0.809017), (0.69, -0.760406), (0.7, 
            -0.707107), (0.71, -0.649448), (0.72, -0.587785), (0.73, -0.522499), (0.74, 
            -0.45399), (0.75, -0.382683), (0.76, -0.309017), (0.77, -0.233445), (0.78, 
            -0.156434), (0.79, -0.078459), (0.8, 0.0), (0.81, 0.078459), (0.82, 
            0.156434), (0.83, 0.233445), (0.84, 0.309017), (0.85, 0.382683), (0.86, 
            0.45399), (0.87, 0.522499), (0.88, 0.587785), (0.89, 0.649448), (0.9, 
            0.707107), (0.91, 0.760406), (0.92, 0.809017), (0.93, 0.85264), (0.94, 
            0.891007), (0.95, 0.92388), (0.96, 0.951057), (0.97, 0.97237), (0.98, 
            0.987688), (0.99, 0.996917), (1.0, 1.0)), name='Amp-1', smooth=
            SOLVER_DEFAULT, timeSpan=STEP)

        m.DisplacementBC(
            amplitude='Amp-1',
            createStepName='Initial',
            distributionType=UNIFORM,
            fieldName='',
            fixed=OFF,
            localCsys=None,
            name='displacement',
            region=ra.sets['RP'],
            u1=0.0,
            u2=UNSET,
            u3=UNSET,
            ur1=UNSET,
            ur2=UNSET,
            ur3=UNSET
        )

        m.boundaryConditions['displacement'].setValuesInStep(
            stepName='Pressure', u1=0.0)

        m.boundaryConditions['displacement'].setValuesInStep(
            amplitude='Amp-1', stepName='Bending', u1=BendFac)

        m.fieldOutputRequests['F-Output-1'].setValues(variables=(
            'S', 'E', 'U', 'RF', 'CSTRESS', 'CDISP'))



        job_name = 'P_%d_Friction_%d_contactStiffness_%d' % (P*100, FrCo*100, conStiff*1000)

        mdb.Job(
            name=job_name,
            model='Model-1',
            type=ANALYSIS,
            memory=90,
            memoryUnits=PERCENTAGE,
            getMemoryFromAnalysis=True,

            multiprocessingMode=DEFAULT,
            numCpus=CPU,
            numDomains=CPU,

            explicitPrecision=SINGLE,
            nodalOutputPrecision=SINGLE,
            echoPrint=OFF,
            modelPrint=OFF,
            contactPrint=ON,
            historyPrint=OFF,
            userSubroutine='',
            scratch='',
            resultsFormat=ODB
        )

        mdb.jobs[job_name].writeInput(consistencyChecking=OFF)
        print("[ABAQUS] INP file formed: {0}.inp".format(job_name))
        sys.stdout.flush()
        print("[ABAQUS] Analysis started: {0}".format(job_name))
        sys.stdout.flush()
        mdb.jobs[job_name].submit(consistencyChecking=OFF)
        mdb.jobs[job_name].waitForCompletion()
        print("[ABAQUS] Analysis completed: {0}".format(job_name))
        sys.stdout.flush()
        mdb.saveAs(pathName=str(cae_path))

        odb_path = os.path.join(job_dir, job_name + '.odb')
        inp_path = os.path.join(job_dir, job_name + '.inp')
        return {
            'status': 'abaqus_analysis_complete' if os.path.exists(odb_path) else 'abaqus_analysis_finished_no_odb',
            'job_name': job_name,
            'inp_path': inp_path,
            'cae_path': cae_path,
            'odb_path': odb_path,
            'odb_exists': os.path.exists(odb_path),
            'candidate_source': 'automatic.py near-direct port',
            'pitch_core': float(pitch_core),
            'pitch_inner': float(pitch_inner),
            'pitch_outer': float(pitch_outer),
            'Dep': float(Dep),
        }
    finally:
        os.chdir(old_cwd)

def main(argv):
    input_path = parse_input_path(argv)
    if not os.path.exists(input_path):
        sys.stderr.write("input JSON not found: {0}\n".format(input_path))
        return 2

    job_dir = os.path.dirname(os.path.abspath(input_path))
    data = normalize_payload(load_payload(input_path))

    result_csv = os.path.join(job_dir, 'result_data.csv')

    try:
        if ABAQUS_AVAILABLE:
            result = build_abaqus_model(data, job_dir)
            write_json(os.path.join(job_dir, 'abaqus_mesh_manifest.json'), result)
            write_result_csv(result_csv, [0.0], [0.0])
            write_json(
                os.path.join(job_dir, 'result_summary.json'),
                fallback_summary(data, result, [0.0], [0.0]),
            )
            extraction_status = run_odb_extraction(job_dir, result.get('odb_path', ''), input_path)
        else:
            curvature, moment = fallback_result_curve(data)
            manifest = fallback_manifest(data)
            write_json(os.path.join(job_dir, 'abaqus_mesh_manifest.json'), manifest)
            write_result_csv(result_csv, curvature, moment)
            write_json(
                os.path.join(job_dir, 'result_summary.json'),
                fallback_summary(data, manifest, curvature, moment),
            )
            print("Abaqus modules not available; wrote mesh contract fallback files.")
        return 0

    except Exception as exc:
        error_detail = "{0}\n{1}".format(str(exc), traceback.format_exc())
        failed_manifest = {
            'status': 'failed',
            'error': str(exc),
            'detail': error_detail,
            'created_at': timestamp_seconds(),
        }
        write_json(os.path.join(job_dir, 'abaqus_mesh_manifest.json'), failed_manifest)
        sys.stderr.write("Abaqus model build failed: {0}\n".format(exc))
        write_result_csv(result_csv, [0.0], [0.0])
        failure_summary = fallback_summary(data, failed_manifest, [0.0], [0.0])
        failure_summary["source"] = "SCLAS_ABAQUS_RUNNER_PLACEHOLDER"
        failure_summary["status"] = "abaqus_model_build_failed"
        failure_summary["error"] = str(exc)
        write_json(os.path.join(job_dir, 'result_summary.json'), failure_summary)
        print("Wrote placeholder result_data.csv")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
