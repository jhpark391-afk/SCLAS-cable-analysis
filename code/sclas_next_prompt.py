#!/usr/bin/env python3
"""Generate the next Codex-session prompt from the current handoff snapshot."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from sclas_handoff_snapshot import PROJECT_DIR, build_snapshot
from sclas_job_summary import DEFAULT_JOB_ROOT


def default_prompt_path() -> Path:
    return PROJECT_DIR / "NEXT_CODEX_PROMPT.md"


def prompt_text(snapshot: dict) -> str:
    focus = snapshot.get("handoff_focus", {})
    status = snapshot.get("project_status", {})
    acceptance = snapshot.get("acceptance_gate", {})
    index = snapshot.get("job_index", {})
    git = snapshot.get("git", {})
    return "\n".join([
        "# Prompt for the next Codex session",
        "",
        "You are continuing the HELIX / SCLAS submarine cable analysis project.",
        "",
        "First, run these commands:",
        "",
        "```bash",
        "git pull",
        "git status --short --branch",
        "python code/sclas_handoff_snapshot.py --save-report --save-markdown",
        "python code/sclas_acceptance_gate.py --save-report --save-markdown",
        "python code/sclas_self_check.py",
        "```",
        "",
        "Preferred one-command validation after the initial pull:",
        "",
        "- Mac/Linux: `./run_validation_suite.sh`",
        "- Windows: `run_validation_suite.bat`",
        "",
        "Then read these files before editing:",
        "",
        "- `CURRENT_HANDOFF.md`",
        "- `README_SCLAS_WORKFLOW.md`",
        "- `handoff_snapshot.md`",
        "",
        "Current snapshot summary:",
        "",
        "- Git branch/head: `{0}` @ `{1}`".format(git.get("branch", "-"), git.get("head", "-")),
        "- Git sync: `{0}`, dirty `{1}`, upstream `{2}`, ahead `{3}`, behind `{4}`".format(
            git.get("sync_status", "-"),
            git.get("dirty", "-"),
            git.get("upstream", "-"),
            git.get("ahead", "-"),
            git.get("behind", "-"),
        ),
        "- Latest job: `{0}`".format(status.get("latest_job", "-")),
        "- Latest health/source/class: `{0}` / `{1}` / `{2}`".format(
            status.get("latest_job_health", "-"),
            status.get("latest_source", "-"),
            status.get("latest_curve_class", "-"),
        ),
        "- Best job: `{0}`".format(focus.get("best_job", "-")),
        "- Best job path: `{0}`".format(focus.get("best_job_path", "-")),
        "- Best job readiness: `{0}` score `{1}`".format(
            focus.get("best_job_readiness_label", "-"),
            focus.get("best_job_readiness_score", "-"),
        ),
        "- Job index reported: `{0}` / `{1}`".format(index.get("reported_count", 0), index.get("total_candidates", 0)),
        "- Contact state: preload `{0}`, CPRESS `{1}`, slip `{2}`".format(
            status.get("contact_preload_status", "-"),
            status.get("contact_pressure_max", "-"),
            status.get("slip_abs_max", "-"),
        ),
        "- Acceptance gate: `{0}` for `{1}`".format(
            acceptance.get("overall_status", "-"),
            acceptance.get("latest_job", "-"),
        ),
        "",
        "Immediate next action:",
        "",
        focus.get("next_action", "-"),
        "",
        "Operating rules:",
        "",
        "- Do not overwrite unrelated local work.",
        "- If `code/sclas_remote_gui.py` changes, sync it to `code/SCLAS_test/sclas_remote_gui.py` and `code/sclas_remote_gui_final_code.txt`.",
        "- Keep generated `jobs/`, `handoff_snapshot.*`, and `NEXT_CODEX_PROMPT.md` out of commits.",
        "- On Mac/home Codex, focus on GUI, diagnostics, documentation, validation automation, and GitHub integration.",
        "- On the remote Abaqus PC, focus on contact preload/closure, ODB field extraction, CPRESS/slip validation, endpoint sweep, and continuous CurveV0.",
        "- After changes, run the relevant py_compile command and `python code/sclas_self_check.py` before committing.",
        "",
    ])


def save_prompt(text: str, output_path: Optional[Path] = None) -> Path:
    path = output_path or default_prompt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate a next-session Codex prompt from the SCLAS handoff snapshot.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of recent jobs in the embedded snapshot.")
    parser.add_argument("--include-self-check", action="store_true", help="Include synthetic self_check job folders.")
    parser.add_argument("--save", action="store_true", help="Save NEXT_CODEX_PROMPT.md.")
    parser.add_argument("--output", help="Custom prompt output path.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        snapshot = build_snapshot(
            Path(args.job_root).expanduser().resolve(),
            limit=args.limit,
            include_self_check=args.include_self_check,
        )
        text = prompt_text(snapshot)
        if args.save or args.output:
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            path = save_prompt(text, output_path)
            print(text)
            print("Saved prompt: {0}".format(path))
        else:
            print(text)
        return 0
    except Exception as exc:
        print("SCLAS next prompt failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
