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
import os
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
        ["-0.008", "-0.032"],
        ["-0.004", "-0.016"],
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
        "child_jobs": [],
    }
    child_values = [
        (-0.1, -0.008, -0.032),
        (-0.05, -0.004, -0.016),
        (0.0, 0.0, 0.0),
        (0.05, 0.004, 0.016),
        (0.1, 0.008, 0.032),
    ]
    for idx, (factor, curvature, moment) in enumerate(child_values, start=1):
        child_dir = job_dir / f"curve_v0_child_{idx}"
        child_dir.mkdir(parents=True, exist_ok=True)
        with (child_dir / "result_data.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["curvature_1_per_m", "moment_kn_m"])
            writer.writerow(["0", "0"])
            writer.writerow([f"{curvature:.12g}", f"{moment:.12g}"])
        child_odb = {
            "status": "extracted",
            "method": "history",
            "rows_written": 2,
        }
        child_summary = {
            "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
            "status": "completed",
            "num_points": 2,
            "result_contract": {
                "csv_file": "result_data.csv",
                "required_columns": ["curvature_1_per_m", "moment_kn_m"],
                "summary_file": "result_summary.json",
            },
            "mesh_status": {
                "status": "abaqus_mesh_created",
            },
            "backend_readiness": {
                "bending_stick_slip": {
                    "requested": True,
                    "status": "abaqus_odb_smoke_two_point",
                },
            },
            "odb_extraction": child_odb,
            "abaqus_result_quality": {
                "curve_class": "two_point_odb_smoke",
                "is_research_curve": False,
            },
        }
        (child_dir / "result_summary.json").write_text(json.dumps(child_summary, indent=4), encoding="utf-8")
        (child_dir / "odb_extraction_summary.json").write_text(json.dumps(child_odb, indent=4), encoding="utf-8")
        (child_dir / "solver_stdout.txt").write_text(
            "\n".join([
                "Abaqus JOB curve_v0_child_{0}_mesh COMPLETED".format(idx),
                "COLLECTING MODEL CONSTRAINT INFORMATION FOR OVERCONSTRAINT CHECKS",
                "***WARNING: SURFACE TO SURFACE CONTACT APPROACH FOR CONTACT PAIR IS NOT YET AVAILABLE FOR 3D BEAM OR TRUSS SLAVE SURFACE. NODE TO SURFACE APPROACH WILL BE USED INSTEAD.",
                "",
            ]),
            encoding="utf-8",
        )
        (child_dir / f"curve_v0_child_{idx}.dat").write_text(
            "\n".join([
                "***WARNING: 2 elements are distorted. Either the isoparametric angles are",
                "            out of the suggested limits. The elements have been identified in",
                "            element set WarnElemDistorted.",
                "***WARNING: THE CURVATURE OF SOME B31 BEAM ELEMENTS IS HIGH.",
                "            THE ELEMENTS HAVE BEEN IDENTIFIED IN ELEMENT SET WarnBeamCurvature1.",
                "***WARNING: THE TWIST OF SOME B31 BEAM ELEMENTS IS HIGH.",
                "            THE ELEMENTS HAVE BEEN IDENTIFIED IN ELEMENT SET WarnBeamTwist.",
                "",
                "Distorted isoparametric elements",
                "",
                "             Element               Min/max angle   Adjusted nodes",
                "--------------------------------- ---------------- --------------",
                "           BEDDINGEQUIVALENT_1.1          42.0000       NO",
                "      INNERSHEATHEQUIVALENT_1.2          44.0000       NO",
                "",
            ]),
            encoding="utf-8",
        )
        summary["child_jobs"].append({
            "factor": factor,
            "job": f"curve_v0_child_{idx}",
            "path": str(child_dir),
            "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
            "odb_status": "extracted",
            "odb_rows_written": 2,
            "curve_class": "two_point_odb_smoke",
            "curvature_1_per_m": curvature,
            "moment_kn_m": moment,
        })
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
    if "B31 helical beam curvature/twist warnings remain" not in action:
        fail("Endpoint sweep diagnostics recommended the wrong next action: " + action)
    summary_section = report.get("result_summary_json", {})
    if summary_section.get("child_job_count") != 5 or summary_section.get("rows_written") != 5:
        fail("Endpoint sweep diagnostics did not read parent sweep row/child counts")
    shape_section = report.get("endpoint_sweep_shape", {})
    if not shape_section.get("shape_checks_passed"):
        fail("Endpoint sweep shape diagnostics did not pass: " + json.dumps(shape_section, indent=2))
    if abs(shape_section.get("factor_curvature_scale", 0.0) - 0.08) > 1e-12:
        fail("Endpoint sweep factor-to-curvature scale was not detected")
    child_section = report.get("endpoint_sweep_children", {})
    if not child_section.get("all_children_deep_validated"):
        fail("Endpoint sweep child deep diagnostics did not pass: " + json.dumps(child_section, indent=2))
    if child_section.get("blocking_log_hits") != 0:
        fail("Endpoint sweep child diagnostics found blocking log hits")
    warning_categories = child_section.get("warning_categories", {})
    if warning_categories.get("beam_contact_surface_to_node_fallback") != 5:
        fail("Endpoint sweep child warning taxonomy did not detect contact fallback warnings")
    if warning_categories.get("overconstraint_check"):
        fail("Endpoint sweep warning taxonomy counted overconstraint progress notes as warnings")
    note_categories = child_section.get("note_categories", {})
    if note_categories.get("overconstraint_check") != 5:
        fail("Endpoint sweep note taxonomy did not retain overconstraint progress notes")
    mesh_quality = child_section.get("mesh_quality_warning_details", {})
    if mesh_quality.get("distorted_reported_element_count") != 10:
        fail("Endpoint sweep diagnostics did not aggregate distorted element warning counts")
    distorted_parts = mesh_quality.get("distorted_table_parts", {})
    if distorted_parts.get("BEDDINGEQUIVALENT") != 5 or distorted_parts.get("INNERSHEATHEQUIVALENT") != 5:
        fail("Endpoint sweep diagnostics did not aggregate distorted table part counts")
    if mesh_quality.get("distorted_table_min_angle") != 42.0:
        fail("Endpoint sweep diagnostics did not aggregate distorted table min angle")
    b31_quality = child_section.get("b31_beam_warning_details", {})
    b31_sets = b31_quality.get("warning_sets", {})
    if b31_sets.get("WarnBeamCurvature1") != 5 or b31_sets.get("WarnBeamTwist") != 5:
        fail("Endpoint sweep diagnostics did not aggregate B31 beam warning sets")
    if b31_quality.get("total_warning_sets") != 10:
        fail("Endpoint sweep diagnostics did not count total B31 warning sets")
    if not b31_quality.get("first_warning_context"):
        fail("Endpoint sweep diagnostics did not retain B31 first warning context")

    summary_proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_job_summary.py"),
            str(job_dir),
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    if summary_proc.returncode != 0:
        fail("sclas_job_summary.py failed:\n" + summary_proc.stdout + summary_proc.stderr)
    job_summary = json.loads(summary_proc.stdout)
    if job_summary.get("health") != "REVIEW":
        fail("Job summary did not classify B31-warning endpoint sweep as REVIEW")
    if job_summary.get("curve_class") != "endpoint_sweep_curve_v0":
        fail("Job summary did not preserve endpoint sweep curve class")
    if job_summary.get("b31_total_warning_sets") != 10:
        fail("Job summary did not expose B31 warning totals")
    if "B31 helical beam curvature/twist warnings remain" not in job_summary.get("recommended_next_action", ""):
        fail("Job summary did not preserve the recommended next action")

    print(f"[OK] Endpoint sweep diagnostics: {job_dir}")


def check_continuous_curve_v0_diagnostics() -> None:
    job_dir = JOBS_DIR / ("self_check_continuous_curve_v0_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    job_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        ["curvature_1_per_m", "moment_kn_m"],
        ["0", "0"],
        ["0.008", "2.58674475"],
        ["0", "-4.57153059542e-08"],
        ["-0.008", "-2.586701"],
        ["0", "-8.23443464469e-10"],
    ]
    with (job_dir / "result_data.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)

    odb_summary = {
        "status": "extracted",
        "method": "history",
        "rows_written": 5,
    }
    summary = {
        "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
        "status": "completed",
        "rows_written": 5,
        "num_points": 5,
        "max_abs_moment_kn_m": 2.58674475,
        "result_contract": {
            "csv_file": "result_data.csv",
            "required_columns": ["curvature_1_per_m", "moment_kn_m"],
            "summary_file": "result_summary.json",
            "primary_result": "bending moment-curvature loop",
        },
        "mesh_status": {
            "status": "abaqus_mesh_created",
        },
        "backend_readiness": {
            "bending_stick_slip": {
                "requested": True,
                "status": "abaqus_odb_curve_v0",
            },
            "source": "SCLAS_ABAQUS_ODB_EXTRACTOR",
        },
        "odb_extraction": odb_summary,
        "abaqus_result_quality": {
            "curve_class": "multi_point_curve_v0",
            "is_research_curve": True,
            "backend_readiness_status": "abaqus_odb_curve_v0",
        },
    }
    manifest = {
        "status": "abaqus_mesh_created",
        "contact_region_scaffold_status": "created",
        "contact_interaction_scaffold_status": "created",
        "contact_pair_scaffold_status": "partial",
        "boundary_condition_scaffold_status": "created",
        "abaqus_files": ["continuous_curve_v0.inp"],
        "contact_binding_scaffold": [],
        "components": [],
        "beam_orientation_adjustments": [
            {
                "component": "ARMOUR",
                "status": "assigned",
                "assigned_count": 48,
                "expected_segments": 48,
                "mode": "bishop_segment",
            }
        ],
    }
    (job_dir / "result_summary.json").write_text(json.dumps(summary, indent=4), encoding="utf-8")
    (job_dir / "odb_extraction_summary.json").write_text(json.dumps(odb_summary, indent=4), encoding="utf-8")
    (job_dir / "abaqus_mesh_manifest.json").write_text(json.dumps(manifest, indent=4), encoding="utf-8")
    (job_dir / "continuous_curve_v0.inp").write_text(
        "\n".join([
            "*Heading",
            "** synthetic continuous CurveV0 self-check input deck",
            "*Assembly, name=Assembly",
            "*End Assembly",
            "*Step, name=SCLAS_CyclicBendingStep, nlgeom=YES",
            "*Static",
            "1., 1.",
            "*End Step",
            "",
        ]),
        encoding="utf-8",
    )
    (job_dir / "solver_stdout.txt").write_text(
        "\n".join([
            "Abaqus JOB continuous_curve_v0 COMPLETED",
            "",
        ]),
        encoding="utf-8",
    )

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
        fail("Continuous CurveV0 diagnostics failed:\n" + proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if any(item.get("severity") == "error" for item in report.get("issues", [])):
        fail("Continuous CurveV0 diagnostics reported errors: " + json.dumps(report.get("issues"), indent=2))
    shape = report.get("continuous_curve_v0_shape", {})
    if not shape.get("shape_checks_passed"):
        fail("Continuous CurveV0 shape diagnostics did not pass: " + json.dumps(shape, indent=2))
    if shape.get("numeric_rows") != 5 or shape.get("near_zero_count") < 3:
        fail("Continuous CurveV0 shape diagnostics did not read the expected path rows")
    if abs(shape.get("max_abs_curvature_1_per_m", 0.0) - 0.008) > 1e-12:
        fail("Continuous CurveV0 shape diagnostics reported the wrong max curvature")
    action = report.get("diagnostic_summary", {}).get("recommended_next_action", "")
    if "Continuous CurveV0 multi-point ODB curve passed" not in action:
        fail("Continuous CurveV0 diagnostics recommended the wrong next action: " + action)

    summary_proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_job_summary.py"),
            str(job_dir),
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    if summary_proc.returncode != 0:
        fail("sclas_job_summary.py failed for continuous CurveV0:\n" + summary_proc.stdout + summary_proc.stderr)
    job_summary = json.loads(summary_proc.stdout)
    if job_summary.get("health") != "REVIEW":
        fail("Job summary should classify partial contact scaffold continuous CurveV0 as REVIEW")
    if not job_summary.get("continuous_curve_v0_shape_passed"):
        fail("Job summary did not expose continuous CurveV0 shape status")
    if job_summary.get("continuous_curve_v0_rows") != 5:
        fail("Job summary did not expose continuous CurveV0 row count")

    latest_proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_job_summary.py"),
            "--latest",
            "--json",
            "--include-self-check",
        ],
        text=True,
        capture_output=True,
    )
    if latest_proc.returncode != 0:
        fail("sclas_job_summary.py --latest --include-self-check failed:\n" + latest_proc.stdout + latest_proc.stderr)
    latest_summary = json.loads(latest_proc.stdout)
    if Path(latest_summary.get("job_dir", "")).resolve() != job_dir.resolve():
        fail("Job summary --latest --include-self-check did not select the newest continuous CurveV0 self-check job")

    print(f"[OK] Continuous CurveV0 diagnostics: {job_dir}")


def check_curve_v0_comparison() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_curve_compare.py"),
            "--json",
            "--include-self-check",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_curve_compare.py failed:\n" + proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if report.get("status") != "review":
        fail("CurveV0 comparison should classify synthetic scale mismatch as review")
    if "self_check_endpoint_sweep_" not in report.get("endpoint_job", ""):
        fail("CurveV0 comparison did not select the latest endpoint self-check job")
    if "self_check_continuous_curve_v0_" not in report.get("continuous_job", ""):
        fail("CurveV0 comparison did not select the latest continuous self-check job")
    if report.get("peak_moment_ratio_continuous_over_endpoint", 0.0) < 10.0:
        fail("CurveV0 comparison did not expose the expected synthetic scale mismatch")
    if not report.get("warnings"):
        fail("CurveV0 comparison did not report warnings for the synthetic scale mismatch")
    saved_report = Path(report.get("saved_report", ""))
    if not saved_report.exists():
        fail("CurveV0 comparison did not save JSON report")
    saved_markdown = Path(report.get("saved_markdown_report", ""))
    if not saved_markdown.exists():
        fail("CurveV0 comparison did not save Markdown report")
    if "SCLAS CurveV0 Comparison" not in saved_markdown.read_text(encoding="utf-8"):
        fail("CurveV0 comparison Markdown report does not contain the expected heading")
    summary_proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_job_summary.py"),
            report["continuous_job"],
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    if summary_proc.returncode != 0:
        fail("sclas_job_summary.py failed to read saved CurveV0 comparison report:\n" + summary_proc.stdout + summary_proc.stderr)
    job_summary = json.loads(summary_proc.stdout)
    if job_summary.get("curve_v0_comparison_status") != "review":
        fail("Job summary did not expose saved CurveV0 comparison status")
    if job_summary.get("curve_v0_comparison_warning_count") != 3:
        fail("Job summary did not expose saved CurveV0 comparison warning count")
    if job_summary.get("curve_v0_comparison_peak_ratio", 0.0) < 10.0:
        fail("Job summary did not expose saved CurveV0 comparison peak ratio")
    if "boundary-condition scaling" not in job_summary.get("recommended_next_action", ""):
        fail("Job summary did not prioritize saved CurveV0 comparison next action")

    print("[OK] CurveV0 endpoint/continuous comparison")


def write_minimal_job(job_dir: Path, source: str) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    with (job_dir / "result_data.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["curvature_1_per_m", "moment_kn_m"])
        writer.writerow(["0", "0"])
        writer.writerow(["0.01", "0.04"])
    summary = {
        "source": source,
        "status": "completed",
        "num_points": 2,
        "rows_written": 2,
        "result_contract": {
            "csv_file": "result_data.csv",
            "required_columns": ["curvature_1_per_m", "moment_kn_m"],
            "summary_file": "result_summary.json",
        },
    }
    (job_dir / "result_summary.json").write_text(json.dumps(summary, indent=4), encoding="utf-8")


def check_latest_job_filtering() -> None:
    root = JOBS_DIR / ("self_check_filter_root_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    user_job = root / "job_filter_user"
    self_job = root / "self_check_filter_newer"
    write_minimal_job(user_job, "FILTER_USER_JOB")
    write_minimal_job(self_job, "FILTER_SELF_CHECK_JOB")
    newer_time = datetime.now().timestamp() + 10
    for path in [self_job / "result_data.csv", self_job / "result_summary.json"]:
        os.utime(path, (newer_time, newer_time))

    base_cmd = [
        sys.executable,
        str(CODE_DIR / "sclas_job_summary.py"),
        "--latest",
        "--json",
        "--job-root",
        str(root),
    ]
    default_proc = subprocess.run(base_cmd, text=True, capture_output=True)
    if default_proc.returncode != 0:
        fail("Default latest job filtering failed:\n" + default_proc.stdout + default_proc.stderr)
    default_summary = json.loads(default_proc.stdout)
    if Path(default_summary.get("job_dir", "")).name != user_job.name:
        fail("Default latest job selection did not exclude self_check jobs")

    include_proc = subprocess.run(base_cmd + ["--include-self-check"], text=True, capture_output=True)
    if include_proc.returncode != 0:
        fail("Latest job filtering with --include-self-check failed:\n" + include_proc.stdout + include_proc.stderr)
    include_summary = json.loads(include_proc.stdout)
    if Path(include_summary.get("job_dir", "")).name != self_job.name:
        fail("--include-self-check did not allow the newer self_check job")

    index_cmd = [
        sys.executable,
        str(CODE_DIR / "sclas_job_index.py"),
        "--json",
        "--job-root",
        str(root),
        "--limit",
        "5",
        "--save-report",
        "--save-markdown",
    ]
    index_proc = subprocess.run(index_cmd, text=True, capture_output=True)
    if index_proc.returncode != 0:
        fail("sclas_job_index.py failed:\n" + index_proc.stdout + index_proc.stderr)
    index = json.loads(index_proc.stdout)
    if index.get("total_candidates") != 1 or index.get("reported_count") != 1:
        fail("Job index did not exclude self_check jobs by default")
    if index.get("jobs", [{}])[0].get("name") != user_job.name:
        fail("Job index reported the wrong default job")
    first_job = index.get("jobs", [{}])[0]
    if first_job.get("readiness_label") not in ("low", "triage", "promising", "candidate") or first_job.get("readiness_score") is None:
        fail("Job index did not assign a readiness score/label to the default job")
    best_job = index.get("best_job", {})
    if best_job.get("name") != user_job.name:
        fail("Job index did not expose the best default candidate")
    saved_index = Path(index.get("saved_report", ""))
    saved_markdown = Path(index.get("saved_markdown_report", ""))
    if not saved_index.exists() or not saved_markdown.exists():
        fail("Job index did not save JSON and Markdown reports")
    markdown_text = saved_markdown.read_text(encoding="utf-8")
    if "SCLAS Job Index" not in markdown_text:
        fail("Job index Markdown report does not contain the expected heading")
    if "Best Candidate" not in markdown_text:
        fail("Job index Markdown report does not contain the best candidate section")

    include_index_proc = subprocess.run(index_cmd + ["--include-self-check"], text=True, capture_output=True)
    if include_index_proc.returncode != 0:
        fail("sclas_job_index.py --include-self-check failed:\n" + include_index_proc.stdout + include_index_proc.stderr)
    include_index = json.loads(include_index_proc.stdout)
    if include_index.get("total_candidates") != 2:
        fail("Job index --include-self-check did not include both fixture jobs")

    print("[OK] Latest job filtering and job index exclude self_check by default")


def check_project_status() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_project_status.py"),
            "--json",
            "--include-self-check",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_project_status.py failed:\n" + proc.stdout + proc.stderr)
    status = json.loads(proc.stdout)
    if not status.get("completion_flags"):
        fail("Project status did not emit completion flags")
    if status.get("curve_v0_comparison_status") != "review":
        fail("Project status did not expose latest CurveV0 comparison status")
    if "contact preload" not in status.get("recommended_next_action", "").lower():
        fail("Project status did not prioritize the contact preload/closure blocker")
    saved_report = Path(status.get("saved_report", ""))
    saved_markdown_report = Path(status.get("saved_markdown_report", ""))
    if not saved_report.exists():
        fail("Project status did not save project_status_report.json")
    if not saved_markdown_report.exists():
        fail("Project status did not save project_status_report.md")
    if "HELIX / SCLAS Project Status" not in saved_markdown_report.read_text(encoding="utf-8"):
        fail("Project status Markdown report does not contain the expected heading")

    print("[OK] Project status dashboard")


def check_acceptance_gate() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_acceptance_gate.py"),
            "--json",
            "--include-self-check",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_acceptance_gate.py failed:\n" + proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if report.get("overall_status") != "blocked":
        fail("Acceptance gate should block synthetic contact-incomplete jobs")
    gate_statuses = {item.get("name"): item.get("status") for item in report.get("gates", [])}
    if gate_statuses.get("contact_preload_closure") != "blocked":
        fail("Acceptance gate did not block missing/nonzero CPRESS contact closure")
    if gate_statuses.get("odb_local_fields") != "blocked":
        fail("Acceptance gate did not block missing required ODB local fields")
    if "remote Abaqus PC" not in report.get("recommended_next_action", ""):
        fail("Acceptance gate did not route the next action to the remote Abaqus PC")
    saved_report = Path(report.get("saved_report", ""))
    saved_markdown = Path(report.get("saved_markdown_report", ""))
    if not saved_report.exists() or not saved_markdown.exists():
        fail("Acceptance gate did not save JSON and Markdown reports")
    if "HELIX / SCLAS Acceptance Gate" not in saved_markdown.read_text(encoding="utf-8"):
        fail("Acceptance gate Markdown report does not contain the expected heading")

    print("[OK] Acceptance gate")


def check_handoff_snapshot() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_handoff_snapshot.py"),
            "--json",
            "--include-self-check",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_handoff_snapshot.py failed:\n" + proc.stdout + proc.stderr)
    snapshot = json.loads(proc.stdout)
    focus = snapshot.get("handoff_focus", {})
    if not focus.get("best_job"):
        fail("Handoff snapshot did not expose a best job")
    if "contact preload" not in str(focus.get("next_action", "")).lower():
        fail("Handoff snapshot did not carry the current contact preload next action")
    if not snapshot.get("project_status", {}).get("completion_flags"):
        fail("Handoff snapshot did not embed project status")
    git = snapshot.get("git", {})
    if "ahead" not in git or "behind" not in git:
        fail("Handoff snapshot did not embed git ahead/behind state")
    if "dirty" not in git or "sync_status" not in git:
        fail("Handoff snapshot did not embed git dirty/sync status")
    acceptance = snapshot.get("acceptance_gate", {})
    if not acceptance.get("overall_status"):
        fail("Handoff snapshot did not embed acceptance gate status")
    if acceptance.get("overall_status") != "blocked":
        fail("Handoff snapshot should carry the blocked acceptance state for synthetic fixtures")
    if focus.get("acceptance_status") != acceptance.get("overall_status"):
        fail("Handoff focus did not mirror the acceptance gate status")
    if not snapshot.get("job_index", {}).get("jobs"):
        fail("Handoff snapshot did not embed the job index")
    saved_report = Path(snapshot.get("saved_report", ""))
    saved_markdown = Path(snapshot.get("saved_markdown_report", ""))
    if not saved_report.exists() or not saved_markdown.exists():
        fail("Handoff snapshot did not save JSON and Markdown reports")
    if "HELIX / SCLAS Handoff Snapshot" not in saved_markdown.read_text(encoding="utf-8"):
        fail("Handoff snapshot Markdown report does not contain the expected heading")

    print("[OK] Handoff snapshot")


def check_next_prompt() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_next_prompt.py"),
            "--include-self-check",
            "--save",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_next_prompt.py failed:\n" + proc.stdout + proc.stderr)
    prompt_path = PROJECT_DIR / "NEXT_CODEX_PROMPT.md"
    if not prompt_path.exists():
        fail("sclas_next_prompt.py did not save NEXT_CODEX_PROMPT.md")
    prompt = prompt_path.read_text(encoding="utf-8")
    for expected in [
        "git pull",
        "python code/sclas_handoff_snapshot.py --save-report --save-markdown",
        "python code/sclas_acceptance_gate.py --save-report --save-markdown",
        "python code/sclas_self_check.py",
        "./run_validation_suite.sh",
        "run_validation_suite.bat",
        "Git sync:",
        "Acceptance gate:",
        "contact preload",
    ]:
        if expected not in prompt:
            fail("NEXT_CODEX_PROMPT.md missing expected text: " + expected)

    print("[OK] Next Codex prompt")


def check_validation_suite() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(CODE_DIR / "sclas_validation_suite.py"),
            "--include-self-check",
            "--skip-self-check",
            "--json",
            "--save-report",
            "--save-markdown",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("sclas_validation_suite.py failed:\n" + proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if report.get("self_check", {}).get("status") != "skipped":
        fail("Validation suite did not honor --skip-self-check")
    if not report.get("git", {}).get("head"):
        fail("Validation suite did not embed git head")
    if "ahead" not in report.get("git", {}) or "behind" not in report.get("git", {}):
        fail("Validation suite did not embed git ahead/behind state")
    if "dirty" not in report.get("git", {}) or "sync_status" not in report.get("git", {}):
        fail("Validation suite did not embed git dirty/sync status")
    if not report.get("acceptance_gate", {}).get("overall_status"):
        fail("Validation suite did not embed acceptance gate status")
    if not report.get("handoff_snapshot", {}).get("saved_report"):
        fail("Validation suite did not save a handoff snapshot")
    if not report.get("next_prompt", {}).get("saved_prompt"):
        fail("Validation suite did not save the next prompt")
    saved_report = Path(report.get("saved_report", ""))
    saved_markdown = Path(report.get("saved_markdown_report", ""))
    if not saved_report.exists() or not saved_markdown.exists():
        fail("Validation suite did not save JSON and Markdown reports")
    if "HELIX / SCLAS Validation Suite" not in saved_markdown.read_text(encoding="utf-8"):
        fail("Validation suite Markdown report does not contain the expected heading")

    print("[OK] Validation suite")


def main() -> int:
    checks = [
        check_pyproj_references,
        check_synced_files,
        check_compile,
        check_backend_contract,
        check_endpoint_sweep_diagnostics,
        check_continuous_curve_v0_diagnostics,
        check_curve_v0_comparison,
        check_latest_job_filtering,
        check_project_status,
        check_acceptance_gate,
        check_handoff_snapshot,
        check_next_prompt,
        check_validation_suite,
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
