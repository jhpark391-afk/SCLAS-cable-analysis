#!/usr/bin/env python3
"""Concise HELIX/SCLAS project status dashboard.

This command summarizes the latest local job artifacts without requiring
Abaqus. It is meant for Mac/home Codex sessions and quick handoffs.
"""

import argparse
import json
import sys
from pathlib import Path

from sclas_curve_compare import compare, latest_job
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir
from sclas_offline_diagnostics import build_report


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        return {"error": str(exc)} if default is None else default


def latest_summary(job_root: Path) -> dict:
    job_dir = latest_job_dir(job_root)
    return collect_summary(build_report(job_dir))


def latest_curve_comparison(job_root: Path) -> dict:
    endpoint = latest_job(job_root, "endpoint")
    continuous = latest_job(job_root, "continuous")
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


def build_status(job_root: Path) -> dict:
    summary = safe_call(lambda: latest_summary(job_root), default={"health": "unknown"})
    comparison = safe_call(lambda: latest_curve_comparison(job_root), default={})
    flags = completion_flags(summary, comparison)
    return {
        "job_root": str(job_root),
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


def print_human(status: dict) -> None:
    print("HELIX / SCLAS Project Status")
    print("============================")
    print("Job root: {0}".format(status.get("job_root", "-")))
    print("Latest job: {0}".format(status.get("latest_job", "-")))
    print("Latest health: {0}".format(status.get("latest_job_health", "-")))
    print("Latest source/class: {0} / {1}".format(status.get("latest_source", "-"), status.get("latest_curve_class", "-")))
    print("CurveV0 comparison: status={0}, peak_ratio={1}".format(
        status.get("curve_v0_comparison_status", "-"),
        status.get("curve_v0_peak_ratio", "-"),
    ))
    print("Contact: preload={0}, CPRESS max={1}, slip max={2}".format(
        status.get("contact_preload_status", "-"),
        status.get("contact_pressure_max", "-"),
        status.get("slip_abs_max", "-"),
    ))
    print()
    print("Completion flags:")
    for flag in status.get("completion_flags", []):
        print("- {0}: {1} ({2})".format(flag.get("area", "-"), flag.get("status", "-"), flag.get("detail", "-")))
    print()
    print("Next action:")
    print(status.get("recommended_next_action", "-"))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Print the current HELIX/SCLAS project status.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        status = build_status(Path(args.job_root).expanduser().resolve())
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
