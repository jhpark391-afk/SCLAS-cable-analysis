#!/usr/bin/env python3
"""Create a compact HELIX/SCLAS handoff snapshot."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_job_index import build_index
from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir
from sclas_offline_diagnostics import build_report
from sclas_acceptance_gate import build_gate
from sclas_project_status import build_status


PROJECT_DIR = Path(__file__).resolve().parent.parent


def run_git(args) -> str:
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=str(PROJECT_DIR),
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return "unavailable: {0}".format(exc)
    if proc.returncode != 0:
        return "unavailable: {0}".format((proc.stderr or proc.stdout).strip())
    return proc.stdout.strip()


def git_state() -> dict:
    upstream = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    ahead = None
    behind = None
    if upstream and not upstream.startswith("unavailable:"):
        counts = run_git(["rev-list", "--left-right", "--count", "HEAD...@{u}"])
        parts = counts.split()
        if len(parts) == 2:
            try:
                ahead = int(parts[0])
                behind = int(parts[1])
            except ValueError:
                ahead = None
                behind = None
    return {
        "branch": run_git(["branch", "--show-current"]),
        "head": run_git(["rev-parse", "--short", "HEAD"]),
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "status_short": run_git(["status", "--short", "--branch"]),
    }


def safe_latest_summary(job_root: Path, include_self_check: bool) -> dict:
    try:
        job_dir = latest_job_dir(job_root, include_self_check=include_self_check)
        return collect_summary(build_report(job_dir))
    except Exception as exc:
        return {"error": str(exc)}


def safe_acceptance_gate(job_root: Path, include_self_check: bool) -> dict:
    try:
        return build_gate(job_root, include_self_check=include_self_check)
    except Exception as exc:
        return {
            "overall_status": "unavailable",
            "error": str(exc),
            "recommended_next_action": "Run or copy a valid SCLAS job folder, then rerun the acceptance gate.",
        }


def build_snapshot(job_root: Path, limit: int = 15, include_self_check: bool = False) -> dict:
    index = build_index(job_root, limit=limit, include_self_check=include_self_check)
    status = build_status(job_root, include_self_check=include_self_check)
    acceptance = safe_acceptance_gate(job_root, include_self_check=include_self_check)
    latest_summary = safe_latest_summary(job_root, include_self_check=include_self_check)
    best_job = index.get("best_job") or {}
    next_action = (
        acceptance.get("recommended_next_action")
        or status.get("recommended_next_action")
        or latest_summary.get("recommended_next_action")
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(PROJECT_DIR),
        "job_root": str(job_root),
        "include_self_check": include_self_check,
        "git": git_state(),
        "project_status": status,
        "acceptance_gate": acceptance,
        "job_index": index,
        "latest_summary": latest_summary,
        "handoff_focus": {
            "best_job": best_job.get("name"),
            "best_job_path": best_job.get("path"),
            "best_job_readiness_score": best_job.get("readiness_score"),
            "best_job_readiness_label": best_job.get("readiness_label"),
            "acceptance_status": acceptance.get("overall_status"),
            "next_action": next_action,
        },
    }


def default_report_path(suffix: str) -> Path:
    return PROJECT_DIR / ("handoff_snapshot." + suffix)


def human_report(snapshot: dict) -> str:
    focus = snapshot.get("handoff_focus", {})
    status = snapshot.get("project_status", {})
    acceptance = snapshot.get("acceptance_gate", {})
    index = snapshot.get("job_index", {})
    git = snapshot.get("git", {})
    lines = [
        "HELIX / SCLAS Handoff Snapshot",
        "==============================",
        "Generated: {0}".format(snapshot.get("generated_at", "-")),
        "Project: {0}".format(snapshot.get("project_dir", "-")),
        "Git: {0} @ {1} -> {2} (ahead={3}, behind={4})".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "Job root: {0}".format(snapshot.get("job_root", "-")),
        "",
        "Focus:",
        "- Best job: {0} ({1}, score={2})".format(
            focus.get("best_job", "-"),
            focus.get("best_job_readiness_label", "-"),
            focus.get("best_job_readiness_score", "-"),
        ),
        "- Best job path: {0}".format(focus.get("best_job_path", "-")),
        "- Acceptance: {0}".format(focus.get("acceptance_status", "-")),
        "- Next action: {0}".format(focus.get("next_action", "-")),
        "",
        "Project status:",
        "- Latest job: {0}".format(status.get("latest_job", "-")),
        "- Latest health: {0}".format(status.get("latest_job_health", "-")),
        "- Latest source/class: {0} / {1}".format(status.get("latest_source", "-"), status.get("latest_curve_class", "-")),
        "- Contact: preload={0}, CPRESS={1}, slip={2}".format(
            status.get("contact_preload_status", "-"),
            status.get("contact_pressure_max", "-"),
            status.get("slip_abs_max", "-"),
        ),
        "",
        "Acceptance gate:",
        "- Overall: {0}".format(acceptance.get("overall_status", "-")),
        "- Latest job: {0}".format(acceptance.get("latest_job", "-")),
        "- Contact: CPRESS={0}, slip={1}".format(
            acceptance.get("contact_pressure_max", "-"),
            acceptance.get("slip_abs_max", "-"),
        ),
        "",
        "Job index:",
        "- Reported: {0}/{1}".format(index.get("reported_count", 0), index.get("total_candidates", 0)),
        "- Health counts: {0}".format(index.get("health_counts", {})),
        "- Readiness counts: {0}".format(index.get("readiness_counts", {})),
    ]
    if snapshot.get("saved_report") or snapshot.get("saved_markdown_report"):
        lines.extend([
            "",
            "Saved reports:",
            "- JSON: {0}".format(snapshot.get("saved_report", "-")),
            "- Markdown: {0}".format(snapshot.get("saved_markdown_report", "-")),
        ])
    return "\n".join(lines)


def markdown_report(snapshot: dict) -> str:
    focus = snapshot.get("handoff_focus", {})
    status = snapshot.get("project_status", {})
    acceptance = snapshot.get("acceptance_gate", {})
    index = snapshot.get("job_index", {})
    git = snapshot.get("git", {})
    return "\n".join([
        "# HELIX / SCLAS Handoff Snapshot",
        "",
        "- Generated: `{0}`".format(snapshot.get("generated_at", "-")),
        "- Project: `{0}`".format(snapshot.get("project_dir", "-")),
        "- Git: `{0}` @ `{1}` -> `{2}` (ahead `{3}`, behind `{4}`)".format(
            git.get("branch", "-"),
            git.get("head", "-"),
            git.get("upstream", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "- Job root: `{0}`".format(snapshot.get("job_root", "-")),
        "",
        "## Focus",
        "",
        "- Best job: `{0}`".format(focus.get("best_job", "-")),
        "- Best job path: `{0}`".format(focus.get("best_job_path", "-")),
        "- Readiness: `{0}` score `{1}`".format(
            focus.get("best_job_readiness_label", "-"),
            focus.get("best_job_readiness_score", "-"),
        ),
        "- Acceptance: `{0}`".format(focus.get("acceptance_status", "-")),
        "- Next action: {0}".format(focus.get("next_action", "-")),
        "",
        "## Project Status",
        "",
        "- Latest job: `{0}`".format(status.get("latest_job", "-")),
        "- Latest health: `{0}`".format(status.get("latest_job_health", "-")),
        "- Latest source/class: `{0}` / `{1}`".format(status.get("latest_source", "-"), status.get("latest_curve_class", "-")),
        "- Contact: preload `{0}`, CPRESS `{1}`, slip `{2}`".format(
            status.get("contact_preload_status", "-"),
            status.get("contact_pressure_max", "-"),
            status.get("slip_abs_max", "-"),
        ),
        "",
        "## Acceptance Gate",
        "",
        "- Overall: `{0}`".format(acceptance.get("overall_status", "-")),
        "- Latest job: `{0}`".format(acceptance.get("latest_job", "-")),
        "- CurveV0 comparison: `{0}`, peak ratio `{1}`".format(
            acceptance.get("curve_v0_comparison_status", "-"),
            acceptance.get("curve_v0_peak_ratio", "-"),
        ),
        "- Contact: CPRESS `{0}`, slip `{1}`".format(
            acceptance.get("contact_pressure_max", "-"),
            acceptance.get("slip_abs_max", "-"),
        ),
        "",
        "## Job Index",
        "",
        "- Reported: `{0}` / `{1}`".format(index.get("reported_count", 0), index.get("total_candidates", 0)),
        "- Health counts: `{0}`".format(index.get("health_counts", {})),
        "- Readiness counts: `{0}`".format(index.get("readiness_counts", {})),
        "",
    ])


def save_report(snapshot: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("json")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(snapshot)
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(snapshot: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_report_path("md")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(snapshot)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Create a compact HELIX/SCLAS handoff snapshot.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of recent jobs in the embedded index.")
    parser.add_argument("--include-self-check", action="store_true", help="Include synthetic self_check job folders.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save handoff_snapshot.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save handoff_snapshot.md.")
    parser.add_argument("--output", help="Custom JSON report output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown report output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        snapshot = build_snapshot(
            Path(args.job_root).expanduser().resolve(),
            limit=args.limit,
            include_self_check=args.include_self_check,
        )
        if args.save_report or args.output:
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            snapshot["saved_report"] = str(save_report(snapshot, output_path))
        if args.save_markdown or args.markdown_output:
            markdown_path = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None
            snapshot["saved_markdown_report"] = str(save_markdown_report(snapshot, markdown_path))
        if args.json:
            print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        else:
            print(human_report(snapshot))
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS handoff snapshot failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
