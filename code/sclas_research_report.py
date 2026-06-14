#!/usr/bin/env python3
"""Research interpretation report for HELIX/SCLAS result folders."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_acceptance_gate import contact_gate, curve_gate, odb_field_gate, result_contract_gate, warning_gate
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir, load_curve_v0_comparison
from sclas_offline_diagnostics import build_report
from sclas_result_intake import build_intake


def resolve_job(job_root: Path, job_dir: Optional[Path], include_self_check: bool) -> Path:
    if job_dir:
        return job_dir.expanduser().resolve()
    return latest_job_dir(job_root, include_self_check=include_self_check)


def acceptance_preview(summary: dict, comparison: dict) -> list:
    return [
        result_contract_gate(summary),
        curve_gate(summary, comparison),
        contact_gate(summary),
        odb_field_gate(summary),
        warning_gate(summary),
    ]


def choose_status(gates: list) -> str:
    critical = [gate for gate in gates if gate.get("critical")]
    if any(gate.get("status") == "blocked" for gate in critical):
        return "blocked"
    if any(gate.get("status") == "review" for gate in critical):
        return "needs_review"
    if any(gate.get("status") == "review" for gate in gates):
        return "needs_review"
    return "research_ready"


def curve_summary(diagnostic: dict) -> dict:
    csv_section = diagnostic.get("result_data_csv", {})
    summary = csv_section.get("curve_summary")
    return summary if isinstance(summary, dict) else {}


def interpretation_notes(status: str, summary: dict, gates: list, comparison: dict) -> list:
    notes = []
    if status == "research_ready":
        notes.append("Local evidence is research-ready for reporting: result contract, CurveV0 comparison, contact closure, and ODB field gates pass.")
        notes.append("Use the reported moment-curvature, contact pressure, slip, opening, and stress metrics for literature/calibration comparison.")
    else:
        for gate in gates:
            if gate.get("status") in ("blocked", "review"):
                notes.append("{0}: {1}".format(gate.get("name", "-"), gate.get("detail", "-")))
    if comparison.get("recommended_next_action"):
        notes.append("CurveV0 comparison next action: {0}".format(comparison.get("recommended_next_action")))
    if summary.get("recommended_next_action"):
        notes.append("Diagnostics next action: {0}".format(summary.get("recommended_next_action")))
    return notes


def build_research_report(job_root: Path, job_dir: Optional[Path] = None, include_self_check: bool = False) -> dict:
    selected_job = resolve_job(job_root, job_dir, include_self_check)
    diagnostic = build_report(selected_job)
    summary = collect_summary(diagnostic)
    comparison = load_curve_v0_comparison(selected_job)
    if not comparison.get("exists"):
        comparison = {"status": None, "error": "curve_v0_comparison_report.json is missing"}
    gates = acceptance_preview(summary, comparison)
    status = choose_status(gates)
    intake = build_intake(job_root, job_dir=selected_job, include_self_check=include_self_check)
    curve = curve_summary(diagnostic)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_root": str(job_root),
        "job_dir": str(selected_job),
        "include_self_check": include_self_check,
        "status": status,
        "health": summary.get("health"),
        "source": summary.get("source"),
        "curve_class": summary.get("curve_class"),
        "rows": summary.get("csv_rows"),
        "curve_v0_comparison_status": comparison.get("status"),
        "curve_v0_peak_ratio": comparison.get("peak_moment_ratio_continuous_over_endpoint"),
        "acceptance_gates": gates,
        "intake_status": intake.get("status"),
        "blocked_items": intake.get("blocked_items", []),
        "review_items": intake.get("review_items", []),
        "metrics": {
            "max_abs_curvature_1_per_m": curve.get("max_abs_curvature_1_per_m"),
            "max_abs_moment_kn_m": curve.get("max_abs_moment_kn_m"),
            "loop_energy_proxy_kn": curve.get("loop_energy_proxy_kn"),
            "stress_mises_max": summary.get("odb_stress_mises_max"),
            "contact_pressure_max": summary.get("odb_contact_pressure_max"),
            "slip_abs_max": summary.get("odb_slip_abs_max"),
            "contact_preload_status": summary.get("contact_residual_preload_status"),
        },
        "odb_fields": {
            "present": summary.get("odb_present_local_fields"),
            "missing": summary.get("odb_missing_local_fields"),
            "top_contact_pressure_outputs": summary.get("odb_top_contact_pressure_outputs", []),
            "top_slip_outputs": summary.get("odb_top_slip_outputs", []),
            "top_stress_outputs": summary.get("odb_top_stress_outputs", []),
        },
        "interpretation_notes": interpretation_notes(status, summary, gates, comparison),
    }


def report_dir(report: dict) -> Path:
    return Path(report.get("job_dir") or report.get("job_root") or ".")


def markdown_report(report: dict) -> str:
    metrics = report.get("metrics", {})
    fields = report.get("odb_fields", {})
    lines = [
        "# HELIX / SCLAS Research Report",
        "",
        "- Status: `{0}`".format(report.get("status", "-")),
        "- Job: `{0}`".format(report.get("job_dir", "-")),
        "- Health/source/class: `{0}` / `{1}` / `{2}`".format(
            report.get("health", "-"),
            report.get("source", "-"),
            report.get("curve_class", "-"),
        ),
        "- Result intake: `{0}`".format(report.get("intake_status", "-")),
        "- CurveV0 comparison: `{0}`, peak ratio `{1}`".format(
            report.get("curve_v0_comparison_status", "-"),
            report.get("curve_v0_peak_ratio", "-"),
        ),
        "",
        "## Engineering Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in [
        "max_abs_curvature_1_per_m",
        "max_abs_moment_kn_m",
        "loop_energy_proxy_kn",
        "stress_mises_max",
        "contact_pressure_max",
        "slip_abs_max",
        "contact_preload_status",
    ]:
        lines.append("| {0} | {1} |".format(key, metrics.get(key, "-")))

    lines.extend(["", "## Acceptance Gates", "", "| Gate | Status | Critical | Detail |", "| --- | --- | --- | --- |"])
    for gate in report.get("acceptance_gates", []):
        lines.append("| {0} | {1} | {2} | {3} |".format(
            gate.get("name", "-"),
            gate.get("status", "-"),
            gate.get("critical", "-"),
            str(gate.get("detail", "-")).replace("|", "\\|"),
        ))

    lines.extend([
        "",
        "## ODB Field Evidence",
        "",
        "- Present: `{0}`".format(fields.get("present", "-")),
        "- Missing: `{0}`".format(fields.get("missing", "-")),
        "- Top CPRESS outputs: `{0}`".format(fields.get("top_contact_pressure_outputs", [])),
        "- Top slip outputs: `{0}`".format(fields.get("top_slip_outputs", [])),
        "- Top stress outputs: `{0}`".format(fields.get("top_stress_outputs", [])),
        "",
        "## Interpretation Notes",
        "",
    ])
    for note in report.get("interpretation_notes", []):
        lines.append("- {0}".format(note))
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
    metrics = report.get("metrics", {})
    lines = [
        "HELIX / SCLAS Research Report",
        "=============================",
        "Status: {0}".format(report.get("status", "-")),
        "Job: {0}".format(report.get("job_dir", "-")),
        "Health/source/class: {0} / {1} / {2}".format(
            report.get("health", "-"),
            report.get("source", "-"),
            report.get("curve_class", "-"),
        ),
        "Intake: {0}".format(report.get("intake_status", "-")),
        "CurveV0 comparison: {0}, peak_ratio={1}".format(
            report.get("curve_v0_comparison_status", "-"),
            report.get("curve_v0_peak_ratio", "-"),
        ),
        "",
        "Engineering metrics:",
    ]
    for key, value in metrics.items():
        lines.append("- {0}: {1}".format(key, value))
    lines.extend(["", "Acceptance gates:"])
    for gate in report.get("acceptance_gates", []):
        marker = "critical" if gate.get("critical") else "advisory"
        lines.append("- {0}: {1} [{2}] - {3}".format(gate.get("name", "-"), gate.get("status", "-"), marker, gate.get("detail", "-")))
    lines.extend(["", "Interpretation notes:"])
    for note in report.get("interpretation_notes", []):
        lines.append("- {0}".format(note))
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend(["", "Saved reports:", "- JSON: {0}".format(report.get("saved_report", "-")), "- Markdown: {0}".format(report.get("saved_markdown_report", "-"))])
    return "\n".join(lines)


def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "research_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "research_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate a HELIX/SCLAS research interpretation report.")
    parser.add_argument("job_dir", nargs="?", help="Specific job folder to report. Defaults to latest job under --job-root.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check jobs in latest selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save research_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save research_report.md.")
    parser.add_argument("--output", help="Custom JSON output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown output path.")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless status is research_ready.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        job_root = Path(args.job_root).expanduser().resolve()
        job_dir = Path(args.job_dir) if args.job_dir else None
        report = build_research_report(job_root, job_dir=job_dir, include_self_check=args.include_self_check)
        json_path = Path(args.output).expanduser().resolve() if args.output else report_dir(report) / "research_report.json"
        markdown_path = (
            Path(args.markdown_output).expanduser().resolve()
            if args.markdown_output
            else report_dir(report) / "research_report.md"
        )
        if args.save_report or args.output:
            report["saved_report"] = str(json_path)
        if args.save_markdown or args.markdown_output:
            report["saved_markdown_report"] = str(markdown_path)
        if args.save_report or args.output:
            save_report(report, json_path)
        if args.save_markdown or args.markdown_output:
            save_markdown_report(report, markdown_path)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(human_report(report))
        if args.strict and report.get("status") != "research_ready":
            return 2
        return 0
    except Exception as exc:
        print("[ERROR] {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
