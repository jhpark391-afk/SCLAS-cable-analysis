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
    "THE PROGRAM HAS DISCOVERED",
    "Abaqus Error",
    "Abaqus/Analysis exited",
    "exited with errors",
    "UNKNOWN",
    "INVALID",
    "MISPLACED",
]

NOTABLE_LOG_PATTERNS = [
    "WARNING",
    "ZERO PIVOT",
    "OVERCONSTRAINT",
    "TOO MANY",
    "EXCESSIVE",
    "DISTORTION",
    "COUPLING",
    "KINEMATIC",
    "REF NODE",
]

B31_BEAM_WARNING_SETS = ["WarnBeamCurvature1", "WarnBeamTwist"]


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


def parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_int_like(value, default=0):
    parsed = parse_float(value)
    if parsed is None:
        return default
    return int(parsed)


def nondecreasing(values, tolerance=1e-12):
    return all(values[idx] <= values[idx + 1] + tolerance for idx in range(len(values) - 1))


def close_enough(left, right, tolerance=1e-9):
    return abs(left - right) <= max(abs(left), abs(right), 1.0) * tolerance


def read_numeric_csv_rows(path: Path):
    numeric_rows = []
    invalid_rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            curvature = parse_float(row.get("curvature_1_per_m"))
            moment = parse_float(row.get("moment_kn_m"))
            if curvature is None or moment is None:
                invalid_rows.append(idx)
            else:
                numeric_rows.append((curvature, moment))
    return numeric_rows, invalid_rows


def scan_solver_log_keywords(job_dir: Path):
    log_files = []
    for pattern in ["*.dat", "*.msg", "*.sta", "solver_stdout.txt", "abaqus_stdout.txt"]:
        log_files.extend(sorted(job_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True))
    seen = set()
    unique_logs = []
    for path in log_files:
        if path not in seen:
            unique_logs.append(path)
            seen.add(path)

    combined_text = "\n".join(read_text(path) for path in unique_logs)
    completed = bool(re.search(r"Abaqus JOB .* COMPLETED|COMPLETED SUCCESSFULLY", combined_text, re.IGNORECASE))
    failed = bool(re.search(r"Abaqus Error|Abaqus/Analysis exited with errors|exited with errors", combined_text, re.IGNORECASE))

    blocking_pattern = re.compile("|".join(re.escape(item) for item in BLOCKING_ERROR_PATTERNS), re.IGNORECASE)
    notable_pattern = re.compile("|".join(re.escape(item) for item in NOTABLE_LOG_PATTERNS), re.IGNORECASE)

    blocking = []
    notable = []
    actual_warnings = []
    notes = []
    for path in unique_logs:
        lines = read_text(path).splitlines()
        for idx, line in enumerate(lines):
            if blocking_pattern.search(line):
                blocking.append({
                    "file": path.name,
                    "line": idx + 1,
                    "text": line.strip(),
                })
            elif notable_pattern.search(line):
                item = {
                    "file": path.name,
                    "line": idx + 1,
                    "text": line.strip(),
                }
                notable.append(item)
                if is_actual_warning_line(line):
                    actual_warnings.append(item)
                else:
                    notes.append(item)

    warning_categories = {}
    for item in actual_warnings:
        category = classify_solver_warning(item.get("text", ""))
        warning_categories[category] = warning_categories.get(category, 0) + 1

    note_categories = {}
    for item in notes:
        category = classify_solver_warning(item.get("text", ""))
        note_categories[category] = note_categories.get(category, 0) + 1

    return {
        "files": [path.name for path in unique_logs],
        "completed": completed,
        "failed": failed,
        "blocking_matches": blocking,
        "notable_matches": notable,
        "actual_warning_matches": actual_warnings,
        "note_matches": notes,
        "warning_categories": warning_categories,
        "note_categories": note_categories,
    }


def is_actual_warning_line(text):
    upper = str(text).strip().upper()
    return upper.startswith("***WARNING") or upper.startswith("WARNING:") or "ABAQUS WARNING" in upper


def classify_solver_warning(text):
    upper = str(text).upper()
    if "SURFACE TO SURFACE CONTACT APPROACH" in upper or "NODE TO SURFACE APPROACH" in upper:
        return "beam_contact_surface_to_node_fallback"
    if "BOTH CONTACT PAIRS AND GENERAL CONTACT" in upper:
        return "contact_pair_general_contact_overlap"
    if "STRICTLY-ENFORCED HARD CONTACT" in upper or "PENALTY-ENFORCED CONTACT" in upper:
        return "contact_property_penalty_switch"
    if "UNCONNECTED REGIONS" in upper:
        return "unconnected_regions"
    if "NUMERICAL SINGULARITY" in upper or "ZERO PIVOT" in upper:
        return "numerical_singularity"
    if "DISTORT" in upper:
        return "distorted_elements"
    if "BEAM" in upper and "CURVATURE" in upper:
        return "beam_curvature"
    if "BEAM" in upper and "TWIST" in upper:
        return "beam_twist"
    if "CUT-BACK" in upper or "TOO MANY" in upper or "EXCESSIVE" in upper:
        return "increment_cutback_or_excessive_reporting"
    if "OVERCONSTRAINT" in upper:
        return "overconstraint_check"
    if "COUPLING" in upper or "KINEMATIC" in upper or "REF NODE" in upper:
        return "coupling_or_reference_node_note"
    if "WARNING" in upper:
        return "other_warning"
    return "other_notable"


