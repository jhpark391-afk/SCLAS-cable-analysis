#!/usr/bin/env python3
"""Offline diagnostics for SCLAS/HELIX Abaqus job folders.

This tool is intentionally Abaqus-free. Use it on macOS or Windows to inspect
job folders copied back from the lab PC.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path


BLOCKING_ERROR_PATTERNS = [
    "***ERROR",
    "FATAL",
    "SEVERE",
    "THE PROGRAM HAS DISCOVERED",
    "Abaqus Error",
    "Abaqus/Analysis exited",
    "UNKNOWN",
    "INVALID",
    "MISPLACED",
    "ZERO PIVOT",
    "OVERCONSTRAINT",
    "TOO MANY",
    "EXCESSIVE",
    "DISTORTION",
]

NOTABLE_LOG_PATTERNS = [
    "WARNING",
    "COUPLING",
    "KINEMATIC",
    "REF NODE",
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except TypeError:
        return path.read_text()


def load_json(path: Path):
    return json.loads(read_text(path))


def add_issue(report: dict, severity: str, message: str, detail=None) -> None:
    report["issues"].append({
        "severity": severity,
        "message": message,
        "detail": detail,
    })


def find_first(job_dir: Path, patterns) -> Path:
    for pattern in patterns:
        matches = sorted(job_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


def inspect_result_csv(job_dir: Path, report: dict) -> None:
    path = job_dir / "result_data.csv"
    section = {"exists": path.exists()}
    report["result_data_csv"] = section
    if not path.exists():
        add_issue(report, "error", "result_data.csv is missing")
        return

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0] if rows else []
    section["header"] = header
    section["data_rows"] = max(len(rows) - 1, 0)
    if header != ["curvature_1_per_m", "moment_kn_m"]:
        add_issue(report, "error", "Unexpected result_data.csv header", header)
    if section["data_rows"] < 2:
        add_issue(report, "warning", "result_data.csv has too few data rows", section["data_rows"])


def inspect_summary(job_dir: Path, report: dict) -> None:
    path = job_dir / "result_summary.json"
    section = {"exists": path.exists()}
    report["result_summary_json"] = section
    if not path.exists():
        add_issue(report, "warning", "result_summary.json is missing")
        return

    try:
        data = load_json(path)
    except Exception as exc:
        add_issue(report, "error", "Could not parse result_summary.json", str(exc))
        return

    required = ["source", "status", "result_contract", "backend_readiness", "mesh_status"]
    section["source"] = data.get("source")
    section["status"] = data.get("status")
    section["mesh_status"] = data.get("mesh_status", {}).get("status") if isinstance(data.get("mesh_status"), dict) else data.get("mesh_status")
    section["enabled_assessments"] = data.get("enabled_assessments", [])
    for key in required:
        if key not in data:
            add_issue(report, "warning", "result_summary.json missing key", key)
    contract = data.get("result_contract", {})
    if contract.get("required_columns") != ["curvature_1_per_m", "moment_kn_m"]:
        add_issue(report, "warning", "Summary result contract has unexpected required columns", contract)


def inspect_manifest(job_dir: Path, report: dict) -> None:
    path = job_dir / "abaqus_mesh_manifest.json"
    section = {"exists": path.exists()}
    report["abaqus_mesh_manifest_json"] = section
    if not path.exists():
        add_issue(report, "warning", "abaqus_mesh_manifest.json is missing")
        return

    try:
        data = load_json(path)
    except Exception as exc:
        add_issue(report, "error", "Could not parse abaqus_mesh_manifest.json", str(exc))
        return

    status_keys = [
        "status",
        "contact_region_scaffold_status",
        "contact_interaction_scaffold_status",
        "contact_pair_scaffold_status",
        "boundary_condition_scaffold_status",
    ]
    for key in status_keys:
        section[key] = data.get(key)
    section["abaqus_files"] = data.get("abaqus_files", [])
    section["contact_bindings"] = len(data.get("contact_binding_scaffold", []))
    section["components"] = [item.get("name") for item in data.get("components", []) if isinstance(item, dict)]

    for key in status_keys:
        if key not in data:
            add_issue(report, "warning", "Mesh manifest missing scaffold status key", key)
    if data.get("status") == "abaqus_mesh_failed":
        add_issue(report, "error", "Abaqus mesh scaffold failed", data.get("error", ""))
    if data.get("status") == "abaqus_mesh_created" and not data.get("abaqus_files"):
        add_issue(report, "warning", "Manifest says Abaqus mesh was created but no files are listed")


def keyword_positions(lines, keyword):
    keyword_upper = keyword.upper()
    return [idx for idx, line in enumerate(lines) if line.strip().upper().startswith(keyword_upper)]


def inspect_inp(job_dir: Path, report: dict) -> None:
    path = find_first(job_dir, ["*.inp", "*_mesh.inp", "*_mes.inp"])
    section = {"exists": path is not None}
    report["input_deck"] = section
    if path is None:
        add_issue(report, "info", "No Abaqus .inp file found in job folder")
        return

    text = read_text(path)
    lines = text.splitlines()
    upper = text.upper()
    section["file"] = path.name
    section["line_count"] = len(lines)
    section["has_end_assembly"] = "*END ASSEMBLY" in upper
    section["coupling_count"] = upper.count("*COUPLING")
    section["kinematic_count"] = upper.count("*KINEMATIC")
    section["node_surface_count"] = len(re.findall(r"(?im)^\*SURFACE,\s*TYPE=NODE", text))
    section["sclas_keyword_fallback_present"] = "SCLAS ABAQUS 2019 END-COUPLING KEYWORD FALLBACK" in upper
    section["left_keyword_coupling"] = "SCLAS_LEFTEND_KEYWORDCOUPLING" in upper
    section["right_keyword_coupling"] = "SCLAS_RIGHTEND_KEYWORDCOUPLING" in upper

    end_assembly_positions = keyword_positions(lines, "*End Assembly")
    coupling_positions = keyword_positions(lines, "*Coupling")
    section["coupling_after_end_assembly"] = False
    if end_assembly_positions and coupling_positions:
        first_end = min(end_assembly_positions)
        after = [pos + 1 for pos in coupling_positions if pos > first_end]
        section["coupling_after_end_assembly"] = bool(after)
        if after:
            add_issue(report, "error", "*Coupling appears after *End Assembly", after[:10])
    if section["coupling_count"] and not section["kinematic_count"]:
        add_issue(report, "warning", "*Coupling exists but *Kinematic was not found")
    if section["sclas_keyword_fallback_present"] and not (
        section["left_keyword_coupling"] and section["right_keyword_coupling"]
    ):
        add_issue(report, "warning", "SCLAS keyword fallback marker exists but left/right coupling names are incomplete")


def context_block(lines, index, radius=2):
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join("{0}: {1}".format(i + 1, lines[i]) for i in range(start, end))


def inspect_solver_logs(job_dir: Path, report: dict) -> None:
    log_files = []
    for pattern in ["*.dat", "*.msg", "*.sta", "solver_stdout.txt", "abaqus_stdout.txt"]:
        log_files.extend(sorted(job_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True))
    seen = set()
    unique_logs = []
    for path in log_files:
        if path not in seen:
            unique_logs.append(path)
            seen.add(path)

    section = {"files": [path.name for path in unique_logs], "matches": []}
    report["solver_logs"] = section
    if not unique_logs:
        add_issue(report, "info", "No Abaqus solver log files found")
        return

    def collect_matches(pattern_items, limit):
        pattern = re.compile("|".join(re.escape(item) for item in pattern_items), re.IGNORECASE)
        collected = []
        for path in unique_logs:
            lines = read_text(path).splitlines()
            for idx, line in enumerate(lines):
                if pattern.search(line):
                    collected.append({
                        "file": path.name,
                        "line": idx + 1,
                        "text": line.strip(),
                        "context": context_block(lines, idx),
                    })
                    if len(collected) >= limit:
                        return collected
        return collected

    section["match_priority"] = "blocking"
    section["matches"] = collect_matches(BLOCKING_ERROR_PATTERNS, 80)
    if not section["matches"]:
        section["match_priority"] = "notable"
        section["matches"] = collect_matches(NOTABLE_LOG_PATTERNS, 40)
    if section["matches"]:
        add_issue(report, "warning", "Solver log contains notable Abaqus keywords/errors", len(section["matches"]))


def summarize_report(report: dict) -> None:
    issues = report.get("issues", [])
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    ordered = sorted(issues, key=lambda item: severity_rank.get(item.get("severity"), 9))
    first = ordered[0] if ordered else None
    counts = {
        "error": sum(1 for item in issues if item.get("severity") == "error"),
        "warning": sum(1 for item in issues if item.get("severity") == "warning"),
        "info": sum(1 for item in issues if item.get("severity") == "info"),
    }

    deck = report.get("input_deck", {})
    logs = report.get("solver_logs", {})
    manifest = report.get("abaqus_mesh_manifest_json", {})

    if counts["error"]:
        if deck.get("coupling_after_end_assembly"):
            action = "Move injected *Coupling/*Kinematic blocks inside the assembly scope before *End Assembly."
        elif first and "result_data.csv" in first.get("message", ""):
            action = "Restore the result_data.csv contract before debugging solver output."
        elif manifest.get("status") == "abaqus_mesh_failed":
            action = "Inspect abaqus_mesh_manifest.json error and fix the Abaqus scaffold creation failure first."
        else:
            action = "Fix the first error in this report before expanding the backend."
    elif logs.get("matches"):
        action = "Inspect the first solver log match and make the smallest targeted abaqus_runner.py fix."
    elif not deck.get("exists"):
        action = "Copy the Lab-PC generated .inp/.dat/.msg files into this job folder for deeper offline diagnostics."
    elif counts["warning"]:
        action = "Review warnings, then rerun the Lab-PC noGUI and solver smoke tests."
    else:
        action = "No blocking issue was detected offline; continue with the next Lab-PC Abaqus smoke test."

    report["diagnostic_summary"] = {
        "issue_counts": counts,
        "first_blocking_issue": first,
        "recommended_next_action": action,
    }


def build_report(job_dir: Path) -> dict:
    report = {
        "job_dir": str(job_dir),
        "issues": [],
    }
    if not job_dir.exists() or not job_dir.is_dir():
        add_issue(report, "error", "Job directory does not exist", str(job_dir))
        return report

    inspect_result_csv(job_dir, report)
    inspect_summary(job_dir, report)
    inspect_manifest(job_dir, report)
    inspect_inp(job_dir, report)
    inspect_solver_logs(job_dir, report)
    summarize_report(report)
    return report


def save_report(report: dict, output_path: Path = None) -> Path:
    job_dir = Path(report["job_dir"])
    path = output_path or (job_dir / "offline_diagnostics_report.json")
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def markdown_report(report: dict) -> str:
    def scalar(value, default="-"):
        if value in (None, ""):
            return default
        return str(value)

    lines = [
        "# SCLAS Offline Diagnostics",
        "",
        "## Job",
        "",
        "- Path: `{0}`".format(report.get("job_dir", "-")),
        "",
        "## Summary",
        "",
    ]

    csv_section = report.get("result_data_csv", {})
    summary_section = report.get("result_summary_json", {})
    manifest_section = report.get("abaqus_mesh_manifest_json", {})
    deck_section = report.get("input_deck", {})
    logs_section = report.get("solver_logs", {})
    diagnostic_summary = report.get("diagnostic_summary", {})
    issue_counts = diagnostic_summary.get("issue_counts", {})

    summary_rows = [
        ("Result CSV", scalar(csv_section.get("exists"))),
        ("CSV rows", scalar(csv_section.get("data_rows"))),
        ("Summary status", scalar(summary_section.get("status"))),
        ("Mesh status", scalar(summary_section.get("mesh_status"))),
        ("Manifest status", scalar(manifest_section.get("status"))),
        ("Contact pair scaffold", scalar(manifest_section.get("contact_pair_scaffold_status"))),
        ("Boundary scaffold", scalar(manifest_section.get("boundary_condition_scaffold_status"))),
        ("Input deck", scalar(deck_section.get("file"))),
        ("Couplings after End Assembly", scalar(deck_section.get("coupling_after_end_assembly"))),
        ("Solver log matches", scalar(len(logs_section.get("matches", [])))),
        ("Errors", scalar(issue_counts.get("error"))),
        ("Warnings", scalar(issue_counts.get("warning"))),
    ]
    lines.extend(["| Item | Value |", "|---|---|"])
    for key, value in summary_rows:
        lines.append("| {0} | {1} |".format(key, value))

    lines.extend(["", "## Recommended Next Action", ""])
    lines.append(diagnostic_summary.get("recommended_next_action", "-"))

    lines.extend(["", "## Issues", ""])
    issues = report.get("issues", [])
    if not issues:
        lines.append("No issues were reported.")
    else:
        for issue in issues:
            lines.append("- **{0}**: {1}".format(issue.get("severity", "-"), issue.get("message", "-")))
            if issue.get("detail") not in (None, ""):
                lines.append("  - Detail: `{0}`".format(issue.get("detail")))

    matches = logs_section.get("matches", [])
    lines.extend(["", "## Solver Log Matches", ""])
    if not matches:
        lines.append("No solver log matches were found.")
    else:
        for match in matches[:20]:
            lines.append("### {0}:{1}".format(match.get("file", "-"), match.get("line", "-")))
            lines.append("")
            lines.append("```text")
            lines.append(match.get("context") or match.get("text", ""))
            lines.append("```")
            lines.append("")
        if len(matches) > 20:
            lines.append("Additional matches omitted: {0}".format(len(matches) - 20))

    lines.extend([
        "",
        "## Next Debug Prompt",
        "",
        "```text",
        "This is a SCLAS/HELIX Abaqus offline diagnostics report.",
        "Recommended next action: {0}".format(diagnostic_summary.get("recommended_next_action", "-")),
        "Focus on the first error or warning above. If an .inp keyword placement",
        "or solver log issue is shown, propose the smallest targeted fix in",
        "code/abaqus_runner.py while preserving result_data.csv and",
        "result_summary.json contracts.",
        "```",
        "",
    ])
    return "\n".join(lines)


def save_markdown_report(report: dict, output_path: Path = None) -> Path:
    job_dir = Path(report["job_dir"])
    path = output_path or (job_dir / "offline_diagnostics_report.md")
    path.write_text(markdown_report(report), encoding="utf-8")
    return path


def print_report(report: dict) -> None:
    print("SCLAS Offline Diagnostics")
    print("Job:", report["job_dir"])
    diagnostic_summary = report.get("diagnostic_summary", {})
    issue_counts = diagnostic_summary.get("issue_counts", {})
    print("Recommended next action:", diagnostic_summary.get("recommended_next_action", "-"))
    print("Issue counts:", issue_counts)
    print()

    for key in ["result_data_csv", "result_summary_json", "abaqus_mesh_manifest_json", "input_deck", "solver_logs"]:
        section = report.get(key, {})
        print("[{0}]".format(key))
        for item_key, value in section.items():
            if item_key == "matches":
                print("  matches:", len(value))
                for match in value[:8]:
                    print("  - {file}:{line}: {text}".format(**match))
                if len(value) > 8:
                    print("  ... {0} more".format(len(value) - 8))
            else:
                print("  {0}: {1}".format(item_key, value))
        print()

    if report["issues"]:
        print("Issues:")
        for issue in report["issues"]:
            print("- [{severity}] {message}".format(**issue))
            if issue.get("detail") not in (None, ""):
                print("  detail:", issue["detail"])
    else:
        print("Issues: none")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect SCLAS Abaqus job output without Abaqus.")
    parser.add_argument("job_dir", help="Path to a SCLAS job folder")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON report")
    parser.add_argument(
        "--save-report",
        action="store_true",
        help="Write offline_diagnostics_report.json into the job folder",
    )
    parser.add_argument(
        "--save-markdown",
        action="store_true",
        help="Write offline_diagnostics_report.md into the job folder",
    )
    parser.add_argument("--output", help="Optional JSON output path for --save-report")
    parser.add_argument("--markdown-output", help="Optional Markdown output path for --save-markdown")
    args = parser.parse_args(argv)

    report = build_report(Path(args.job_dir).expanduser().resolve())
    if args.save_report:
        output_path = Path(args.output).expanduser().resolve() if args.output else None
        saved_path = save_report(report, output_path)
        report["saved_report"] = str(saved_path)
    if args.save_markdown:
        markdown_output = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None
        saved_markdown_path = save_markdown_report(report, markdown_output)
        report["saved_markdown_report"] = str(saved_markdown_path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
        if args.save_report:
            print()
            print("Saved report:", report["saved_report"])
        if args.save_markdown:
            print("Saved Markdown report:", report["saved_markdown_report"])

    return 1 if any(issue["severity"] == "error" for issue in report["issues"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
