#!/usr/bin/env python3
"""Run the repeatable HELIX/SCLAS local validation and handoff suite."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_acceptance_gate import build_gate
from sclas_acceptance_gate import human_report as acceptance_human_report
from sclas_acceptance_gate import save_markdown_report as save_acceptance_markdown
from sclas_acceptance_gate import save_report as save_acceptance_report
from sclas_handoff_snapshot import build_snapshot
from sclas_handoff_snapshot import git_state
from sclas_handoff_snapshot import save_markdown_report as save_snapshot_markdown
from sclas_handoff_snapshot import save_report as save_snapshot_report
from sclas_job_summary import DEFAULT_JOB_ROOT
from sclas_next_prompt import prompt_text, save_prompt
from sclas_result_intake import build_intake
from sclas_result_intake import save_markdown_report as save_intake_markdown
from sclas_result_intake import save_report as save_intake_report


PROJECT_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_DIR / "code"


def run_self_check() -> dict:
    proc = subprocess.run(
        [sys.executable, str(CODE_DIR / "sclas_self_check.py")],
        cwd=str(PROJECT_DIR),
        text=True,
        capture_output=True,
    )
    return {
        "command": "{0} {1}".format(sys.executable, CODE_DIR / "sclas_self_check.py"),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "status": "pass" if proc.returncode == 0 else "failed",
    }


def build_suite(job_root: Path, limit: int = 15, include_self_check: bool = False, skip_self_check: bool = False) -> dict:
    started_at = datetime.now().isoformat(timespec="seconds")
    self_check = {
        "status": "skipped",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    } if skip_self_check else run_self_check()

    acceptance = build_gate(job_root, include_self_check=include_self_check)
    acceptance_json = save_acceptance_report(acceptance)
    acceptance["saved_report"] = str(acceptance_json)
    acceptance_markdown = save_acceptance_markdown(acceptance)
    acceptance["saved_markdown_report"] = str(acceptance_markdown)

    intake = build_intake(job_root, include_self_check=include_self_check)
    intake_json = save_intake_report(intake)
    intake["saved_report"] = str(intake_json)
    intake_markdown = save_intake_markdown(intake)
    intake["saved_markdown_report"] = str(intake_markdown)

    snapshot = build_snapshot(job_root, limit=limit, include_self_check=include_self_check)
    snapshot_json = save_snapshot_report(snapshot)
    snapshot["saved_report"] = str(snapshot_json)
    snapshot_markdown = save_snapshot_markdown(snapshot)
    snapshot["saved_markdown_report"] = str(snapshot_markdown)

    prompt_path = save_prompt(prompt_text(snapshot))
    status = "pass"
    if self_check.get("status") == "failed":
        status = "failed"
    elif acceptance.get("overall_status") == "blocked":
        status = "blocked_acceptance"
    elif acceptance.get("overall_status") == "review":
        status = "review_acceptance"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started_at,
        "project_dir": str(PROJECT_DIR),
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "git": git_state(),
        "status": status,
        "self_check": self_check,
        "result_intake": intake,
        "acceptance_gate": acceptance,
        "handoff_snapshot": {
            "saved_report": str(snapshot_json),
            "saved_markdown_report": str(snapshot_markdown),
            "acceptance_status": snapshot.get("handoff_focus", {}).get("acceptance_status"),
            "next_action": snapshot.get("handoff_focus", {}).get("next_action"),
        },
        "next_prompt": {
            "saved_prompt": str(prompt_path),
        },
        "recommended_next_action": acceptance.get("recommended_next_action") or snapshot.get("handoff_focus", {}).get("next_action"),
    }


def default_report_path(suffix: str) -> Path:
    return PROJECT_DIR / ("validation_suite_report." + suffix)


def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def markdown_report(report: dict) -> str:
    acceptance = report.get("acceptance_gate", {})
    intake = report.get("result_intake", {})
    handoff = report.get("handoff_snapshot", {})
    self_check = report.get("self_check", {})
    prompt = report.get("next_prompt", {})
    git = report.get("git", {})
    lines = [
        "# HELIX / SCLAS Validation Suite",
        "",
        "- Status: `{0}`".format(report.get("status", "-")),
        "- Git: `{0}` @ `{1}` -> `{2}` (`{3}`, dirty `{4}`, ahead `{5}`, behind `{6}`)".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("sync_status", "-"),
            git.get("dirty", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "- Project: `{0}`".format(report.get("project_dir", "-")),
        "- Job root: `{0}`".format(report.get("job_root", "-")),
        "- Self-check: `{0}` return code `{1}`".format(
            self_check.get("status", "-"),
            self_check.get("returncode", "-"),
        ),
        "- Result intake: `{0}`".format(intake.get("status", "-")),
        "- Acceptance: `{0}`".format(acceptance.get("overall_status", "-")),
        "- Latest job: `{0}`".format(acceptance.get("latest_job", "-")),
        "- Next action: {0}".format(report.get("recommended_next_action", "-")),
        "",
        "## Saved Outputs",
        "",
        "- Acceptance JSON: `{0}`".format(acceptance.get("saved_report", "-")),
        "- Acceptance Markdown: `{0}`".format(acceptance.get("saved_markdown_report", "-")),
        "- Result intake JSON: `{0}`".format(intake.get("saved_report", "-")),
        "- Result intake Markdown: `{0}`".format(intake.get("saved_markdown_report", "-")),
        "- Handoff JSON: `{0}`".format(handoff.get("saved_report", "-")),
        "- Handoff Markdown: `{0}`".format(handoff.get("saved_markdown_report", "-")),
        "- Next prompt: `{0}`".format(prompt.get("saved_prompt", "-")),
        "",
    ]
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "## Suite Report",
            "",
            "- JSON: `{0}`".format(report.get("saved_report", "-")),
            "- Markdown: `{0}`".format(report.get("saved_markdown_report", "-")),
            "",
        ])
    return "\n".join(lines)


def human_report(report: dict) -> str:
    acceptance = report.get("acceptance_gate", {})
    intake = report.get("result_intake", {})
    handoff = report.get("handoff_snapshot", {})
    prompt = report.get("next_prompt", {})
    self_check = report.get("self_check", {})
    git = report.get("git", {})
    lines = [
        "HELIX / SCLAS Validation Suite",
        "==============================",
        "Status: {0}".format(report.get("status", "-")),
        "Git: {0} @ {1} -> {2} ({3}, dirty={4}, ahead={5}, behind={6})".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("sync_status", "-"),
            git.get("dirty", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "Project: {0}".format(report.get("project_dir", "-")),
        "Job root: {0}".format(report.get("job_root", "-")),
        "Self-check: {0} (return code {1})".format(
            self_check.get("status", "-"),
            self_check.get("returncode", "-"),
        ),
        "Acceptance: {0}".format(acceptance.get("overall_status", "-")),
        "Result intake: {0}".format(intake.get("status", "-")),
        "Latest job: {0}".format(acceptance.get("latest_job", "-")),
        "",
        "Next action:",
        report.get("recommended_next_action", "-"),
        "",
        "Acceptance details:",
        acceptance_human_report(acceptance),
        "",
        "Saved outputs:",
        "- Acceptance JSON: {0}".format(acceptance.get("saved_report", "-")),
        "- Acceptance Markdown: {0}".format(acceptance.get("saved_markdown_report", "-")),
        "- Result intake JSON: {0}".format(intake.get("saved_report", "-")),
        "- Result intake Markdown: {0}".format(intake.get("saved_markdown_report", "-")),
        "- Handoff JSON: {0}".format(handoff.get("saved_report", "-")),
        "- Handoff Markdown: {0}".format(handoff.get("saved_markdown_report", "-")),
        "- Next prompt: {0}".format(prompt.get("saved_prompt", "-")),
    ]
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "- Suite JSON: {0}".format(report.get("saved_report", "-")),
            "- Suite Markdown: {0}".format(report.get("saved_markdown_report", "-")),
        ])
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the repeatable HELIX/SCLAS validation suite.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of recent jobs in the embedded handoff snapshot.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check jobs in latest selection.")
    parser.add_argument("--skip-self-check", action="store_true", help="Do not run sclas_self_check.py; useful from inside self-check.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save validation_suite_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save validation_suite_report.md.")
    parser.add_argument("--output", help="Custom JSON output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown output path.")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless the suite status is pass.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = build_suite(
            Path(args.job_root).expanduser().resolve(),
            limit=args.limit,
            include_self_check=args.include_self_check,
            skip_self_check=args.skip_self_check,
        )
        if args.save_report or args.output:
            path = save_report(report, Path(args.output).expanduser().resolve() if args.output else None)
            report["saved_report"] = str(path)
        if args.save_markdown or args.markdown_output:
            path = save_markdown_report(
                report,
                Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None,
            )
            report["saved_markdown_report"] = str(path)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(human_report(report))
        if args.strict and report.get("status") != "pass":
            return 2
        if report.get("self_check", {}).get("status") == "failed":
            return 1
        return 0
    except Exception as exc:
        print("[ERROR] {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
