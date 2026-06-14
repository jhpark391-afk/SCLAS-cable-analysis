#!/usr/bin/env python3
"""Intake checklist for HELIX/SCLAS job folders copied from the Abaqus PC."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_acceptance_gate import (
    contact_gate,
    curve_gate,
    odb_field_gate,
    result_contract_gate,
    warning_gate,
)
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir, load_curve_v0_comparison
from sclas_offline_diagnostics import build_report


def item(name: str, status: str, detail: str, critical: bool = True) -> dict:
    return {
        "name": name,
        "status": status,
        "critical": critical,
        "detail": detail,
    }


def has_any(job_dir: Path, patterns: list) -> list:
    files = []
    for pattern in patterns:
        files.extend(path.name for path in sorted(job_dir.glob(pattern)))
    return sorted(set(files))


def file_items(job_dir: Path, summary: dict) -> list:
    result_rows = summary.get("csv_rows")
    solver_logs = has_any(job_dir, ["*.dat", "*.msg", "*.sta", "solver_stdout.txt", "abaqus_stdout.txt"])
    input_decks = has_any(job_dir, ["*.inp", "*_mesh.inp", "*_mes.inp"])
    odb_files = has_any(job_dir, ["*.odb"])
    items = []

    if result_rows:
        items.append(item("result_csv", "pass", "result_data.csv has {0} numeric rows".format(result_rows)))
    else:
        items.append(item("result_csv", "blocked", "result_data.csv is missing or has no numeric rows"))

    if (job_dir / "result_summary.json").exists():
        items.append(item("result_summary", "pass", "result_summary.json exists", critical=False))
    else:
        items.append(item("result_summary", "review", "result_summary.json is missing", critical=False))

    if (job_dir / "abaqus_mesh_manifest.json").exists():
        items.append(item("mesh_manifest", "pass", "abaqus_mesh_manifest.json exists", critical=False))
    else:
        items.append(item("mesh_manifest", "review", "abaqus_mesh_manifest.json is missing", critical=False))

    if input_decks:
        items.append(item("input_deck", "pass", "Abaqus input deck found: {0}".format(", ".join(input_decks[:3])), critical=False))
    else:
        items.append(item("input_deck", "review", "No .inp file found in the job folder", critical=False))

    if solver_logs:
        items.append(item("solver_logs", "pass", "solver logs found: {0}".format(", ".join(solver_logs[:4])), critical=False))
    else:
        items.append(item("solver_logs", "review", "No .dat/.msg/.sta or solver stdout logs found", critical=False))

    if summary.get("odb_status") == "extracted":
        items.append(item("odb_extraction", "pass", "ODB extraction completed with {0} rows".format(summary.get("odb_rows_written"))))
    elif odb_files:
        items.append(item("odb_extraction", "review", "ODB file exists but extraction status is {0}".format(summary.get("odb_status"))))
    else:
        items.append(item("odb_extraction", "review", "No .odb file or extracted ODB summary was found"))

    return items


def acceptance_preview(summary: dict, comparison: dict) -> list:
    return [
        result_contract_gate(summary),
        curve_gate(summary, comparison),
        contact_gate(summary),
        odb_field_gate(summary),
        warning_gate(summary),
    ]


def choose_status(items: list) -> str:
    critical = [entry for entry in items if entry.get("critical")]
    if any(entry.get("status") == "blocked" for entry in critical):
        return "blocked"
    if any(entry.get("status") == "review" for entry in critical):
        return "review"
    if any(entry.get("status") == "review" for entry in items):
        return "review"
    return "ready"


def choose_next_action(status: str, items: list) -> str:
    blocked = [entry for entry in items if entry.get("critical") and entry.get("status") == "blocked"]
    if blocked:
        names = ", ".join(entry.get("name", "-") for entry in blocked)
        return "Fix blocked intake items on the remote Abaqus PC or copy the missing artifacts back, then rerun result intake and the acceptance gate: {0}.".format(names)
    review = [entry for entry in items if entry.get("status") == "review"]
    if review:
        return "Review non-passing intake items, then run sclas_acceptance_gate.py before using the job as research evidence."
    if status == "ready":
        return "Run sclas_acceptance_gate.py --save-report --save-markdown, then compare against literature/calibration targets."
    return "Inspect intake details and rerun the local validation suite."


def resolve_job(job_root: Path, job_dir: Optional[Path], include_self_check: bool) -> Path:
    if job_dir:
        return job_dir.expanduser().resolve()
    return latest_job_dir(job_root, include_self_check=include_self_check)


def build_intake(job_root: Path, job_dir: Optional[Path] = None, include_self_check: bool = False) -> dict:
    selected_job = resolve_job(job_root, job_dir, include_self_check)
    diagnostic = build_report(selected_job)
    summary = collect_summary(diagnostic)
    comparison = load_curve_v0_comparison(selected_job)
    if not comparison.get("exists"):
        comparison = {"status": None, "error": "curve_v0_comparison_report.json is missing"}

    checklist = file_items(selected_job, summary)
    gate_preview = acceptance_preview(summary, comparison)
    all_items = checklist + gate_preview
    status = choose_status(all_items)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_root": str(job_root),
        "job_dir": str(selected_job),
        "include_self_check": include_self_check,
        "status": status,
        "latest_health": summary.get("health"),
        "latest_source": summary.get("source"),
        "latest_curve_class": summary.get("curve_class"),
        "checklist": checklist,
        "acceptance_preview": gate_preview,
        "recommended_next_action": choose_next_action(status, all_items),
    }


def report_dir(report: dict) -> Path:
    return Path(report.get("job_dir") or report.get("job_root") or ".")


def markdown_report(report: dict) -> str:
    lines = [
        "# HELIX / SCLAS Result Intake",
        "",
        "- Status: `{0}`".format(report.get("status", "-")),
        "- Job: `{0}`".format(report.get("job_dir", "-")),
        "- Health/source/class: `{0}` / `{1}` / `{2}`".format(
            report.get("latest_health", "-"),
            report.get("latest_source", "-"),
            report.get("latest_curve_class", "-"),
        ),
        "",
        "## Intake Checklist",
        "",
        "| Item | Status | Critical | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for entry in report.get("checklist", []):
        lines.append("| {0} | {1} | {2} | {3} |".format(
            entry.get("name", "-"),
            entry.get("status", "-"),
            entry.get("critical", "-"),
            str(entry.get("detail", "-")).replace("|", "\\|"),
        ))
    lines.extend(["", "## Acceptance Preview", "", "| Gate | Status | Critical | Detail |", "| --- | --- | --- | --- |"])
    for entry in report.get("acceptance_preview", []):
        lines.append("| {0} | {1} | {2} | {3} |".format(
            entry.get("name", "-"),
            entry.get("status", "-"),
            entry.get("critical", "-"),
            str(entry.get("detail", "-")).replace("|", "\\|"),
        ))
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
        "HELIX / SCLAS Result Intake",
        "===========================",
        "Status: {0}".format(report.get("status", "-")),
        "Job: {0}".format(report.get("job_dir", "-")),
        "Health/source/class: {0} / {1} / {2}".format(
            report.get("latest_health", "-"),
            report.get("latest_source", "-"),
            report.get("latest_curve_class", "-"),
        ),
        "",
        "Intake checklist:",
    ]
    for entry in report.get("checklist", []):
        marker = "critical" if entry.get("critical") else "advisory"
        lines.append("- {0}: {1} [{2}] - {3}".format(entry.get("name", "-"), entry.get("status", "-"), marker, entry.get("detail", "-")))
    lines.append("")
    lines.append("Acceptance preview:")
    for entry in report.get("acceptance_preview", []):
        marker = "critical" if entry.get("critical") else "advisory"
        lines.append("- {0}: {1} [{2}] - {3}".format(entry.get("name", "-"), entry.get("status", "-"), marker, entry.get("detail", "-")))
    lines.extend(["", "Next action:", report.get("recommended_next_action", "-")])
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend(["", "Saved reports:", "- JSON: {0}".format(report.get("saved_report", "-")), "- Markdown: {0}".format(report.get("saved_markdown_report", "-"))])
    return "\n".join(lines)


def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "result_intake_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or report_dir(report) / "result_intake_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Inspect a copied HELIX/SCLAS Abaqus job folder before acceptance.")
    parser.add_argument("job_dir", nargs="?", help="Specific job folder to inspect. Defaults to the latest job under --job-root.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check jobs in latest selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save result_intake_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save result_intake_report.md.")
    parser.add_argument("--output", help="Custom JSON output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown output path.")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless intake status is ready.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        job_root = Path(args.job_root).expanduser().resolve()
        job_dir = Path(args.job_dir) if args.job_dir else None
        report = build_intake(job_root, job_dir=job_dir, include_self_check=args.include_self_check)
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
        if args.strict and report.get("status") != "ready":
            return 2
        return 0
    except Exception as exc:
        print("[ERROR] {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