def b31_beam_warning_details(job_dir: Path):
    details = {
        "checked": False,
        "files": [],
        "warning_sets": {},
        "total_warning_sets": 0,
        "actual_warning_categories": {},
        "first_warning_context": None,
        "recommended_probe": "If these remain after annular mesh cleanup, isolate a minimal B31 helix and sweep segment count, beam orientation, lay angle, and helix radius.",
    }
    log_files = []
    for pattern in ["*.dat", "*.msg", "*.sta", "solver_stdout.txt"]:
        log_files.extend(sorted(job_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True))
    seen = set()
    unique_logs = []
    for path in log_files:
        if path not in seen:
            unique_logs.append(path)
            seen.add(path)
    if not unique_logs:
        return details

    details["checked"] = True
    details["files"] = [path.name for path in unique_logs]
    for path in unique_logs:
        lines = read_text(path).splitlines()
        for idx, line in enumerate(lines):
            upper = line.upper()
            for warning_set in B31_BEAM_WARNING_SETS:
                if warning_set.upper() in upper:
                    details["warning_sets"][warning_set] = details["warning_sets"].get(warning_set, 0) + 1
                    details["total_warning_sets"] += 1
                    if details["first_warning_context"] is None:
                        details["first_warning_context"] = {
                            "file": path.name,
                            "line": idx + 1,
                            "context": context_block(lines, idx),
                        }
            if is_actual_warning_line(line):
                category = classify_solver_warning(line)
                if category in {"beam_curvature", "beam_twist"}:
                    details["actual_warning_categories"][category] = details["actual_warning_categories"].get(category, 0) + 1
    return details


def merge_counts(target, source):
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def update_minimum(target, key, value):
    if value is None:
        return
    current = target.get(key)
    if current is None or value < current:
        target[key] = value


