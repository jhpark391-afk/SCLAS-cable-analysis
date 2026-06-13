#!/usr/bin/env python3
"""Local SCLAS contract smoke checks.

This script intentionally writes only under the ignored jobs/ folder.
It validates the Visual Studio project references, synchronized test copies,
Python compilation, and the placeholder backend output contract.
"""

import compileall
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_DIR / "code"
JOBS_DIR = PROJECT_DIR / "jobs" / "SCLAS_jobs"


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_path(include: str) -> Path:
    return PROJECT_DIR.joinpath(*include.replace("\\", "/").split("/"))


def check_pyproj_references() -> None:
    pyproj = PROJECT_DIR / "SCLAS-cable-analysis.pyproj"
    root = ET.parse(pyproj).getroot()
    ns = {"msb": "http://schemas.microsoft.com/developer/msbuild/2003"}
    missing = []
    for item in root.findall(".//msb:Compile", ns) + root.findall(".//msb:Content", ns):
        include = item.attrib.get("Include", "")
        if include and not project_path(include).exists():
            missing.append(include)
    if missing:
        fail("Missing .pyproj references: " + ", ".join(missing))
    print("[OK] Visual Studio project references exist")


def check_synced_files() -> None:
    pairs = [
        (CODE_DIR / "sclas_remote_gui.py", CODE_DIR / "SCLAS_test" / "sclas_remote_gui.py"),
        (CODE_DIR / "abaqus_runner.py", CODE_DIR / "SCLAS_test" / "abaqus_runner.py"),
    ]
    for left, right in pairs:
        if sha256(left) != sha256(right):
            fail(f"Test copy is not synchronized: {left.name}")
    print("[OK] Main GUI/backend files match SCLAS_test copies")


def check_compile() -> None:
    if not compileall.compile_dir(str(CODE_DIR), quiet=1):
        fail("Python compilation failed")
    print("[OK] Python files compile")


def rich_backend_payload() -> dict:
    """Build a GUI-like payload so normal Python checks the Abaqus contract shape."""
    return {
        "metadata": {
            "contract_version": "sclas-abaqus-contract-v1",
            "frontend_version": "self_check",
            "job_id": "self_check_contract",
            "team_name": "HELIX",
        },
        "derived_geometry_mm": {
            "core_outer_radius_mm": 15.3,
            "core_center_radius_mm": 17.66,
            "inner_sheath_inner_radius_mm": 32.96,
            "inner_sheath_outer_radius_mm": 37.46,
            "inner_armour_center_radius_mm": 39.96,
            "inner_armour_wire_radius_mm": 2.0,
            "inner_armour_outer_radius_mm": 41.96,
            "bedding_outer_radius_mm": 43.06,
            "outer_armour_center_radius_mm": 45.56,
            "outer_armour_wire_radius_mm": 2.0,
            "outer_sheath_inner_radius_mm": 47.56,
            "outer_sheath_outer_radius_mm": 52.06,
        },
        "armour": {
            "inner_wire_radius_mm": 2.0,
            "outer_wire_radius_mm": 2.0,
            "inner_wire_count": 55,
            "outer_wire_count": 63,
            "inner_lay_angle_deg": 20.1,
            "outer_lay_angle_deg": 19.6,
            "lay_angle_deg": 19.85,
        },
        "mesh": {
            "requested_element_type": "C3D8R",
            "model_strategy": "periodic_homogenized_cell",
            "armour_model": "beam_with_contact_surface",
            "axial_divisions": 40,
            "core_circumferential_divisions": 24,
            "armour_circumferential_divisions": 8,
            "contact_regularization_beta": 0.001,
        },
        "analysis_conditions": {
            "effective_length_mm": 234.2,
            "hydrostatic_pressure_mpa": 40.0,
            "residual_contact_pressure_mpa": 0.3,
            "friction_coefficient": 0.22,
            "max_curvature_1_per_m": 0.08,
            "max_twist_rad_per_m": 0.05,
            "max_axial_strain": 0.002,
            "radial_compression_ratio": 0.015,
            "contact_regularization_beta": 0.001,
            "loading_cycles": 2,
            "solver_steps": 500,
        },
        "study_scope": {
            "enabled_assessments": {
                "bending_stick_slip": True,
                "torsion": True,
                "tension_bending_coupling": True,
                "compression_bird_caging": True,
                "pressure_effect": True,
            }
        },
        "numerical_model": {
            "contact_interfaces": [
                {
                    "name": "inner_armour_to_inner_sheath",
                    "master": "inner_armour_helical_beams_or_surfaces",
                    "slave": "inner_sheath_outer_surface",
                    "priority": "high",
                },
                {
                    "name": "inner_armour_to_bedding",
                    "master": "inner_armour_helical_beams_or_surfaces",
                    "slave": "bedding_inner_surface",
                    "priority": "high",
                },
                {
                    "name": "outer_armour_to_bedding",
                    "master": "outer_armour_helical_beams_or_surfaces",
                    "slave": "bedding_outer_surface",
                    "priority": "high",
                },
                {
                    "name": "outer_armour_to_outer_sheath",
                    "master": "outer_armour_helical_beams_or_surfaces",
                    "slave": "outer_sheath_inner_surface",
                    "priority": "high",
                },
                {
                    "name": "armour_cross_layer_interaction",
                    "master": "outer_armour_layer",
                    "slave": "inner_armour_layer",
                    "priority": "medium",
                },
            ],
            "contact_interface_defaults": {
                "normal": "penalty_or_augmented_lagrange",
                "tangential": "regularized_coulomb",
                "friction_coefficient": 0.22,
                "residual_contact_pressure_mpa": 0.3,
                "regularization_beta": 0.001,
            },
        },
        "equivalent_properties": {
            "core_equivalent_EI_N_m2": 65.14406526483796,
        },
    }


