#!/usr/bin/env python3
"""Local SCLAS contract smoke checks.

This script intentionally writes only under the ignored jobs/ folder.
It validates the Visual Studio project references, synchronized test copies,
Python compilation, and the placeholder backend output contract.
"""

import compileall
import csv
import hashlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_DIR / "code"
JOBS_DIR = PROJECT_DIR / "jobs" / "SCLAS_jobs"


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_pyproj_references() -> None:
    pyproj = PROJECT_DIR / "SCLAS-cable-analysis.pyproj"
    root = ET.parse(pyproj).getroot()
    ns = {"msb": "http://schemas.microsoft.com/developer/msbuild/2003"}
    missing = []
    for item in root.findall(".//msb:Compile", ns) + root.findall(".//msb:Content", ns):
        include = item.attrib.get("Include", "")
        if include and not (PROJECT_DIR / include).exists():
            missing.append(include)
    if missing:
        fail("Missing .pyproj references: " + ", ".join(missing))
    print("[OK] Visual Studio project references exist")


def check_synced_files() -> None:
    pairs = [
        (CODE_DIR / "sclas_remote_gui.py", CODE_DIR / "SCLAS_test" / "sclas_remote_gui.py"),
        (CODE_DIR / "abaqus_runner.py", CODE_DIR / "SCLAS_test" / "abaqus_runner.py"),
    ]
    for left, right in pairs:
        if sha256(left) != sha256(right):
            fail(f"Test copy is not synchronized: {left.name}")
    print("[OK] Main GUI/backend files match SCLAS_test copies")


def check_compile() -> None:
    if not compileall.compile_dir(str(CODE_DIR), quiet=1):
        fail("Python compilation failed")
    print("[OK] Python files compile")


def check_backend_contract() -> None:
    job_dir = JOBS_DIR / ("self_check_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    job_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_DIR / "data" / "input_data.json", job_dir / "input_data.json")
    shutil.copy2(CODE_DIR / "abaqus_runner.py", job_dir / "abaqus_runner.py")

    proc = subprocess.run(
        [sys.executable, "abaqus_runner.py", "input_data.json"],
        cwd=str(job_dir),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("abaqus_runner.py failed:\n" + proc.stdout + proc.stderr)

    result_csv = job_dir / "result_data.csv"
    summary_json = job_dir / "result_summary.json"
    manifest_json = job_dir / "abaqus_mesh_manifest.json"
    for path in [result_csv, summary_json, manifest_json]:
        if not path.exists():
            fail(f"Backend did not create {path.name}")

    with result_csv.open("r", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), [])
    if header != ["curvature_1_per_m", "moment_kn_m"]:
        fail(f"Unexpected result_data.csv header: {header}")

    text = summary_json.read_text(encoding="utf-8")
    for required in ["result_contract", "backend_readiness", "hysteresis_loss_kj_per_m_proxy"]:
        if required not in text:
            fail(f"result_summary.json missing {required}")

    print(f"[OK] Backend contract smoke job: {job_dir}")


def main() -> int:
    checks = [
        check_pyproj_references,
        check_synced_files,
        check_compile,
        check_backend_contract,
    ]
    try:
        for check in checks:
            check()
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print("[OK] SCLAS self-check complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