def mesh_quality_warning_details(job_dir: Path):
    details = {
        "checked": False,
        "files": [],
        "warning_sets": {},
        "distorted_reported_element_count": 0,
        "distorted_table_parts": {},
        "distorted_table_row_count": 0,
        "distorted_table_min_angle": None,
        "distorted_sample_parts": {},
        "distorted_sample_min_angle": None,
        "distorted_sample_count": 0,
        "distorted_sample_limit": 500,
    }
    dat_files = sorted(job_dir.glob("*.dat"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dat_files:
        return details

    details["checked"] = True
    details["files"] = [path.name for path in dat_files]
    distorted_count_pattern = re.compile(r"^\s*\*\*\*WARNING:\s+(\d+)\s+elements are distorted", re.IGNORECASE)
    distorted_pattern = re.compile(r"^\s+([A-Z][A-Z0-9_]+)_\d+\.\d+\s+([-+0-9.Ee]+)")
    for path in dat_files:
        lines = read_text(path).splitlines()
        for line in lines:
            count_match = distorted_count_pattern.search(line)
            if count_match:
                details["distorted_reported_element_count"] += int(count_match.group(1))
            for warning_set in ["WarnElemDistorted", "WarnBeamCurvature1", "WarnBeamTwist"]:
                if warning_set.upper() in line.upper():
                    details["warning_sets"][warning_set] = details["warning_sets"].get(warning_set, 0) + 1

        in_distorted_table = False
        rows_seen = 0
        for line in lines:
            if "Distorted isoparametric elements" in line:
                in_distorted_table = True
                rows_seen = 0
                continue
            if not in_distorted_table:
                continue
            match = distorted_pattern.search(line)
            if not match:
                if rows_seen > 0 and not line.strip():
                    in_distorted_table = False
                continue
            part_name = match.group(1)
            details["distorted_table_parts"][part_name] = details["distorted_table_parts"].get(part_name, 0) + 1
            angle = parse_float(match.group(2))
            update_minimum(details, "distorted_table_min_angle", angle)
            details["distorted_table_row_count"] += 1
            if details["distorted_sample_count"] < details["distorted_sample_limit"]:
                details["distorted_sample_parts"][part_name] = details["distorted_sample_parts"].get(part_name, 0) + 1
                update_minimum(details, "distorted_sample_min_angle", angle)
                details["distorted_sample_count"] += 1
            rows_seen += 1
    return details


def inspect_endpoint_sweep_shape(job_dir: Path, report: dict, summary_data: dict) -> None:
    if summary_data.get("source") != "SCLAS_CURVE_V0_ENDPOINT_SWEEP":
        return

    path = job_dir / "result_data.csv"
    section = {
        "checked": path.exists(),
    }
    report["endpoint_sweep_shape"] = section
    if not path.exists():
        return

    numeric_rows, invalid_rows = read_numeric_csv_rows(path)

    section["numeric_rows"] = len(numeric_rows)
    section["invalid_numeric_rows"] = invalid_rows
    section["numeric_format_valid"] = not invalid_rows
    if invalid_rows:
        add_issue(report, "error", "Endpoint sweep result_data.csv contains non-numeric rows", invalid_rows)
        return
    if not numeric_rows:
        return

    curvatures = [row[0] for row in numeric_rows]
    moments = [row[1] for row in numeric_rows]
    max_abs_moment = max([abs(value) for value in moments] + [1.0])

    section["curvature_monotonic_non_decreasing"] = nondecreasing(curvatures)
    section["moment_monotonic_non_decreasing"] = nondecreasing(moments, max_abs_moment * 1e-9)
    section["zero_endpoint_present"] = any(abs(c) <= 1e-12 and abs(m) <= max_abs_moment * 1e-9 for c, m in numeric_rows)

    positive = [(c, m) for c, m in numeric_rows if c > 1e-12]
    negative = [(c, m) for c, m in numeric_rows if c < -1e-12]
    symmetry_errors = []
    for pos_c, pos_m in positive:
        candidates = [
            (neg_c, neg_m)
            for neg_c, neg_m in negative
            if abs(abs(neg_c) - pos_c) <= max(abs(pos_c) * 1e-6, 1e-12)
        ]
        if not candidates:
            continue
        neg_c, neg_m = min(candidates, key=lambda item: abs(abs(item[0]) - pos_c))
        abs_error = abs(pos_m + neg_m)
        rel_error = abs_error / max(abs(pos_m), abs(neg_m), 1e-12)
        symmetry_errors.append({
            "positive_curvature": pos_c,
            "negative_curvature": neg_c,
            "moment_sum_abs": abs_error,
            "moment_sum_relative": rel_error,
        })
    max_symmetry_rel = max([item["moment_sum_relative"] for item in symmetry_errors] + [0.0])
    section["odd_symmetry_pairs"] = len(symmetry_errors)
    section["odd_symmetry_max_relative_moment_sum"] = max_symmetry_rel
    section["odd_symmetry_pass"] = bool(symmetry_errors) and max_symmetry_rel <= 0.05

    child_jobs = summary_data.get("child_jobs", [])
    factor_scales = []
    child_numeric_invalid = []
    if isinstance(child_jobs, list):
        for idx, child in enumerate(child_jobs):
            if not isinstance(child, dict):
                continue
            factor = parse_float(child.get("factor"))
            curvature = parse_float(child.get("curvature_1_per_m"))
            moment = parse_float(child.get("moment_kn_m"))
            if curvature is None or moment is None:
                child_numeric_invalid.append(child.get("job", "child_{0}".format(idx)))
            if factor is not None and curvature is not None and abs(factor) > 1e-12:
                factor_scales.append(curvature / factor)

    section["child_endpoint_numeric_format_valid"] = not child_numeric_invalid
    section["child_endpoint_numeric_invalid"] = child_numeric_invalid
    if child_numeric_invalid:
        add_issue(report, "error", "Endpoint sweep child summary has non-numeric endpoint rows", child_numeric_invalid)

    if factor_scales:
        mean_scale = sum(factor_scales) / float(len(factor_scales))
        deviations = [
            abs(scale - mean_scale) / max(abs(mean_scale), 1e-12)
            for scale in factor_scales
        ]
        section["factor_curvature_scale"] = mean_scale
        section["factor_curvature_scale_max_relative_deviation"] = max(deviations)
        section["factor_curvature_scale_consistent"] = max(deviations) <= 0.01 and mean_scale > 0

    if not section["curvature_monotonic_non_decreasing"]:
        add_issue(report, "warning", "Endpoint sweep curvature values are not monotonic")
    if not section["moment_monotonic_non_decreasing"]:
        add_issue(report, "warning", "Endpoint sweep moment values are not monotonic with curvature")
    if not section["zero_endpoint_present"]:
        add_issue(report, "warning", "Endpoint sweep does not include a near-zero endpoint")
    if not section["odd_symmetry_pass"]:
        add_issue(report, "warning", "Endpoint sweep failed the basic odd-symmetry check", max_symmetry_rel)
    if factor_scales and not section.get("factor_curvature_scale_consistent"):
        add_issue(report, "warning", "Endpoint sweep factor-to-curvature scale is inconsistent", section.get("factor_curvature_scale_max_relative_deviation"))

    section["shape_checks_passed"] = (
        section["numeric_format_valid"]
        and section["curvature_monotonic_non_decreasing"]
        and section["moment_monotonic_non_decreasing"]
        and section["zero_endpoint_present"]
        and section["odd_symmetry_pass"]
        and section.get("factor_curvature_scale_consistent", True)
        and section["child_endpoint_numeric_format_valid"]
    )


def inspect_endpoint_sweep_children(job_dir: Path, report: dict, summary_data: dict) -> None:
    if summary_data.get("source") != "SCLAS_CURVE_V0_ENDPOINT_SWEEP":
        return

    child_jobs = summary_data.get("child_jobs", [])
    section = {
        "checked": True,
        "child_count": len(child_jobs) if isinstance(child_jobs, list) else 0,
        "children": [],
        "all_children_deep_validated": True,
        "blocking_log_hits": 0,
        "notable_log_hits": 0,
        "actual_warning_log_hits": 0,
        "note_log_hits": 0,
        "warning_categories": {},
        "note_categories": {},
        "mesh_quality_warning_details": {
            "warning_sets": {},
            "distorted_reported_element_count": 0,
            "distorted_table_parts": {},
            "distorted_table_row_count": 0,
            "distorted_table_min_angle": None,
            "distorted_sample_parts": {},
            "distorted_sample_count": 0,
            "distorted_sample_min_angle": None,
        },
        "b31_beam_warning_details": {
            "warning_sets": {},
            "total_warning_sets": 0,
            "actual_warning_categories": {},
            "first_warning_context": None,
            "recommended_probe": "If these remain after annular mesh cleanup, isolate a minimal B31 helix and sweep segment count, beam orientation, lay angle, and helix radius.",
        },
    }
    report["endpoint_sweep_children"] = section
    if not isinstance(child_jobs, list):
        add_issue(report, "error", "Endpoint sweep child_jobs is not a list")
        section["all_children_deep_validated"] = False
        return

    for idx, child in enumerate(child_jobs):
        if not isinstance(child, dict):
            add_issue(report, "error", "Endpoint sweep child record is not an object", idx)
            section["all_children_deep_validated"] = False
            continue

        child_name = child.get("job", "child_{0}".format(idx))
        raw_path = child.get("path")
        child_path = Path(raw_path) if raw_path else (job_dir.parent / child_name)
        child_detail = {
            "job": child_name,
            "path": str(child_path),
            "exists": child_path.exists(),
        }
        section["children"].append(child_detail)
        if not child_path.exists() or not child_path.is_dir():
            add_issue(report, "error", "Endpoint sweep child job folder is missing", child_detail)
            section["all_children_deep_validated"] = False
            continue

        child_summary_path = child_path / "result_summary.json"
        odb_summary_path = child_path / "odb_extraction_summary.json"
        child_csv_path = child_path / "result_data.csv"
        child_detail["result_summary_exists"] = child_summary_path.exists()
        child_detail["odb_extraction_summary_exists"] = odb_summary_path.exists()
        child_detail["result_csv_exists"] = child_csv_path.exists()

        child_summary = {}
        odb_summary = {}
        try:
            child_summary = load_json(child_summary_path)
        except Exception as exc:
            add_issue(report, "error", "Could not parse child result_summary.json", {
                "child": child_name,
                "error": str(exc),
            })
            section["all_children_deep_validated"] = False
        try:
            odb_summary = load_json(odb_summary_path)
        except Exception as exc:
            add_issue(report, "error", "Could not parse child odb_extraction_summary.json", {
                "child": child_name,
                "error": str(exc),
            })
            section["all_children_deep_validated"] = False

        child_odb = child_summary.get("odb_extraction", {}) if isinstance(child_summary, dict) else {}
        child_detail["source"] = child_summary.get("source") if isinstance(child_summary, dict) else None
        child_detail["status"] = child_summary.get("status") if isinstance(child_summary, dict) else None
        child_detail["odb_status"] = child_odb.get("status") or odb_summary.get("status")
        child_detail["odb_rows_written"] = child_odb.get("rows_written") or odb_summary.get("rows_written")

        if child_detail["source"] != "SCLAS_ABAQUS_ODB_EXTRACTOR":
            add_issue(report, "error", "Endpoint sweep child source is not ODB extractor", child_detail)
            section["all_children_deep_validated"] = False
        if child_detail["status"] != "completed":
            add_issue(report, "error", "Endpoint sweep child summary status is not completed", child_detail)
            section["all_children_deep_validated"] = False
        if child_detail["odb_status"] != "extracted":
            add_issue(report, "error", "Endpoint sweep child ODB extraction did not succeed", child_detail)
            section["all_children_deep_validated"] = False
        if parse_int_like(child_detail["odb_rows_written"]) < 2:
            add_issue(report, "error", "Endpoint sweep child wrote too few ODB rows", child_detail)
            section["all_children_deep_validated"] = False

        if child_csv_path.exists():
            numeric_rows, invalid_rows = read_numeric_csv_rows(child_csv_path)
            child_detail["csv_rows"] = len(numeric_rows)
            child_detail["invalid_numeric_rows"] = invalid_rows
            if invalid_rows or not numeric_rows:
                add_issue(report, "error", "Endpoint sweep child result_data.csv has invalid numeric rows", child_detail)
                section["all_children_deep_validated"] = False
            else:
                last_curvature, last_moment = numeric_rows[-1]
                child_detail["last_curvature_1_per_m"] = last_curvature
                child_detail["last_moment_kn_m"] = last_moment
                parent_curvature = parse_float(child.get("curvature_1_per_m"))
                parent_moment = parse_float(child.get("moment_kn_m"))
                if parent_curvature is not None and not close_enough(parent_curvature, last_curvature):
                    add_issue(report, "error", "Endpoint sweep child curvature does not match actual last CSV row", child_detail)
                    section["all_children_deep_validated"] = False
                if parent_moment is not None and not close_enough(parent_moment, last_moment):
                    add_issue(report, "error", "Endpoint sweep child moment does not match actual last CSV row", child_detail)
                    section["all_children_deep_validated"] = False
        else:
            add_issue(report, "error", "Endpoint sweep child result_data.csv is missing", child_detail)
            section["all_children_deep_validated"] = False

        log_scan = scan_solver_log_keywords(child_path)
        child_detail["solver_completed"] = log_scan["completed"]
        child_detail["solver_failed"] = log_scan["failed"]
        child_detail["blocking_log_hits"] = len(log_scan["blocking_matches"])
        child_detail["notable_log_hits"] = len(log_scan["notable_matches"])
        child_detail["actual_warning_log_hits"] = len(log_scan.get("actual_warning_matches", []))
        child_detail["note_log_hits"] = len(log_scan.get("note_matches", []))
        child_detail["warning_categories"] = log_scan.get("warning_categories", {})
        child_detail["note_categories"] = log_scan.get("note_categories", {})
        child_detail["mesh_quality_warning_details"] = mesh_quality_warning_details(child_path)
        child_detail["b31_beam_warning_details"] = b31_beam_warning_details(child_path)
        if log_scan["blocking_matches"]:
            child_detail["first_blocking_log_hit"] = log_scan["blocking_matches"][0]
        section["blocking_log_hits"] += child_detail["blocking_log_hits"]
        section["notable_log_hits"] += child_detail["notable_log_hits"]
        section["actual_warning_log_hits"] += child_detail["actual_warning_log_hits"]
        section["note_log_hits"] += child_detail["note_log_hits"]
        merge_counts(section["warning_categories"], child_detail["warning_categories"])
        merge_counts(section["note_categories"], child_detail["note_categories"])
        child_mesh_quality = child_detail["mesh_quality_warning_details"]
        aggregate_mesh_quality = section["mesh_quality_warning_details"]
        merge_counts(aggregate_mesh_quality["warning_sets"], child_mesh_quality.get("warning_sets", {}))
        aggregate_mesh_quality["distorted_reported_element_count"] += child_mesh_quality.get("distorted_reported_element_count", 0)
        merge_counts(aggregate_mesh_quality["distorted_table_parts"], child_mesh_quality.get("distorted_table_parts", {}))
        aggregate_mesh_quality["distorted_table_row_count"] += child_mesh_quality.get("distorted_table_row_count", 0)
        update_minimum(
            aggregate_mesh_quality,
            "distorted_table_min_angle",
            child_mesh_quality.get("distorted_table_min_angle"),
        )
        merge_counts(aggregate_mesh_quality["distorted_sample_parts"], child_mesh_quality.get("distorted_sample_parts", {}))
        aggregate_mesh_quality["distorted_sample_count"] += child_mesh_quality.get("distorted_sample_count", 0)
        update_minimum(
            aggregate_mesh_quality,
            "distorted_sample_min_angle",
            child_mesh_quality.get("distorted_sample_min_angle"),
        )
        child_b31 = child_detail["b31_beam_warning_details"]
        aggregate_b31 = section["b31_beam_warning_details"]
        merge_counts(aggregate_b31["warning_sets"], child_b31.get("warning_sets", {}))
        aggregate_b31["total_warning_sets"] += child_b31.get("total_warning_sets", 0)
        merge_counts(aggregate_b31["actual_warning_categories"], child_b31.get("actual_warning_categories", {}))
        if aggregate_b31["first_warning_context"] is None and child_b31.get("first_warning_context"):
            aggregate_b31["first_warning_context"] = child_b31.get("first_warning_context")

        if log_scan["failed"] or log_scan["blocking_matches"]:
            add_issue(report, "error", "Endpoint sweep child solver logs contain a blocking failure", child_detail)
            section["all_children_deep_validated"] = False
        elif not log_scan["completed"]:
            add_issue(report, "warning", "Endpoint sweep child solver completion was not confirmed in logs", child_detail)
            section["all_children_deep_validated"] = False


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
    section["num_points"] = data.get("num_points")
    section["rows_written"] = data.get("rows_written")
    section["mesh_status"] = data.get("mesh_status", {}).get("status") if isinstance(data.get("mesh_status"), dict) else data.get("mesh_status")
    section["enabled_assessments"] = data.get("enabled_assessments", [])
    odb_extraction = data.get("odb_extraction", {})
    if isinstance(odb_extraction, dict) and odb_extraction:
        section["odb_extraction_status"] = odb_extraction.get("status")
        section["odb_rows_written"] = odb_extraction.get("rows_written")
    quality = data.get("abaqus_result_quality", {})
    if isinstance(quality, dict) and quality:
        section["abaqus_curve_class"] = quality.get("curve_class")
        section["abaqus_is_research_curve"] = quality.get("is_research_curve")
    endpoint_validation = data.get("endpoint_sweep_validation", {})
    if isinstance(endpoint_validation, dict) and endpoint_validation:
        section["endpoint_sweep_validated"] = endpoint_validation.get("all_child_jobs_validated")
        section["endpoint_sweep_rule"] = endpoint_validation.get("aggregation_rule")
    child_jobs = data.get("child_jobs", [])
    if isinstance(child_jobs, list):
        section["child_job_count"] = len(child_jobs)
        invalid_children = [
            item.get("job", f"child_{idx}")
            for idx, item in enumerate(child_jobs)
            if isinstance(item, dict)
            and (
                item.get("source") != "SCLAS_ABAQUS_ODB_EXTRACTOR"
                or item.get("odb_status") != "extracted"
            )
        ]
        if invalid_children:
            add_issue(report, "error", "Endpoint sweep contains child jobs without ODB-extracted results", invalid_children)
    if data.get("source") == "SCLAS_CURVE_V0_ENDPOINT_SWEEP":
        rows_written = int(data.get("rows_written") or 0)
        if rows_written < 5:
            add_issue(report, "warning", "Endpoint sweep has fewer than five aggregated rows", rows_written)
        csv_rows = report.get("result_data_csv", {}).get("data_rows")
        if csv_rows is not None and rows_written != csv_rows:
            add_issue(report, "warning", "Endpoint sweep rows_written does not match result_data.csv rows", {
                "rows_written": rows_written,
                "csv_rows": csv_rows,
            })
        inspect_endpoint_sweep_shape(job_dir, report, data)
        inspect_endpoint_sweep_children(job_dir, report, data)
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

    section = {
        "files": [path.name for path in unique_logs],
        "matches": [],
        "completed": False,
        "failed": False,
        "warning_categories": {},
        "note_categories": {},
    }
    report["solver_logs"] = section
    if not unique_logs:
        add_issue(report, "info", "No Abaqus solver log files found")
        return

    combined_text = "\n".join(read_text(path) for path in unique_logs)
    section["completed"] = bool(re.search(r"Abaqus JOB .* COMPLETED|COMPLETED SUCCESSFULLY", combined_text, re.IGNORECASE))
    section["failed"] = bool(re.search(r"Abaqus Error|Abaqus/Analysis exited with errors|exited with errors", combined_text, re.IGNORECASE))
    keyword_scan = scan_solver_log_keywords(job_dir)
    section["blocking_match_count"] = len(keyword_scan.get("blocking_matches", []))
    section["notable_match_count"] = len(keyword_scan.get("notable_matches", []))
    section["actual_warning_match_count"] = len(keyword_scan.get("actual_warning_matches", []))
    section["note_match_count"] = len(keyword_scan.get("note_matches", []))
    section["warning_categories"] = keyword_scan.get("warning_categories", {})
    section["note_categories"] = keyword_scan.get("note_categories", {})
    section["mesh_quality_warning_details"] = mesh_quality_warning_details(job_dir)
    section["b31_beam_warning_details"] = b31_beam_warning_details(job_dir)

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
        section["match_priority"] = "notable_after_completion" if section["completed"] else "notable"
        section["matches"] = collect_matches(NOTABLE_LOG_PATTERNS, 40)
    if section["failed"]:
        add_issue(report, "error", "Abaqus solver exited with errors")
    elif section["matches"] and not section["completed"]:
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
    summary = report.get("result_summary_json", {})
    sweep_shape = report.get("endpoint_sweep_shape", {})
    sweep_children = report.get("endpoint_sweep_children", {})
    sweep_b31 = sweep_children.get("b31_beam_warning_details", {}) if isinstance(sweep_children, dict) else {}
    solver_b31 = logs.get("b31_beam_warning_details", {}) if isinstance(logs, dict) else {}
    b31_warning_count = int(sweep_b31.get("total_warning_sets") or solver_b31.get("total_warning_sets") or 0)
    log_match_text = "\n".join(
        "{0}\n{1}".format(item.get("text", ""), item.get("context", ""))
        for item in logs.get("matches", [])
        if isinstance(item, dict)
    ).upper()

    if counts["error"]:
        if deck.get("coupling_after_end_assembly"):
            action = "Move injected *Coupling/*Kinematic blocks inside the assembly scope before *End Assembly."
        elif first and "result_data.csv" in first.get("message", ""):
            action = "Restore the result_data.csv contract before debugging solver output."
        elif manifest.get("status") == "abaqus_mesh_failed":
            action = "Inspect abaqus_mesh_manifest.json error and fix the Abaqus scaffold creation failure first."
        else:
            action = "Fix the first error in this report before expanding the backend."
    elif summary.get("source") == "SCLAS_CURVE_V0_ENDPOINT_SWEEP":
        if int(summary.get("rows_written") or 0) >= 5:
            if sweep_shape.get("shape_checks_passed") and sweep_children.get("all_children_deep_validated"):
                if b31_warning_count:
                    action = "Endpoint sweep curve-v0 is valid, but B31 helical beam curvature/twist warnings remain; investigate a minimal B31 helix probe before changing the full cable model."
                else:
                    action = "Endpoint sweep curve-v0 aggregated at least five validated ODB child endpoints, passed basic shape checks, and deep-validated child ODB/log artifacts; validate it against a continuous bending path before research use."
            elif sweep_shape.get("shape_checks_passed"):
                action = "Endpoint sweep curve-v0 passed parent shape checks, but inspect child deep-validation diagnostics before promoting it."
            else:
                action = "Endpoint sweep curve-v0 aggregated at least five validated ODB child endpoints; inspect the shape diagnostics and child solver warnings before promoting it."
        else:
            action = "Endpoint sweep completed partially; add more validated ODB child endpoints or reduce the curvature factors further."
    elif logs.get("completed"):
        if summary.get("abaqus_curve_class") == "two_point_odb_smoke":
            if b31_warning_count:
                action = "Stable two-row Abaqus ODB smoke completed; remaining B31 helical beam curvature/twist warnings should be isolated in a minimal helix probe."
            else:
                action = "Stable two-row Abaqus ODB smoke completed; keep it as the bridge baseline and design the multi-point curve as a separate backend task."
        elif summary.get("abaqus_curve_class") == "endpoint_sweep_curve_v0":
            action = "Endpoint sweep curve-v0 was extracted; validate it against a continuous bending path before treating it as research data."
        elif summary.get("abaqus_is_research_curve"):
            action = "A multi-point Abaqus ODB curve was extracted; validate contact warnings, curve shape, and calibration metrics next."
        else:
            action = "Small Abaqus smoke solve completed; use this job to validate ODB extraction and then refine real contact/BC modelling."
    elif logs.get("matches"):
        if "LINE ELEMENTS" in log_match_text and "MASTER SURFACE" in log_match_text:
            action = "Avoid explicit contact pairs that use B31 armour line-element surfaces as master; swap solid/beam order or skip beam-beam pairs."
        else:
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
    is_endpoint_parent = report.get("result_summary_json", {}).get("source") == "SCLAS_CURVE_V0_ENDPOINT_SWEEP"
    if is_endpoint_parent:
        report["abaqus_mesh_manifest_json"] = {
            "exists": False,
            "skipped": True,
            "reason": "Endpoint sweep parent; Abaqus artifacts are stored in child job folders.",
        }
        report["input_deck"] = {
            "exists": False,
            "skipped": True,
            "reason": "Endpoint sweep parent; input decks are stored in child job folders.",
        }
        report["solver_logs"] = {
            "files": [],
            "matches": [],
            "completed": False,
            "failed": False,
            "skipped": True,
            "reason": "Endpoint sweep parent; solver logs are stored in child job folders.",
        }
    else:
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

    def top_counts(counts, limit=5):
        if not isinstance(counts, dict) or not counts:
            return "-"
        ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return ", ".join("{0}={1}".format(key, value) for key, value in ordered[:limit])

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
    sweep_shape_section = report.get("endpoint_sweep_shape", {})
    sweep_children_section = report.get("endpoint_sweep_children", {})
    sweep_mesh_quality = sweep_children_section.get("mesh_quality_warning_details", {}) if isinstance(sweep_children_section, dict) else {}
    sweep_b31_quality = sweep_children_section.get("b31_beam_warning_details", {}) if isinstance(sweep_children_section, dict) else {}
    solver_mesh_quality = logs_section.get("mesh_quality_warning_details", {}) if isinstance(logs_section, dict) else {}
    solver_b31_quality = logs_section.get("b31_beam_warning_details", {}) if isinstance(logs_section, dict) else {}
    diagnostic_summary = report.get("diagnostic_summary", {})
    issue_counts = diagnostic_summary.get("issue_counts", {})

    summary_rows = [
        ("Result CSV", scalar(csv_section.get("exists"))),
        ("CSV rows", scalar(csv_section.get("data_rows"))),
        ("Summary status", scalar(summary_section.get("status"))),
        ("Summary source", scalar(summary_section.get("source"))),
        ("Curve class", scalar(summary_section.get("abaqus_curve_class"))),
        ("Mesh status", scalar(summary_section.get("mesh_status"))),
        ("Manifest status", scalar(manifest_section.get("status"))),
        ("Contact pair scaffold", scalar(manifest_section.get("contact_pair_scaffold_status"))),
        ("Boundary scaffold", scalar(manifest_section.get("boundary_condition_scaffold_status"))),
        ("Sweep child jobs", scalar(summary_section.get("child_job_count"))),
        ("Sweep rows", scalar(summary_section.get("rows_written"))),
        ("Sweep shape checks", scalar(sweep_shape_section.get("shape_checks_passed"))),
        ("Sweep child deep checks", scalar(sweep_children_section.get("all_children_deep_validated"))),
        ("Sweep child blocking hits", scalar(sweep_children_section.get("blocking_log_hits"))),
        ("Sweep actual warning hits", scalar(sweep_children_section.get("actual_warning_log_hits"))),
        ("Sweep note/progress hits", scalar(sweep_children_section.get("note_log_hits"))),
        ("Sweep warning categories", top_counts(sweep_children_section.get("warning_categories"))),
        ("Sweep note categories", top_counts(sweep_children_section.get("note_categories"))),
        ("Sweep mesh warning sets", top_counts(sweep_mesh_quality.get("warning_sets"))),
        ("Sweep B31 warning sets", top_counts(sweep_b31_quality.get("warning_sets"))),
        ("Sweep B31 warning total", scalar(sweep_b31_quality.get("total_warning_sets"))),
        ("Sweep distorted reported elements", scalar(sweep_mesh_quality.get("distorted_reported_element_count"))),
        ("Sweep distorted table parts", top_counts(sweep_mesh_quality.get("distorted_table_parts"))),
        ("Sweep distorted table min angle", scalar(sweep_mesh_quality.get("distorted_table_min_angle"))),
        ("Sweep distorted sample parts", top_counts(sweep_mesh_quality.get("distorted_sample_parts"))),
        ("Sweep distorted sample min angle", scalar(sweep_mesh_quality.get("distorted_sample_min_angle"))),
        ("Sweep odd symmetry max rel", scalar(sweep_shape_section.get("odd_symmetry_max_relative_moment_sum"))),
        ("Sweep factor scale", scalar(sweep_shape_section.get("factor_curvature_scale"))),
        ("Input deck", scalar(deck_section.get("file"))),
        ("Couplings after End Assembly", scalar(deck_section.get("coupling_after_end_assembly"))),
        ("Solver log matches", scalar(len(logs_section.get("matches", [])))),
        ("Solver actual warning hits", scalar(logs_section.get("actual_warning_match_count"))),
        ("Solver note/progress hits", scalar(logs_section.get("note_match_count"))),
        ("Solver warning categories", top_counts(logs_section.get("warning_categories"))),
        ("Solver note categories", top_counts(logs_section.get("note_categories"))),
        ("Solver mesh warning sets", top_counts(solver_mesh_quality.get("warning_sets"))),
        ("Solver B31 warning sets", top_counts(solver_b31_quality.get("warning_sets"))),
        ("Solver B31 warning total", scalar(solver_b31_quality.get("total_warning_sets"))),
        ("Solver distorted reported elements", scalar(solver_mesh_quality.get("distorted_reported_element_count"))),
        ("Solver distorted table parts", top_counts(solver_mesh_quality.get("distorted_table_parts"))),
        ("Solver distorted table min angle", scalar(solver_mesh_quality.get("distorted_table_min_angle"))),
        ("Solver distorted sample parts", top_counts(solver_mesh_quality.get("distorted_sample_parts"))),
        ("Solver distorted sample min angle", scalar(solver_mesh_quality.get("distorted_sample_min_angle"))),
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

    for key in ["result_data_csv", "result_summary_json", "endpoint_sweep_shape", "endpoint_sweep_children", "abaqus_mesh_manifest_json", "input_deck", "solver_logs"]:
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