def require_keys(data: dict, keys, label: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        fail(f"{label} missing keys: {', '.join(missing)}")


def check_backend_contract() -> None:
    job_dir = JOBS_DIR / ("self_check_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "input_data.json").write_text(
        json.dumps(rich_backend_payload(), indent=4),
        encoding="utf-8",
    )
    shutil.copy2(CODE_DIR / "abaqus_runner.py", job_dir / "abaqus_runner.py")

    proc = subprocess.run(
        [sys.executable, "abaqus_runner.py", "input_data.json"],
        cwd=str(job_dir),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("abaqus_runner.py failed:\n" + proc.stdout + proc.stderr)

    result_csv = job_dir / "result_data.csv"
    summary_json = job_dir / "result_summary.json"
    manifest_json = job_dir / "abaqus_mesh_manifest.json"
    for path in [result_csv, summary_json, manifest_json]:
        if not path.exists():
            fail(f"Backend did not create {path.name}")

    with result_csv.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0] if rows else []
    if header != ["curvature_1_per_m", "moment_kn_m"]:
        fail(f"Unexpected result_data.csv header: {header}")
    if len(rows) != 501:
        fail(f"Unexpected result_data.csv row count: {len(rows)}")

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))

    require_keys(
        summary,
        [
            "result_contract",
            "backend_readiness",
            "hysteresis_loss_kj_per_m_proxy",
            "derived_placeholder_metrics",
            "enabled_assessments",
        ],
        "result_summary.json",
    )
    if summary["result_contract"].get("required_columns") != ["curvature_1_per_m", "moment_kn_m"]:
        fail("result_summary.json has an unexpected result contract")
    expected_assessments = {
        "bending_stick_slip",
        "torsion",
        "tension_bending_coupling",
        "compression_bird_caging",
        "pressure_effect",
    }
    if set(summary.get("enabled_assessments", [])) != expected_assessments:
        fail("result_summary.json enabled assessments do not match the GUI-like payload")
    for key in expected_assessments:
        if key not in summary["backend_readiness"]:
            fail(f"backend_readiness missing {key}")
    derived = summary["derived_placeholder_metrics"]
    require_keys(
        derived,
        [
            "axial_torsional_stiffness_matrix_proxy",
            "calibration_targets",
            "pressure_softening_factor",
            "bird_caging_risk_index",
        ],
        "derived_placeholder_metrics",
    )

    require_keys(
        manifest,
        [
            "mesh_settings_from_gui",
            "contact_interface_defaults",
            "contact_binding_scaffold",
            "contact_property_scaffold",
            "contact_region_scaffold_status",
            "contact_interaction_scaffold_status",
            "contact_pair_scaffold_status",
            "boundary_condition_scaffold_status",
            "components",
        ],
        "abaqus_mesh_manifest.json",
    )
    if manifest.get("status") != "mesh_request_only":
        fail(f"Unexpected non-Abaqus manifest status: {manifest.get('status')}")
    defaults = manifest["contact_interface_defaults"]
    if defaults.get("friction_coefficient") != 0.22 or defaults.get("regularization_beta") != 0.001:
        fail("contact interface defaults were not carried into the manifest")
    bindings = manifest["contact_binding_scaffold"]
    if len(bindings) != 5:
        fail(f"Expected 5 contact binding scaffold records, found {len(bindings)}")
    if any(item.get("status") != "resolved_scaffold_not_bound_to_pair" for item in bindings):
        fail("At least one contact binding was not resolved to scaffold regions")
    component_names = {item.get("name") for item in manifest["components"]}
    for required in [
        "inner_sheath_equivalent_solid",
        "bedding_equivalent_solid",
        "outer_sheath_equivalent_solid",
        "inner_armour_helical_beams",
        "outer_armour_helical_beams",
    ]:
        if required not in component_names:
            fail(f"manifest components missing {required}")
    if manifest["contact_property_scaffold"].get("status") != "not_created":
        fail("Non-Abaqus self-check should leave the Abaqus contact property as not_created")
    if manifest.get("boundary_condition_scaffold_status") != "not_created":
        fail("Non-Abaqus self-check should leave boundary conditions as not_created")

    diag_proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_offline_diagnostics.py"),
            str(job_dir),
            "--json",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if diag_proc.returncode != 0:
        fail("sclas_offline_diagnostics.py failed:\n" + diag_proc.stdout + diag_proc.stderr)
    try:
        diag = json.loads(diag_proc.stdout)
    except Exception as exc:
        fail(f"sclas_offline_diagnostics.py did not emit JSON: {exc}")
    if any(item.get("severity") == "error" for item in diag.get("issues", [])):
        fail("Offline diagnostics reported an error: " + json.dumps(diag.get("issues"), indent=2))
    diagnostic_summary = diag.get("diagnostic_summary", {})
    if not diagnostic_summary.get("recommended_next_action"):
        fail("Offline diagnostics did not produce a recommended next action")
    if diag.get("result_data_csv", {}).get("data_rows") != 500:
        fail("Offline diagnostics did not read the expected result CSV row count")
    saved_report = job_dir / "offline_diagnostics_report.json"
    if not saved_report.exists():
        fail("Offline diagnostics did not save offline_diagnostics_report.json")
    saved_markdown_report = job_dir / "offline_diagnostics_report.md"
    if not saved_markdown_report.exists():
        fail("Offline diagnostics did not save offline_diagnostics_report.md")

    print(f"[OK] Backend contract smoke job: {job_dir}")


