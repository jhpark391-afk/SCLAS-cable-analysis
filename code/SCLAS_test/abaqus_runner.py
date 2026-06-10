#!/usr/bin/env python3
"""
SCLAS Abaqus backend runner template.

This file is intentionally small and dependency-light so it can be copied into
each job folder. Replace `run_placeholder_solver` with real Abaqus/CAE model
creation and ODB extraction when the backend model is ready.
"""

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path


def load_payload(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_result_csv(path: Path, curvature, moment_kn_m) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["curvature_1_per_m", "moment_kn_m"])
        for k, m in zip(curvature, moment_kn_m):
            writer.writerow([f"{k:.12g}", f"{m:.12g}"])


def write_summary(path: Path, source: str, payload: dict, curvature, moment_kn_m, derived: dict) -> None:
    max_abs = max((abs(x) for x in moment_kn_m), default=0.0)
    study_scope = payload.get("study_scope", {})
    summary = {
        "source": source,
        "status": "completed",
        "max_abs_moment_kn_m": max_abs,
        "num_points": len(moment_kn_m),
        "study_scope": study_scope,
        "derived_placeholder_metrics": derived,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "note": "Placeholder runner. Replace with Abaqus ODB-derived local behavior results.",
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)


def run_placeholder_solver(payload: dict):
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


def main(argv) -> int:
    input_path = Path(argv[1]) if len(argv) > 1 else Path("input_data.json")
    if not input_path.exists():
        print(f"input JSON not found: {input_path}", file=sys.stderr)
        return 2

    payload = load_payload(input_path)
    job_dir = input_path.resolve().parent
    curvature, moment_kn_m, derived = run_placeholder_solver(payload)
    write_result_csv(job_dir / "result_data.csv", curvature, moment_kn_m)
    write_summary(job_dir / "result_summary.json", "PLACEHOLDER_BACKEND_RUNNER", payload, curvature, moment_kn_m, derived)
    print(f"Wrote {job_dir / 'result_data.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
