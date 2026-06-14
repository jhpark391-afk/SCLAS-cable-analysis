#!/usr/bin/env python
"""Extract a first SCLAS moment-curvature CSV from an Abaqus ODB.

This script is intended to run with Abaqus Python:

    abaqus python sclas_odb_extractor.py job.odb --job-dir .

It is deliberately conservative. If the requested RP outputs are not present,
it leaves the existing placeholder result_data.csv in place and writes a clear
odb_extraction_summary.json for the next backend fix.
"""

from __future__ import print_function

import argparse
import csv
import json
import os
import sys
import traceback


RIGHT_RP_TOKENS = [
    "SCLAS_RP_RIGHTEND",
    "SCLAS_RP_RIGHT",
    "RP_RIGHTEND",
    "RIGHTEND",
]

LOCAL_FIELD_TARGETS = [
    ("S", "stress"),
    ("CPRESS", "contact_pressure"),
    ("COPEN", "contact_opening"),
    ("CSLIP1", "contact_slip"),
    ("CSLIP2", "contact_slip"),
    ("CSHEAR1", "contact_shear"),
    ("CSHEAR2", "contact_shear"),
    ("CSTATUS", "contact_status"),
]

MAX_LOCAL_FIELD_FRAMES_PER_STEP = 25
MAX_LOCAL_FIELD_VALUES_PER_FRAME = 20000

try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


def path_text(path):
    return os.fspath(path) if hasattr(os, "fspath") else str(path)


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path_text(path), "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    return json.loads(text)


def write_json(path, data):
    with open(path_text(path), "w") as handle:
        json.dump(data, handle, indent=4)


def write_result_csv(path, rows):
    with open(path_text(path), "w") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["curvature_1_per_m", "moment_kn_m"])
        for curvature, moment in rows:
            writer.writerow(["{0:.12g}".format(curvature), "{0:.12g}".format(moment)])


def build_result_quality(extraction_summary):
    rows = int(extraction_summary.get("rows_written") or 0)
    status = extraction_summary.get("status")
    if status != "extracted":
        return {
            "curve_class": "odb_extraction_failed",
            "is_research_curve": False,
            "backend_readiness_status": "odb_extraction_failed",
            "next_step": "Fix ODB reference-point output extraction before using Abaqus results in the GUI.",
        }
    if rows >= 5:
        return {
            "curve_class": "multi_point_curve_v0",
            "is_research_curve": True,
            "backend_readiness_status": "abaqus_odb_curve_v0",
            "next_step": "Validate moment-curvature shape, contact warnings, and calibration targets before treating this as a research curve.",
        }
    if rows >= 2:
        return {
            "curve_class": "two_point_odb_smoke",
            "is_research_curve": False,
            "backend_readiness_status": "abaqus_odb_smoke_two_point",
            "next_step": "Use this as an end-to-end Abaqus bridge smoke only; design a separate multi-point curve load path for research use.",
        }
    return {
        "curve_class": "too_few_odb_rows",
        "is_research_curve": False,
        "backend_readiness_status": "odb_extraction_incomplete",
        "next_step": "Regenerate the ODB with at least two valid UR2/RM2 rows.",
    }


def update_result_summary(job_dir, extraction_summary):
    summary_path = os.path.join(job_dir, "result_summary.json")
    summary = load_json(summary_path, default={}) or {}
    summary["odb_extraction"] = extraction_summary
    local_field_summary = extraction_summary.get("local_field_summary")
    if isinstance(local_field_summary, dict):
        summary["odb_local_field_summary"] = local_field_summary
    quality = build_result_quality(extraction_summary)
    summary["abaqus_result_quality"] = quality
    if extraction_summary.get("status") == "extracted":
        summary["source"] = "SCLAS_ABAQUS_ODB_EXTRACTOR"
        summary["status"] = "completed"
        rows_written = extraction_summary.get("rows_written", summary.get("rows_written", summary.get("num_points")))
        summary["num_points"] = rows_written
        summary["rows_written"] = rows_written
        summary["note"] = "result_data.csv was updated from Abaqus ODB reference-point outputs."
        readiness = summary.get("backend_readiness")
        if isinstance(readiness, dict):
            bending = readiness.get("bending_stick_slip")
            if isinstance(bending, dict):
                bending["status"] = quality["backend_readiness_status"]
                bending["next_step"] = quality["next_step"]
    write_json(summary_path, summary)