def check_endpoint_sweep_diagnostics() -> None:
    job_dir = JOBS_DIR / ("self_check_endpoint_sweep_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    job_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        ["curvature_1_per_m", "moment_kn_m"],
        ["-0.008", "-0.031"],
        ["-0.004", "-0.015"],
        ["0", "0"],
        ["0.004", "0.016"],
        ["0.008", "0.032"],
    ]
    with (job_dir / "result_data.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)
    summary = {
        "source": "SCLAS_CURVE_V0_ENDPOINT_SWEEP",
        "status": "completed",
        "num_points": 5,
        "rows_written": 5,
        "result_contract": {
            "csv_file": "result_data.csv",
            "required_columns": ["curvature_1_per_m", "moment_kn_m"],
            "summary_file": "result_summary.json",
            "primary_result": "bending moment-curvature endpoint sweep",
        },
        "mesh_status": {
            "status": "endpoint_sweep_parent",
            "child_job_count": 5,
        },
        "backend_readiness": {
            "bending_stick_slip": {
                "requested": True,
                "status": "abaqus_endpoint_sweep_curve_v0",
                "next_step": "Validate endpoint sweep shape against a continuous bending load path.",
            },
            "source": "SCLAS_CURVE_V0_ENDPOINT_SWEEP",
        },
        "abaqus_result_quality": {
            "curve_class": "endpoint_sweep_curve_v0",
            "is_research_curve": False,
            "backend_readiness_status": "abaqus_endpoint_sweep_curve_v0",
        },
        "endpoint_sweep_validation": {
            "required_child_source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
            "required_child_odb_status": "extracted",
            "all_child_jobs_validated": True,
            "aggregation_rule": "last ODB-extracted CSV row from each child job",
        },
        "child_jobs": [
            {
                "factor": factor,
                "job": f"curve_v0_child_{idx}",
                "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
                "odb_status": "extracted",
                "odb_rows_written": 2,
                "curve_class": "two_point_odb_smoke",
            }
            for idx, factor in enumerate([-0.1, -0.05, 0.0, 0.05, 0.1], start=1)
        ],
    }
    (job_dir / "result_summary.json").write_text(json.dumps(summary, indent=4), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_offline_diagnostics.py"),
            str(job_dir),
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("Endpoint sweep diagnostics failed:\n" + proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if any(item.get("severity") == "error" for item in report.get("issues", [])):
        fail("Endpoint sweep diagnostics reported errors: " + json.dumps(report.get("issues"), indent=2))
    action = report.get("diagnostic_summary", {}).get("recommended_next_action", "")
    if "Endpoint sweep curve-v0 aggregated" not in action:
        fail("Endpoint sweep diagnostics recommended the wrong next action: " + action)
    summary_section = report.get("result_summary_json", {})
    if summary_section.get("child_job_count") != 5 or summary_section.get("rows_written") != 5:
        fail("Endpoint sweep diagnostics did not read parent sweep row/child counts")

    print(f"[OK] Endpoint sweep diagnostics: {job_dir}")


def main() -> int:
    checks = [
        check_pyproj_references,
        check_synced_files,
        check_compile,
        check_backend_contract,
        check_endpoint_sweep_diagnostics,
    ]
    try:
        for check in checks:
            check()
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print("[OK] SCLAS self-check complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
