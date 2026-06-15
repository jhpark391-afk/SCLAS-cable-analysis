#!/usr/bin/env python3
"""Concise SCLAS/HELIX job-folder status summary.

This is a lightweight companion to sclas_offline_diagnostics.py. Use it when a
Lab-PC Abaqus run has produced a job folder and you want a fast one-page answer:
what ran, what quality signals were detected, and what to do next.
"""

import argparse
import json
import sys
from pathlib import Path

from sclas_job_filters import candidate_job_dirs, describe_filter
from sclas_offline_diagnostics import build_report


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_JOB_ROOT = PROJECT_DIR / "jobs" / "SCLAS_jobs"


def scalar(value, default="-"):
    if value in (None, ""):
        return default
    return value


def int_scalar(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def top_counts(counts, limit=4):
    if not isinstance(counts, dict) or not counts:
        return "-"
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return ", ".join("{0}={1}".format(key, value) for key, value in ordered[:limit])


def top_outputs(items, limit=2):
    if not isinstance(items, list) or not items:
        return "-"
    labels = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        name = item.get("interface") or item.get("target") or item.get("output")
        value = item.get("value")
        job_count = item.get("job_count")
        suffix = "" if job_count in (None, "") else " jobs={0}".format(job_count)
        labels.append("{0}={1}{2}".format(name, value, suffix))
    return ", ".join(labels) if labels else "-"


def names_to_counts(names):
    counts = {}
    if isinstance(names, list):
        for name in names:
            counts[str(name)] = counts.get(str(name), 0) + 1
    return counts


def latest_job_dir(job_root: Path, include_self_check: bool = False) -> Path:
    if not job_root.exists():
        raise FileNotFoundError("Job root does not exist: {0}".format(job_root))

    candidates = candidate_job_dirs(job_root, include_self_check=include_self_check)
    if not candidates:
        raise FileNotFoundError(
            "No SCLAS job folders were found under {0} ({1})".format(
                job_root,
                describe_filter(include_self_check),
            )
        )
    def job_mtime(path: Path) -> float:
        mtimes = []
        for file_name in ["result_summary.json", "result_data.csv", "offline_diagnostics_report.json", "curve_v0_comparison_report.json"]:
            candidate = path / file_name
            if candidate.exists():
                mtimes.append(candidate.stat().st_mtime)
        return max(mtimes) if mtimes else path.stat().st_mtime

    return max(candidates, key=job_mtime)


def load_curve_v0_comparison(job_dir: Path) -> dict:
    path = job_dir / "curve_v0_comparison_report.json"
    if not path.exists():
        return {"exists": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "exists": True,
            "parse_error": str(exc),
        }
    return {
        "exists": True,
        "path": str(path),
        "status": data.get("status"),
        "endpoint_job": data.get("endpoint_job"),
        "continuous_job": data.get("continuous_job"),
        "common_abs_curvature_1_per_m": data.get("common_abs_curvature_1_per_m"),
        "peak_moment_ratio_continuous_over_endpoint": data.get("peak_moment_ratio_continuous_over_endpoint"),
        "positive_branch_relative_delta": data.get("positive_branch_relative_delta"),
        "negative_branch_relative_delta": data.get("negative_branch_relative_delta"),
        "warning_count": len(data.get("warnings", [])) if isinstance(data.get("warnings"), list) else 0,
        "error_count": len(data.get("errors", [])) if isinstance(data.get("errors"), list) else 0,
        "recommended_next_action": data.get("recommended_next_action"),
    }


def quality_details(report: dict):
    logs = report.get("solver_logs", {})
    children = report.get("endpoint_sweep_children", {})
    result_summary = report.get("result_summary_json", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})
    mesh_quality = {}
    b31_quality = {}
    local_field = {}

    if isinstance(children, dict) and children:
        mesh_quality = children.get("mesh_quality_warning_details", {}) or {}
        b31_quality = children.get("b31_beam_warning_details", {}) or {}
        local_field = children.get("local_field_summary", {}) or {}
    if not mesh_quality and isinstance(logs, dict):
        mesh_quality = logs.get("mesh_quality_warning_details", {}) or {}
    if not b31_quality and isinstance(logs, dict):
        b31_quality = logs.get("b31_beam_warning_details", {}) or {}
    if not local_field and isinstance(result_summary, dict):
        local_field = result_summary.get("odb_local_field_summary", {}) or {}
    contact_clearance = manifest.get("contact_initial_clearance_summary", {}) if isinstance(manifest, dict) else {}
    contact_keyword = manifest.get("contact_pair_keyword_adjustment", {}) if isinstance(manifest, dict) else {}

    available_outputs = local_field.get("available_field_outputs", {})
    present_outputs = local_field.get("present_target_outputs", {})
    missing_outputs = local_field.get("missing_target_outputs", {})
    if isinstance(available_outputs, list):
        available_outputs = names_to_counts(available_outputs)
    if isinstance(present_outputs, list):
        present_outputs = names_to_counts(present_outputs)
    if isinstance(missing_outputs, list):
        missing_outputs = names_to_counts(missing_outputs)

    return {
        "actual_warning_hits": int_scalar(
            children.get("actual_warning_log_hits")
            if isinstance(children, dict) and children
            else logs.get("actual_warning_match_count")
        ),
        "blocking_log_hits": int_scalar(
            children.get("blocking_log_hits")
            if isinstance(children, dict) and children
            else len(logs.get("blocking_matches", [])) if isinstance(logs, dict) else 0
        ),
        "warning_categories": (
            children.get("warning_categories")
            if isinstance(children, dict) and children
            else logs.get("warning_categories", {}) if isinstance(logs, dict) else {}
        ),
        "mesh_warning_sets": mesh_quality.get("warning_sets", {}),
        "distorted_reported_element_count": mesh_quality.get("distorted_reported_element_count", 0),
        "distorted_table_min_angle": mesh_quality.get("distorted_table_min_angle"),
        "b31_warning_sets": b31_quality.get("warning_sets", {}),
        "b31_total_warning_sets": int_scalar(b31_quality.get("total_warning_sets")),
        "beam_orientation_status": manifest.get("beam_orientation_status"),
        "beam_orientation_modes": manifest.get("beam_orientation_modes"),
        "odb_available_field_outputs": available_outputs,
        "odb_present_local_fields": present_outputs,
        "odb_missing_local_fields": missing_outputs,
        "odb_stress_mises_max": local_field.get("stress_mises_max"),
        "odb_contact_pressure_max": local_field.get("contact_pressure_max"),
        "odb_slip_abs_max": local_field.get("slip_abs_max"),
        "odb_top_contact_pressure_outputs": local_field.get("top_contact_pressure_outputs", []),
        "odb_top_contact_opening_outputs": local_field.get("top_contact_opening_outputs", []),
        "odb_top_slip_outputs": local_field.get("top_slip_outputs", []),
        "odb_top_stress_outputs": local_field.get("top_stress_outputs", []),
        "contact_clearance_status": contact_clearance.get("status") if isinstance(contact_clearance, dict) else None,
        "contact_clearance_checked_pairs": int_scalar(contact_clearance.get("checked_pair_count")) if isinstance(contact_clearance, dict) else None,
        "contact_clearance_gapped_pairs": int_scalar(contact_clearance.get("gapped_pair_count")) if isinstance(contact_clearance, dict) else None,
        "contact_clearance_touching_pairs": int_scalar(contact_clearance.get("touching_pair_count")) if isinstance(contact_clearance, dict) else None,
        "contact_clearance_overclosed_pairs": int_scalar(contact_clearance.get("overclosed_pair_count")) if isinstance(contact_clearance, dict) else None,
        "contact_clearance_min_mm": contact_clearance.get("min_initial_clearance_mm") if isinstance(contact_clearance, dict) else None,
        "contact_clearance_max_mm": contact_clearance.get("max_initial_clearance_mm") if isinstance(contact_clearance, dict) else None,
        "contact_residual_preload_status": contact_clearance.get("residual_pressure_preload_status") if isinstance(contact_clearance, dict) else None,
        "contact_residual_pressure_mpa": contact_clearance.get("residual_contact_pressure_mpa") if isinstance(contact_clearance, dict) else None,
        "contact_pair_keyword_status": contact_keyword.get("status") if isinstance(contact_keyword, dict) else None,
        "contact_pair_keyword_target_type": contact_keyword.get("target_type") if isinstance(contact_keyword, dict) else None,
        "contact_pair_keyword_adjusted_count": int_scalar(contact_keyword.get("adjusted_count")) if isinstance(contact_keyword, dict) else 0,
        "contact_pair_keyword_beam_surface_count": len(contact_keyword.get("beam_surfaces", [])) if isinstance(contact_keyword, dict) and isinstance(contact_keyword.get("beam_surfaces"), list) else 0,
    }