def scalar_component(data, index):
    try:
        return float(data[index])
    except TypeError:
        return float(data)
    except IndexError:
        return None


def numeric_components(data):
    if isinstance(data, STRING_TYPES):
        return []
    try:
        return [float(data)]
    except (TypeError, ValueError):
        pass
    try:
        iterator = iter(data)
    except TypeError:
        return []
    values = []
    for item in iterator:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            continue
    return values


def update_range(summary, value):
    if value is None:
        return
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    current_min = summary.get("min")
    current_max = summary.get("max")
    current_abs = summary.get("abs_max")
    if current_min is None or value < current_min:
        summary["min"] = value
    if current_max is None or value > current_max:
        summary["max"] = value
    abs_value = abs(value)
    if current_abs is None or abs_value > current_abs:
        summary["abs_max"] = abs_value


def update_named_max(summary, key, value):
    if value is None:
        return
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    current = summary.get(key)
    if current is None or value > current:
        summary[key] = value


def field_target_category(output_name):
    upper = output_name.upper()
    for target, category in LOCAL_FIELD_TARGETS:
        if upper == target:
            return category
    return "other"


def selected_frames(step):
    frames = list(step.frames)
    if len(frames) <= MAX_LOCAL_FIELD_FRAMES_PER_STEP:
        return frames, False
    return frames[-MAX_LOCAL_FIELD_FRAMES_PER_STEP:], True


def matching_field_output_names(output_names, target):
    target_upper = target.upper()
    matches = []
    for name in output_names:
        upper = name.upper()
        if upper == target_upper or upper.startswith(target_upper + " ") or upper.startswith(target_upper + "\t"):
            matches.append(name)
    return matches


def summarize_local_field_value(variable_summary, value):
    numeric = numeric_components(getattr(value, "data", None))
    if not numeric:
        variable_summary["non_numeric_values"] = variable_summary.get("non_numeric_values", 0) + 1
        return
    variable_summary["value_count"] = variable_summary.get("value_count", 0) + 1
    variable_summary["component_count"] = variable_summary.get("component_count", 0) + len(numeric)
    for component in numeric:
        update_range(variable_summary, component)
    for invariant_name in ["mises", "maxPrincipal", "minPrincipal", "press"]:
        try:
            invariant_value = getattr(value, invariant_name)
        except Exception:
            continue
        try:
            invariant_value = float(invariant_value)
        except (TypeError, ValueError):
            continue
        key = invariant_name + "_max"
        update_named_max(variable_summary, key, invariant_value)


def local_field_metrics(target_outputs):
    metrics = {
        "stress_mises_max": None,
        "stress_component_abs_max": None,
        "contact_pressure_max": None,
        "contact_opening_abs_max": None,
        "slip_abs_max": None,
        "contact_shear_abs_max": None,
        "contact_status_max": None,
    }
    stress = target_outputs.get("S", {})
    if stress.get("status") == "present":
        metrics["stress_mises_max"] = stress.get("mises_max")
        metrics["stress_component_abs_max"] = stress.get("abs_max")
    cpress = target_outputs.get("CPRESS", {})
    if cpress.get("status") == "present":
        metrics["contact_pressure_max"] = cpress.get("max")
    copen = target_outputs.get("COPEN", {})
    if copen.get("status") == "present":
        metrics["contact_opening_abs_max"] = copen.get("abs_max")
    for key in ["CSLIP1", "CSLIP2"]:
        value = target_outputs.get(key, {})
        if value.get("status") == "present":
            current = metrics.get("slip_abs_max")
            candidate = value.get("abs_max")
            if candidate is not None and (current is None or candidate > current):
                metrics["slip_abs_max"] = candidate
    for key in ["CSHEAR1", "CSHEAR2"]:
        value = target_outputs.get(key, {})
        if value.get("status") == "present":
            current = metrics.get("contact_shear_abs_max")
            candidate = value.get("abs_max")
            if candidate is not None and (current is None or candidate > current):
                metrics["contact_shear_abs_max"] = candidate
    cstatus = target_outputs.get("CSTATUS", {})
    if cstatus.get("status") == "present":
        metrics["contact_status_max"] = cstatus.get("max")
    return metrics


