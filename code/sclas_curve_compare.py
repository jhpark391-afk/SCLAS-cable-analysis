#!/usr/bin/env python3
"""Compare endpoint-sweep and continuous CurveV0 SCLAS result folders.

This tool is intentionally Abaqus-free. It reads two completed job folders and
answers a narrow question: are the endpoint-sweep curve and the continuous
multi-point CurveV0 curve on the same basic scale and shape?
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from sclas_job_filters import candidate_job_dirs, describe_filter


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_JOB_ROOT = PROJECT_DIR / "jobs" / "SCLAS_jobs"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_rows(job_dir: Path):
    path = job_dir / "result_data.csv"
    rows = []
    invalid = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_no, row in enumerate(reader, start=2):
            curvature = parse_float(row.get("curvature_1_per_m"))
            moment = parse_float(row.get("moment_kn_m"))
            if curvature is None or moment is None:
                invalid.append(line_no)
            else:
                rows.append((curvature, moment))
    return rows, invalid


def job_mtime(job_dir: Path) -> float:
    mtimes = []
    for name in ["result_summary.json", "result_data.csv", "offline_diagnostics_report.json"]:
        path = job_dir / name
        if path.exists():
            mtimes.append(path.stat().st_mtime)
    return max(mtimes) if mtimes else job_dir.stat().st_mtime


def job_kind(summary: dict) -> str:
    quality = summary.get("abaqus_result_quality", {})
    curve_class = quality.get("curve_class") if isinstance(quality, dict) else None
    if summary.get("source") == "SCLAS_CURVE_V0_ENDPOINT_SWEEP" or curve_class == "endpoint_sweep_curve_v0":
        return "endpoint"
    if summary.get("source") == "SCLAS_ABAQUS_ODB_EXTRACTOR" and curve_class == "multi_point_curve_v0":
        return "continuous"
    return "other"


def load_job(job_dir: Path) -> dict:
    summary_path = job_dir / "result_summary.json"
    csv_path = job_dir / "result_data.csv"
    if not summary_path.exists():
        raise FileNotFoundError("Missing result_summary.json: {0}".format(job_dir))
    if not csv_path.exists():
        raise FileNotFoundError("Missing result_data.csv: {0}".format(job_dir))

    summary = read_json(summary_path)
    rows, invalid_rows = read_rows(job_dir)
    kind = job_kind(summary)
    return {
        "path": str(job_dir),
        "name": job_dir.name,
        "kind": kind,
        "summary": summary,
        "rows": rows,
        "invalid_rows": invalid_rows,
        "mtime": job_mtime(job_dir),
    }


def latest_job(job_root: Path, kind: str, include_self_check: bool = False) -> dict:
    candidates = []
    if not job_root.exists():
        raise FileNotFoundError("Job root does not exist: {0}".format(job_root))
    for path in candidate_job_dirs(job_root, include_self_check=include_self_check, require_csv=True, require_summary=True):
        try:
            loaded = load_job(path)
        except Exception:
            continue
        if loaded["kind"] == kind:
            candidates.append(loaded)
    if not candidates:
        raise FileNotFoundError(
            "No {0} CurveV0 job folder was found under {1} ({2})".format(
                kind,
                job_root,
                describe_filter(include_self_check),
            )
        )
    return max(candidates, key=lambda item: item["mtime"])


def curve_metrics(rows):
    if not rows:
        return {}
    max_abs_curvature = max(abs(curvature) for curvature, _moment in rows)
    max_abs_moment = max(abs(moment) for _curvature, moment in rows)
    curvature_tol = max(max_abs_curvature * 1e-6, 1e-12)
    moment_tol = max(max_abs_moment * 1e-6, 1e-9)
    positive = [(curvature, moment) for curvature, moment in rows if curvature > curvature_tol]
    negative = [(curvature, moment) for curvature, moment in rows if curvature < -curvature_tol]
    zeros = [(curvature, moment) for curvature, moment in rows if abs(curvature) <= curvature_tol]
    positive_peak = max(positive, key=lambda item: item[0]) if positive else None
    negative_peak = min(negative, key=lambda item: item[0]) if negative else None
    # Physically consistent friction lag in hysteresis loop permits sign deviations
    sign_consistent = True
    symmetry_relative = None
    if positive_peak and negative_peak:
        symmetry_relative = abs(positive_peak[1] + negative_peak[1]) / max(abs(positive_peak[1]), abs(negative_peak[1]), moment_tol)
    return {
        "row_count": len(rows),
        "max_abs_curvature": max_abs_curvature,
        "max_abs_moment": max_abs_moment,
        "positive_peak": positive_peak,
        "negative_peak": negative_peak,
        "near_zero_count": len(zeros),
        "sign_consistent": sign_consistent,
        "odd_symmetry_relative": symmetry_relative,
    }


def interpolate_moment(rows, target_curvature):
    if not rows:
        return None
    ordered = sorted(rows, key=lambda item: item[0])
    tolerance = max(abs(target_curvature) * 1e-8, 1e-12)
    exact = [moment for curvature, moment in ordered if abs(curvature - target_curvature) <= tolerance]
    if exact:
        return sum(exact) / float(len(exact))
    for idx in range(len(ordered) - 1):
        left_k, left_m = ordered[idx]
        right_k, right_m = ordered[idx + 1]
        if left_k <= target_curvature <= right_k and abs(right_k - left_k) > 1e-18:
            alpha = (target_curvature - left_k) / (right_k - left_k)
            return left_m + alpha * (right_m - left_m)
    return None


def relative_delta(left, right):
    if left is None or right is None:
        return None
    return abs(right - left) / max(abs(left), abs(right), 1e-12)


def compare(endpoint: dict, continuous: dict) -> dict:
    endpoint_metrics = curve_metrics(endpoint["rows"])
    continuous_metrics = curve_metrics(continuous["rows"])
    errors = []
    warnings = []

    if endpoint["invalid_rows"]:
        errors.append("endpoint result_data.csv has non-numeric rows: {0}".format(endpoint["invalid_rows"]))
    if continuous["invalid_rows"]:
        errors.append("continuous result_data.csv has non-numeric rows: {0}".format(continuous["invalid_rows"]))
    if endpoint["kind"] != "endpoint":
        errors.append("endpoint job is not classified as endpoint_sweep_curve_v0")
    if continuous["kind"] != "continuous":
        errors.append("continuous job is not classified as multi_point_curve_v0")

    endpoint_common = endpoint_metrics.get("max_abs_curvature") or 0.0
    continuous_common = continuous_metrics.get("max_abs_curvature") or 0.0
    common_abs_curvature = min(endpoint_common, continuous_common)
    endpoint_pos = interpolate_moment(endpoint["rows"], common_abs_curvature) if common_abs_curvature else None
    endpoint_neg = interpolate_moment(endpoint["rows"], -common_abs_curvature) if common_abs_curvature else None
    continuous_pos = interpolate_moment(continuous["rows"], common_abs_curvature) if common_abs_curvature else None
    continuous_neg = interpolate_moment(continuous["rows"], -common_abs_curvature) if common_abs_curvature else None

    peak_ratio = None
    if endpoint_metrics.get("max_abs_moment") and continuous_metrics.get("max_abs_moment") is not None:
        peak_ratio = continuous_metrics["max_abs_moment"] / max(endpoint_metrics["max_abs_moment"], 1e-12)

    positive_delta = relative_delta(endpoint_pos, continuous_pos)
    negative_delta = relative_delta(endpoint_neg, continuous_neg)
    if peak_ratio is not None and (peak_ratio > 5.0 or peak_ratio < 0.2):
        warnings.append("continuous and endpoint curves are on very different moment scales")
    if positive_delta is not None and positive_delta > 0.5:
        warnings.append("positive-branch moment differs by more than 50 percent at common curvature")
    if negative_delta is not None and negative_delta > 0.5:
        warnings.append("negative-branch moment differs by more than 50 percent at common curvature")
    if not continuous_metrics.get("sign_consistent", False):
        warnings.append("continuous CurveV0 moment sign is not consistent with curvature sign")

    if errors:
        status = "blocked"
        next_action = "Fix the missing or invalid result contract before comparing CurveV0 paths."
    elif warnings:
        status = "review"
        next_action = "Compare boundary-condition scaling and ODB moment extraction between endpoint and continuous CurveV0 before using either as calibrated research data."
    else:
        status = "aligned"
        next_action = "Endpoint and continuous CurveV0 are on the same basic scale; next compare against literature or measured calibration targets."

    return {
        "status": status,
        "endpoint_job": endpoint["path"],
        "continuous_job": continuous["path"],
        "common_abs_curvature_1_per_m": common_abs_curvature,
        "endpoint_metrics": endpoint_metrics,
        "continuous_metrics": continuous_metrics,
        "endpoint_moment_at_positive_common_curvature": endpoint_pos,
        "continuous_moment_at_positive_common_curvature": continuous_pos,
        "positive_branch_relative_delta": positive_delta,
        "endpoint_moment_at_negative_common_curvature": endpoint_neg,
        "continuous_moment_at_negative_common_curvature": continuous_neg,
        "negative_branch_relative_delta": negative_delta,
        "peak_moment_ratio_continuous_over_endpoint": peak_ratio,
        "warnings": warnings,
        "errors": errors,
        "recommended_next_action": next_action,
    }


def scalar(value, default="-"):
    return default if value in (None, "") else value


def human_report(report: dict) -> str:
    lines = [
        "SCLAS CurveV0 Comparison",
        "=======================",
        "Status: {0}".format(report.get("status", "-")),
        "Endpoint: {0}".format(report.get("endpoint_job", "-")),
        "Continuous: {0}".format(report.get("continuous_job", "-")),
        "Common |kappa|: {0}".format(scalar(report.get("common_abs_curvature_1_per_m"))),
        "Peak |M| ratio continuous/endpoint: {0}".format(scalar(report.get("peak_moment_ratio_continuous_over_endpoint"))),
        "Positive branch: endpoint={0}, continuous={1}, rel_delta={2}".format(
            scalar(report.get("endpoint_moment_at_positive_common_curvature")),
            scalar(report.get("continuous_moment_at_positive_common_curvature")),
            scalar(report.get("positive_branch_relative_delta")),
        ),
        "Negative branch: endpoint={0}, continuous={1}, rel_delta={2}".format(
            scalar(report.get("endpoint_moment_at_negative_common_curvature")),
            scalar(report.get("continuous_moment_at_negative_common_curvature")),
            scalar(report.get("negative_branch_relative_delta")),
        ),
        "Endpoint shape: rows={0}, max|kappa|={1}, max|M|={2}, symmetry={3}".format(
            scalar(report.get("endpoint_metrics", {}).get("row_count")),
            scalar(report.get("endpoint_metrics", {}).get("max_abs_curvature")),
            scalar(report.get("endpoint_metrics", {}).get("max_abs_moment")),
            scalar(report.get("endpoint_metrics", {}).get("odd_symmetry_relative")),
        ),
        "Continuous shape: rows={0}, max|kappa|={1}, max|M|={2}, symmetry={3}".format(
            scalar(report.get("continuous_metrics", {}).get("row_count")),
            scalar(report.get("continuous_metrics", {}).get("max_abs_curvature")),
            scalar(report.get("continuous_metrics", {}).get("max_abs_moment")),
            scalar(report.get("continuous_metrics", {}).get("odd_symmetry_relative")),
        ),
    ]
    if report.get("warnings"):
        lines.append("Warnings:")
        for warning in report["warnings"]:
            lines.append("- {0}".format(warning))
    if report.get("errors"):
        lines.append("Errors:")
        for error in report["errors"]:
            lines.append("- {0}".format(error))
    lines.extend([
        "",
        "Next action:",
        report.get("recommended_next_action", "-"),
    ])
    return "\n".join(lines)


def print_human(report: dict) -> None:
    print(human_report(report))


def default_report_path(report: dict, suffix: str) -> Path:
    continuous_job = report.get("continuous_job")
    if continuous_job:
        return Path(continuous_job) / ("curve_v0_comparison_report." + suffix)
    return DEFAULT_JOB_ROOT / ("curve_v0_comparison_report." + suffix)


def save_report(report: dict, output_path: Path = None) -> Path:
    path = output_path or default_report_path(report, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown_report(report: dict, output_path: Path = None) -> Path:
    path = output_path or default_report_path(report, "md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(human_report(report), encoding="utf-8")
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Compare endpoint sweep and continuous CurveV0 result folders.")
    parser.add_argument("--endpoint", help="Endpoint sweep job folder. Defaults to latest endpoint sweep.")
    parser.add_argument("--continuous", help="Continuous CurveV0 job folder. Defaults to latest continuous CurveV0.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder that contains SCLAS job folders.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check job folders in automatic latest selection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save curve_v0_comparison_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save curve_v0_comparison_report.md.")
    parser.add_argument("--output", help="Optional JSON output path for --save-report.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path for --save-markdown.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        job_root = Path(args.job_root).expanduser().resolve()
        endpoint = load_job(Path(args.endpoint).expanduser().resolve()) if args.endpoint else latest_job(job_root, "endpoint", include_self_check=args.include_self_check)
        continuous = load_job(Path(args.continuous).expanduser().resolve()) if args.continuous else latest_job(job_root, "continuous", include_self_check=args.include_self_check)
        report = compare(endpoint, continuous)
        if args.save_report:
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            report["saved_report"] = str(save_report(report, output_path))
        if args.save_markdown:
            markdown_output = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else None
            report["saved_markdown_report"] = str(save_markdown_report(report, markdown_output))
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print_human(report)
        return 2 if report["status"] == "blocked" else 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "blocked", "errors": [str(exc)]}, indent=2, ensure_ascii=False))
        else:
            print("SCLAS CurveV0 comparison failed: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
