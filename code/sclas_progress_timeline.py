#!/usr/bin/env python3
"""Build a chronological HELIX/SCLAS job progress timeline."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_acceptance_gate import (
    choose_overall,
    contact_gate,
    curve_gate,
    odb_field_gate,
    result_contract_gate,
    warning_gate,
)
from sclas_job_filters import candidate_job_dirs, describe_filter
from sclas_job_index import job_mtime, readiness
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, load_curve_v0_comparison
from sclas_offline_diagnostics import build_report


PROJECT_DIR = Path(__file__).resolve().parent.parent


def scalar(value, default="-"):
    return default if value in (None, "") else value


def numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gate_map(summary: dict, comparison: dict) -> dict:
    gates = [
        result_contract_gate(summary),
        curve_gate(summary, comparison),
        contact_gate(summary),
        odb_field_gate(summary),
        warning_gate(summary),
    ]
    return {
        "overall": choose_overall(gates),
        "gates": gates,
        "statuses": {item.get("name"): item.get("status") for item in gates},
        "blocked": [
            item.get("name")
            for item in gates
            if item.get("critical") and item.get("status") == "blocked"
        ],
        "review": [
            item.get("name")
            for item in gates
            if item.get("critical") and item.get("status") == "review"
        ],
    }


def summarize_job(job_dir: Path) -> dict:
    error = None
    try:
        summary = collect_summary(build_report(job_dir))
    except Exception as exc:
        summary = {}
        error = str(exc)
    comparison = load_curve_v0_comparison(job_dir)
    if not comparison.get("exists") and not comparison.get("status"):
        comparison = {"status": None, "error": "curve_v0_comparison_report.json is missing"}
    gates = gate_map(summary, comparison)
    ready = readiness(summary, error=error)
    cpress = numeric(summary.get("odb_contact_pressure_max"))
    slip = numeric(summary.get("odb_slip_abs_max"))
    return {
        "name": job_dir.name,
        "path": str(job_dir),
        "modified_at": datetime.fromtimestamp(job_mtime(job_dir)).isoformat(timespec="seconds"),
        "health": summary.get("health", "ERROR" if error else "UNKNOWN"),
        "source": summary.get("source"),
        "curve_class": summary.get("curve_class"),
        "csv_rows": summary.get("csv_rows"),
        "readiness_score": ready.get("readiness_score"),
        "readiness_label": ready.get("readiness_label"),
        "acceptance_status": gates["overall"],
        "blocked_gates": gates["blocked"],
        "review_gates": gates["review"],
        "gate_statuses": gates["statuses"],
        "curve_v0_comparison_status": comparison.get("status"),
        "curve_v0_peak_ratio": comparison.get("peak_moment_ratio_continuous_over_endpoint"),
        "contact_preload_status": summary.get("contact_residual_preload_status"),
        "contact_pressure_max": cpress,
        "slip_abs_max": slip,
        "odb_status": summary.get("odb_status"),
        "missing_local_fields": summary.get("odb_missing_local_fields"),
        "recommended_next_action": summary.get("recommended_next_action"),
        "error": error,
    }


def count_by(rows, key):
    counts = {}
    for row in rows:
        value = row.get(key)
        label = str(value if value not in (None, "") else "-")
        counts[label] = counts.get(label, 0) + 1
    return counts


def first_matching(rows, predicate):
    for row in rows:
        if predicate(row):
            return {
                "name": row.get("name"),
                "modified_at": row.get("modified_at"),
                "path": row.get("path"),
            }
    return None


def latest_delta(rows):
    if len(rows) < 2:
        return {}
    previous = rows[-2]
    latest = rows[-1]
    delta = {
        "previous_job": previous.get("name"),
        "latest_job": latest.get("name"),
        "readiness_score_delta": None,
        "contact_pressure_delta": None,
        "slip_delta": None,
        "acceptance_changed": previous.get("acceptance_status") != latest.get("acceptance_status"),
    }
    for key, out_key in [
        ("readiness_score", "readiness_score_delta"),
        ("contact_pressure_max", "contact_pressure_delta"),
        ("slip_abs_max", "slip_delta"),
    ]:
        left = numeric(previous.get(key))
        right = numeric(latest.get(key))
        if left is not None and right is not None:
            delta[out_key] = right - left
    return delta


def progress_markers(rows):
    return {
        "first_abaqus_backed": first_matching(
            rows,
            lambda row: row.get("source") not in (None, "", "FAST_GUI_APPROXIMATION"),
        ),
        "first_continuous_curve_v0": first_matching(
            rows,
            lambda row: row.get("curve_class") == "multi_point_curve_v0",
        ),
        "first_nonzero_contact_pressure": first_matching(
            rows,
            lambda row: (row.get("contact_pressure_max") or 0.0) > 0.0,
        ),
        "first_research_accepted": first_matching(
            rows,
            lambda row: row.get("acceptance_status") == "accepted",
        ),
    }


def build_timeline(job_root: Path, limit: int = 20, include_self_check: bool = False) -> dict:
    if not job_root.exists():
        raise FileNotFoundError("Job root does not exist: {0}".format(job_root))
    candidates = candidate_job_dirs(job_root, include_self_check=include_self_check)
    selected_newest = sorted(candidates, key=job_mtime, reverse=True)[:max(limit, 0)]
    rows = [summarize_job(job_dir) for job_dir in sorted(selected_newest, key=job_mtime)]
    latest = rows[-1] if rows else {}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(PROJECT_DIR),
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "filter": describe_filter(include_self_check),
        "total_candidates": len(candidates),
        "reported_count": len(rows),
        "latest_job": latest.get("path"),
        "latest_acceptance_status": latest.get("acceptance_status"),
        "acceptance_counts": count_by(rows, "acceptance_status"),
        "health_counts": count_by(rows, "health"),
        "source_counts": count_by(rows, "source"),
        "curve_class_counts": count_by(rows, "curve_class"),
        "progress_markers": progress_markers(rows),
        "latest_delta": latest_delta(rows),
        "timeline": rows,
    }


def default_report_path(suffix: str) -> Path:
    return PROJECT_DIR / ("progress_timeline." + suffix)


def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def markdown_escape(value) -> str:
    return str(scalar(value)).replace("|", "\\|")


def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def marker_line(label: str, marker: dict) -> str:
    if not marker:
        return "- {0}: `-`".format(label)
    return "- {0}: `{1}` at `{2}`".format(
        label,
        marker.get("name", "-"),
        marker.get("modified_at", "-"),
    )


def markdown_report(report: dict) -> str:
    markers = report.get("progress_markers", {})
    delta = report.get("latest_delta", {})
    lines = [
        "# HELIX / SCLAS Progress Timeline",
        "",
        "- Generated: `{0}`".format(report.get("generated_at", "-")),
        "- Job root: `{0}`".format(report.get("job_root", "-")),
        "- Filter: `{0}`".format(report.get("filter", "-")),
        "- Reported: `{0}` / `{1}`".format(report.get("reported_count", 0), report.get("total_candidates", 0)),
        "- Latest acceptance: `{0}`".format(report.get("latest_acceptance_status", "-")),
        "- Acceptance counts: `{0}`".format(report.get("acceptance_counts", {})),
        "- Health counts: `{0}`".format(report.get("health_counts", {})),
        "",
        "## Progress Markers",
        "",
        marker_line("First Abaqus-backed result", markers.get("first_abaqus_backed")),
        marker_line("First continuous CurveV0", markers.get("first_continuous_curve_v0")),
        marker_line("First nonzero CPRESS", markers.get("first_nonzero_contact_pressure")),
        marker_line("First accepted research result", markers.get("first_research_accepted")),
        "",
        "## Latest Delta",
        "",
        "- Previous/latest: `{0}` -> `{1}`".format(delta.get("previous_job", "-"), delta.get("latest_job", "-")),
        "- Readiness score delta: `{0}`".format(delta.get("readiness_score_delta", "-")),
        "- CPRESS delta: `{0}`".format(delta.get("contact_pressure_delta", "-")),
        "- Slip delta: `{0}`".format(delta.get("slip_delta", "-")),
        "- Acceptance changed: `{0}`".format(delta.get("acceptance_changed", "-")),
        "",
        "## Timeline",
        "",
        "| Modified | Job | Accept | Score | Health | Source | Curve | CurveV0 | CPRESS | Slip | Blocked gates |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.get("timeline", []):
        lines.append("| {0} | `{1}` | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} | {10} |".format(
            markdown_escape(row.get("modified_at")),
            markdown_escape(row.get("name")),
            markdown_escape(row.get("acceptance_status")),
            markdown_escape(row.get("readiness_score")),
            markdown_escape(row.get("health")),
            markdown_escape(row.get("source")),
            markdown_escape(row.get("curve_class")),
            markdown_escape(row.get("curve_v0_comparison_status")),
            markdown_escape(row.get("contact_pressure_max")),
            markdown_escape(row.get("slip_abs_max")),
            markdown_escape(", ".join(row.get("blocked_gates", [])) or "-"),
        ))
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "",
            "## Saved Reports",
            "",
            "- JSON: `{0}`".format(report.get("saved_report", "-")),
            "- Markdown: `{0}`".format(report.get("saved_markdown_report", "-")),
            "",
        ])
    return "\n".join(lines)


def human_report(report: dict) -> str:
    markers = report.get("progress_markers", {})
    delta = report.get("latest_delta", {})
    lines = [
        "HELIX / SCLAS Progress Timeline",
        "===============================",
        "Job root: {0}".format(report.get("job_root", "-")),
        "Filter: {0}".format(report.get("filter", "-")),
        "Reported: {0}/{1}".format(report.get("reported_count", 0), report.get("total_candidates", 0)),
        "Latest acceptance: {0}".format(report.get("latest_acceptance_status", "-")),
        "Acceptance counts: {0}".format(report.get("acceptance_counts", {})),
        "Health counts: {0}".format(report.get("health_counts", {})),
        "",
        "Progress markers:",
        marker_line("First Abaqus-backed result", markers.get("first_abaqus_backed")),
        marker_line("First continuous CurveV0", markers.get("first_continuous_curve_v0")),
        marker_line("First nonzero CPRESS", markers.get("first_nonzero_contact_pressure")),
        marker_line("First accepted research result", markers.get("first_research_accepted")),
        "",
        "Latest delta: {0} -> {1}, score={2}, CPRESS={3}, slip={4}, acceptance_changed={5}".format(
            delta.get("previous_job", "-"),
            delta.get("latest_job", "-"),
            delta.get("readiness_score_delta", "-"),
            delta.get("contact_pressure_delta", "-"),
            delta.get("slip_delta", "-"),
            delta.get("acceptance_changed", "-"),
        ),
        "",
        "Timeline:",
    ]
    for row in report.get("timeline", []):
        lines.append(
            "- {modified_at} | {name} | accept={accept} | score={score} | health={health} | source={source} | curve={curve} | CPRESS={cpress} | blocked={blocked}".format(
                modified_at=scalar(row.get("modified_at")),
                name=scalar(row.get("name")),
                accept=scalar(row.get("acceptance_status")),
                score=scalar(row.get("readiness_score")),
                health=scalar(row.get("health")),
                source=scalar(row.get("source")),
                curve=scalar(row.get("curve_class")),
                cpress=scalar(row.get("contact_pressure_max")),
                blocked=", ".join(row.get("blocked_gates", [])) or "-",
            )
        )
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "",
            "Saved reports:",
            "- JSON: {0}".format(report.get("saved_report", "-")),
            "- Markdown: {0}".format(report.get("saved_markdown_report", "-")),
        ])
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build a chronological HELIX/SCLAS job progress timeline.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of newest jobs to include.")
    parser.add_argument("--include-self-check", action="store_true", help="Include synthetic self_check job folders.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save progress_timeline.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save progress_timeline.md.")
    parser.add_argument("--output", help="Custom JSON report output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown report output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = build_timeline(
            Path(args.job_root).expanduser().resolve(),
            limit=args.limit,
            include_self_check=args.include_self_check,
        )
        if args.save_report or args.output:
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            report["saved_report"] = str(save_report(report, output_path))
        if args.save_markdown or args.markdown_output:
            markdown_path = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None
            report["saved_markdown_report"] = str(save_markdown_report(report, markdown_path))
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(human_report(report))
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS progress timeline failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