def summarize_local_fields(steps):
    summary = {
        "checked": True,
        "status": "checked",
        "frame_scan_policy": "selected SCLAS steps; all frames unless more than {0}, then last {0} frames per step".format(MAX_LOCAL_FIELD_FRAMES_PER_STEP),
        "value_scan_limit_per_frame": MAX_LOCAL_FIELD_VALUES_PER_FRAME,
        "steps_checked": [],
        "available_field_outputs": {},
        "target_outputs": {},
        "present_target_outputs": [],
        "missing_target_outputs": [],
        "warnings": [],
    }
    target_names = [name for name, _category in LOCAL_FIELD_TARGETS]
    target_outputs = {}
    for target, category in LOCAL_FIELD_TARGETS:
        target_outputs[target] = {
            "status": "missing",
            "category": category,
            "frames_checked": 0,
            "frames_with_values": 0,
            "value_count": 0,
            "component_count": 0,
            "non_numeric_values": 0,
            "min": None,
            "max": None,
            "abs_max": None,
        }

    try:
        for step_name, step in steps:
            frames, truncated = selected_frames(step)
            summary["steps_checked"].append({
                "step": step_name,
                "frames_total": len(step.frames),
                "frames_checked": len(frames),
                "truncated_to_last_frames": truncated,
            })
            step_outputs = {}
            for frame in frames:
                output_names = list(frame.fieldOutputs.keys())
                for output_name in output_names:
                    step_outputs[output_name] = True
                for target in target_names:
                    target_summary = target_outputs[target]
                    target_summary["frames_checked"] += 1
                    actual_names = matching_field_output_names(output_names, target)
                    if not actual_names:
                        continue
                    for actual_name in actual_names:
                        try:
                            values = frame.fieldOutputs[actual_name].values
                        except Exception as exc:
                            target_summary["warnings"] = target_summary.get("warnings", [])
                            target_summary["warnings"].append("Could not read {0}: {1}".format(actual_name, exc))
                            continue
                        try:
                            value_length = len(values)
                        except Exception:
                            value_length = 0
                        if value_length:
                            target_summary["status"] = "present"
                            output_names_seen = target_summary.get("output_names", [])
                            if actual_name not in output_names_seen:
                                output_names_seen.append(actual_name)
                                target_summary["output_names"] = output_names_seen
                            target_summary["frames_with_values"] += 1
                        count = 0
                        for value in values:
                            summarize_local_field_value(target_summary, value)
                            count += 1
                            if count >= MAX_LOCAL_FIELD_VALUES_PER_FRAME:
                                target_summary["truncated_values"] = True
                                break
            summary["available_field_outputs"][step_name] = sorted(step_outputs.keys())
    except Exception as exc:
        summary["status"] = "partial"
        summary["warnings"].append("Local field summary failed partially: {0}".format(exc))

    present = []
    missing = []
    for target, _category in LOCAL_FIELD_TARGETS:
        target_summary = target_outputs[target]
        if target_summary.get("status") == "present":
            present.append(target)
        else:
            missing.append(target)
    summary["target_outputs"] = target_outputs
    summary["present_target_outputs"] = present
    summary["missing_target_outputs"] = missing
    summary["metrics"] = local_field_metrics(target_outputs)
    return summary


def find_step(odb, preferred_name):
    if preferred_name and preferred_name in odb.steps.keys():
        return preferred_name, odb.steps[preferred_name]
    for name in odb.steps.keys():
        if "SCLAS" in name.upper() or "BENDING" in name.upper():
            return name, odb.steps[name]
    names = list(odb.steps.keys())
    if names:
        return names[-1], odb.steps[names[-1]]
    return None, None


def find_steps(odb, preferred_name):
    names = list(odb.steps.keys())
    selected = []
    if preferred_name and preferred_name in names:
        selected.append(preferred_name)
    prefix = (preferred_name or "").upper() + "_"
    for name in names:
        upper = name.upper()
        if name not in selected and prefix and upper.startswith(prefix):
            selected.append(name)
    if selected:
        return [(name, odb.steps[name]) for name in selected]
    step_name, step = find_step(odb, preferred_name)
    if step is None:
        return []
    return [(step_name, step)]


