import csv
import json
import os
import sys
import traceback
from datetime import datetime
from decimal import Decimal
from math import sqrt, asin, pi, tan

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


def normalized_geometry(data):
    geo = data.get("geometry_mm", {})
    dgeo = data.get("derived_geometry_mm", {})
    arm = data.get("armour", {})

    roc = as_float(geo.get("core_outer_radius_mm", dgeo.get("core_outer_radius_mm")), 15.3)
    coc = core_center_from_outer_radius(roc)
    r_cond = as_float(geo.get("conductor_radius_mm"), 4.0)
    r_insu = as_float(geo.get("insulation_radius_mm"), 11.3)
    tis = as_float(geo.get("inner_sheath_thickness_mm"), 4.5)
    tos = as_float(geo.get("outer_sheath_thickness_mm"), 4.5)
    gap = as_float(geo.get("clearance_gap_mm"), 0.5)
    ria = as_float(arm.get("inner_wire_radius_mm", dgeo.get("inner_armour_wire_radius_mm")), 2.0)
    roa = as_float(arm.get("outer_wire_radius_mm", dgeo.get("outer_armour_wire_radius_mm")), 2.0)
    bedding = as_float(dgeo.get("bedding_thickness_mm"), 0.6)

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
    geo["core_center_radius_mm"] = geometry["core_center_radius_mm"]
    geo.setdefault("inner_sheath_thickness_mm", 4.5)
    geo.setdefault("outer_sheath_thickness_mm", 4.5)
    geo.setdefault("clearance_gap_mm", 0.5)
    data["geometry_mm"] = geo
    merged_dgeo = dict(data.get("derived_geometry_mm", {}))
    merged_dgeo.update(geometry)
    data["derived_geometry_mm"] = merged_dgeo

    arm = dict(data.get("armour", {}))
    arm.setdefault("inner_wire_radius_mm", geometry["inner_armour_wire_radius_mm"])
    arm.setdefault("outer_wire_radius_mm", geometry["outer_armour_wire_radius_mm"])
    arm.setdefault("inner_wire_count", geometry["inner_armour_wire_count_input"])
    arm.setdefault("outer_wire_count", geometry["outer_armour_wire_count_input"])
    arm.setdefault("core_lay_angle_deg", 8.98)
    arm.setdefault("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg", arm.get("lay_angle_deg", 20.32)))
    arm.setdefault("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg", arm.get("lay_angle_deg", 19.62)))
    arm["inner_wire_count_resolved"] = geometry["inner_armour_wire_count"]
    arm["outer_wire_count_resolved"] = geometry["outer_armour_wire_count"]
    data["armour"] = arm

    mesh = dict(data.get("mesh", {}))
    mesh.setdefault("axial_divisions", 40)
    mesh.setdefault("core_circumferential_divisions", 24)
    mesh.setdefault("armour_circumferential_divisions", 8)
    mesh.setdefault("inner_sheath_radial_divisions", mesh.get("radial_divisions_per_layer", 3))
    mesh.setdefault("bedding_radial_divisions", mesh.get("radial_divisions_per_layer", 1))
    mesh.setdefault("outer_sheath_radial_divisions", mesh.get("radial_divisions_per_layer", 3))
    mesh.setdefault("requested_element_type", mesh.get("solid_element_type", "C3D8R"))
    mesh.setdefault("global_seed_size_mm", None)
    mesh.setdefault("contact_regularization_beta", 0.001)
    data["mesh"] = mesh

    ac = dict(data.get("analysis_conditions", {}))
    pressure = ac.get("external_pressure_mpa", ac.get("hydrostatic_pressure_mpa", 0.0))
    ac["external_pressure_mpa"] = as_float(pressure, 0.0)
    ac["hydrostatic_pressure_mpa"] = ac["external_pressure_mpa"]
    ac.setdefault("effective_length_mm", 234.2)
    ac.setdefault("residual_contact_pressure_mpa", 0.3)
    ac.setdefault("friction_coefficient", 0.22)
    ac.setdefault("max_curvature_1_per_m", 0.08)
    ac.setdefault("curve_factors", [-0.1, -0.05, 0.0, 0.05, 0.1])
    ac.setdefault("loading_cycles", 1)
    ac.setdefault("solver_steps", 500)
    ac.setdefault("contact_regularization_beta", mesh.get("contact_regularization_beta", 0.001))
    data["analysis_conditions"] = ac

    solver = dict(data.get("solver", {}))
    solver.setdefault("initial_increment", 1.0e-5)
    solver.setdefault("minimum_increment", 1.0e-11)
    solver.setdefault("maximum_increment", 0.001)
    solver.setdefault("max_num_increments", 10000)
    solver.setdefault("step_time", 1.0)
    solver.setdefault("nlgeom", False)
    solver.setdefault("stabilization_enabled", True)
    solver.setdefault("stabilization_factor", 0.0002)
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
    kmax = as_float(ac.get("max_curvature_1_per_m"), 0.08)
    friction = as_float(ac.get("friction_coefficient"), 0.22)
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
    pitch_design = {
        "core_lay_angle_deg": as_float(arm.get("core_lay_angle_deg"), 8.98),
        "inner_armour_lay_angle_deg": as_float(arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")), 20.32),
        "outer_armour_lay_angle_deg": as_float(arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")), 19.62),
        "core_pitch_mm": pitch_from_lay_angle(geom["core_center_radius_mm"], arm.get("core_lay_angle_deg"), 702.6, sign=1.0),
        "inner_armour_pitch_mm": pitch_from_lay_angle(geom["inner_armour_center_radius_mm"], arm.get("inner_armour_lay_angle_deg", arm.get("inner_lay_angle_deg")), -677.94737, sign=-1.0),
        "outer_armour_pitch_mm": pitch_from_lay_angle(geom["outer_armour_center_radius_mm"], arm.get("outer_armour_lay_angle_deg", arm.get("outer_lay_angle_deg")), 776.55789, sign=1.0),
    }
    defaults = {
        "normal": "penalty_or_augmented_lagrange",
        "tangential": "regularized_coulomb",
        "friction_coefficient": as_float(ac.get("friction_coefficient"), 0.22),
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


def build_abaqus_model(data, job_dir):
    geo  = data['geometry_mm']
    dgeo = data['derived_geometry_mm']
    arm  = data['armour']
    ac   = data['analysis_conditions']
    sol  = data['solver']
    msh  = data['mesh']
    out  = data['output_requests']
    mod  = data['modeling']

    Roc  = Decimal(str(geo['conductor_radius_mm']))
    RoI  = Decimal(str(geo['insulation_radius_mm']))
    RoC  = Decimal(str(geo['core_outer_radius_mm']))
    TIS  = Decimal(str(geo['inner_sheath_thickness_mm']))
    TOS  = Decimal(str(geo['outer_sheath_thickness_mm']))
    RoIA = Decimal(str(arm['inner_wire_radius_mm']))
    RoOA = Decimal(str(arm['outer_wire_radius_mm']))
    TB   = Decimal(str(dgeo['bedding_thickness_mm']))

    CoC  = Decimal(round((2*sqrt(3)*float(RoC)/3), 5))
    IRIS = RoC + CoC
    ORIS = IRIS + TIS
    GAP  = Decimal(str(geo.get('clearance_gap_mm', 0.0)))
    CoIA = RoIA + ORIS + GAP
    IRB  = CoIA + RoIA
    ORB  = IRB + TB
    CoOA = RoOA + ORB + GAP
    IROS = CoOA + RoOA
    OROS = IROS + TOS
    scale = RoC / Decimal('15.3')

    if 'inner_wire_count' not in arm or arm['inner_wire_count'] == 0:
        NoIA = Decimal(int(pi / asin(float(RoIA) / float(CoIA))))
    else:
        NoIA = Decimal(str(arm['inner_wire_count']))

    if 'outer_wire_count' not in arm or arm['outer_wire_count'] == 0:
        NoOA = Decimal(int(pi / asin(float(RoOA) / float(CoOA))))
    else:
        NoOA = Decimal(str(arm['outer_wire_count']))

    RAoIA = round(Decimal(360) / NoIA, 5)
    RAoOA = round(Decimal(360) / NoOA, 5)
    core_lay_angle = as_float(arm.get('core_lay_angle_deg'), 8.98)
    inner_lay_angle = as_float(arm.get('inner_armour_lay_angle_deg', arm.get('inner_lay_angle_deg')), 20.32)
    outer_lay_angle = as_float(arm.get('outer_armour_lay_angle_deg', arm.get('outer_lay_angle_deg')), 19.62)
    pitch_core = pitch_from_lay_angle(CoC, core_lay_angle, 702.6, sign=1.0)
    pitch_inner = pitch_from_lay_angle(CoIA, inner_lay_angle, -677.94737, sign=-1.0)
    pitch_outer = pitch_from_lay_angle(CoOA, outer_lay_angle, 776.55789, sign=1.0)

    depth          = as_float(ac.get('effective_length_mm'), 234.2)
    pressure       = as_float(ac.get('external_pressure_mpa', ac.get('hydrostatic_pressure_mpa')), 0.0)
    friction       = as_float(ac.get('friction_coefficient'), 0.22)
    contact_beta   = as_float(ac.get('contact_regularization_beta', msh.get('contact_regularization_beta')), 0.001)
    max_curvature  = as_float(ac.get('max_curvature_1_per_m'), 0.08)
    curve_factors  = ac['curve_factors']
    loading_cycles = ac['loading_cycles']

    initialInc = sol['initial_increment'] if sol['initial_increment'] is not None else 1e-05
    maxInc     = sol['maximum_increment'] if sol['maximum_increment'] is not None else 0.001
    maxNumInc  = sol['max_num_increments']
    stabilization = as_float(sol.get('stabilization_factor'), 0.0002)

    axial_div       = msh['axial_divisions']
    core_circ_div   = msh['core_circumferential_divisions']
    armour_circ_div = msh['armour_circumferential_divisions']
    inner_sheath_radial_div = max(1, as_int(msh.get('inner_sheath_radial_divisions'), 3))
    outer_sheath_radial_div = max(1, as_int(msh.get('outer_sheath_radial_divisions'), 3))

    field_output   = out['field']
    history_output = out['history']

    L         = Decimal(str(depth))
    coef_dof2 = float(L * L / 2)
    coef_dof4 = float(-L)

    job_name = 'Cable_Bending'

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

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+Roc)))
    m.Part(dimensionality=THREE_D, name='Conductor', type=DEFORMABLE_BODY)
    p = m.parts['Conductor']
    p.BaseSolidExtrude(depth=depth, pitch=pitch_core, sketch=sk)
    p.Set(cells=p.cells[:], name='Conductor')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['Conductor'], sectionName='Conductor', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+RoI)))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+Roc)))
    m.Part(dimensionality=THREE_D, name='Insulation', type=DEFORMABLE_BODY)
    p = m.parts['Insulation']
    p.BaseSolidExtrude(depth=depth, pitch=pitch_core, sketch=sk)
    p.Set(cells=p.cells[:], name='Insulation')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['Insulation'], sectionName='Insulation', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(CoC+RoI)))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoC)), point1=(0.0, float(IRIS)))
    m.Part(dimensionality=THREE_D, name='CoreShield', type=DEFORMABLE_BODY)
    p = m.parts['CoreShield']
    p.BaseSolidExtrude(depth=depth, pitch=pitch_core, sketch=sk)
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
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#29 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#40 ]', ), ), number=core_circ_div)
    p.setMeshControls(algorithm=MEDIAL_AXIS,
        regions=p.cells.getSequenceFromMask(('[#7 ]', ), ))
    p.generateMesh(seedConstraintOverride=ON)
    p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
        secondOrderAccuracy=OFF, distortionControl=DEFAULT),
        ElemType(elemCode=C3D6, elemLibrary=STANDARD),
        ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
        regions=(p.cells.getSequenceFromMask(('[#7 ]', ), ), ))

    for i in range(3):
        ra.rotate(angle=120 * i, axisDirection=(0.0, 0.0, 1.0),
            axisPoint=(0.0, 0.0, 0.0), instanceList=('Core-%d' % (i+1),))

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IRIS)))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(ORIS)))
    m.Part(dimensionality=THREE_D, name='InnerSheath', type=DEFORMABLE_BODY)
    p = m.parts['InnerSheath']
    p.BaseSolidExtrude(depth=depth, sketch=sk)
    p.Set(cells=p.cells[:], name='InnerSheath')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['InnerSheath'], sectionName='InnerSheath', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=core_circ_div)
    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
        datumPlane=p.datums[5])
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
        datumPlane=p.datums[4])
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#8001000 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#2000000 ]', ), ), number=inner_sheath_radial_div)
    p.generateMesh()

    ra.Instance(dependent=ON, name='InnerSheath', part=m.parts['InnerSheath'])

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoIA)), point1=(0.0, float(IRB)))
    m.Part(dimensionality=THREE_D, name='InnerArmour', type=DEFORMABLE_BODY)
    p = m.parts['InnerArmour']
    p.BaseSolidExtrude(depth=depth, pitch=pitch_inner, sketch=sk)
    p.Set(cells=p.cells[:], name='InnerArmour')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['InnerArmour'], sectionName='InnerArmour', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#1 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), number=armour_circ_div)
    p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
        secondOrderAccuracy=OFF, distortionControl=DEFAULT),
        ElemType(elemCode=C3D6, elemLibrary=STANDARD),
        ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
        regions=(p.cells.getSequenceFromMask(('[#1 ]', ), ), ))
    p.setMeshControls(algorithm=MEDIAL_AXIS,
        regions=p.cells.getSequenceFromMask(('[#1 ]', ), ))
    p.generateMesh()

    for i in range(int(NoIA)):
        ra.Instance(dependent=ON, name='InnerArmour-%d' % (i+1), part=m.parts['InnerArmour'])
        ra.rotate(angle=float(RAoIA) * i, axisDirection=(0.0, 0.0, 1.0),
            axisPoint=(0.0, 0.0, 0.0), instanceList=('InnerArmour-%d' % (i+1),))

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IRB)))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(ORB)))
    m.Part(dimensionality=THREE_D, name='Bedding', type=DEFORMABLE_BODY)
    p = m.parts['Bedding']
    p.BaseSolidExtrude(depth=depth, sketch=sk)
    p.Set(cells=p.cells[:], name='Bedding')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['Bedding'], sectionName='Bedding', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
        datumPlane=p.datums[4])
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
        datumPlane=p.datums[3])
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=core_circ_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#a1a02500 ]', ), ), number=axial_div)
    p.generateMesh()
    p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
        secondOrderAccuracy=OFF, distortionControl=DEFAULT),
        ElemType(elemCode=C3D6, elemLibrary=STANDARD),
        ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
        regions=(p.cells.getSequenceFromMask(('[#f ]', ), ), ))

    ra.Instance(dependent=ON, name='Bedding', part=m.parts['Bedding'])

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, float(CoOA)), point1=(0.0, float(IROS)))
    m.Part(dimensionality=THREE_D, name='OuterArmour', type=DEFORMABLE_BODY)
    p = m.parts['OuterArmour']
    p.BaseSolidExtrude(depth=depth, pitch=pitch_outer, sketch=sk)
    p.Set(cells=p.cells[:], name='OuterArmour')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['OuterArmour'], sectionName='OuterArmour', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#2 ]', ), ), number=armour_circ_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#1 ]', ), ), number=axial_div)
    p.setMeshControls(algorithm=MEDIAL_AXIS,
        regions=p.cells.getSequenceFromMask(('[#1 ]', ), ))
    p.setElementType(elemTypes=(ElemType(elemCode=C3D8, elemLibrary=STANDARD,
        secondOrderAccuracy=OFF, distortionControl=DEFAULT),
        ElemType(elemCode=C3D6, elemLibrary=STANDARD),
        ElemType(elemCode=C3D4, elemLibrary=STANDARD)),
        regions=(p.cells.getSequenceFromMask(('[#1 ]', ), ), ))
    p.generateMesh()

    for i in range(int(NoOA)):
        ra.Instance(dependent=ON, name='OuterArmour-%d' % (i+1), part=m.parts['OuterArmour'])
        ra.rotate(angle=float(RAoOA) * i, axisDirection=(0.0, 0.0, 1.0),
            axisPoint=(0.0, 0.0, 0.0), instanceList=('OuterArmour-%d' % (i+1),))

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
    sk = m.sketches['__profile__']
    sk.Spot(point=(0.0, 0.0))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(IROS)))
    sk.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, float(OROS)))
    m.Part(dimensionality=THREE_D, name='OuterSheath', type=DEFORMABLE_BODY)
    p = m.parts['OuterSheath']
    p.BaseSolidExtrude(depth=depth, pitch=0, sketch=sk)
    p.Set(cells=p.cells[:], name='OuterSheath')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['OuterSheath'], sectionName='OuterSheath', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#5 ]', ), ), number=core_circ_div)
    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=YZPLANE)
    p.DatumPlaneByPrincipalPlane(offset=0.0, principalPlane=XZPLANE)
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#1 ]', ), ),
        datumPlane=p.datums[4])
    p.PartitionCellByDatumPlane(cells=p.cells.getSequenceFromMask(('[#3 ]', ), ),
        datumPlane=p.datums[5])
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#4008000 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#80000 ]', ), ), number=outer_sheath_radial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#50554800 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#a1a02500 ]', ), ), number=axial_div)
    p.generateMesh()

    ra.Instance(dependent=ON, name='OuterSheath', part=m.parts['OuterSheath'])

    m.ConstrainedSketch(name='__profile__', sheetSize=235.0)
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
    p.BaseSolidExtrude(depth=depth, pitch=pitch_core, sketch=sk)
    p.Set(cells=p.cells[:], name='Filler')
    p.SectionAssignment(offset=0.0, offsetField='', offsetType=MIDDLE_SURFACE,
        region=p.sets['Filler'], sectionName='Filler', thicknessAssignment=FROM_SECTION)
    del m.sketches['__profile__']

    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#100 ]', ), ), number=axial_div)
    p.seedEdgeByNumber(constraint=FIXED,
        edges=p.edges.getSequenceFromMask(('[#92491 ]', ), ), number=axial_div)
    p.generateMesh(seedConstraintOverride=ON)
    for i in range(3):
        ra.Instance(dependent=ON, name='Filler-%d' % (i+1), part=m.parts['Filler'])
        ra.rotate(angle=120 * i, axisDirection=(0.0, 0.0, 1.0),
            axisPoint=(0.0, 0.0, 0.0), instanceList=('Filler-%d' % (i+1),))
    ra.regenerate()
    ra.regenerate()

    all_instances = ['Core-1', 'Core-2', 'Core-3', 'InnerSheath', 'Bedding', 'OuterSheath']
    for i in range(int(NoIA)):
        all_instances.append('InnerArmour-%d' % (i+1))
    for i in range(int(NoOA)):
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
        formulation=PENALTY, fraction=contact_beta, maximumElasticSlip=FRACTION,
        pressureDependency=OFF, shearStressLimit=None, slipRateDependency=OFF,
        table=((friction, ), ), temperatureDependency=OFF)
    m.interactionProperties['IntProp-1'].NormalBehavior(
        allowSeparation=ON, clearanceAtZeroContactPressure=0.0,
        constraintEnforcementMethod=PENALTY, contactStiffness=DEFAULT,
        contactStiffnessScaleFactor=max(contact_beta, 1.0e-6), lowerQuadraticRatio=0.33333,
        pressureOverclosure=HARD, stiffnessBehavior=NONLINEAR, stiffnessRatio=0.01,
        upperQuadraticFactor=0.03)
    ra.regenerate()

    m.StdInitialization(name='CInit-1')
    m.ContactStd(createStepName='Initial', name='Int-1')

    contact_pairs = []
    for i in range(1, 4):
        next1 = i % 3 + 1
        next2 = (i + 1) % 3 + 1
        contact_pairs.append((ra.instances['Core-%d' % i].surfaces['CO'],
                               ra.instances['Filler-%d' % next1].surfaces['FR']))
        contact_pairs.append((ra.instances['Core-%d' % i].surfaces['CO'],
                               ra.instances['Filler-%d' % next2].surfaces['FL']))
    for i in range(1, 4):
        contact_pairs.append((ra.instances['InnerSheath'].surfaces['IAI'],
                               ra.instances['Core-%d' % i].surfaces['CO']))
        contact_pairs.append((ra.instances['InnerSheath'].surfaces['IAI'],
                               ra.instances['Filler-%d' % i].surfaces['FO']))
    for i in range(1, int(NoIA)+1):
        contact_pairs.append((ra.instances['InnerSheath'].surfaces['ISO'],
                               ra.instances['InnerArmour-%d' % i].surfaces['IAS']))
        contact_pairs.append((ra.instances['Bedding'].surfaces['BeddingI'],
                               ra.instances['InnerArmour-%d' % i].surfaces['IAS']))
    for i in range(1, int(NoOA)+1):
        contact_pairs.append((ra.instances['Bedding'].surfaces['BeddingO'],
                               ra.instances['OuterArmour-%d' % i].surfaces['OAS']))
        contact_pairs.append((ra.instances['OuterSheath'].surfaces['OSI'],
                               ra.instances['OuterArmour-%d' % i].surfaces['OAS']))

    m.interactions['Int-1'].includedPairs.setValuesInStep(
        addPairs=tuple(contact_pairs), stepName='Initial')
    ra.regenerate()

    front_seq = None
    back_seq = None
    for inst_name in all_instances:
        inst = ra.instances[inst_name]
        for f in inst.faces:
            pt = f.pointOn[0]
            if abs(pt[2] - 0.0) < 1e-3:
                single = inst.faces.findAt((pt, ))
                front_seq = single if front_seq is None else front_seq + single
            elif abs(pt[2] - depth) < 1e-3:
                single = inst.faces.findAt((pt, ))
                back_seq = single if back_seq is None else back_seq + single

    ra.ReferencePoint(point=(0.0, 0.0, 0.0))
    rp2_key = ra.referencePoints.keys()[-1]
    ra.ReferencePoint(point=(0.0, 0.0, depth))
    rp1_key = ra.referencePoints.keys()[-1]
    ra.ReferencePoint(point=(float(OROS) + 30.0, 0.0, 0.0))
    rp3_key = ra.referencePoints.keys()[-1]

    ra.Set(name='m_Set-1', referencePoints=(ra.referencePoints[rp1_key], ))
    ra.Set(name='m_Set-2', referencePoints=(ra.referencePoints[rp2_key], ))
    ra.Set(name='RP', referencePoints=(ra.referencePoints[rp3_key], ))

    ra.Surface(side1Faces=back_seq, name='s_Surf-1')
    ra.Surface(side1Faces=front_seq, name='s_Surf-2')

    m.Coupling(controlPoint=ra.sets['m_Set-1'], couplingType=KINEMATIC,
        influenceRadius=WHOLE_SURFACE, localCsys=None, name='Constraint-1',
        surface=ra.surfaces['s_Surf-1'], u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON)
    m.Coupling(controlPoint=ra.sets['m_Set-2'], couplingType=KINEMATIC,
        influenceRadius=WHOLE_SURFACE, localCsys=None, name='Constraint-2',
        surface=ra.surfaces['s_Surf-2'], u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON)

    m.Equation(name='Constraint-3', terms=((1.0, 'm_Set-1', 1), (-1.0, 'm_Set-2', 1)))
    m.Equation(name='Constraint-4', terms=((1.0, 'm_Set-1', 2), (-1.0, 'm_Set-2', 2), (coef_dof2, 'RP', 1)))
    m.Equation(name='Constraint-5', terms=((1.0, 'm_Set-1', 3), (-1.0, 'm_Set-2', 3)))
    m.Equation(name='Constraint-6', terms=((1.0, 'm_Set-1', 4), (-1.0, 'm_Set-2', 4), (coef_dof4, 'RP', 1)))
    m.Equation(name='Constraint-7', terms=((1.0, 'm_Set-1', 5), (-1.0, 'm_Set-2', 5)))
    m.Equation(name='Constraint-8', terms=((1.0, 'm_Set-1', 6), (-1.0, 'm_Set-2', 6)))

    m.constraints.changeKey(fromName='Constraint-3', toName='DOF1')
    m.constraints.changeKey(fromName='Constraint-4', toName='DOF2')
    m.constraints.changeKey(fromName='Constraint-5', toName='DOF3')
    m.constraints.changeKey(fromName='Constraint-6', toName='DOF4')
    m.constraints.changeKey(fromName='Constraint-7', toName='DOF5')
    m.constraints.changeKey(fromName='Constraint-8', toName='DOF6')

    m.constraints['DOF1'].suppress()
    m.constraints['DOF3'].suppress()
    m.constraints['DOF5'].suppress()
    m.constraints['DOF6'].suppress()

    m.StaticStep(adaptiveDampingRatio=0.05,
        continueDampingFactors=False, initialInc=initialInc, maxInc=maxInc,
        maxNumInc=maxNumInc, name='Pressure', previous='Initial',
        stabilizationMagnitude=stabilization,
        stabilizationMethod=DISSIPATED_ENERGY_FRACTION)

    ra.Surface(name='Surf-3', side1Faces=
        ra.instances['OuterSheath'].faces.getSequenceFromMask(('[#12088 ]', ), ))

    m.Pressure(amplitude=UNSET, createStepName='Pressure',
        distributionType=UNIFORM, field='', magnitude=pressure, name='Load-1',
        region=ra.surfaces['Surf-3'])

    prev_step = 'Pressure'
    step_count = 0
    for factor in curve_factors:
        u1_val = max_curvature * float(factor) * float(depth) / 1000.0
        for cycle in range(int(loading_cycles)):
            pos_name = 'Bending-%d-pos' % (step_count * int(loading_cycles) + cycle + 1)
            neg_name = 'Bending-%d-neg' % (step_count * int(loading_cycles) + cycle + 1)

            m.StaticStep(adaptiveDampingRatio=0.05,
                continueDampingFactors=False, initialInc=initialInc, maxInc=maxInc,
                maxNumInc=maxNumInc, name=pos_name, previous=prev_step,
                stabilizationMagnitude=stabilization,
                stabilizationMethod=DISSIPATED_ENERGY_FRACTION)
            m.DisplacementBC(amplitude=UNSET, createStepName=pos_name,
                distributionType=UNIFORM, fieldName='', fixed=OFF, localCsys=None,
                name='BC-%s' % pos_name, region=ra.sets['RP'],
                u1=u1_val, u2=UNSET, u3=UNSET, ur1=UNSET, ur2=UNSET, ur3=UNSET)

            m.StaticStep(adaptiveDampingRatio=0.05,
                continueDampingFactors=False, initialInc=initialInc, maxInc=maxInc,
                maxNumInc=maxNumInc, name=neg_name, previous=pos_name,
                stabilizationMagnitude=stabilization,
                stabilizationMethod=DISSIPATED_ENERGY_FRACTION)
            m.DisplacementBC(amplitude=UNSET, createStepName=neg_name,
                distributionType=UNIFORM, fieldName='', fixed=OFF, localCsys=None,
                name='BC-%s' % neg_name, region=ra.sets['RP'],
                u1=-u1_val, u2=UNSET, u3=UNSET, ur1=UNSET, ur2=UNSET, ur3=UNSET)

            prev_step = neg_name
        step_count += 1

    m.fieldOutputRequests['F-Output-1'].setValues(
        variables=tuple(str(v) for v in field_output))
    m.HistoryOutputRequest(createStepName='Pressure', name='H-Output-1',
        rebar=EXCLUDE, region=ra.sets['RP'], sectionPoints=DEFAULT,
        variables=tuple(str(v) for v in history_output))

    old_cwd = os.getcwd()
    os.chdir(str(job_dir))
    inp_path = os.path.join(path_text(job_dir), job_name + '.inp')
    cae_path = os.path.join(path_text(job_dir), job_name + '.cae')
    try:
        mdb.Job(atTime=None, contactPrint=OFF, description='', echoPrint=OFF,
            explicitPrecision=SINGLE, getMemoryFromAnalysis=True, historyPrint=OFF,
            memory=90, memoryUnits=PERCENTAGE, model='Model-1', modelPrint=OFF,
            multiprocessingMode=DEFAULT, name=job_name, nodalOutputPrecision=SINGLE,
            numCpus=12, numDomains=12, numGPUs=0, queue=None, resultsFormat=ODB,
            scratch='', type=ANALYSIS, userSubroutine='', waitHours=0, waitMinutes=0)
        mdb.jobs[job_name].writeInput(consistencyChecking=OFF)
        mdb.saveAs(pathName=str(cae_path))
    finally:
        os.chdir(old_cwd)

    files = [os.path.basename(p) for p in [inp_path, cae_path] if os.path.exists(p)]
    return {
        'status': 'abaqus_inp_created',
        'job_name': job_name,
        'files': files,
        'created_at': timestamp_seconds(),
    }


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
            print("Wrote: {0}".format(", ".join(result.get('files', []))))
            write_result_csv(result_csv, [0.0], [0.0])
            write_json(
                os.path.join(job_dir, 'result_summary.json'),
                fallback_summary(data, result, [0.0], [0.0]),
            )
            print("Wrote placeholder result_data.csv")
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
        write_json(os.path.join(job_dir, 'abaqus_mesh_manifest.json'), {
            'status': 'failed',
            'error': str(exc),
            'detail': error_detail,
            'created_at': timestamp_seconds(),
        })
        sys.stderr.write("Abaqus model build failed: {0}\n".format(exc))
        write_result_csv(result_csv, [0.0], [0.0])
        print("Wrote placeholder result_data.csv")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
