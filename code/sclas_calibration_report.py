#!/usr/bin/env python3
"""Calibration report generator for HELIX/SCLAS moment-curvature runs.

This tool evaluates bending stiffness (elastic & slip-zone), hysteresis energy,
and stick-to-slip transition characteristics against literature targets.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sclas_job_summary import DEFAULT_JOB_ROOT, collect_summary, latest_job_dir
from sclas_offline_diagnostics import build_report

# Default targets for calibration comparison (e.g. from literature/Dai et al. 2025)
DEFAULT_CALIBRATION_TARGETS = {
    "elastic_bending_stiffness_kn_m2": 150.0,
    "slip_zone_bending_stiffness_kn_m2": 35.0,
    "hysteresis_energy_loss_kn": 0.05,
    "stick_to_slip_curvature_1_per_m": 0.003
}

def resolve_job(job_root: Path, job_dir: Optional[Path], include_self_check: bool) -> Path:
    if job_dir:
        return job_dir.expanduser().resolve()
    return latest_job_dir(job_root, include_self_check=include_self_check)

def load_csv_data(job_dir: Path) -> list:
    csv_path = job_dir / "result_data.csv"
    if not csv_path.exists():
        return []
    rows = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or "curvature_1_per_m" not in header:
                return []
            k_idx = header.index("curvature_1_per_m")
            m_idx = header.index("moment_kn_m")
            for r in reader:
                if len(r) > max(k_idx, m_idx):
                    try:
                        k = float(r[k_idx])
                        m = float(r[m_idx])
                        rows.append((k, m))
                    except ValueError:
                        continue
    except Exception:
        return []
    return rows

def evaluate_calibration(rows: list, summary: dict) -> dict:
    if len(rows) < 2:
        return {
            "status": "insufficient_data",
            "error": "At least 2 data points are required in result_data.csv",
            "metrics": {}
        }
    
    # Extract curvatures and moments
    curvatures = [r[0] for r in rows]
    moments = [r[1] for r in rows]
    max_k = max(curvatures)
    min_k = min(curvatures)
    
    # Calculate Loop Energy (Dissipated Hysteresis Energy) using trapezoidal rule
    # Area = 0.5 * sum((k_i - k_{i-1}) * (m_i + m_{i-1}))
    loop_energy = 0.0
    for i in range(1, len(rows)):
        dk = rows[i][0] - rows[i-1][0]
        avg_m = 0.5 * (rows[i][1] + rows[i-1][1])
        loop_energy += dk * avg_m
    # Energy loss is the absolute loop area
    loop_energy_abs = abs(loop_energy)
    
    # Estimate Elastic Bending Stiffness (Stick Stiffness)
    # We look for the steepest tangent slope near the origin
    tangents = []
    for i in range(1, len(rows)):
        dk = rows[i][0] - rows[i-1][0]
        dm = rows[i][1] - rows[i-1][1]
        if abs(dk) > 1e-12:
            tangents.append(dm / dk)
    
    elastic_stiffness = max([abs(t) for t in tangents]) if tangents else 0.0
    
    # Estimate Slip-zone Bending Stiffness
    # Defined as the stiffness at the maximum curvature factor
    peak_tangents = []
    for i in range(1, len(rows)):
        avg_k = 0.5 * (abs(rows[i][0]) + abs(rows[i-1][0]))
        if avg_k >= 0.8 * max(abs(max_k), abs(min_k)):
            dk = rows[i][0] - rows[i-1][0]
            dm = rows[i][1] - rows[i-1][1]
            if abs(dk) > 1e-12:
                peak_tangents.append(dm / dk)
    
    slip_zone_stiffness = min([abs(t) for t in peak_tangents]) if peak_tangents else 0.2 * elastic_stiffness

    # Estimate Stick-to-Slip Transition Curvature
    # Find the curvature where the tangent stiffness drops below 60% of the elastic stiffness
    stick_to_slip_k = None
    for i in range(1, len(rows)):
        dk = rows[i][0] - rows[i-1][0]
        dm = rows[i][1] - rows[i-1][1]
        if abs(dk) > 1e-12:
            current_stiffness = abs(dm / dk)
            if current_stiffness < 0.6 * elastic_stiffness:
                stick_to_slip_k = abs(rows[i][0])
                break
    
    if stick_to_slip_k is None:
        stick_to_slip_k = 0.5 * max(abs(max_k), abs(min_k))

    # Compare against targets
    t = DEFAULT_CALIBRATION_TARGETS
    
    elastic_dev = (elastic_stiffness - t["elastic_bending_stiffness_kn_m2"]) / t["elastic_bending_stiffness_kn_m2"]
    slip_dev = (slip_zone_stiffness - t["slip_zone_bending_stiffness_kn_m2"]) / t["slip_zone_bending_stiffness_kn_m2"]
    energy_dev = (loop_energy_abs - t["hysteresis_energy_loss_kn"]) / t["hysteresis_energy_loss_kn"] if t["hysteresis_energy_loss_kn"] > 0 else 0.0
    transition_dev = (stick_to_slip_k - t["stick_to_slip_curvature_1_per_m"]) / t["stick_to_slip_curvature_1_per_m"]

    # Overall calibration status
    # Tolerable deviation is 30% for these models
    is_calibrated = (
        abs(elastic_dev) < 0.3 and
        abs(slip_dev) < 0.3 and
        (loop_energy_abs == 0.0 or abs(energy_dev) < 0.3)
    )
    
    return {
        "status": "calibrated" if is_calibrated else "requires_calibration_tuning",
        "metrics": {
            "elastic_bending_stiffness_kn_m2": elastic_stiffness,
            "slip_zone_bending_stiffness_kn_m2": slip_zone_stiffness,
            "hysteresis_energy_loss_kn": loop_energy_abs,
            "stick_to_slip_curvature_1_per_m": stick_to_slip_k
        },
        "targets": t,
        "deviations": {
            "elastic_bending_stiffness_relative_dev": elastic_dev,
            "slip_zone_bending_stiffness_relative_dev": slip_dev,
            "hysteresis_energy_loss_relative_dev": energy_dev,
            "stick_to_slip_curvature_relative_dev": transition_dev
        }
    }

def build_calibration_report(job_root: Path, job_dir: Optional[Path] = None, include_self_check: bool = False) -> dict:
    selected_job = resolve_job(job_root, job_dir, include_self_check)
    diagnostic = build_report(selected_job)
    summary = collect_summary(diagnostic)
    rows = load_csv_data(selected_job)
    eval_res = evaluate_calibration(rows, summary)
    
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_root": str(job_root),
        "job_dir": str(selected_job),
        "include_self_check": include_self_check,
        "status": eval_res.get("status"),
        "error": eval_res.get("error", ""),
        "health": summary.get("health"),
        "source": summary.get("source"),
        "curve_class": summary.get("curve_class"),
        "metrics": eval_res.get("metrics"),
        "targets": eval_res.get("targets"),
        "deviations": eval_res.get("deviations"),
        "recommended_next_action": "Tune contact penalty stiffness or friction coefficient to align model with literature targets." if eval_res.get("status") != "calibrated" else "Calibration metrics aligned; ready for production parameter studies."
    }

def markdown_report(report: dict) -> str:
    metrics = report.get("metrics", {})
    targets = report.get("targets", {})
    deviations = report.get("deviations", {})
    
    lines = [
        "# HELIX / SCLAS Calibration Report",
        "",
        "- Status: `{0}`".format(report.get("status", "-")),
        "- Job: `{0}`".format(report.get("job_dir", "-")),
        "- Health/source/class: `{0}` / `{1}` / `{2}`".format(
            report.get("health", "-"),
            report.get("source", "-"),
            report.get("curve_class", "-"),
        ),
        "",
        "## Calibration Stiffness & Energy Comparison",
        "",
        "| Metric | Model Value | Target Value | Relative Deviation | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    
    keys = [
        ("elastic_bending_stiffness_kn_m2", "Elastic Bending Stiffness (kN*m^2)"),
        ("slip_zone_bending_stiffness_kn_m2", "Slip-zone Bending Stiffness (kN*m^2)"),
        ("hysteresis_energy_loss_kn", "Hysteresis Energy Loss (kN)"),
        ("stick_to_slip_curvature_1_per_m", "Stick-to-slip Curvature (1/m)")
    ]
    
    for key, label in keys:
        val = metrics.get(key)
        tgt = targets.get(key)
        dev = deviations.get(key + "_relative_dev")
        
        val_str = "{0:.4f}".format(val) if val is not None else "-"
        tgt_str = "{0:.4f}".format(tgt) if tgt is not None else "-"
        dev_str = "{0:+.2%}".format(dev) if dev is not None else "-"
        
        status = "OK" if dev is not None and abs(dev) < 0.3 else "Needs Tuning"
        if key == "hysteresis_energy_loss_kn" and val == 0.0:
            status = "No Hysteresis (Monotonic)"
        
        lines.append("| {0} | {1} | {2} | {3} | {4} |".format(
            label, val_str, tgt_str, dev_str, status
        ))
        
    lines.extend([
        "",
        "## Next Action",
        "",
        report.get("recommended_next_action", "-"),
        ""
    ])
    
    if report.get("saved_report") or report.get("saved_markdown_report"):
        lines.extend([
            "## Saved Reports",
            "",
            "- JSON: `{0}`".format(report.get("saved_report", "-")),
            "- Markdown: `{0}`".format(report.get("saved_markdown_report", "-")),
            "",
        ])
        
    return "\n".join(lines)

def save_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or Path(report["job_dir"]) / "calibration_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved["saved_report"] = str(path)
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

def save_markdown_report(report: dict, output_path: Optional[Path] = None) -> Path:
    path = output_path or Path(report["job_dir"]) / "calibration_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(report)
    saved["saved_markdown_report"] = str(path)
    path.write_text(markdown_report(saved), encoding="utf-8")
    return path

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate a HELIX/SCLAS calibration report.")
    parser.add_argument("job_dir", nargs="?", help="Specific job folder. Defaults to latest under --job-root.")
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT), help="Folder containing SCLAS jobs.")
    parser.add_argument("--include-self-check", action="store_true", help="Allow synthetic self_check jobs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--save-report", action="store_true", help="Save calibration_report.json.")
    parser.add_argument("--save-markdown", action="store_true", help="Save calibration_report.md.")
    parser.add_argument("--output", help="Custom JSON output path.")
    parser.add_argument("--markdown-output", help="Custom Markdown output path.")
    return parser.parse_args(argv)

def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        job_root = Path(args.job_root).expanduser().resolve()
        job_dir = Path(args.job_dir) if args.job_dir else None
        report = build_calibration_report(job_root, job_dir=job_dir, include_self_check=args.include_self_check)
        
        json_path = Path(args.output).expanduser().resolve() if args.output else Path(report["job_dir"]) / "calibration_report.json"
        markdown_path = Path(args.markdown_output).expanduser().resolve() if args.markdown_output else Path(report["job_dir"]) / "calibration_report.md"
        
        if args.save_report or args.output:
            report["saved_report"] = str(json_path)
        if args.save_markdown or args.markdown_output:
            report["saved_markdown_report"] = str(markdown_path)
            
        if args.save_report or args.output:
            save_report(report, json_path)
        if args.save_markdown or args.markdown_output:
            save_markdown_report(report, markdown_path)
            
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            metrics = report.get("metrics", {})
            print("HELIX / SCLAS Calibration Summary")
            print("================================")
            print("Status: {0}".format(report.get("status")))
            print("Job: {0}".format(report.get("job_dir")))
            print("Stiffnesses:")
            print("  Elastic: {0:.4f} kN*m^2".format(metrics.get("elastic_bending_stiffness_kn_m2", 0.0)))
            print("  Slip-zone: {0:.4f} kN*m^2".format(metrics.get("slip_zone_bending_stiffness_kn_m2", 0.0)))
            print("Hysteresis Energy Loss: {0:.4f} kN".format(metrics.get("hysteresis_energy_loss_kn", 0.0)))
            print("Transition Curvature: {0:.4f} 1/m".format(metrics.get("stick_to_slip_curvature_1_per_m", 0.0)))
            print("Next Action: {0}".format(report.get("recommended_next_action")))
        return 0
    except Exception as exc:
        print("[ERROR] {0}".format(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
