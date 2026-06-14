#!/usr/bin/env python3
"""Research acceptance gate for HELIX/SCLAS Abaqus result folders."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir
from sclas_offline_diagnostics import build_report
from sclas_project_status import latest_curve_comparison


def numeric(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gate(name: str, status: str, detail: str, critical: bool = True) -> dict:
    return {
        "name": name,
        "status": status,
        "critical": critical,
        "detail": detail,
    }


def present_local_fields(summary: dict) -> set:
    fields = summary.get("odb_present_local_fields")
    if isinstance(fields, dict):
        return {str(key) for key, value in fields.items() if value}
    if isinstance(fields, list):
        return {str(item) for item in fields}
    return set()


def result_contract_gate(summary: dict) -> dict:
    health = summary.get("health")
    rows = summary.get("csv_rows")
    source = summary.get("source")
    if health == "BLOCKED":
        return gate("result_contract", "blocked", "latest job diagnostics are BLOCKED")
    if not rows:
        return gate("result_contract", "blocked", "latest job has no numeric result_data.csv rows")
    if source in (None, "", "FAST_GUI_APPROXIMATION"):
        return gate("result_contract", "review", "latest result is not Abaqus ODB-backed: source={0}".format(source))
    if health == "PASS":
        return gate("result_contract", "pass", "latest job is PASS with {0} result rows".format(rows))
    return gate("result_contract", "review", "latest job is diagnostic-usable but needs review: health={0}".format(health))


def curve_gate(summary: dict, comparison: dict) -> dict:
    curve_class = summary.get("curve_class")
    shape_passed = summary.get("continuous_curve_v0_shape_passed")
    comparison_status = comparison.get("status")
    if curve_class != "multi_point_curve_v0":
        return gate(
            "curve_v0_continuous_path",
            "blocked",
            "latest accepted candidate must be continuous multi-point CurveV0; got {0}".format(curve_class),
        )
    if shape_passed is False:
        return gate("curve_v0_continuous_path", "blocked", "continuous CurveV0 shape diagnostics failed")
    if comparison.get("error"):
        return gate("curve_v0_continuous_path", "review", "endpoint-vs-continuous comparison is missing: {0}".format(comparison.get("error")))
    if comparison_status == "aligned":
        return gate("curve_v0_continuous_path", "pass", "continuous CurveV0 aligns with endpoint sweep")
    if comparison_status == "review":
        return gate(
            "curve_v0_continuous_path",
            "review",
            "continuous CurveV0 exists but endpoint comparison needs review; peak_ratio={0}".format(
                comparison.get("peak_moment_ratio_continuous_over_endpoint")
            ),
        )
    if comparison_status == "blocked":
        return gate("curve_v0_continuous_path", "blocked", "CurveV0 comparison is blocked")
    return gate("curve_v0_continuous_path", "review", "CurveV0 comparison status is {0}".format(comparison_status))


def contact_gate(summary: dict) -> dict:
    cpress = numeric(summary.get("odb_contact_pressure_max"))
    slip = numeric(summary.get("odb_slip_abs_max"))
    preload = summary.get("contact_residual_preload_status")
    if cpress is None:
        return gate("contact_preload_closure", "blocked", "CPRESS was not extracted")
    if cpress <= 0.0:
        return gate(
            "contact_preload_closure",
            "blocked",
            "contact output exists but CPRESS max is zero; close/preload contact before claiming stick-slip physics",
        )
    if preload in ("not_applied", "not_requested", None, ""):
        return gate(
            "contact_preload_closure",
            "review",
            "CPRESS is nonzero but residual preload status is {0}; verify interference/shrink-fit preload".format(preload),
        )
    if slip is None:
        return gate("contact_preload_closure", "review", "CPRESS is nonzero but slip output was not extracted")
    if slip <= 0.0:
        return gate("contact_preload_closure", "review", "CPRESS is nonzero but slip max is zero")
    return gate("contact_preload_closure", "pass", "contact is closed: preload={0}, CPRESS max={1}, slip max={2}".format(preload, cpress, slip))


def odb_field_gate(summary: dict) -> dict:
    present = present_local_fields(summary)
    required = {"S", "CPRESS", "COPEN"}
    missing = sorted(required - present)
    slip_ok = bool({"CSLIP1", "CSLIP2"} & present)
    if missing:
        return gate("odb_local_fields", "blocked", "missing required ODB fields: {0}".format(", ".join(missing)))
    if not slip_ok:
        return gate("odb_local_fields", "review", "stress/contact fields exist, but CSLIP1/CSLIP2 slip output is missing")
    return gate("odb_local_fields", "pass", "required ODB fields are present: {0}".format(", ".join(sorted(present))))


def warning_gate(summary: dict) -> dict:
    b31_warnings = numeric(summary.get("b31_total_warning_sets")) or 0.0
    distorted = numeric(summary.get("distorted_reported_element_count")) or 0.0
    blocking = numeric(summary.get("blocking_log_hits")) or 0.0
    if blocking > 0:
        return gate("solver_warning_budget", "blocked", "blocking solver log hits detected: {0}".format(int(blocking)), critical=False)
    if b31_warnings or distorted:
        return gate(
            "solver_warning_budget",
            "review",
            "solver completed but warning budget needs review: B31 sets={0}, distorted elements={1}".format(int(b31_warnings), int(distorted)),
            critical=False,
        )
    return gate("solver_warning_budget", "pass", "no blocking warnings detected", critical=False)


def choose_overall(gates: list) -> str:
    critical = [item for item in gates if item.get("critical")]
    if any(item.get("status") == "blocked" for item in critical):
        return "blocked"
    if any(item.get("status") == "review" for item in critical):
        return "review"
    if any(item.get("status") == "review" for item in gates):
        return "review"
    return "accepted"


def recommended_next_action(overall: str, gates: list, summary: dict, comparison: dict) -> str:
    for item in gates:
        if not item.get("critical") or item.get("status") != "blocked":
            continue
        if item.get("name") == "contact_preload_closure":
            return "On the remote Abaqus PC, apply/validate contact preload or closure, then rerun SmallSmoke, endpoint sweep, and continuous CurveV0."
        if item.get("name") == "curve_v0_continuous_path":
            return "Generate a continuous multi-point CurveV0 ODB run and compare it with the endpoint sweep before calibration."
        if item.get("name") == "odb_local_fields":
            return "Add required ODB field outputs S, CPRESS, COPEN, and CSLIP*, then rerun the Abaqus extraction."
        return item.get("detail", "Fix the blocked acceptance gate.")
    for item in gates:
        if item.get("critical") and item.get("status") == "review":
            return item.get("detail", "Review the acceptance gate before using results as calibrated research data.")
    if comparison.get("recommended_next_action"):
        return comparison["recommended_next_action"]
    if summary.get("recommended_next_action"):
        return summary["recommended_next_action"]
    if overall == "accepted":
        return "Result is accepted by the local gate; next compare against literature/calibration targets and prepare reporting plots."
    return "Inspect acceptance-gate details and rerun the validation loop."


def latest_summary(job_root: Path, include_self_check: bool = False) -> dict:
    job_dir = latest_job_dir(job_root, include_self_check=include_self_check)
    return collect_summary(build_report(job_dir))


def build_gate(job_root: Path, include_self_check: bool = False) -> dict:
    summary = latest_summary(job_root, include_self_check=include_self_check)
    try:
        comparison = latest_curve_comparison(job_root, include_self_check=include_self_check)
    except Exception as exc:
        comparison = {"error": str(exc)}
    gates = [
        result_contract_gate(summary),
        curve_gate(summary, comparison),
        contact_gate(summary),
        odb_field_gate(summary),
        warning_gate(summary),
    ]
    overall = choose_overall(gates)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "latest_job": summary.get("job_dir"),
        "latest_health": summary.get("health"),
        "latest_source": summary.get("source"),
        "latest_curve_class": summary.get("curve_class"),
        "overall_status": overall,
        "gates": gates,
        "curve_v0_comparison_status": comparison.get("status"),
        "curve_v0_peak_ratio": comparison.get("peak_moment_ratio_continuous_over_endpoint"),
        "contact_pressure_max": summary.get("odb_contact_pressure_max"),
        "slip_abs_max": summary.get("odb_slip_abs_max"),
        "recommended_next_action": recommended_next_action(overall, gates, summary, comparison),
    }


def report_dir(report: dict) -> Path:
    latest = report.get("latest_job")
    return Path(latest) if latest else Path(report.get("job_root", "."))


def markdown_report(report: dict) -> str:
    lines = [
        "# HELIX / SCLAS Acceptance Gate",
        "",
        "- Overall status: `{0}`".format(report.get("overall_status", "-")),
        "- Latest job: `{0}`".format(report.get("latest_job", "-")),
        "- Latest health/source/class: `{0}` / `{1}` / `{2}`".format(report.get("latest_health", "-"), report.get("latest_source", "-"), report.get("latest_curve_class", "-")),
        "- CurveV0 comparison: `{0}`, peak ratio `{1}`".format(report.get("curve_v0_comparison_status", "-"), report.get("curve_v0_peak_ratio", "-")),
        "- Contact: CPRESS max `{0}`, slip max `{1}`".format(report.get("contact_pressure_max", "-"), report.get("slip_abs_max", "-")),
        "",
        "## Gates",
        "",
        "| Gate | Status | Critical | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for item in report.get("gates", []):
        lines.append("| {0} | {1} | {2} | {3} |".format(item.get("name", "-"), item.get("status", "-"), item.get("critical", "-"), str(item.get("detail", "-")).replace("|", "\\|")))
    lines.extend(["", "## Next Action", "", report.get("recommended_next_action", "-"), ""])
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "## Saved Reports",
            "",
            "- JSON: `{0}`".format(report.get("saved_report", "-")),
            "- Markdown: `{0}`".format(report.get("saved_markdown_report", "-")),
            "",
        ])
    return "\n".join(lines)


def human_report(report: dict) -> str:
    lines = [
        "HELIX / SCLAS Acceptance Gate",
        "=============================",
        "Overall status: {0}".format(report.get("overall_status", "-")),
        "Latest job: {0}".format(report.get("latest_job", "-")),
        "Latest health/source/class: {0} / {1} / {2}".format(report.get("latest_health", "-"), report.get("latest_source", "-"), report.get("latest_curve_class", "-")),
        "CurveV0 comparison: status={0}, peak_ratio={1}".format(report.get("curve_v0_comparison_status", "-"), report.get("curve_v0_peak_ratio", "-")),
        "Contact: CPRESS max={0}, slip max={1}".format(report.get("contact_pressure_max", "-"), report.get("slip_abs_max", "-")),
        "",
        "Gates:",
    ]
    for item in report.get("gates", []):
        marker = "critical" if item.get("critical") else "advisory"
        lines.append("- {0}: {1} [{2}] - {3}".format(item.get("name", "-"), item.get("status", "-"), marker, item.get("detail", "-")))
    lines.extend(["", "Next action:", report.get("recommended_next_action", "-")])
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend(["", "Saved reports:", "- JSON: {0}".format(report.get("saved_report", "-")), "- Markdown: {0}".format(report.get("saved_markdown_report", "-"))])
    return "\n".join(lines)


def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "acceptance_gate_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "acceptance_gate_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate whether the latest HELIX/SCLAS Abaqus result is research-ready.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check jobs in latest selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save acceptance_gate_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save acceptance_gate_report.md.")
    parser.add_argument("--output", help="Custom JSON output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown output path.")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless the overall status is accepted.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = build_gate(Path(args.job_root).expanduser().resolve(), include_self_check=args.include_self_check)
        if args.save_report or args.output:
            path = save_report(report, Path(args.output).expanduser().resolve() if args.output else None)
            report["saved_report"] = str(path)
        if args.save_markdown or args.markdown_output:
            path = save_markdown_report(report, Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None)
            report["saved_markdown_report"] = str(path)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(human_report(report))
        if args.strict and report.get("overall_status") != "accepted":
            return 2
        return 0
    except Exception as exc:
        print("[ERROR] {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
