#!/usr/bin/env python3
"""Concise HELIX/SCLAS project status dashboard.

This command summarizes the latest local job artifacts without requiring
Abaqus. It is meant for Mac/home Codex sessions and quick handoffs.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_curve_compare import compare, latest_job
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir
from sclas_offline_diagnostics import build_report


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        return {"error": str(exc)} if default is None else default


def latest_summary(job_root: Path, include_self_check: bool = False) -> dict:
    job_dir = latest_job_dir(job_root, include_self_check=include_self_check)
    return collect_summary(build_report(job_dir))


def latest_curve_comparison(job_root: Path, include_self_check: bool = False) -> dict:
    endpoint = latest_job(job_root, "endpoint", include_self_check=include_self_check)
    continuous = latest_job(job_root, "continuous", include_self_check=include_self_check)
    return compare(endpoint, continuous)


def completion_flags(summary: dict, comparison: dict) -> list:
    flags = []
    flags.append({
        "area": "GUI/result contract",
        "status": "ready",
        "detail": "self-check covers GUI/backend file sync and result contracts",
    })
    flags.append({
        "area": "Latest job health",
        "status": str(summary.get("health", "unknown")).lower(),
        "detail": "{0} / {1}".format(summary.get("source", "-"), summary.get("curve_class", "-")),
    })
    if comparison.get("error"):
        flags.append({
            "area": "CurveV0 comparison",
            "status": "missing",
            "detail": comparison.get("error"),
        })
    else:
        flags.append({
            "area": "CurveV0 comparison",
            "status": comparison.get("status", "unknown"),
            "detail": "peak_ratio={0}".format(comparison.get("peak_moment_ratio_continuous_over_endpoint", "-")),
        })

    contact_pressure = summary.get("odb_contact_pressure_max")
    slip = summary.get("odb_slip_abs_max")
    preload = summary.get("contact_residual_preload_status")
    contact_status = "ready" if contact_pressure and float(contact_pressure) > 0.0 else "blocked"
    flags.append({
        "area": "Contact preload/closure",
        "status": contact_status,
        "detail": "preload={0}, CPRESS max={1}, slip max={2}".format(preload, contact_pressure, slip),
    })

    fields = summary.get("odb_present_local_fields", {})
    field_status = "ready" if fields else "pending"
    flags.append({
        "area": "ODB local fields",
        "status": field_status,
        "detail": ", ".join(sorted(fields.keys())) if isinstance(fields, dict) and fields else "-",
    })
    return flags


def choose_next_action(summary: dict, comparison: dict, flags: list) -> str:
    for flag in flags:
        if flag.get("area") == "Contact preload/closure" and flag.get("status") == "blocked":
            return "Implement or validate contact preload/closure on the remote Abaqus PC, then rerun SmallSmoke, endpoint sweep, and continuous CurveV0."
    if comparison.get("recommended_next_action"):
        return comparison.get("recommended_next_action")
    if summary.get("recommended_next_action"):
        return summary.get("recommended_next_action")
    return "Run the stable validation loop and inspect the latest job summary."


def build_status(job_root: Path, include_self_check: bool = False) -> dict:
    summary = safe_call(lambda: latest_summary(job_root, include_self_check=include_self_check), default={"health": "unknown"})
    comparison = safe_call(lambda: latest_curve_comparison(job_root, include_self_check=include_self_check))
    flags = completion_flags(summary, comparison)
    return {
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "latest_job": summary.get("job_dir"),
        "latest_job_health": summary.get("health"),
        "latest_source": summary.get("source"),
        "latest_curve_class": summary.get("curve_class"),
        "curve_v0_comparison_status": comparison.get("status"),
        "curve_v0_peak_ratio": comparison.get("peak_moment_ratio_continuous_over_endpoint"),
        "contact_preload_status": summary.get("contact_residual_preload_status"),
        "contact_pressure_max": summary.get("odb_contact_pressure_max"),
        "slip_abs_max": summary.get("odb_slip_abs_max"),
        "completion_flags": flags,
        "recommended_next_action": choose_next_action(summary, comparison, flags),
    }


def default_report_dir(status: dict) -> Path:
    latest = status.get("latest_job")
    if latest:
        return Path(latest)
    return Path(status.get("job_root", "."))


def default_report_path(status: dict, suffix: str) -> Path:
    return default_report_dir(status) / ("project_status_report." + suffix)


def save_report(status: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path(status, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved_status = dict(status)
    saved_status["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved_status["saved_report"] = str(path)
    path.write_text(json.dumps(saved_status, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(status: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path(status, "md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved_status = dict(status)
    saved_status["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved_status), encoding="utf-8")
    return path


def human_report(status: dict) -> str:
    lines = [
        "HELIX / SCLAS Project Status",
        "============================",
        "Job root: {0}".format(status.get("job_root", "-")),
        "Latest job: {0}".format(status.get("latest_job", "-")),
        "Latest health: {0}".format(status.get("latest_job_health", "-")),
        "Latest source/class: {0} / {1}".format(status.get("latest_source", "-"), status.get("latest_curve_class", "-")),
        "CurveV0 comparison: status={0}, peak_ratio={1}".format(
            status.get("curve_v0_comparison_status", "-"),
            status.get("curve_v0_peak_ratio", "-"),
        ),
        "Contact: preload={0}, CPRESS max={1}, slip max={2}".format(
            status.get("contact_preload_status", "-"),
            status.get("contact_pressure_max", "-"),
            status.get("slip_abs_max", "-"),
        ),
        "",
        "Completion flags:",
    ]
    for flag in status.get("completion_flags", []):
        lines.append("- {0}: {1} ({2})".format(flag.get("area", "-"), flag.get("status", "-"), flag.get("detail", "-")))
    lines.extend([
        "",
        "Next action:",
        status.get("recommended_next_action", "-"),
    ])
    if status.get("saved_report") or status.get("saved_markdown_report"):
        lines.extend([
            "",
            "Saved reports:",
            "- JSON: {0}".format(status.get("saved_report", "-")),
            "- Markdown: {0}".format(status.get("saved_markdown_report", "-")),
        ])
    return "\n".join(lines)


def markdown_report(status: dict) -> str:
    lines = [
        "# HELIX / SCLAS Project Status",
        "",
        "- Job root: `{0}`".format(status.get("job_root", "-")),
        "- Latest job: `{0}`".format(status.get("latest_job", "-")),
        "- Latest health: `{0}`".format(status.get("latest_job_health", "-")),
        "- Latest source/class: `{0}` / `{1}`".format(
            status.get("latest_source", "-"),
            status.get("latest_curve_class", "-"),
        ),
        "- CurveV0 comparison: `{0}`, peak ratio `{1}`".format(
            status.get("curve_v0_comparison_status", "-"),
            status.get("curve_v0_peak_ratio", "-"),
        ),
        "- Contact: preload `{0}`, CPRESS max `{1}`, slip max `{2}`".format(
            status.get("contact_preload_status", "-"),
            status.get("contact_pressure_max", "-"),
            status.get("slip_abs_max", "-"),
        ),
        "",
        "## Completion Flags",
        "",
        "| Area | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for flag in status.get("completion_flags", []):
        lines.append("| {0} | {1} | {2} |".format(
            flag.get("area", "-"),
            flag.get("status", "-"),
            str(flag.get("detail", "-")).replace("|", "\\|"),
        ))
    lines.extend([
        "",
        "## Next Action",
        "",
        status.get("recommended_next_action", "-"),
        "",
    ])
    if status.get("saved_report") or status.get("saved_markdown_report"):
        lines.extend([
            "## Saved Reports",
            "",
            "- JSON: `{0}`".format(status.get("saved_report", "-")),
            "- Markdown: `{0}`".format(status.get("saved_markdown_report", "-")),
            "",
        ])
    return "\n".join(lines)


def print_human(status: dict) -> None:
    print(human_report(status))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Print the current HELIX/SCLAS project status.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check job folders in latest status selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save project_status_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save project_status_report.md.")
    parser.add_argument("--output", help="Custom JSON report output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown report output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        status = build_status(Path(args.job_root).expanduser().resolve(), include_self_check=args.include_self_check)
        if args.save_report or args.output:
            saved_path = save_report(status, Path(args.output).expanduser().resolve() if args.output else None)
            status["saved_report"] = str(saved_path)
        if args.save_markdown or args.markdown_output:
            saved_markdown_path = save_markdown_report(
                status,
                Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None,
            )
            status["saved_markdown_report"] = str(saved_markdown_path)
        if args.json:
            print(json.dumps(status, indent=2, ensure_ascii=False))
        else:
            print_human(status)
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS project status failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
