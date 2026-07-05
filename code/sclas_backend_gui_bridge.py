#!/usr/bin/env python3
"""Pure-Python helpers for GUI/backend input-data bridging."""

import math
from pathlib import Path


BACKEND_FIXTURE_ROOT = Path("C:/HELIX/Abaqus+_work/for_test")
BACKEND_WORK_ROOT = Path("C:/HELIX/Abaqus+_work")
BACKEND_JSON_PRESETS = {
    "RoC15 backend fixture": BACKEND_FIXTURE_ROOT / "input_data_RoC15.json",
    "RoC20 backend fixture": BACKEND_FIXTURE_ROOT / "input_data_RoC20.json",
    "RoC25 auto-count fixture": BACKEND_FIXTURE_ROOT / "input_data_RoC25.json",
}
BACKEND_JOB_FOLDER_PRESETS = {
    "Backend for_test job folder": BACKEND_WORK_ROOT / "for_test",
    "Backend run job folder": BACKEND_WORK_ROOT / "run",
    "Backend Final job folder": BACKEND_WORK_ROOT / "Final",
}


GUI_COMBO_ALIASES = {
    "periodic_homogenized_cell": "Periodic homogenized cell",
    "full_3d_segment": "Full 3D segment",
    "axisymmetric_tension_torsion": "Axisymmetric tension/torsion",
    "beam_with_contact_surface": "Beam + contact surface",
    "solid_wire": "Solid wire",
    "analytical_equivalent": "Analytical equivalent",
}


def first_present(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def core_center_from_outer_radius(core_outer_radius_mm):
    return round(2.0 * math.sqrt(3.0) * float(core_outer_radius_mm) / 3.0, 5)


def auto_armour_count(wire_radius_mm, center_radius_mm):
    wire_radius = float(wire_radius_mm)
    center_radius = float(center_radius_mm)
    if wire_radius <= 0 or center_radius <= wire_radius:
        return 1
    ratio = min(0.999999, max(1.0e-9, wire_radius / center_radius))
    return max(1, int(math.pi / math.asin(ratio)))


def backend_payload_gui_values(payload):
    geometry = payload.get("geometry_mm", {})
    armour = payload.get("armour", {})
    mesh = payload.get("mesh", {})
    analysis = payload.get("analysis_conditions", {})
    enabled = payload.get("study_scope", {}).get("enabled_assessments", {})

    return {
        "geometry": {
            "r_cond": first_present(geometry, "conductor_radius_mm"),
            "r_insu": first_present(geometry, "insulation_radius_mm"),
            "roc": first_present(geometry, "core_outer_radius_mm", "radius_of_core_mm"),
            "coc": first_present(geometry, "core_center_radius_mm"),
            "tis": first_present(geometry, "inner_sheath_thickness_mm"),
            "gap": first_present(geometry, "clearance_gap_mm"),
            "tos": first_present(geometry, "outer_sheath_thickness_mm"),
            "r_ia": first_present(armour, "inner_wire_radius_mm", "inner_armour_wire_radius_mm"),
            "no_ia": first_present(armour, "inner_wire_count", "inner_armour_wire_count"),
            "r_oa": first_present(armour, "outer_wire_radius_mm", "outer_armour_wire_radius_mm"),
            "no_oa": first_present(armour, "outer_wire_count", "outer_armour_wire_count"),
            "core_lay_angle": first_present(armour, "core_lay_angle_deg", "core_helix_angle_deg"),
            "inner_lay_angle": first_present(
                armour,
                "inner_armour_lay_angle_deg",
                "inner_lay_angle_deg",
                "lay_angle_deg",
            ),
            "outer_lay_angle": first_present(
                armour,
                "outer_armour_lay_angle_deg",
                "outer_lay_angle_deg",
                "lay_angle_deg",
            ),
        },
        "analysis_conditions": {
            "eff_length": first_present(analysis, "effective_length_mm"),
            "pressure": first_present(analysis, "external_pressure_mpa", "hydrostatic_pressure_mpa"),
            "residual_contact_pressure": first_present(analysis, "residual_contact_pressure_mpa"),
            "friction": first_present(analysis, "friction_coefficient"),
            "curvature": first_present(analysis, "max_curvature_1_per_m"),
            "twist": first_present(analysis, "max_twist_rad_per_m"),
            "axial_strain": first_present(analysis, "max_axial_strain"),
            "radial_compression": first_present(analysis, "radial_compression_ratio"),
            "cycles": first_present(analysis, "loading_cycles"),
            "steps": first_present(analysis, "solver_steps"),
        },
        "mesh": {
            "elem_type": first_present(mesh, "solid_element_type", "requested_element_type"),
            "model_strategy": first_present(mesh, "model_strategy"),
            "armour_model": first_present(mesh, "armour_model"),
            "contact_beta": first_present(mesh, "contact_regularization_beta"),
            "z_elem": first_present(mesh, "axial_divisions"),
            "c_elem_core": first_present(mesh, "core_circumferential_divisions"),
            "c_elem_armour": first_present(mesh, "armour_circumferential_divisions"),
            "r_elem_inner_sheath": first_present(mesh, "inner_sheath_radial_divisions"),
            "r_elem_bedding": first_present(mesh, "bedding_radial_divisions", "radial_divisions_per_layer"),
            "r_elem_outer_sheath": first_present(mesh, "outer_sheath_radial_divisions"),
        },
        "materials": payload.get("materials", []),
        "study_scope": enabled if isinstance(enabled, dict) else {},
    }


def resolved_backend_geometry(payload):
    values = backend_payload_gui_values(payload)
    geometry = values["geometry"]
    roc = float(geometry.get("roc") or 15.3)
    coc = core_center_from_outer_radius(roc)
    tis = float(geometry.get("tis") or 4.5)
    gap = float(geometry.get("gap") or 0.5)
    ria = float(geometry.get("r_ia") or 2.0)
    roa = float(geometry.get("r_oa") or 2.0)
    iris = roc + coc
    oris = iris + tis
    co_ia = oris + gap + ria
    irb = co_ia + ria
    orb = irb + 0.6
    co_oa = orb + gap + roa
    nia_input = int(float(geometry.get("no_ia") or 0))
    noa_input = int(float(geometry.get("no_oa") or 0))
    return {
        "core_outer_radius_mm": roc,
        "core_center_radius_mm": coc,
        "inner_armour_center_radius_mm": co_ia,
        "outer_armour_center_radius_mm": co_oa,
        "inner_armour_wire_count": nia_input if nia_input > 0 else auto_armour_count(ria, co_ia),
        "outer_armour_wire_count": noa_input if noa_input > 0 else auto_armour_count(roa, co_oa),
        "inner_armour_wire_count_source": "user" if nia_input > 0 else "auto_from_wire_radius_and_center_radius",
        "outer_armour_wire_count_source": "user" if noa_input > 0 else "auto_from_wire_radius_and_center_radius",
    }
