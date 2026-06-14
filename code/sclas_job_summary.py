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


def latest_job_dir(job_root: Path) -> Path:
    if not job_root.exists():
        raise FileNotFoundError("Job root does not exist: {0}".format(job_root))

    candidates = []
    for path in job_root.iterdir():
        if not path.is_dir():
            continue
        if (path / "result_data.csv").exists() or (path / "result_summary.json").exists():
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError("No SCLAS job folders were found under: {0}".format(job_root))
    return max(candidates, key=lambda path: path.stat().st_mtime)


def quality_details(report: dict):
    logs = report.get("solver_logs", {})
    children = report.get("endpoint_sweep_children", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})
    mesh_quality = {}
    b31_quality = {}

    if isinstance(children, dict) and children:
        mesh_quality = children.get("mesh_quality_warning_details", {}) or {}
        b31_quality = children.get("b31_beam_warning_details", {}) or {}
    if not mesh_quality and isinstance(logs, dict):
        mesh_quality = logs.get("mesh_quality_warning_details", {}) or {}
    if not b31_quality and isinstance(logs, dict):
        b31_quality = logs.get("b31_beam_warning_details", {}) or {}

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
    }


def health_label(report: dict, details: dict) -> str:
    counts = report.get("diagnostic_summary", {}).get("issue_counts", {})
    if int_scalar(counts.get("error")):
        return "BLOCKED"
    if details.get("blocking_log_hits"):
        return "BLOCKED"
    if int_scalar(counts.get("warning")) or details.get("actual_warning_hits") or details.get("b31_total_warning_sets"):
        return "REVIEW"
    return "PASS"


def collect_summary(report: dict) -> dict:
    result_csv = report.get("result_data_csv", {})
    result_summary = report.get("result_summary_json", {})
    sweep_shape = report.get("endpoint_sweep_shape", {})
    sweep_children = report.get("endpoint_sweep_children", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})
    logs = report.get("solver_logs", {})
    diagnostic = report.get("diagnostic_summary", {})
    issue_counts = diagnostic.get("issue_counts", {})
    details = quality_details(report)

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
        "issue_counts": issue_counts,
        "recommended_next_action": diagnostic.get("recommended_next_action"),
    }
    summary.update(details)
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
    print("Mesh: summary={0}, manifest={1}".format(scalar(summary.get("mesh_status")), scalar(summary.get("manifest_status"))))
    print("Contact scaffold: {0}".format(scalar(summary.get("contact_pair_scaffold_status"))))
    print("Endpoint sweep: validated={0}, shape={1}, children={2}, child_jobs={3}".format(
        scalar(summary.get("endpoint_sweep_validated")),
        scalar(summary.get("endpoint_sweep_shape_passed")),
        scalar(summary.get("endpoint_sweep_children_deep_validated")),
        scalar(summary.get("child_job_count")),
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
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of human text.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.job_dir and not args.latest:
            job_dir = Path(args.job_dir).expanduser().resolve()
        else:
            job_dir = latest_job_dir(Path(args.job_root).expanduser().resolve())
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
