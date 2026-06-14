#!/usr/bin/env python3
"""One-page startup brief for HELIX/SCLAS Codex sessions."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_handoff_snapshot import PROJECT_DIR, build_snapshot
from sclas_job_summary import DEFAULT_JOB_ROOT


def blocked_gate_names(acceptance: dict) -> list:
    return [
        item.get("name", "-")
        for item in acceptance.get("gates", [])
        if item.get("critical") and item.get("status") == "blocked"
    ]


def review_gate_names(acceptance: dict) -> list:
    return [
        item.get("name", "-")
        for item in acceptance.get("gates", [])
        if item.get("status") == "review"
    ]


def choose_brief_status(snapshot: dict) -> str:
    git = snapshot.get("git", {})
    acceptance = snapshot.get("acceptance_gate", {})
    intake = snapshot.get("result_intake", {})
    if git.get("sync_status") == "diverged":
        return "git_diverged"
    if intake.get("status") == "blocked" or acceptance.get("overall_status") == "blocked":
        return "remote_blocked"
    if intake.get("status") == "review" or acceptance.get("overall_status") == "review":
        return "review"
    if acceptance.get("overall_status") == "accepted":
        return "research_candidate"
    return "triage"


def choose_mac_next_action(status: str, snapshot: dict) -> str:
    git = snapshot.get("git", {})
    if git.get("sync_status") in ("behind", "diverged"):
        return "Synchronize with GitHub first, then regenerate the session brief."
    if git.get("dirty"):
        return "Review local changes and either commit/push them or keep them intentionally uncommitted before handoff."
    if status == "remote_blocked":
        return "Keep Mac-side work to GUI, diagnostics, docs, and comparison tools while the remote Abaqus PC resolves the blocked physics gates."
    if status == "review":
        return "Inspect the review gates, compare against the latest Abaqus artifacts, and update diagnostics or documentation as needed."
    if status == "research_candidate":
        return "Prepare reporting plots, literature comparison notes, and final validation documentation."
    return "Run the validation suite and inspect the latest handoff snapshot before editing."


def startup_commands() -> list:
    return [
        "git pull",
        "git status --short --branch",
        "python code/sclas_session_brief.py --save-report --save-markdown",
        "python code/sclas_result_intake.py --save-report --save-markdown",
        "python code/sclas_research_report.py --save-report --save-markdown",
        "python code/sclas_handoff_snapshot.py --save-report --save-markdown",
        "python code/sclas_acceptance_gate.py --save-report --save-markdown",
        "python code/sclas_self_check.py",
    ]


def build_brief(job_root: Path, limit: int = 15, include_self_check: bool = False) -> dict:
    snapshot = build_snapshot(job_root, limit=limit, include_self_check=include_self_check)
    status = choose_brief_status(snapshot)
    acceptance = snapshot.get("acceptance_gate", {})
    intake = snapshot.get("result_intake", {})
    focus = snapshot.get("handoff_focus", {})
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(PROJECT_DIR),
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "status": status,
        "git": snapshot.get("git", {}),
        "latest_job": focus.get("best_job_path") or intake.get("job_dir") or acceptance.get("latest_job"),
        "best_job": focus.get("best_job"),
        "best_job_readiness_label": focus.get("best_job_readiness_label"),
        "best_job_readiness_score": focus.get("best_job_readiness_score"),
        "result_intake_status": intake.get("status"),
        "acceptance_status": acceptance.get("overall_status"),
        "blocked_gates": blocked_gate_names(acceptance),
        "review_gates": review_gate_names(acceptance),
        "contact_pressure_max": acceptance.get("contact_pressure_max"),
        "slip_abs_max": acceptance.get("slip_abs_max"),
        "remote_next_action": focus.get("next_action"),
        "mac_next_action": choose_mac_next_action(status, snapshot),
        "startup_commands": startup_commands(),
    }


def default_report_path(suffix: str) -> Path:
    return PROJECT_DIR / ("session_brief." + suffix)


def save_report(brief: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(brief)
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(brief: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(brief)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def markdown_report(brief: dict) -> str:
    git = brief.get("git", {})
    lines = [
        "# HELIX / SCLAS Session Brief",
        "",
        "- Status: `{0}`".format(brief.get("status", "-")),
        "- Git: `{0}` @ `{1}` -> `{2}` (`{3}`, dirty `{4}`, ahead `{5}`, behind `{6}`)".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("sync_status", "-"),
            git.get("dirty", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "- Latest/best job: `{0}`".format(brief.get("latest_job", "-")),
        "- Best readiness: `{0}` score `{1}`".format(
            brief.get("best_job_readiness_label", "-"),
            brief.get("best_job_readiness_score", "-"),
        ),
        "- Result intake: `{0}`".format(brief.get("result_intake_status", "-")),
        "- Acceptance: `{0}`".format(brief.get("acceptance_status", "-")),
        "- Blocked gates: `{0}`".format(", ".join(brief.get("blocked_gates", [])) or "-"),
        "- Contact: CPRESS `{0}`, slip `{1}`".format(
            brief.get("contact_pressure_max", "-"),
            brief.get("slip_abs_max", "-"),
        ),
        "",
        "## Next Actions",
        "",
        "- Mac/Home Codex: {0}".format(brief.get("mac_next_action", "-")),
        "- Remote Abaqus PC: {0}".format(brief.get("remote_next_action", "-")),
        "",
        "## Startup Commands",
        "",
        "```bash",
    ]
    lines.extend(brief.get("startup_commands", []))
    lines.extend(["```", ""])
    if brief.get("saved_report") or brief.get("saved_markdown_report"):
        lines.extend([
            "## Saved Reports",
            "",
            "- JSON: `{0}`".format(brief.get("saved_report", "-")),
            "- Markdown: `{0}`".format(brief.get("saved_markdown_report", "-")),
            "",
        ])
    return "\n".join(lines)


def human_report(brief: dict) -> str:
    git = brief.get("git", {})
    lines = [
        "HELIX / SCLAS Session Brief",
        "===========================",
        "Status: {0}".format(brief.get("status", "-")),
        "Git: {0} @ {1} -> {2} ({3}, dirty={4}, ahead={5}, behind={6})".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("sync_status", "-"),
            git.get("dirty", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "Latest/best job: {0}".format(brief.get("latest_job", "-")),
        "Best readiness: {0} score={1}".format(
            brief.get("best_job_readiness_label", "-"),
            brief.get("best_job_readiness_score", "-"),
        ),
        "Result intake: {0}".format(brief.get("result_intake_status", "-")),
        "Acceptance: {0}".format(brief.get("acceptance_status", "-")),
        "Blocked gates: {0}".format(", ".join(brief.get("blocked_gates", [])) or "-"),
        "Contact: CPRESS={0}, slip={1}".format(brief.get("contact_pressure_max", "-"), brief.get("slip_abs_max", "-")),
        "",
        "Next actions:",
        "- Mac/Home Codex: {0}".format(brief.get("mac_next_action", "-")),
        "- Remote Abaqus PC: {0}".format(brief.get("remote_next_action", "-")),
        "",
        "Startup commands:",
    ]
    lines.extend("- {0}".format(command) for command in brief.get("startup_commands", []))
    if brief.get("saved_report") or brief.get("saved_markdown_report"):
        lines.extend([
            "",
            "Saved reports:",
            "- JSON: {0}".format(brief.get("saved_report", "-")),
            "- Markdown: {0}".format(brief.get("saved_markdown_report", "-")),
        ])
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Print a one-page HELIX/SCLAS startup brief.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of recent jobs in the embedded snapshot.")
    parser.add_argument("--include-self-check", action="store_true", help="Include synthetic self_check job folders.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save session_brief.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save session_brief.md.")
    parser.add_argument("--output", help="Custom JSON report output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown report output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        brief = build_brief(
            Path(args.job_root).expanduser().resolve(),
            limit=args.limit,
            include_self_check=args.include_self_check,
        )
        json_path = Path(args.output).expanduser().resolve() if args.output else default_report_path("json")
        markdown_path = (
            Path(args.markdown_output).expanduser().resolve()
            if args.markdown_output
            else default_report_path("md")
        )
        if args.save_report or args.output:
            brief["saved_report"] = str(json_path)
        if args.save_markdown or args.markdown_output:
            brief["saved_markdown_report"] = str(markdown_path)
        if args.save_report or args.output:
            save_report(brief, json_path)
        if args.save_markdown or args.markdown_output:
            save_markdown_report(brief, markdown_path)
        if args.json:
            print(json.dumps(brief, indent=2, ensure_ascii=False))
        else:
            print(human_report(brief))
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS session brief failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