def health_label(report: dict, details: dict) -> str:
    counts = report.get("diagnostic_summary", {}).get("issue_counts", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})
    comparison_status = details.get("curve_v0_comparison_status")
    if int_scalar(counts.get("error")):
        return "BLOCKED"
    if details.get("blocking_log_hits"):
        return "BLOCKED"
    if comparison_status == "blocked":
        return "BLOCKED"
    if manifest.get("contact_pair_scaffold_status") in ("partial", "failed"):
        return "REVIEW"
    if comparison_status == "review":
        return "REVIEW"
    if int_scalar(counts.get("warning")) or details.get("actual_warning_hits") or details.get("b31_total_warning_sets"):
        return "REVIEW"
    return "PASS"


def collect_summary(report: dict) -> dict:
    result_csv = report.get("result_data_csv", {})
    result_summary = report.get("result_summary_json", {})
    sweep_shape = report.get("endpoint_sweep_shape", {})
    sweep_children = report.get("endpoint_sweep_children", {})
    continuous_shape = report.get("continuous_curve_v0_shape", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})
    logs = report.get("solver_logs", {})
    diagnostic = report.get("diagnostic_summary", {})
    issue_counts = diagnostic.get("issue_counts", {})
    details = quality_details(report)
    job_dir = Path(report.get("job_dir", ""))
    comparison = load_curve_v0_comparison(job_dir) if str(job_dir) else {"exists": False}
    details["curve_v0_comparison_status"] = comparison.get("status")
    curve_summary = result_summary.get("curve_summary") if isinstance(result_summary.get("curve_summary"), dict) else None
    if curve_summary is None:
        curve_summary = result_csv.get("curve_summary", {})

    summary = {
        "job_dir": report.get("job_dir"),
        "health": health_label(report, details),
        "source": result_summary.get("source"),
        "status": result_summary.get("status"),
        "curve_class": result_summary.get("abaqus_curve_class"),
        "is_research_curve": result_summary.get("abaqus_is_research_curve"),
        "csv_rows": result_csv.get("data_rows"),
        "rows_written": result_summary.get("rows_written"),
        "child_job_count": result_summary.get("child_job_count"),
        "odb_status": result_summary.get("odb_extraction_status"),
        "odb_rows_written": result_summary.get("odb_rows_written"),
        "mesh_status": result_summary.get("mesh_status"),
        "manifest_status": manifest.get("status"),
        "contact_pair_scaffold_status": manifest.get("contact_pair_scaffold_status"),
        "solver_completed": logs.get("completed") if isinstance(logs, dict) else None,
        "endpoint_sweep_validated": result_summary.get("endpoint_sweep_validated"),
        "endpoint_sweep_shape_passed": sweep_shape.get("shape_checks_passed"),
        "endpoint_sweep_children_deep_validated": sweep_children.get("all_children_deep_validated") if isinstance(sweep_children, dict) else None,
        "continuous_curve_v0_shape_passed": continuous_shape.get("shape_checks_passed"),
        "continuous_curve_v0_rows": continuous_shape.get("numeric_rows"),
        "continuous_curve_v0_near_zero_count": continuous_shape.get("near_zero_count"),
        "continuous_curve_v0_symmetry_error": continuous_shape.get("odd_symmetry_max_relative_moment_sum"),
        "continuous_curve_v0_max_abs_curvature": continuous_shape.get("max_abs_curvature_1_per_m"),
        "continuous_curve_v0_max_abs_moment": continuous_shape.get("max_abs_moment_kn_m"),
        "curve_max_abs_curvature": curve_summary.get("max_abs_curvature_1_per_m") if isinstance(curve_summary, dict) else None,
        "curve_max_abs_moment": curve_summary.get("max_abs_moment_kn_m") if isinstance(curve_summary, dict) else None,
        "curve_loop_energy_proxy": curve_summary.get("loop_energy_proxy_kn") if isinstance(curve_summary, dict) else None,
        "curve_moment_span": curve_summary.get("moment_span_kn_m") if isinstance(curve_summary, dict) else None,
        "curve_v0_comparison_report_exists": comparison.get("exists"),
        "curve_v0_comparison_report_path": comparison.get("path"),
        "curve_v0_comparison_status": comparison.get("status"),
        "curve_v0_comparison_peak_ratio": comparison.get("peak_moment_ratio_continuous_over_endpoint"),
        "curve_v0_comparison_positive_delta": comparison.get("positive_branch_relative_delta"),
        "curve_v0_comparison_negative_delta": comparison.get("negative_branch_relative_delta"),
        "curve_v0_comparison_common_abs_curvature": comparison.get("common_abs_curvature_1_per_m"),
        "curve_v0_comparison_warning_count": comparison.get("warning_count"),
        "curve_v0_comparison_error_count": comparison.get("error_count"),
        "curve_v0_comparison_next_action": comparison.get("recommended_next_action"),
        "curve_v0_comparison_parse_error": comparison.get("parse_error"),
        "issue_counts": issue_counts,
        "recommended_next_action": diagnostic.get("recommended_next_action"),
    }
    
    cal_report = report.get("calibration_report", {})
    if cal_report:
        summary["calibration_status"] = cal_report.get("status")
        cal_metrics = cal_report.get("metrics", {})
        if cal_metrics:
            summary["calibration_elastic_stiffness"] = cal_metrics.get("elastic_bending_stiffness_kn_m2")
            summary["calibration_slip_stiffness"] = cal_metrics.get("slip_zone_bending_stiffness_kn_m2")
            summary["calibration_hysteresis_loss"] = cal_metrics.get("hysteresis_energy_loss_kn")
            summary["calibration_transition_curvature"] = cal_metrics.get("stick_to_slip_curvature_1_per_m")

    summary.update(details)
    if (
        summary.get("curve_v0_comparison_status") in ("review", "blocked")
        and summary.get("curve_v0_comparison_next_action")
    ):
        summary["recommended_next_action"] = summary.get("curve_v0_comparison_next_action")
    return summary


