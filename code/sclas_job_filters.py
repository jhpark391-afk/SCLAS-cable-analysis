#!/usr/bin/env python3
"""Shared SCLAS job-folder filtering helpers."""

from pathlib import Path
from typing import List


SELF_CHECK_PREFIXES = ("self_check",)


def is_self_check_job(path: Path) -> bool:
    return Path(path).name.startswith(SELF_CHECK_PREFIXES)


def has_job_artifact(path: Path, require_csv: bool = False, require_summary: bool = False) -> bool:
    result_csv = path / "result_data.csv"
    result_summary = path / "result_summary.json"
    if require_csv and not result_csv.exists():
        return False
    if require_summary and not result_summary.exists():
        return False
    return result_csv.exists() or result_summary.exists()


def candidate_job_dirs(
    job_root: Path,
    include_self_check: bool = False,
    require_csv: bool = False,
    require_summary: bool = False,
) -> List[Path]:
    candidates = []
    for path in job_root.iterdir():
        if not path.is_dir():
            continue
        if not include_self_check and is_self_check_job(path):
            continue
        if has_job_artifact(path, require_csv=require_csv, require_summary=require_summary):
            candidates.append(path)
    return candidates


def describe_filter(include_self_check: bool) -> str:
    return "including self_check jobs" if include_self_check else "excluding self_check jobs"