def append_nonduplicate_rows(target_rows, source_rows):
    for index, row in enumerate(source_rows):
        if target_rows and index == 0:
            prev = target_rows[-1]
            if abs(prev[0] - row[0]) <= 1.0e-12 and abs(prev[1] - row[1]) <= 1.0e-12:
                continue
        target_rows.append(row)


def find_node_set(assembly, tokens):
    node_sets = assembly.nodeSets
    names = list(node_sets.keys())
    upper_names = [(name, name.upper()) for name in names]
    for token in tokens:
        token_upper = token.upper()
        for name, upper in upper_names:
            if token_upper in upper:
                return name, node_sets[name]
    for name, upper in upper_names:
        if "RP" in upper and "RIGHT" in upper:
            return name, node_sets[name]
    return None, None


def field_value(frame, output_name, node_set, component_index):
    outputs = frame.fieldOutputs
    if output_name not in outputs.keys():
        return None
    try:
        subset = outputs[output_name].getSubset(region=node_set)
        values = subset.values
    except Exception:
        return None
    if not values:
        return None
    total = 0.0
    count = 0
    for value in values:
        component = scalar_component(value.data, component_index)
        if component is not None:
            total += component
            count += 1
    if count == 0:
        return None
    if output_name.upper() in ("RF", "RM"):
        return total
    return total / float(count)


def find_history_key(history_outputs, candidates):
    keys = list(history_outputs.keys())
    for candidate in candidates:
        candidate_upper = candidate.upper()
        for key in keys:
            if key.upper() == candidate_upper:
                return key
        for key in keys:
            if candidate_upper in key.upper():
                return key
    return None


def extract_from_history(step, effective_length_m):
    preferred_regions = []
    fallback_regions = []
    for region_name, region in step.historyRegions.items():
        outputs = region.historyOutputs
        ur_key = find_history_key(outputs, ["UR2", "Spatial rotation: UR2"])
        rm_key = find_history_key(outputs, ["RM2", "Reaction moment: RM2"])
        if ur_key and rm_key:
            if "RIGHT" in region_name.upper() or "SCLAS_RP" in region_name.upper():
                preferred_regions.append((region_name, region, ur_key, rm_key))
            else:
                fallback_regions.append((region_name, region, ur_key, rm_key))
    candidates = preferred_regions + fallback_regions
    if not candidates:
        return [], None
    region_name, region, ur_key, rm_key = candidates[0]
    ur_data = list(region.historyOutputs[ur_key].data)
    rm_data = list(region.historyOutputs[rm_key].data)
    count = min(len(ur_data), len(rm_data))
    rows = []
    for i in range(count):
        rotation = float(ur_data[i][1])
        moment_n_mm = float(rm_data[i][1])
        curvature = rotation / effective_length_m if effective_length_m else rotation
        moment_kn_m = moment_n_mm * 1.0e-6
        rows.append((curvature, moment_kn_m))
    return rows, {
        "method": "history",
        "history_region": region_name,
        "rotation_output": ur_key,
        "moment_output": rm_key,
    }


def extract_from_fields(step, node_set, effective_length_m):
    rows = []
    frames_used = 0
    for frame in step.frames:
        rotation = field_value(frame, "UR", node_set, 1)
        moment_n_mm = field_value(frame, "RM", node_set, 1)
        if rotation is None or moment_n_mm is None:
            continue
        curvature = rotation / effective_length_m if effective_length_m else rotation
        moment_kn_m = moment_n_mm * 1.0e-6
        rows.append((curvature, moment_kn_m))
        frames_used += 1
    if not rows:
        return [], None
    return rows, {
        "method": "field",
        "frames_used": frames_used,
        "rotation_output": "UR2",
        "moment_output": "RM2",
    }


