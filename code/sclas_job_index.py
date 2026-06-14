#!/usr/bin/env python3
"""Inventory SCLAS/HELIX job folders for handoff and triage."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_job_filters import candidate_job_dirs, describe_filter, is_self_check_job
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary
from sclas_offline_diagnostics import build_report


REPORT_NAMES = [
    "result_summary.json",
    "result_data.csv",
    "project_status_report.json",
    "offline_diagnostics_report.json",
    "curve_v0_comparison_report.json",
]


def scalar(value, default="-"):
    return default if value in (None, "") else value


def job_mtime(job_dir: Path) -> float:
    mtimes = []
    for name in REPORT_NAMES:
        path = job_dir / name
        if path.exists():
            mtimes.append(path.stat().st_mtime)
    return max(mtimes) if mtimes else job_dir.stat().st_mtime


def summarize_one(job_dir: Path) -> dict:
    try:
        summary = collect_summary(build_report(job_dir))
        error = None
    except Exception as exc:
        summary = {}
        error = str(exc)
    mtime = job_mtime(job_dir)
    return {
        "name": job_dir.name,
        "path": str(job_dir),
        "modified_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "is_self_check": is_self_check_job(job_dir),
        "health": summary.get("health", "ERROR" if error else "UNKNOWN"),
        "source": summary.get("source"),
        "curve_class": summary.get("curve_class"),
        "csv_rows": summary.get("csv_rows"),
        "mesh_status": summary.get("mesh_status"),
        "odb_status": summary.get("odb_status"),
        "contact_preload_status": summary.get("contact_residual_preload_status"),
        "contact_pressure_max": summary.get("odb_contact_pressure_max"),
        "slip_abs_max": summary.get("odb_slip_abs_max"),
        "curve_v0_comparison_status": summary.get("curve_v0_comparison_status"),
        "recommended_next_action": summary.get("recommended_next_action"),
        "error": error,
    }


def count_by(items, key):
    counts = {}
    for item in items:
        value = item.get(key)
        label = str(value if value not in (None, "") else "-")
        counts[label] = counts.get(label, 0) + 1
    return counts


def build_index(job_root: Path, limit: int = 15, include_self_check: bool = False) -> dict:
    if not job_root.exists():
        raise FileNotFoundError("Job root does not exist: {0}".format(job_root))
    candidates = candidate_job_dirs(job_root, include_self_check=include_self_check)
    candidates = sorted(candidates, key=job_mtime, reverse=True)
    selected = candidates[:max(limit, 0)]
    jobs = [summarize_one(job_dir) for job_dir in selected]
    return {
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "filter": describe_filter(include_self_check),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_candidates": len(candidates),
        "reported_count": len(jobs),
        "health_counts": count_by(jobs, "health"),
        "source_counts": count_by(jobs, "source"),
        "curve_class_counts": count_by(jobs, "curve_class"),
        "jobs": jobs,
    }


def human_report(index: dict) -> str:
    lines = [
        "SCLAS Job Index",
        "===============",
        "Job root: {0}".format(index.get("job_root", "-")),
        "Filter: {0}".format(index.get("filter", "-")),
        "Total candidates: {0}".format(index.get("total_candidates", 0)),
        "Reported: {0}".format(index.get("reported_count", 0)),
        "Health counts: {0}".format(index.get("health_counts", {})),
        "Source counts: {0}".format(index.get("source_counts", {})),
        "",
        "Recent jobs:",
    ]
    for item in index.get("jobs", []):
        lines.append(
            "- {modified_at} | {name} | health={health} | source={source} | curve={curve} | CPRESS={cpress} | slip={slip}".format(
                modified_at=scalar(item.get("modified_at")),
                name=scalar(item.get("name")),
                health=scalar(item.get("health")),
                source=scalar(item.get("source")),
                curve=scalar(item.get("curve_class")),
                cpress=scalar(item.get("contact_pressure_max")),
                slip=scalar(item.get("slip_abs_max")),
            )
        )
        if item.get("recommended_next_action"):
            lines.append("  next: {0}".format(item.get("recommended_next_action")))
        if item.get("error"):
            lines.append("  error: {0}".format(item.get("error")))
    return "\n".join(lines)


def markdown_report(index: dict) -> str:
    lines = [
        "# SCLAS Job Index",
        "",
        "- Job root: `{0}`".format(index.get("job_root", "-")),
        "- Filter: `{0}`".format(index.get("filter", "-")),
        "- Generated at: `{0}`".format(index.get("generated_at", "-")),
        "- Total candidates: `{0}`".format(index.get("total_candidates", 0)),
        "- Reported: `{0}`".format(index.get("reported_count", 0)),
        "",
        "## Counts",
        "",
        "- Health: `{0}`".format(index.get("health_counts", {})),
        "- Source: `{0}`".format(index.get("source_counts", {})),
        "- Curve class: `{0}`".format(index.get("curve_class_counts", {})),
        "",
        "## Recent Jobs",
        "",
        "| Modified | Job | Health | Source | Curve | CPRESS max | Slip max |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in index.get("jobs", []):
        lines.append("| {0} | `{1}` | {2} | {3} | {4} | {5} | {6} |".format(
            scalar(item.get("modified_at")),
            scalar(item.get("name")),
            scalar(item.get("health")),
            scalar(item.get("source")),
            scalar(item.get("curve_class")),
            scalar(item.get("contact_pressure_max")),
            scalar(item.get("slip_abs_max")),
        ))
    lines.extend(["", "## Next Actions", ""])
    for item in index.get("jobs", []):
        action = item.get("recommended_next_action")
        if action:
            lines.append("- `{0}`: {1}".format(item.get("name", "-"), action))
    lines.append("")
    return "\n".join(lines)


def default_report_path(job_root: Path, suffix: str) -> Path:
    return job_root / ("sclas_job_index." + suffix)


def save_report(index: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path(Path(index["job_root"]), "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(index)
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(index: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path(Path(index["job_root"]), "md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(index)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="List recent SCLAS job folders for handoff triage.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of recent jobs to report.")
    parser.add_argument("--include-self-check", action="store_true", help="Include synthetic self_check job folders.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save sclas_job_index.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save sclas_job_index.md.")
    parser.add_argument("--output", help="Custom JSON report output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown report output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        job_root = Path(args.job_root).expanduser().resolve()
        index = build_index(job_root, limit=args.limit, include_self_check=args.include_self_check)
        if args.save_report or args.output:
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            index["saved_report"] = str(save_report(index, output_path))
        if args.save_markdown or args.markdown_output:
            markdown_path = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None
            index["saved_markdown_report"] = str(save_markdown_report(index, markdown_path))
        if args.json:
            print(json.dumps(index, indent=2, ensure_ascii=False))
        else:
            print(human_report(index))
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS Job Index failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