def print_human(summary: dict) -> None:
    print("SCLAS Job Summary")
    print("=================")
    print("Job: {0}".format(summary.get("job_dir", "-")))
    print("Health: {0}".format(summary.get("health", "-")))
    print("Source: {0}".format(scalar(summary.get("source"))))
    print("Status: {0}".format(scalar(summary.get("status"))))
    print("Curve class: {0}".format(scalar(summary.get("curve_class"))))
    print("Research curve: {0}".format(scalar(summary.get("is_research_curve"))))
    print("Rows: csv={0}, summary={1}".format(scalar(summary.get("csv_rows")), scalar(summary.get("rows_written"))))
    print("ODB: status={0}, rows={1}".format(scalar(summary.get("odb_status")), scalar(summary.get("odb_rows_written"))))
    print("ODB fields: available={0}, present={1}, missing={2}".format(
        top_counts(summary.get("odb_available_field_outputs"), 8),
        top_counts(summary.get("odb_present_local_fields"), 8),
        top_counts(summary.get("odb_missing_local_fields"), 8),
    ))
    print("ODB local metrics: stress_mises_max={0}, contact_pressure_max={1}, slip_abs_max={2}".format(
        scalar(summary.get("odb_stress_mises_max")),
        scalar(summary.get("odb_contact_pressure_max")),
        scalar(summary.get("odb_slip_abs_max")),
    ))
    print("ODB top outputs: pressure={0}; opening={1}; slip={2}; stress={3}".format(
        top_outputs(summary.get("odb_top_contact_pressure_outputs")),
        top_outputs(summary.get("odb_top_contact_opening_outputs")),
        top_outputs(summary.get("odb_top_slip_outputs")),
        top_outputs(summary.get("odb_top_stress_outputs")),
    ))
    print("Curve scalar: max|kappa|={0}, max|M|={1}, loop_energy_proxy={2}, moment_span={3}".format(
        scalar(summary.get("curve_max_abs_curvature")),
        scalar(summary.get("curve_max_abs_moment")),
        scalar(summary.get("curve_loop_energy_proxy")),
        scalar(summary.get("curve_moment_span")),
    ))
    print("Mesh: summary={0}, manifest={1}".format(scalar(summary.get("mesh_status")), scalar(summary.get("manifest_status"))))
    print("Contact scaffold: {0}".format(scalar(summary.get("contact_pair_scaffold_status"))))
    print("Contact clearance: status={0}, checked={1}, gapped={2}, touching={3}, overclosed={4}, min_gap={5}, max_gap={6}, preload={7}, residual_mpa={8}".format(
        scalar(summary.get("contact_clearance_status")),
        scalar(summary.get("contact_clearance_checked_pairs")),
        scalar(summary.get("contact_clearance_gapped_pairs")),
        scalar(summary.get("contact_clearance_touching_pairs")),
        scalar(summary.get("contact_clearance_overclosed_pairs")),
        scalar(summary.get("contact_clearance_min_mm")),
        scalar(summary.get("contact_clearance_max_mm")),
        scalar(summary.get("contact_residual_preload_status")),
        scalar(summary.get("contact_residual_pressure_mpa")),
    ))
    print("Contact keyword: status={0}, target={1}, adjusted_pairs={2}, beam_surfaces={3}".format(
        scalar(summary.get("contact_pair_keyword_status")),
        scalar(summary.get("contact_pair_keyword_target_type")),
        scalar(summary.get("contact_pair_keyword_adjusted_count")),
        scalar(summary.get("contact_pair_keyword_beam_surface_count")),
    ))
    print("Endpoint sweep: validated={0}, shape={1}, children={2}, child_jobs={3}".format(
        scalar(summary.get("endpoint_sweep_validated")),
        scalar(summary.get("endpoint_sweep_shape_passed")),
        scalar(summary.get("endpoint_sweep_children_deep_validated")),
        scalar(summary.get("child_job_count")),
    ))
    print("Continuous CurveV0: shape={0}, rows={1}, zero_returns={2}, symmetry_error={3}".format(
        scalar(summary.get("continuous_curve_v0_shape_passed")),
        scalar(summary.get("continuous_curve_v0_rows")),
        scalar(summary.get("continuous_curve_v0_near_zero_count")),
        scalar(summary.get("continuous_curve_v0_symmetry_error")),
    ))
    print("Continuous CurveV0 scale: max|kappa|={0}, max|M|={1}".format(
        scalar(summary.get("continuous_curve_v0_max_abs_curvature")),
        scalar(summary.get("continuous_curve_v0_max_abs_moment")),
    ))
    print("CurveV0 comparison: exists={0}, status={1}, peak_ratio={2}, pos_delta={3}, neg_delta={4}".format(
        scalar(summary.get("curve_v0_comparison_report_exists")),
        scalar(summary.get("curve_v0_comparison_status")),
        scalar(summary.get("curve_v0_comparison_peak_ratio")),
        scalar(summary.get("curve_v0_comparison_positive_delta")),
        scalar(summary.get("curve_v0_comparison_negative_delta")),
    ))
    print("Warnings: actual={0}, blocking={1}, categories={2}".format(
        scalar(summary.get("actual_warning_hits")),
        scalar(summary.get("blocking_log_hits")),
        top_counts(summary.get("warning_categories")),
    ))
    print("Mesh quality: distorted_elements={0}, min_angle={1}, sets={2}".format(
        scalar(summary.get("distorted_reported_element_count")),
        scalar(summary.get("distorted_table_min_angle")),
        top_counts(summary.get("mesh_warning_sets")),
    ))
    print("B31 quality: total_sets={0}, sets={1}".format(
        scalar(summary.get("b31_total_warning_sets")),
        top_counts(summary.get("b31_warning_sets")),
    ))
    print("Beam orientation: status={0}, modes={1}".format(
        scalar(summary.get("beam_orientation_status")),
        top_counts(summary.get("beam_orientation_modes")),
    ))
    print("Issues: {0}".format(summary.get("issue_counts", {})))
    print()
    print("Next action:")
    print(scalar(summary.get("recommended_next_action")))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Print a concise SCLAS job-folder status summary.")
    parser.add_argument("job_dir", nargs="?", help="Job folder to inspect. Defaults to the latest job folder.")
    parser.add_argument("--latest", action="store_true", help="Inspect the newest job folder under --job-root.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check job folders in --latest selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of human text.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.job_dir and not args.latest:
            job_dir = Path(args.job_dir).expanduser().resolve()
        else:
            job_dir = latest_job_dir(Path(args.job_root).expanduser().resolve(), include_self_check=args.include_self_check)
        report = build_report(job_dir)
        summary = collect_summary(report)
        if args.json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            print_human(summary)
        return 0 if summary.get("health") != "BLOCKED" else 2
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS Job Summary failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