def extract_odb(odb_path, job_dir, input_data_path):
    try:
        from odbAccess import openOdb
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "odbAccess is not available; run with Abaqus Python",
            "error": str(exc),
        }, []

    payload = load_json(input_data_path, default={}) or {}
    analysis = payload.get("analysis_conditions", {})
    effective_length_mm = float(analysis.get("effective_length_mm", 1000.0))
    effective_length_m = effective_length_mm / 1000.0 if effective_length_mm else 0.0

    odb = openOdb(path=odb_path, readOnly=True)
    try:
        steps = find_steps(odb, "SCLAS_CyclicBendingStep")
        if not steps:
            return {
                "status": "failed",
                "reason": "No analysis step found in ODB",
                "odb_file": os.path.basename(odb_path),
            }, []

        local_field_summary = summarize_local_fields(steps)
        history_rows = []
        field_rows = []
        history_info = None
        field_info = None
        step_names = []
        node_set_name = None
        node_set_name, node_set = find_node_set(odb.rootAssembly, RIGHT_RP_TOKENS)
        for step_name, step in steps:
            step_names.append(step_name)
            step_history_rows, step_history_info = extract_from_history(step, effective_length_m)
            if step_history_info and history_info is None:
                history_info = step_history_info
            append_nonduplicate_rows(history_rows, step_history_rows)
            if node_set is not None:
                step_field_rows, step_field_info = extract_from_fields(step, node_set, effective_length_m)
                if step_field_info and field_info is None:
                    field_info = step_field_info
                append_nonduplicate_rows(field_rows, step_field_rows)

        rows = history_rows
        method_info = history_info
        if field_rows and len(field_rows) > len(rows):
            rows = field_rows
            method_info = field_info

        if len(rows) < 2:
            available_field_outputs = []
            if steps[-1][1].frames:
                available_field_outputs = list(steps[-1][1].frames[-1].fieldOutputs.keys())
            return {
                "status": "failed",
                "reason": "Could not find enough UR2/RM2 reference-point output rows",
                "odb_file": os.path.basename(odb_path),
                "steps": step_names,
                "node_set": node_set_name,
                "available_field_outputs": available_field_outputs,
                "local_field_summary": local_field_summary,
                "history_rows_available": len(history_rows),
                "field_rows_available": len(field_rows),
                "history_region_count": len(steps[-1][1].historyRegions.keys()),
                "next_step": "Regenerate the input deck with SCLAS_RP_FieldOutput/SCLAS_RightRP_HistoryOutput enabled and rerun the smoke solve.",
            }, []

        summary = {
            "status": "extracted",
            "odb_file": os.path.basename(odb_path),
            "step": step_names[0],
            "steps": step_names,
            "effective_length_mm": effective_length_mm,
            "rows_written": len(rows),
            "history_rows_available": len(history_rows),
            "field_rows_available": len(field_rows),
            "moment_units_assumed": "N-mm converted to kN-m",
            "curvature_definition": "UR2 / effective_length_m",
            "local_field_summary": local_field_summary,
        }
        if method_info:
            summary.update(method_info)
        if node_set_name:
            summary["node_set"] = node_set_name
        return summary, rows
    finally:
        odb.close()


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Extract SCLAS moment-curvature data from an Abaqus ODB.")
    parser.add_argument("odb_path")
    parser.add_argument("--job-dir", default=".")
    parser.add_argument("--input-data", default="input_data.json")
    parser.add_argument("--output-csv", default="result_data.csv")
    parser.add_argument("--summary", default="odb_extraction_summary.json")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv[1:])
    job_dir = os.path.abspath(args.job_dir)
    odb_path = os.path.abspath(args.odb_path)
    input_data_path = args.input_data
    if not os.path.isabs(input_data_path):
        input_data_path = os.path.join(job_dir, input_data_path)
    output_csv = args.output_csv
    if not os.path.isabs(output_csv):
        output_csv = os.path.join(job_dir, output_csv)
    summary_path = args.summary
    if not os.path.isabs(summary_path):
        summary_path = os.path.join(job_dir, summary_path)

    try:
        summary, rows = extract_odb(odb_path, job_dir, input_data_path)
        if summary.get("status") == "extracted":
            write_result_csv(output_csv, rows)
        write_json(summary_path, summary)
        update_result_summary(job_dir, summary)
        print("ODB extraction status: {0}".format(summary.get("status")))
        print("Wrote {0}".format(summary_path))
        if summary.get("status") == "extracted":
            print("Updated {0}".format(output_csv))
            return 0
        print(summary.get("reason", "ODB extraction did not produce result rows"))
        return 1
    except Exception as exc:
        summary = {
            "status": "failed",
            "reason": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(summary_path, summary)
        update_result_summary(job_dir, summary)
        sys.stderr.write("ODB extraction failed: {0}\n".format(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
