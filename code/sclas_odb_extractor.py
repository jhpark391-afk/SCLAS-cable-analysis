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


def update_result_summary(job_dir, extraction_summary):
    summary_path = os.path.join(job_dir, "result_summary.json")
    summary = load_json(summary_path, default={}) or {}
    summary["odb_extraction"] = extraction_summary
    if extraction_summary.get("status") == "extracted":
        summary["source"] = "SCLAS_ABAQUS_ODB_EXTRACTOR"
        summary["status"] = "completed"
        summary["num_points"] = extraction_summary.get("rows_written", summary.get("num_points"))
        summary["note"] = "result_data.csv was updated from Abaqus ODB reference-point outputs."
    write_json(summary_path, summary)


def scalar_component(data, index):
    try:
        return float(data[index])
    except TypeError:
        return float(data)
    except IndexError:
        return None


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
        step_name, step = find_step(odb, "SCLAS_CyclicBendingStep")
        if step is None:
            return {
                "status": "failed",
                "reason": "No analysis step found in ODB",
                "odb_file": os.path.basename(odb_path),
            }, []

        rows, method_info = extract_from_history(step, effective_length_m)
        node_set_name = None
        if not rows:
            node_set_name, node_set = find_node_set(odb.rootAssembly, RIGHT_RP_TOKENS)
            if node_set is not None:
                rows, method_info = extract_from_fields(step, node_set, effective_length_m)

        if len(rows) < 2:
            available_field_outputs = []
            if step.frames:
                available_field_outputs = list(step.frames[-1].fieldOutputs.keys())
            return {
                "status": "failed",
                "reason": "Could not find enough UR2/RM2 reference-point output rows",
                "odb_file": os.path.basename(odb_path),
                "step": step_name,
                "node_set": node_set_name,
                "available_field_outputs": available_field_outputs,
                "history_region_count": len(step.historyRegions.keys()),
                "next_step": "Regenerate the input deck with SCLAS_RP_FieldOutput/SCLAS_RightRP_HistoryOutput enabled and rerun the smoke solve.",
            }, []

        summary = {
            "status": "extracted",
            "odb_file": os.path.basename(odb_path),
            "step": step_name,
            "effective_length_mm": effective_length_mm,
            "rows_written": len(rows),
            "moment_units_assumed": "N-mm converted to kN-m",
            "curvature_definition": "UR2 / effective_length_m",
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
