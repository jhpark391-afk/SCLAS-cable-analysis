#!/usr/bin/env python3
"""
SCLAS Remote GUI v10.0
Mac/VS Code friendly PyQt5 front-end for cable bending analysis.

Role split:
- GUI developer: edits this file, validates inputs, exports job JSON, plots results.
- Abaqus backend developers: read input_data.json, run Abaqus, write result_data.csv/result_summary.json.

Remote execution uses macOS system ssh/scp and assumes SSH key login is already configured.
"""

import csv
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# macOS + VS Code Qt/OpenGL stability settings. Must be set before Qt app creation.
if sys.platform == "darwin":
    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import numpy as np
import psutil
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg
import pyqtgraph.opengl as gl

APP_VERSION = "11.4-advanced-gui-refinement"
CONTRACT_VERSION = "sclas-abaqus-contract-v1"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_JOB_ROOT = PROJECT_DIR / "jobs" / "SCLAS_jobs"
SETTINGS_PATH = PROJECT_DIR / "settings.json"
BACKEND_RUNNER_TEMPLATE = APP_DIR / "abaqus_runner.py"
TEAM_LOGO_PATH = PROJECT_DIR / "assets" / "helix_logo.png"
TEAM_ICON_PATH = PROJECT_DIR / "assets" / "helix_icon.png"


def quote_command_path(path: str) -> str:
    if sys.platform.startswith("win"):
        return f'"{path}"'
    return shlex.quote(path)


def default_local_backend_command() -> str:
    return f"{quote_command_path(sys.executable)} abaqus_runner.py input_data.json"


def normalize_local_backend_command(command: str) -> str:
    old_defaults = {
        "python abaqus_runner.py input_data.json",
        "python3 abaqus_runner.py input_data.json",
    }
    if command.strip() in old_defaults:
        return default_local_backend_command()
    return command


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def now_job_id() -> str:
    return datetime.now().strftime("job_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def safe_float(widget: QLineEdit, default: float, name: str) -> float:
    text = widget.text().strip()
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number. Current value: {text!r}") from exc


def table_float(table: QTableWidget, row: int, col: int, default: float, name: str) -> float:
    item = table.item(row, col)
    text = item.text().strip() if item else str(default)
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number. Current value: {text!r}") from exc


def parse_csv_number(text: str) -> float:
    cleaned = text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return float(cleaned)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_result_csv(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    k_values: List[float] = []
    m_values: List[float] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            lower = [x.strip().lower() for x in reader.fieldnames]
            k_key = reader.fieldnames[lower.index("curvature_1_per_m")] if "curvature_1_per_m" in lower else reader.fieldnames[0]
            if "moment_kn_m" in lower:
                m_key = reader.fieldnames[lower.index("moment_kn_m")]
            elif len(reader.fieldnames) >= 2:
                m_key = reader.fieldnames[1]
            else:
                raise ValueError("result_data.csv must include curvature and moment columns.")
            for row in reader:
                k_values.append(float(row[k_key]))
                m_values.append(float(row[m_key]))
        else:
            raise ValueError("result_data.csv has no header.")
    if not k_values:
        raise ValueError("result_data.csv contains no data rows.")
    return np.array(k_values, dtype=float), np.array(m_values, dtype=float)


def hysteresis_loss(k: np.ndarray, m_knm: np.ndarray) -> float:
    """Approximate loop work. k is 1/m, m is kN*m, result is kJ per loop-like path."""
    if len(k) < 2:
        return 0.0
    if hasattr(np, "trapezoid"):
        return float(abs(np.trapezoid(m_knm, k)))
    return float(abs(np.sum(0.5 * (m_knm[1:] + m_knm[:-1]) * (k[1:] - k[:-1]))))


# -----------------------------------------------------------------------------
# Backend worker
# -----------------------------------------------------------------------------

class AnalysisWorker(QThread):
    plot_sig = pyqtSignal(np.ndarray, np.ndarray)
    metrics_sig = pyqtSignal(dict)
    summary_sig = pyqtSignal(dict)
    log_sig = pyqtSignal(str)
    progress_sig = pyqtSignal(int)
    finished_sig = pyqtSignal(str)

    def __init__(self, payload: dict, mode: str, job_root: Path, remote_cfg: dict):
        super().__init__()
        self.payload = payload
        self.mode = mode
        self.job_root = job_root
        self.remote_cfg = remote_cfg
        self.job_dir: Optional[Path] = None

    def run(self) -> None:
        try:
            self.job_dir = create_job_package(self.job_root, self.payload)
            self.log_sig.emit(f"[JOB] Created job package: {self.job_dir}")
            self.progress_sig.emit(15)

            if self.mode == "FAST":
                self.run_fast_solver()
            elif self.mode == "LOCAL_FOLDER":
                self.log_sig.emit("[LOCAL] input_data.json exported. Backend team can run Abaqus using this folder.")
                self.progress_sig.emit(100)
                self.finished_sig.emit(str(self.job_dir))
            elif self.mode == "LOCAL_COMMAND":
                self.run_local_command()
            elif self.mode == "REMOTE_SSH":
                self.run_remote_ssh()
            else:
                raise ValueError(f"Unknown mode: {self.mode}")
        except Exception as exc:
            self.progress_sig.emit(0)
            self.log_sig.emit(f"[ERROR] {exc}")
            self.finished_sig.emit("")

    def run_fast_solver(self) -> None:
        self.log_sig.emit("[FAST] Running local Bouc-Wen style analytical fallback.")
        analysis = self.payload["analysis_conditions"]
        equivalent = self.payload["equivalent_properties"]

        k_max = float(analysis["max_curvature_1_per_m"])
        friction = float(analysis["friction_coefficient"])
        pressure = float(analysis["hydrostatic_pressure_mpa"])
        ei_init = float(equivalent["core_equivalent_EI_N_m2"])

        steps = int(analysis.get("solver_steps", 500))
        t = np.linspace(0.0, 4.0 * np.pi, steps)
        k = k_max * np.sin(t)

        # Simple GUI-side approximation only; Abaqus remains source of truth.
        ei_slip = ei_init * (0.28 + 0.10 * friction)
        m_yield_n_m = (ei_init - ei_slip) * k_max * 0.45 * (1.0 + 2.2 * friction + pressure / 45.0)

        z = 0.0
        m_n_m = np.zeros(steps)
        for i in range(1, steps):
            dk = k[i] - k[i - 1]
            sign = np.sign(dk) if dk != 0 else 1.0
            z += (1.0 - 0.55 * sign * z - 0.45 * abs(z)) * dk
            m_n_m[i] = ei_slip * k[i] + m_yield_n_m * np.tanh(12.0 * z)

        m_kn_m = m_n_m / 1000.0
        metrics = self.write_result_files(k, m_kn_m, source="FAST_GUI_APPROXIMATION")
        self.progress_sig.emit(100)
        self.plot_sig.emit(k, m_kn_m)
        self.metrics_sig.emit(metrics)
        self.summary_sig.emit(metrics)
        self.log_sig.emit("[FAST] Finished. This result is for GUI preview, not final Abaqus validation.")
        self.finished_sig.emit(str(self.job_dir))

    def run_local_command(self) -> None:
        command = self.remote_cfg.get("local_command", "").strip()
        if not command:
            raise ValueError("Local backend command is empty.")
        self.log_sig.emit(f"[LOCAL] Running backend command in job folder: {command}")
        self.progress_sig.emit(35)
        proc = subprocess.run(command, shell=True, cwd=str(self.job_dir), text=True, capture_output=True)
        if proc.stdout:
            self.log_sig.emit(proc.stdout.strip())
        if proc.stderr:
            self.log_sig.emit(proc.stderr.strip())
        if proc.returncode != 0:
            raise RuntimeError(f"Local command failed with exit code {proc.returncode}.")
        self.progress_sig.emit(75)
        self.load_backend_result()

    def run_remote_ssh(self) -> None:
        target = self.remote_cfg.get("remote_target", "").strip()
        remote_root = self.remote_cfg.get("remote_root", "").strip().rstrip("/")
        remote_command = self.remote_cfg.get("remote_command", "").strip()
        if not target or not remote_root or not remote_command:
            raise ValueError("Remote target, remote root, and remote command are required for SSH mode.")
        if shutil.which("ssh") is None or shutil.which("scp") is None:
            raise RuntimeError("ssh/scp were not found on this Mac.")

        job_name = self.job_dir.name
        remote_job_dir = f"{remote_root}/{job_name}"
        self.log_sig.emit(f"[REMOTE] Uploading job to {target}:{remote_job_dir}")
        self.progress_sig.emit(30)

        subprocess.run(["ssh", target, "mkdir", "-p", remote_job_dir], check=True, text=True)
        subprocess.run(["scp", "-r", str(self.job_dir / "."), f"{target}:{remote_job_dir}/"], check=True, text=True)

        self.log_sig.emit("[REMOTE] Running Abaqus backend command on remote computer.")
        self.progress_sig.emit(50)
        full_command = f"cd {shlex.quote(remote_job_dir)} && {remote_command}"
        proc = subprocess.run(["ssh", target, full_command], text=True, capture_output=True)
        if proc.stdout:
            self.log_sig.emit(proc.stdout.strip())
        if proc.stderr:
            self.log_sig.emit(proc.stderr.strip())
        if proc.returncode != 0:
            raise RuntimeError(f"Remote command failed with exit code {proc.returncode}.")

        self.log_sig.emit("[REMOTE] Downloading result files.")
        self.progress_sig.emit(75)
        subprocess.run(["scp", f"{target}:{remote_job_dir}/result_data.csv", str(self.job_dir / "result_data.csv")], check=True, text=True)
        # Summary is optional.
        summary_proc = subprocess.run(
            ["scp", f"{target}:{remote_job_dir}/result_summary.json", str(self.job_dir / "result_summary.json")],
            text=True,
            capture_output=True,
        )
        if summary_proc.returncode != 0:
            self.log_sig.emit("[REMOTE] Optional result_summary.json was not found.")
        self.load_backend_result()

    def load_backend_result(self) -> None:
        result_csv = self.job_dir / "result_data.csv"
        if not result_csv.exists():
            raise FileNotFoundError(f"Backend did not produce {result_csv}")
        k, m = read_result_csv(result_csv)
        metrics = make_metrics(k, m, source="ABAQUS_BACKEND")
        summary = read_json(self.job_dir / "result_summary.json", metrics)
        self.plot_sig.emit(k, m)
        self.metrics_sig.emit(metrics)
        self.summary_sig.emit(summary)
        self.progress_sig.emit(100)
        self.log_sig.emit("[RESULT] Loaded result_data.csv successfully.")
        if (self.job_dir / "result_summary.json").exists():
            self.log_sig.emit("[RESULT] Loaded result_summary.json successfully.")
        self.finished_sig.emit(str(self.job_dir))

    def write_result_files(self, k: np.ndarray, m_knm: np.ndarray, source: str) -> dict:
        result_csv = self.job_dir / "result_data.csv"
        with result_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["curvature_1_per_m", "moment_kn_m"])
            for ki, mi in zip(k, m_knm):
                writer.writerow([f"{ki:.12g}", f"{mi:.12g}"])
        metrics = make_metrics(k, m_knm, source=source)
        write_json(self.job_dir / "result_summary.json", metrics)
        return metrics


def make_metrics(k: np.ndarray, m_knm: np.ndarray, source: str) -> dict:
    return {
        "source": source,
        "max_abs_moment_kn_m": float(np.max(np.abs(m_knm))) if len(m_knm) else 0.0,
        "min_moment_kn_m": float(np.min(m_knm)) if len(m_knm) else 0.0,
        "max_moment_kn_m": float(np.max(m_knm)) if len(m_knm) else 0.0,
        "hysteresis_loss_kj_per_m_proxy": hysteresis_loss(k, m_knm),
        "num_points": int(len(k)),
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }


def create_job_package(job_root: Path, payload: dict) -> Path:
    job_id = payload["metadata"]["job_id"]
    job_dir = job_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(job_dir / "input_data.json", payload)
    write_json(job_dir / "units_manifest.json", payload["units"])
    (job_dir / "BACKEND_CONTRACT.md").write_text(BACKEND_CONTRACT_TEXT, encoding="utf-8")
    if BACKEND_RUNNER_TEMPLATE.exists():
        shutil.copy2(BACKEND_RUNNER_TEMPLATE, job_dir / "abaqus_runner.py")
    return job_dir


BACKEND_CONTRACT_TEXT = """# SCLAS Abaqus Backend Contract v1

## Input
Read `input_data.json` in the job folder.

Important sections:
- `metadata`: job id, contract version, frontend version.
- `geometry_mm`: raw GUI geometry values in mm.
- `derived_geometry_mm`: GUI-derived radii and armor center radii in mm.
- `materials`: layer elastic properties from GUI table.
- `mesh`: requested element type, model strategy, armour representation, preview discretization.
- `analysis_conditions`: length, pressure, friction, curvature, twist, axial strain, radial compression, cycle count.
- `study_scope`: enabled local behavior assessments requested by the GUI.
- `numerical_model`: literature-informed backend modelling recommendations.
  `numerical_model.contact_interfaces` lists the first contact pairs to define
  in Abaqus.
- `equivalent_properties`: GUI-side equivalent EI estimates.

## Required output
Write `result_data.csv` in the same job folder.

Required CSV header:
```csv
curvature_1_per_m,moment_kn_m
```

Each following row must contain one result point.

## Optional output
Write `abaqus_mesh_manifest.json` when the runner converts the GUI mesh request
into Abaqus files. When executed inside Abaqus/CAE, the bundled
`abaqus_runner.py` also attempts to create:
- `sclas_mesh_model.cae`
- `<job_name>_mesh.inp`

Write `result_summary.json` with any backend metrics, for example:
```json
{
  "source": "ABAQUS_BACKEND",
  "status": "completed",
  "max_abs_moment_kn_m": 123.4,
  "hysteresis_loss_kj_per_m_proxy": 0.45,
  "mesh_status": {"status": "abaqus_mesh_created"},
  "backend_readiness": {
    "bending_stick_slip": {"requested": true, "status": "abaqus_solved"},
    "contact_friction": {"requested": true, "status": "calibrated"}
  },
  "derived_placeholder_metrics": {
    "torsion_proxy_N_m2": 12.3,
    "tension_bending_coupling_index": 0.002,
    "bird_caging_risk_index": 0.018
  },
  "odb_path": "..."
}
```

## Research evaluation scope
The primary GUI plot remains the bending moment-curvature hysteresis loop.
The backend should use `study_scope.enabled_assessments` to decide which extra
local behavior evaluations to run:
- `bending_stick_slip`: bending stiffness drop and hysteresis loop.
- `torsion`: torsion stiffness and torsion-bending coupling candidates.
- `tension_bending_coupling`: axial load influence on bending response.
- `compression_bird_caging`: radial/diameter instability risk.
- `pressure_effect`: hydrostatic pressure influence on stiffness and slip.

## Literature-informed modelling notes
- Use a periodic/homogenized cell when possible to reduce the 3D FE domain to a
  helical period while preserving contact interactions.
- Treat armour layers efficiently with beam elements plus contact surface
  elements when the backend needs many wires.
- Use penalty/augmented-Lagrange normal contact and regularized Coulomb
  tangential contact. `contact_regularization_beta` is included for this.
- Calibrate friction and residual contact pressure against slip-zone bending
  stiffness and dissipated energy, then use those values for local stress
  extraction.
- For coupled axisymmetric studies, report axial/torsional stiffness and
  pressure/compression-induced softening in `result_summary.json`.

## Abaqus command pattern
A typical backend command may look like:
```bash
abaqus cae noGUI=abaqus_runner.py -- input_data.json
```

The bundled runner creates a first-pass Abaqus mesh scaffold from the GUI mesh
settings. Final contact pairs, bending boundary conditions, ODB extraction, and
paper-calibrated local behavior metrics remain backend development work.
"""


# -----------------------------------------------------------------------------
# Main GUI
# -----------------------------------------------------------------------------

class SCLASRemoteGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.derived_geom: Dict[str, float] = {}
        self.mesh_cache_solid: List[gl.GLMeshItem] = []
        self.mesh_cache_wire: List[gl.GLMeshItem] = []
        self.view_mode = "2D"
        self.current_k = np.array([])
        self.current_m = np.array([])
        self.current_metrics: dict = {}
        self.compare_items: List[pg.PlotDataItem] = []
        self.compare_metrics: List[dict] = []
        self.job_history_paths: List[Path] = []
        self.ui_language = "EN"
        self.last_summary_data: dict = {}
        self.last_job_dir = ""
        self.setWindowTitle("HELIX Cable Analysis")
        self.setMinimumSize(1280, 720)
        self.init_ui()
        self.apply_theme()
        self.load_settings()
        self.refresh_job_history()
        self.fit_to_screen()

        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self.update_telemetry)
        self.sys_timer.start(1000)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.rebuild_solid_geometry)
        self.trigger_rebuild()

    # ---------------- UI builders ----------------
    def fit_to_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1440, 820)
            return
        available = screen.availableGeometry()
        width = min(1680, max(1280, available.width() - 36))
        height = min(940, max(720, available.height() - 60))
        self.resize(width, height)
        self.move(
            available.x() + max(16, (available.width() - width) // 2),
            available.y() + max(16, (available.height() - height) // 2),
        )

    def translations(self) -> Dict[str, str]:
        return {
            "HELIX Cable Analysis": "HELIX 케이블 해석",
            "Helical Element Localised Interaction eXamination": "나선형 유한요소 국부 상호작용 분석",
            "Submarine cable modelling | mesh bridge | nonlinear response": "해저 케이블 모델링 | 메시 연동 | 비선형 응답",
            "Local project": "로컬 프로젝트",
            "Workflow": "작업 흐름",
            "Design\nGeometry inputs": "설계\n형상 입력",
            "Mesh\nAbaqus bridge": "메시\n아바쿠스 연동",
            "Analysis\nResults": "해석\n결과",
            "Ready | Local session": "준비됨 | 로컬 세션",
            "Cable Geometry Inputs": "케이블 형상 입력",
            "Import key,value CSV": "key,value CSV 불러오기",
            "Visible Layers": "표시 레이어",
            "Layer Presets": "레이어 프리셋",
            "All": "전체",
            "Armour only": "아머만",
            "Core only": "코어만",
            "Sheath only": "시스만",
            "Outer sheath": "외부 시스",
            "Outer armour": "외부 아머",
            "Bedding": "베딩",
            "Inner armour": "내부 아머",
            "Inner sheath": "내부 시스",
            "Three cores": "3상 코어",
            "Material Table": "재료 표",
            "Digital Twin View": "디지털 트윈 뷰",
            "Toggle 2D / 3D": "2D / 3D 전환",
            "Reset View": "뷰 초기화",
            "Mesh Request for Backend": "백엔드 메시 요청",
            "Abaqus element type": "아바쿠스 요소 타입",
            "Strategy": "전략",
            "Armour model": "아머 모델",
            "Contact beta": "접촉 beta",
            "Axial divisions": "축방향 분할",
            "Core divisions": "코어 분할",
            "Armour divisions": "아머 분할",
            "Generate mesh preview": "메시 프리뷰 생성",
            "Visual request only. Abaqus backend owns actual mesh generation.": "시각화 요청입니다. 실제 메시 생성은 Abaqus 백엔드가 담당합니다.",
            "Mesh Readiness": "메시 준비도",
            "Ready state": "준비 상태",
            "Est. elements": "예상 요소 수",
            "Contact pairs": "접촉 쌍",
            "Not generated": "생성 전",
            "Preview ready": "프리뷰 준비됨",
            "Preview Only": "프리뷰 전용",
            "Top": "상단",
            "Iso": "등각",
            "Reset": "초기화",
            "Analysis Conditions": "해석 조건",
            "Conditions": "조건",
            "Effective length (mm)": "유효 길이 (mm)",
            "Hydrostatic pressure (MPa)": "정수압 (MPa)",
            "Residual contact pressure (MPa)": "잔류 접촉압 (MPa)",
            "Friction coefficient": "마찰 계수",
            "Max curvature (1/m)": "최대 곡률 (1/m)",
            "Max twist (rad/m)": "최대 비틀림 (rad/m)",
            "Max axial strain": "최대 축 변형률",
            "Radial compression ratio": "반경 방향 압축률",
            "Loading cycles": "하중 사이클",
            "Result steps": "결과 스텝",
            "Research Scope / Local Behavior": "연구 범위 / 국부 거동",
            "Bending: stick-slip / hysteresis": "굽힘: 스틱-슬립 / 히스테리시스",
            "Torsion stiffness": "비틀림 강성",
            "Tension-bending coupling": "인장-굽힘 연성",
            "Compression: bird-caging risk": "압축: bird-caging 위험",
            "Hydrostatic pressure effect": "정수압 효과",
            "Backend Mode": "백엔드 모드",
            "FAST GUI preview": "FAST GUI 프리뷰",
            "Export job package only": "작업 패키지만 내보내기",
            "Run local/shared-folder command": "로컬/공유폴더 명령 실행",
            "Run remote computer via SSH/scp": "SSH/scp로 원격 컴퓨터 실행",
            "Remote / Backend Settings": "원격 / 백엔드 설정",
            "Run Controls": "실행 제어",
            "Local job root": "로컬 작업 폴더",
            "Local command": "로컬 명령",
            "SSH target": "SSH 대상",
            "Remote job root": "원격 작업 폴더",
            "Remote command": "원격 명령",
            "Validate inputs": "입력 검증",
            "Export JSON": "JSON 내보내기",
            "Run / Create Job": "실행 / 작업 생성",
            "Load result CSV": "결과 CSV 불러오기",
            "System log": "시스템 로그",
            "Moment-Curvature Result": "모멘트-곡률 결과",
            "Comparison": "비교",
            "Primary": "기준",
            "Compared": "비교",
            "Delta peak": "최대값 차이",
            "Delta loss": "손실 차이",
            "None": "없음",
            "Focus Plot": "그래프 확대",
            "Show Details": "상세 보기",
            "Export PNG": "PNG 저장",
            "Compare CSV": "CSV 비교",
            "Clear": "지우기",
            "Peak |M|": "최대 |M|",
            "Loop loss proxy": "루프 손실 지표",
            "Points": "데이터 수",
            "Recent Jobs": "최근 작업",
            "Refresh": "새로고침",
            "Load selected": "선택 항목 불러오기",
            "No result jobs found": "결과 작업 없음",
            "Model: pending": "모델: 대기",
            "Model: edited": "모델: 수정됨",
            "Model: valid": "모델: 유효",
            "Model: error": "모델: 오류",
            "Result: none": "결과: 없음",
            "Result: running": "결과: 실행 중",
            "Result: ready": "결과: 준비됨",
            "Result: loaded": "결과: 불러옴",
            "Result: stopped": "결과: 중단됨",
            "Result: error": "결과: 오류",
            "Bending Moment M": "굽힘 모멘트 M",
            "Curvature kappa": "곡률 kappa",
            "Layer": "레이어",
            "Density": "밀도",
        }

    def ui_text(self, text: str) -> str:
        if self.ui_language == "KO":
            return self.translations().get(text, text)
        return text

    def toggle_language(self) -> None:
        self.ui_language = "KO" if self.ui_language == "EN" else "EN"
        self.apply_language()
        self.save_settings()

    def apply_language(self) -> None:
        reverse = {ko: en for en, ko in self.translations().items()}
        for widget in self.findChildren(QWidget):
            if widget.property("no_translate"):
                continue
            if widget.objectName() == "SectionToggle":
                title = str(widget.property("section_title") or "")
                prefix = "[-]" if widget.isChecked() else "[+]"
                widget.setText(f"{prefix} {self.ui_text(title)}")
                continue
            if not isinstance(widget, (QLabel, QPushButton, QCheckBox, QRadioButton, QGroupBox)):
                continue
            if not hasattr(widget, "text") or not hasattr(widget, "setText"):
                continue
            current = widget.text()
            english = widget.property("en_text")
            if not english:
                english = reverse.get(current, current)
                widget.setProperty("en_text", english)
            widget.setText(self.ui_text(str(english)))

        if hasattr(self, "btn_language"):
            self.btn_language.setText("EN" if self.ui_language == "KO" else "KO")
            self.btn_language.setToolTip(
                "Switch interface language to English." if self.ui_language == "KO"
                else "인터페이스 언어를 한국어로 전환합니다."
            )
        if hasattr(self, "table"):
            self.table.setHorizontalHeaderLabels([
                self.ui_text("Layer"),
                "E (GPa)",
                "Nu",
                self.ui_text("Density"),
            ])
        if hasattr(self, "plot_canvas"):
            self.plot_canvas.setLabel("left", self.ui_text("Bending Moment M"), units="kN.m")
            self.plot_canvas.setLabel("bottom", self.ui_text("Curvature kappa"), units="1/m")
        if hasattr(self, "summary_text"):
            if self.last_summary_data:
                self.summary_text.setPlainText(self.format_summary(self.last_summary_data))
            else:
                self.summary_text.setPlainText(self.summary_placeholder_text())

    def summary_placeholder_text(self) -> str:
        if self.ui_language == "KO":
            return (
                "FAST 프리뷰, 로컬 Abaqus 실행, 또는 수동 result_data.csv 로드 후 "
                "백엔드 요약이 여기에 표시됩니다.\n\n"
                "예상 계약: result_data.csv 및 선택적 result_summary.json."
            )
        return (
            "Backend summary will appear here after FAST preview, local Abaqus runner, "
            "or manual result_data.csv load.\n\n"
            "Expected contract: result_data.csv plus optional result_summary.json."
        )

    def init_ui(self) -> None:
        main = QWidget()
        root = QHBoxLayout(main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(main)

        self.nav_buttons: List[QPushButton] = []
        root.addWidget(self.build_sidebar())

        content = QFrame()
        content.setObjectName("ContentPane")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 16)
        content_layout.setSpacing(12)

        topbar = QHBoxLayout()
        topbar.setSpacing(10)
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title = QLabel("HELIX Cable Analysis")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Submarine cable modelling | mesh bridge | nonlinear response")
        subtitle.setObjectName("AppSubtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        topbar.addLayout(title_block)
        topbar.addStretch()
        self.lbl_model_status = QLabel("Model: pending")
        self.lbl_model_status.setObjectName("TopbarMeta")
        self.lbl_result_status = QLabel("Result: none")
        self.lbl_result_status.setObjectName("TopbarMeta")
        session = QLabel("Local project")
        session.setObjectName("TopbarMeta")
        self.btn_language = QPushButton("KO")
        self.btn_language.setObjectName("LangToggle")
        self.btn_language.setFixedWidth(58)
        self.btn_language.setToolTip("인터페이스 언어를 한국어로 전환합니다.")
        self.btn_language.setProperty("no_translate", True)
        self.btn_language.clicked.connect(self.toggle_language)
        topbar.addWidget(self.lbl_model_status)
        topbar.addWidget(self.lbl_result_status)
        topbar.addWidget(session)
        topbar.addWidget(self.btn_language)
        content_layout.addLayout(topbar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("PageStack")
        content_layout.addWidget(self.pages, 1)
        root.addWidget(content, 1)

        self.build_design_tab()
        self.build_mesh_tab()
        self.build_analysis_tab()
        self.show_page(0)

    def build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(8)

        logo_label = QLabel()
        logo_label.setObjectName("TeamLogo")
        logo_label.setProperty("no_translate", True)
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedHeight(104)
        logo_pixmap = QPixmap(str(TEAM_ICON_PATH if TEAM_ICON_PATH.exists() else TEAM_LOGO_PATH))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(logo_label)

        brand = QLabel("HELIX")
        brand.setObjectName("SidebarBrand")
        brand_sub = QLabel("Helical Element Localised Interaction eXamination")
        brand_sub.setObjectName("SidebarSub")
        brand_sub.setWordWrap(True)
        layout.addWidget(brand)
        layout.addWidget(brand_sub)
        layout.addSpacing(14)

        nav_label = QLabel("Workflow")
        nav_label.setObjectName("SidebarSection")
        layout.addWidget(nav_label)

        nav_items = [("Design", "Geometry inputs"), ("Mesh", "Abaqus bridge"), ("Analysis", "Results")]
        for index, (title, subtitle) in enumerate(nav_items):
            btn = QPushButton(f"{title}\n{subtitle}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setFixedHeight(58)
            btn.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            self.nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()
        status = QLabel("Ready | Local session")
        status.setObjectName("SidebarStatus")
        layout.addWidget(status)
        return sidebar

    def add_page(self, page: QWidget) -> None:
        self.pages.addWidget(page)

    def scroll_panel(
        self,
        widget: QWidget,
        *,
        fixed_width: Optional[int] = None,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
    ) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("PanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if fixed_width is not None:
            scroll.setFixedWidth(fixed_width)
        if min_width is not None:
            scroll.setMinimumWidth(min_width)
        if max_width is not None:
            scroll.setMaximumWidth(max_width)
        scroll.setWidget(widget)
        return scroll

    def collapsible_section(self, title: str, content: QWidget, *, expanded: bool = True) -> QFrame:
        wrapper = QFrame()
        wrapper.setObjectName("CollapsibleSection")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toggle = QPushButton()
        toggle.setObjectName("SectionToggle")
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setProperty("section_title", title)
        content.setVisible(expanded)

        def update_label(checked: bool) -> None:
            prefix = "[-]" if checked else "[+]"
            toggle.setText(f"{prefix} {self.ui_text(title)}")

        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(update_label)
        update_label(expanded)
        layout.addWidget(toggle)
        layout.addWidget(content)
        return wrapper

    def show_page(self, index: int) -> None:
        if not hasattr(self, "pages"):
            return
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(getattr(self, "nav_buttons", [])):
            button.setChecked(i == index)

    def set_badge(self, label: QLabel, text: str, tone: str = "neutral") -> None:
        palette = {
            "neutral": ("#ffffff", "#d7dee8", "#405066"),
            "good": ("#ecfdf5", "#a7f3d0", "#047857"),
            "warn": ("#fffbeb", "#fde68a", "#92400e"),
            "busy": ("#eff6ff", "#bfdbfe", "#1d4ed8"),
            "error": ("#fef2f2", "#fecaca", "#b91c1c"),
        }
        bg, border, fg = palette.get(tone, palette["neutral"])
        label.setProperty("en_text", text)
        label.setText(self.ui_text(text))
        label.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border: 1px solid {border}; "
            "border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 650;"
        )

    def layer_visible(self, key: str) -> bool:
        checks = getattr(self, "layer_checks", {})
        return key not in checks or checks[key].isChecked()

    def apply_layer_preset(self, mode: str) -> None:
        if not hasattr(self, "layer_checks"):
            return
        presets = {
            "all": {
                "outer_sheath": True,
                "outer_armour": True,
                "bedding": True,
                "inner_armour": True,
                "inner_sheath": True,
                "cores": True,
            },
            "armour": {
                "outer_sheath": False,
                "outer_armour": True,
                "bedding": False,
                "inner_armour": True,
                "inner_sheath": False,
                "cores": False,
            },
            "core": {
                "outer_sheath": False,
                "outer_armour": False,
                "bedding": False,
                "inner_armour": False,
                "inner_sheath": False,
                "cores": True,
            },
            "sheath": {
                "outer_sheath": True,
                "outer_armour": False,
                "bedding": True,
                "inner_armour": False,
                "inner_sheath": True,
                "cores": False,
            },
        }
        for key, visible in presets.get(mode, presets["all"]).items():
            self.layer_checks[key].blockSignals(True)
            self.layer_checks[key].setChecked(visible)
            self.layer_checks[key].blockSignals(False)
        self.trigger_rebuild()

    def build_design_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel_inputs = QFrame(); panel_inputs.setObjectName("Card")
        panel_inputs.setMinimumWidth(430)
        left = QVBoxLayout(panel_inputs)
        left.setContentsMargins(18, 16, 18, 16)
        left.setSpacing(10)
        left.addWidget(self.header("Cable Geometry Inputs"))
        self.btn_load_csv = QPushButton("Import key,value CSV")
        self.btn_load_csv.setFixedHeight(42)
        self.btn_load_csv.setToolTip("Load the original SCLAS CSV-style key/value input table.")
        self.btn_load_csv.clicked.connect(self.load_csv)
        left.addWidget(self.btn_load_csv)

        self.inputs = {
            "r_cond": QLineEdit("4.00"),
            "r_insu": QLineEdit("11.30"),
            "roc": QLineEdit("15.30"),
            "coc": QLineEdit("17.66"),
            "tis": QLineEdit("4.50"),
            "r_ia": QLineEdit("2.00"),
            "no_ia": QSpinBox(),
            "gap": QLineEdit("0.50"),
            "r_oa": QLineEdit("2.00"),
            "no_oa": QSpinBox(),
            "tos": QLineEdit("4.50"),
            "inner_lay_angle": QLineEdit("20.1"),
            "outer_lay_angle": QLineEdit("19.6"),
        }
        self.inputs["no_ia"].setRange(1, 300); self.inputs["no_ia"].setValue(55)
        self.inputs["no_oa"].setRange(1, 300); self.inputs["no_oa"].setValue(63)

        form = QFormLayout()
        form.setVerticalSpacing(9)
        form.setHorizontalSpacing(16)
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        labels = [
            ("Conductor radius r_cond (mm)", "r_cond"),
            ("Insulation radius r_insu (mm)", "r_insu"),
            ("Core outer radius roc (mm)", "roc"),
            ("Core center radius coc (mm)", "coc"),
            ("Inner sheath thickness tis (mm)", "tis"),
            ("Inner armour wire radius (mm)", "r_ia"),
            ("Inner armour wire count", "no_ia"),
            ("Clearance gap (mm)", "gap"),
            ("Outer armour wire radius (mm)", "r_oa"),
            ("Outer armour wire count", "no_oa"),
            ("Outer sheath thickness tos (mm)", "tos"),
            ("Inner armour lay angle (deg)", "inner_lay_angle"),
            ("Outer armour lay angle (deg)", "outer_lay_angle"),
        ]
        for label, key in labels:
            self.inputs[key].setMinimumWidth(112)
            self.inputs[key].setToolTip(f"Edit {label}. The digital twin preview updates automatically.")
            form.addRow(label, self.inputs[key])
        left.addLayout(form)

        layer_box = QGroupBox("Visible Layers")
        layer_layout = QGridLayout(layer_box)
        layer_layout.addWidget(QLabel("Layer Presets"), 0, 0, 1, 2)
        preset_specs = [
            ("All", "all"),
            ("Armour only", "armour"),
            ("Core only", "core"),
            ("Sheath only", "sheath"),
        ]
        for idx, (text, mode) in enumerate(preset_specs):
            btn = QPushButton(text)
            btn.setFixedHeight(32)
            btn.setToolTip("Apply a quick visibility preset to the digital twin layers.")
            btn.clicked.connect(lambda checked=False, m=mode: self.apply_layer_preset(m))
            layer_layout.addWidget(btn, 1 + idx // 2, idx % 2)
        self.layer_checks = {
            "outer_sheath": QCheckBox("Outer sheath"),
            "outer_armour": QCheckBox("Outer armour"),
            "bedding": QCheckBox("Bedding"),
            "inner_armour": QCheckBox("Inner armour"),
            "inner_sheath": QCheckBox("Inner sheath"),
            "cores": QCheckBox("Three cores"),
        }
        for idx, check in enumerate(self.layer_checks.values()):
            check.setChecked(True)
            check.setToolTip("Toggle this layer in the digital twin view.")
            check.toggled.connect(self.trigger_rebuild)
            layer_layout.addWidget(check, 3 + idx // 2, idx % 2)
        left.addWidget(layer_box)
        left.addStretch()
        input_scroll = self.scroll_panel(panel_inputs, min_width=430, max_width=520)

        panel_mat = QFrame(); panel_mat.setObjectName("Card")
        panel_mat.setMinimumWidth(360)
        mid = QVBoxLayout(panel_mat)
        mid.setContentsMargins(18, 16, 18, 16)
        mid.addWidget(self.header("Material Table"))
        self.table = QTableWidget(9, 4)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["Layer", "E (GPa)", "Nu", "Density"])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(430)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.init_material_table()
        mid.addWidget(self.table)

        panel_view = QFrame(); panel_view.setObjectName("Card")
        panel_view.setMinimumWidth(380)
        right = QVBoxLayout(panel_view)
        right.setContentsMargins(18, 16, 18, 16)
        header = QHBoxLayout()
        header.addWidget(self.header("Digital Twin View"))
        self.btn_toggle = QPushButton("Toggle 2D / 3D")
        self.btn_toggle.setToolTip("Switch between top-down section view and tilted 3D inspection.")
        self.btn_toggle.clicked.connect(self.toggle_view_mode)
        self.btn_reset_solid = QPushButton("Reset View")
        self.btn_reset_solid.setToolTip("Return the digital twin camera to the default engineering view.")
        self.btn_reset_solid.clicked.connect(self.reset_solid_view)
        header.addWidget(self.btn_toggle)
        header.addWidget(self.btn_reset_solid)
        right.addLayout(header)
        self.view_solid = gl.GLViewWidget()
        self.view_solid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_solid.setMinimumHeight(360)
        self.view_solid.setBackgroundColor("#f7f8fa")
        self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        right.addWidget(self.view_solid, 1)

        workspace = QFrame()
        workspace.setObjectName("WorkspaceFrame")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(14)
        workspace_layout.addWidget(panel_view, 3)
        workspace_layout.addWidget(panel_mat, 2)
        workspace_scroll = self.scroll_panel(workspace)

        layout.addWidget(workspace_scroll, 1)
        layout.addWidget(input_scroll)
        self.add_page(tab)

        for w in self.inputs.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self.trigger_rebuild)
            else:
                w.valueChanged.connect(self.trigger_rebuild)

    def build_mesh_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        panel = QFrame(); panel.setObjectName("Card"); panel.setFixedWidth(430)
        left = QVBoxLayout(panel)
        left.setContentsMargins(18, 16, 18, 16)
        left.setSpacing(12)
        left.addWidget(self.header("Mesh Request for Backend"))
        self.mesh_inputs = {
            "elem_type": QComboBox(),
            "model_strategy": QComboBox(),
            "armour_model": QComboBox(),
            "contact_beta": QLineEdit("0.001"),
            "z_elem": QSpinBox(),
            "c_elem_core": QSpinBox(),
            "c_elem_armour": QSpinBox(),
        }
        self.mesh_inputs["elem_type"].addItems(["C3D8R", "C3D4", "B31"])
        self.mesh_inputs["model_strategy"].addItems(["Periodic homogenized cell", "Full 3D segment", "Axisymmetric tension/torsion"])
        self.mesh_inputs["armour_model"].addItems(["Beam + contact surface", "Solid wire", "Analytical equivalent"])
        self.mesh_inputs["z_elem"].setRange(2, 500); self.mesh_inputs["z_elem"].setValue(40)
        self.mesh_inputs["c_elem_core"].setRange(4, 160); self.mesh_inputs["c_elem_core"].setValue(24)
        self.mesh_inputs["c_elem_armour"].setRange(4, 64); self.mesh_inputs["c_elem_armour"].setValue(8)
        mesh_tips = {
            "elem_type": "Abaqus element family requested in input_data.json.",
            "model_strategy": "Controls whether the backend should build a periodic cell, full segment, or axisymmetric study.",
            "armour_model": "Recommended representation for helical armour layers in Abaqus.",
            "contact_beta": "Tangential contact regularization value for stick-slip stability.",
            "z_elem": "Preview and backend-requested divisions along the cable axis.",
            "c_elem_core": "Circumferential divisions for sheath/core preview surfaces.",
            "c_elem_armour": "Circumferential divisions for armour wire preview surfaces.",
        }
        for key in ["elem_type", "model_strategy", "armour_model", "contact_beta"]:
            self.mesh_inputs[key].setMinimumWidth(250)
        for key, tip in mesh_tips.items():
            self.mesh_inputs[key].setToolTip(tip)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Abaqus element type", self.mesh_inputs["elem_type"])
        form.addRow("Strategy", self.mesh_inputs["model_strategy"])
        form.addRow("Armour model", self.mesh_inputs["armour_model"])
        form.addRow("Contact beta", self.mesh_inputs["contact_beta"])
        form.addRow("Axial divisions", self.mesh_inputs["z_elem"])
        form.addRow("Core divisions", self.mesh_inputs["c_elem_core"])
        form.addRow("Armour divisions", self.mesh_inputs["c_elem_armour"])
        left.addLayout(form)
        self.btn_mesh = QPushButton("Generate mesh preview")
        self.btn_mesh.setObjectName("RunBtn")
        self.btn_mesh.setFixedHeight(50)
        self.btn_mesh.setToolTip("Build a visual mesh preview from the current geometry and mesh request.")
        self.btn_mesh.clicked.connect(self.generate_mesh_preview)
        left.addWidget(self.btn_mesh)
        note = QLabel("Visual request only. Abaqus backend owns actual mesh generation.")
        note.setWordWrap(True)
        left.addWidget(note)
        mesh_ready_box = QGroupBox("Mesh Readiness")
        mesh_ready_layout = QGridLayout(mesh_ready_box)
        self.lbl_mesh_ready = self.metric_box("Ready state", "Not generated")
        self.lbl_mesh_elements = self.metric_box("Est. elements", "-")
        self.lbl_mesh_contacts = self.metric_box("Contact pairs", "5")
        mesh_ready_layout.addWidget(self.lbl_mesh_ready, 0, 0)
        mesh_ready_layout.addWidget(self.lbl_mesh_elements, 1, 0)
        mesh_ready_layout.addWidget(self.lbl_mesh_contacts, 2, 0)
        left.addWidget(mesh_ready_box)
        left.addStretch()

        viewer = QFrame(); viewer.setObjectName("Card")
        right = QVBoxLayout(viewer)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)
        mesh_header = QHBoxLayout()
        mesh_header.addWidget(self.header("Preview Only"))
        mesh_header.addStretch()
        self.btn_mesh_top = QPushButton("Top")
        self.btn_mesh_iso = QPushButton("Iso")
        self.btn_mesh_reset = QPushButton("Reset")
        for btn in [self.btn_mesh_top, self.btn_mesh_iso, self.btn_mesh_reset]:
            btn.setFixedWidth(72)
        self.btn_mesh_top.setToolTip("Set the mesh camera to top-down section view.")
        self.btn_mesh_iso.setToolTip("Set the mesh camera to an isometric inspection view.")
        self.btn_mesh_reset.setToolTip("Reset the mesh preview camera.")
        self.btn_mesh_top.clicked.connect(self.reset_mesh_view)
        self.btn_mesh_iso.clicked.connect(self.set_mesh_iso_view)
        self.btn_mesh_reset.clicked.connect(self.reset_mesh_view)
        mesh_header.addWidget(self.btn_mesh_top)
        mesh_header.addWidget(self.btn_mesh_iso)
        mesh_header.addWidget(self.btn_mesh_reset)
        right.addLayout(mesh_header)
        self.view_wire = gl.GLViewWidget()
        self.view_wire.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_wire.setMinimumHeight(360)
        self.view_wire.setBackgroundColor("#1e1e1e")
        self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)
        right.addWidget(self.view_wire, 1)
        viewer_scroll = self.scroll_panel(viewer)
        mesh_scroll = self.scroll_panel(panel, fixed_width=450)
        layout.addWidget(viewer_scroll, 1)
        layout.addWidget(mesh_scroll)
        self.add_page(tab)

    def build_analysis_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left_panel = QFrame(); left_panel.setObjectName("Card"); left_panel.setMinimumWidth(430)
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(18, 16, 18, 16)
        self.cond = {
            "eff_length": QLineEdit("234.20"),
            "pressure": QLineEdit("40.00"),
            "residual_contact_pressure": QLineEdit("0.30"),
            "friction": QLineEdit("0.22"),
            "curvature": QLineEdit("0.08"),
            "twist": QLineEdit("0.05"),
            "axial_strain": QLineEdit("0.002"),
            "radial_compression": QLineEdit("0.015"),
            "cycles": QSpinBox(),
            "steps": QSpinBox(),
        }
        self.cond["cycles"].setRange(1, 20); self.cond["cycles"].setValue(2)
        self.cond["steps"].setRange(50, 10000); self.cond["steps"].setValue(500)
        analysis_tips = {
            "eff_length": "Effective cable length used for the periodic/homogenized bending request.",
            "pressure": "Hydrostatic pressure term used by the GUI fallback and exported for Abaqus.",
            "residual_contact_pressure": "Residual normal contact pressure for stick-slip/friction calibration.",
            "friction": "Coulomb friction coefficient for armour-to-sheath and armour-to-bedding contact.",
            "curvature": "Maximum curvature for the moment-curvature loop.",
            "twist": "Maximum twist requested for future coupled torsion studies.",
            "axial_strain": "Axial strain requested for tension-bending coupling studies.",
            "radial_compression": "Compression ratio used for bird-caging risk proxy.",
            "cycles": "Number of loading cycles in the preview/result request.",
            "steps": "Number of output samples in the result curve.",
        }
        for key, tip in analysis_tips.items():
            self.cond[key].setToolTip(tip)
        conditions_box = QFrame()
        form = QFormLayout(conditions_box)
        form.addRow("Effective length (mm)", self.cond["eff_length"])
        form.addRow("Hydrostatic pressure (MPa)", self.cond["pressure"])
        form.addRow("Residual contact pressure (MPa)", self.cond["residual_contact_pressure"])
        form.addRow("Friction coefficient", self.cond["friction"])
        form.addRow("Max curvature (1/m)", self.cond["curvature"])
        form.addRow("Max twist (rad/m)", self.cond["twist"])
        form.addRow("Max axial strain", self.cond["axial_strain"])
        form.addRow("Radial compression ratio", self.cond["radial_compression"])
        form.addRow("Loading cycles", self.cond["cycles"])
        form.addRow("Result steps", self.cond["steps"])
        left.addWidget(self.collapsible_section("Conditions", conditions_box, expanded=True))

        scope_box = QFrame()
        scope_layout = QVBoxLayout(scope_box)
        self.study_checks = {
            "bending_stick_slip": QCheckBox("Bending: stick-slip / hysteresis"),
            "torsion": QCheckBox("Torsion stiffness"),
            "tension_bending_coupling": QCheckBox("Tension-bending coupling"),
            "compression_bird_caging": QCheckBox("Compression: bird-caging risk"),
            "pressure_effect": QCheckBox("Hydrostatic pressure effect"),
        }
        self.study_checks["bending_stick_slip"].setChecked(True)
        self.study_checks["pressure_effect"].setChecked(True)
        for check in self.study_checks.values():
            check.setToolTip("Enable this assessment in the exported backend contract.")
            scope_layout.addWidget(check)
        left.addWidget(self.collapsible_section("Research Scope / Local Behavior", scope_box, expanded=True))

        backend_box = QFrame()
        backend_layout = QVBoxLayout(backend_box)
        backend_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_fast = QRadioButton("FAST GUI preview")
        self.radio_package = QRadioButton("Export job package only")
        self.radio_local = QRadioButton("Run local/shared-folder command")
        self.radio_remote = QRadioButton("Run remote computer via SSH/scp")
        self.radio_fast.setChecked(True)
        for r in [self.radio_fast, self.radio_package, self.radio_local, self.radio_remote]:
            r.setToolTip("Choose how the current input package should be handled.")
            backend_layout.addWidget(r)
        left.addWidget(self.collapsible_section("Backend Mode", backend_box, expanded=True))

        remote_box = QFrame()
        remote_form = QFormLayout(remote_box)
        self.job_root_input = QLineEdit(str(DEFAULT_JOB_ROOT))
        self.local_command_input = QLineEdit(default_local_backend_command())
        self.remote_target_input = QLineEdit("user@remote-host")
        self.remote_root_input = QLineEdit("~/SCLAS_jobs")
        self.remote_command_input = QLineEdit("abaqus cae noGUI=abaqus_runner.py -- input_data.json")
        self.job_root_input.setToolTip("Folder where generated SCLAS job packages are saved.")
        self.local_command_input.setToolTip("Command run inside each job folder for local or shared-folder backend execution.")
        self.remote_target_input.setToolTip("SSH target for the lab desktop or remote Abaqus computer.")
        self.remote_root_input.setToolTip("Remote folder where job packages should be copied.")
        self.remote_command_input.setToolTip("Abaqus command executed remotely after the job package is copied.")
        self.job_root_input.editingFinished.connect(self.refresh_job_history)
        remote_form.addRow("Local job root", self.job_root_input)
        remote_form.addRow("Local command", self.local_command_input)
        remote_form.addRow("SSH target", self.remote_target_input)
        remote_form.addRow("Remote job root", self.remote_root_input)
        remote_form.addRow("Remote command", self.remote_command_input)
        left.addWidget(self.collapsible_section("Remote / Backend Settings", remote_box, expanded=False))

        run_box = QFrame()
        run_layout = QVBoxLayout(run_box)
        run_layout.setContentsMargins(0, 0, 0, 0)
        buttons = QGridLayout()
        self.btn_validate = QPushButton("Validate inputs")
        self.btn_json = QPushButton("Export JSON")
        self.btn_run = QPushButton("Run / Create Job")
        self.btn_run.setObjectName("RunBtn")
        self.btn_load_result = QPushButton("Load result CSV")
        self.btn_validate.clicked.connect(self.validate_inputs_dialog)
        self.btn_json.clicked.connect(self.export_json_dialog)
        self.btn_run.clicked.connect(self.run_analysis)
        self.btn_load_result.clicked.connect(self.load_result_csv_dialog)
        self.btn_validate.setToolTip("Validate geometry, materials, mesh settings, and analysis conditions.")
        self.btn_json.setToolTip("Export only input_data.json for backend review.")
        self.btn_run.setToolTip("Create a job folder, then run the selected backend mode.")
        self.btn_load_result.setToolTip("Load an existing result_data.csv and optional result_summary.json.")
        buttons.addWidget(self.btn_validate, 0, 0)
        buttons.addWidget(self.btn_json, 0, 1)
        buttons.addWidget(self.btn_run, 1, 0, 1, 2)
        buttons.addWidget(self.btn_load_result, 2, 0, 1, 2)
        run_layout.addLayout(buttons)

        self.progress = QProgressBar(); self.progress.setValue(0)
        run_layout.addWidget(self.progress)
        self.lbl_hw = QLabel("HW: CPU - | RAM -")
        run_layout.addWidget(self.lbl_hw)
        run_layout.addWidget(QLabel("System log"))
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setMaximumHeight(130)
        run_layout.addWidget(self.console)
        left.addWidget(self.collapsible_section("Run Controls", run_box, expanded=True))
        left.addStretch()

        result_panel = QFrame(); result_panel.setObjectName("Card")
        right = QVBoxLayout(result_panel)
        result_header = QHBoxLayout()
        result_header.addWidget(self.header("Moment-Curvature Result"))
        result_header.addStretch()
        self.btn_export_plot = QPushButton("Export PNG")
        self.btn_compare_csv = QPushButton("Compare CSV")
        self.btn_clear_compare = QPushButton("Clear")
        self.btn_focus_plot = QPushButton("Focus Plot")
        self.btn_focus_plot.setCheckable(True)
        self.btn_export_plot.setToolTip("Save the current plot view as a PNG image.")
        self.btn_compare_csv.setToolTip("Overlay another result_data.csv for FAST/Abaqus comparison.")
        self.btn_clear_compare.setToolTip("Remove all comparison curves from the plot.")
        self.btn_focus_plot.setToolTip("Hide detail panels and give the result plot more vertical space.")
        self.btn_export_plot.clicked.connect(self.export_plot_png)
        self.btn_compare_csv.clicked.connect(self.compare_result_csv_dialog)
        self.btn_clear_compare.clicked.connect(self.clear_compare_curves)
        self.btn_focus_plot.toggled.connect(self.set_plot_focus)
        result_header.addWidget(self.btn_focus_plot)
        result_header.addWidget(self.btn_export_plot)
        result_header.addWidget(self.btn_compare_csv)
        result_header.addWidget(self.btn_clear_compare)
        right.addLayout(result_header)
        self.plot_canvas = pg.PlotWidget(background="#1e1e1e")
        self.plot_canvas.setMinimumHeight(520)
        self.plot_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plot_canvas.showGrid(x=True, y=True, alpha=0.13)
        self.plot_canvas.setLabel("left", "Bending Moment M", units="kN.m")
        self.plot_canvas.setLabel("bottom", "Curvature kappa", units="1/m")
        self.plot_canvas.getAxis("left").setTextPen("#a7a7a7")
        self.plot_canvas.getAxis("bottom").setTextPen("#a7a7a7")
        self.plot_canvas.getAxis("left").setPen("#555555")
        self.plot_canvas.getAxis("bottom").setPen("#555555")
        self.curve = self.plot_canvas.plot(pen=pg.mkPen(color="#8ab4ff", width=2.8))
        right.addWidget(self.plot_canvas, 100)
        self.metric_panel = QFrame()
        self.metric_panel.setObjectName("MetricStrip")
        metric_layout = QHBoxLayout(self.metric_panel)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_peak = self.metric_box("Peak |M|", "-")
        self.lbl_loss = self.metric_box("Loop loss proxy", "-")
        self.lbl_points = self.metric_box("Points", "-")
        metric_layout.addWidget(self.lbl_peak)
        metric_layout.addWidget(self.lbl_loss)
        metric_layout.addWidget(self.lbl_points)
        right.addWidget(self.metric_panel)

        self.compare_panel = QFrame()
        self.compare_panel.setObjectName("MetricStrip")
        compare_layout = QHBoxLayout(self.compare_panel)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_compare_primary = self.metric_box("Primary", "FAST")
        self.lbl_compare_count = self.metric_box("Compared", "None")
        self.lbl_compare_peak_delta = self.metric_box("Delta peak", "-")
        self.lbl_compare_loss_delta = self.metric_box("Delta loss", "-")
        compare_layout.addWidget(self.lbl_compare_primary)
        compare_layout.addWidget(self.lbl_compare_count)
        compare_layout.addWidget(self.lbl_compare_peak_delta)
        compare_layout.addWidget(self.lbl_compare_loss_delta)
        right.addWidget(self.compare_panel)

        self.summary_text = QTextEdit()
        self.summary_text.setObjectName("SummaryText")
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(155)
        self.summary_text.setPlainText(self.summary_placeholder_text())
        right.addWidget(self.summary_text)

        self.history_box = QGroupBox("Recent Jobs")
        history_layout = QGridLayout(self.history_box)
        self.job_history_combo = QComboBox()
        self.job_history_combo.setToolTip("Recent job folders containing result_data.csv.")
        self.btn_refresh_jobs = QPushButton("Refresh")
        self.btn_load_job = QPushButton("Load selected")
        self.btn_refresh_jobs.setToolTip("Scan the job root for recent SCLAS result folders.")
        self.btn_load_job.setToolTip("Load result_data.csv from the selected job folder.")
        self.btn_refresh_jobs.clicked.connect(self.refresh_job_history)
        self.btn_load_job.clicked.connect(self.load_selected_job)
        history_layout.addWidget(self.job_history_combo, 0, 0, 1, 2)
        history_layout.addWidget(self.btn_refresh_jobs, 1, 0)
        history_layout.addWidget(self.btn_load_job, 1, 1)
        right.addWidget(self.history_box)

        left_scroll = self.scroll_panel(left_panel, fixed_width=460)
        result_scroll = self.scroll_panel(result_panel)

        layout.addWidget(result_scroll, 1)
        layout.addWidget(left_scroll)
        self.add_page(tab)

    def header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 17px; font-weight: 700; color: #17202a; padding: 2px 0 8px 0;")
        return label

    def metric_box(self, title: str, value: str) -> QFrame:
        box = QFrame(); box.setObjectName("MetricBox")
        layout = QVBoxLayout(box)
        title_label = QLabel(title); title_label.setStyleSheet("color: #5f6b7a; font-size: 13px;")
        value_label = QLabel(value); value_label.setStyleSheet("color: #132033; font-size: 23px; font-weight: 750;")
        value_label.setProperty("no_translate", True)
        layout.addWidget(title_label); layout.addWidget(value_label)
        box.value_label = value_label
        return box

    def init_material_table(self) -> None:
        materials = [
            ("Copper Core", 108.0, 0.33, 8960, QColor(217, 115, 38)),
            ("XLPE Insulation", 1.2, 0.46, 940, QColor(230, 230, 230)),
            ("Lead Sheath", 16.0, 0.44, 11340, QColor(150, 150, 160)),
            ("Filler Matrix", 0.8, 0.48, 1200, QColor(60, 60, 65)),
            ("Inner Sheath", 1.5, 0.45, 1300, QColor(30, 30, 30)),
            ("Inner Armour", 210.0, 0.30, 7850, QColor(100, 120, 150)),
            ("Bedding", 0.5, 0.49, 1100, QColor(90, 70, 50)),
            ("Outer Armour", 210.0, 0.30, 7850, QColor(130, 150, 180)),
            ("Outer Sheath", 1.4, 0.45, 1300, QColor(40, 40, 45)),
        ]
        for row, (name, e, nu, density, color) in enumerate(materials):
            item = QTableWidgetItem(name)
            item.setIcon(QIcon(self.color_icon(color)))
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(str(e)))
            self.table.setItem(row, 2, QTableWidgetItem(str(nu)))
            self.table.setItem(row, 3, QTableWidgetItem(str(density)))

    def color_icon(self, color: QColor) -> QPixmap:
        pix = QPixmap(16, 16)
        pix.fill(color)
        return pix

    # ---------------- Data model ----------------
    def parse_geometry(self) -> Dict[str, float]:
        rc = safe_float(self.inputs["r_cond"], 4.0, "Conductor radius")
        ri = safe_float(self.inputs["r_insu"], 11.3, "Insulation radius")
        roc = safe_float(self.inputs["roc"], 15.3, "Core outer radius")
        coc = safe_float(self.inputs["coc"], 17.66, "Core center radius")
        tis = safe_float(self.inputs["tis"], 4.5, "Inner sheath thickness")
        ria = safe_float(self.inputs["r_ia"], 2.0, "Inner armour wire radius")
        gap = safe_float(self.inputs["gap"], 0.5, "Clearance gap")
        roa = safe_float(self.inputs["r_oa"], 2.0, "Outer armour wire radius")
        tos = safe_float(self.inputs["tos"], 4.5, "Outer sheath thickness")
        nia = int(self.inputs["no_ia"].value())
        noa = int(self.inputs["no_oa"].value())

        if not (0 < rc < ri <= roc):
            raise ValueError("Geometry must satisfy 0 < conductor_radius < insulation_radius <= core_outer_radius.")
        if min(coc, tis, ria, gap, roa, tos) < 0:
            raise ValueError("Radii/thickness/gap values must be non-negative.")

        iris = roc + coc
        oris = iris + tis
        co_ia = oris + gap + ria
        irb = co_ia + ria
        bedding_thickness = 0.6
        orb = irb + bedding_thickness
        co_oa = orb + gap + roa
        iros = co_oa + roa
        oros = iros + tos

        self.derived_geom = {
            "conductor_radius_mm": rc,
            "insulation_radius_mm": ri,
            "core_outer_radius_mm": roc,
            "core_center_radius_mm": coc,
            "inner_sheath_inner_radius_mm": iris,
            "inner_sheath_outer_radius_mm": oris,
            "inner_armour_center_radius_mm": co_ia,
            "inner_armour_wire_radius_mm": ria,
            "inner_armour_outer_radius_mm": irb,
            "bedding_outer_radius_mm": orb,
            "outer_armour_center_radius_mm": co_oa,
            "outer_armour_wire_radius_mm": roa,
            "outer_sheath_inner_radius_mm": iros,
            "outer_sheath_outer_radius_mm": oros,
            "inner_armour_wire_count": nia,
            "outer_armour_wire_count": noa,
            "bedding_thickness_mm": bedding_thickness,
        }
        return self.derived_geom

    def mesh_value(self, key: str) -> str:
        maps = {
            "model_strategy": {
                "Periodic homogenized cell": "periodic_homogenized_cell",
                "Full 3D segment": "full_3d_segment",
                "Axisymmetric tension/torsion": "axisymmetric_tension_torsion",
            },
            "armour_model": {
                "Beam + contact surface": "beam_with_contact_surface",
                "Solid wire": "solid_wire",
                "Analytical equivalent": "analytical_equivalent",
            },
        }
        text = self.mesh_inputs[key].currentText()
        return maps.get(key, {}).get(text, text)

    def build_payload(self) -> dict:
        dg = self.parse_geometry()
        materials = self.collect_materials()
        eq = self.compute_equivalent_properties(materials, dg)
        job_id = now_job_id()
        payload = {
            "metadata": {
                "contract_version": CONTRACT_VERSION,
                "frontend_version": APP_VERSION,
                "job_id": job_id,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "created_by_role": "GUI_frontend",
                "team_name": "HELIX",
                "team_acronym": "Helical Element Localised Interaction eXamination",
            },
            "units": {
                "length": "mm unless key ends with _m",
                "pressure": "MPa",
                "angle": "deg",
                "curvature": "1/m",
                "twist": "rad/m",
                "strain": "dimensionless",
                "contact_regularization_beta": "dimensionless",
                "elastic_modulus": "GPa in materials, Pa in equivalent_properties",
                "moment_output_required": "kN.m",
            },
            "geometry_mm": {
                "conductor_radius_mm": safe_float(self.inputs["r_cond"], 4.0, "Conductor radius"),
                "insulation_radius_mm": safe_float(self.inputs["r_insu"], 11.3, "Insulation radius"),
                "core_outer_radius_mm": safe_float(self.inputs["roc"], 15.3, "Core outer radius"),
                "core_center_radius_mm": safe_float(self.inputs["coc"], 17.66, "Core center radius"),
                "inner_sheath_thickness_mm": safe_float(self.inputs["tis"], 4.5, "Inner sheath thickness"),
                "clearance_gap_mm": safe_float(self.inputs["gap"], 0.5, "Clearance gap"),
                "outer_sheath_thickness_mm": safe_float(self.inputs["tos"], 4.5, "Outer sheath thickness"),
            },
            "derived_geometry_mm": dg,
            "armour": {
                "inner_wire_radius_mm": safe_float(self.inputs["r_ia"], 2.0, "Inner armour wire radius"),
                "outer_wire_radius_mm": safe_float(self.inputs["r_oa"], 2.0, "Outer armour wire radius"),
                "inner_wire_count": int(self.inputs["no_ia"].value()),
                "outer_wire_count": int(self.inputs["no_oa"].value()),
                "inner_lay_angle_deg": safe_float(self.inputs["inner_lay_angle"], 20.1, "Inner armour lay angle"),
                "outer_lay_angle_deg": safe_float(self.inputs["outer_lay_angle"], 19.6, "Outer armour lay angle"),
                "lay_angle_deg": 0.5 * (
                    safe_float(self.inputs["inner_lay_angle"], 20.1, "Inner armour lay angle")
                    + safe_float(self.inputs["outer_lay_angle"], 19.6, "Outer armour lay angle")
                ),
            },
            "materials": materials,
            "mesh": {
                "requested_element_type": self.mesh_inputs["elem_type"].currentText(),
                "model_strategy": self.mesh_value("model_strategy"),
                "armour_model": self.mesh_value("armour_model"),
                "axial_divisions": int(self.mesh_inputs["z_elem"].value()),
                "core_circumferential_divisions": int(self.mesh_inputs["c_elem_core"].value()),
                "armour_circumferential_divisions": int(self.mesh_inputs["c_elem_armour"].value()),
                "note": "GUI preview only. Abaqus backend decides final seed/mesh controls.",
            },
            "analysis_conditions": {
                "effective_length_mm": safe_float(self.cond["eff_length"], 234.2, "Effective length"),
                "hydrostatic_pressure_mpa": safe_float(self.cond["pressure"], 40.0, "Hydrostatic pressure"),
                "residual_contact_pressure_mpa": safe_float(self.cond["residual_contact_pressure"], 0.3, "Residual contact pressure"),
                "friction_coefficient": safe_float(self.cond["friction"], 0.22, "Friction coefficient"),
                "max_curvature_1_per_m": safe_float(self.cond["curvature"], 0.08, "Max curvature"),
                "max_twist_rad_per_m": safe_float(self.cond["twist"], 0.05, "Max twist"),
                "max_axial_strain": safe_float(self.cond["axial_strain"], 0.002, "Max axial strain"),
                "radial_compression_ratio": safe_float(self.cond["radial_compression"], 0.015, "Radial compression ratio"),
                "contact_regularization_beta": safe_float(self.mesh_inputs["contact_beta"], 0.001, "Contact regularization beta"),
                "loading_cycles": int(self.cond["cycles"].value()),
                "solver_steps": int(self.cond["steps"].value()),
            },
            "study_scope": self.collect_study_scope(),
            "numerical_model": self.build_numerical_model_notes(),
            "equivalent_properties": eq,
            "backend_output_contract": {
                "required_csv": "result_data.csv",
                "required_columns": ["curvature_1_per_m", "moment_kn_m"],
                "optional_summary": "result_summary.json",
                "primary_result": "bending moment-curvature loop",
                "additional_requested_assessments": [
                    "torsion stiffness",
                    "tension-bending coupling",
                    "compression bird-caging risk",
                    "hydrostatic pressure effect",
                ],
            },
        }
        return payload

    def build_numerical_model_notes(self) -> dict:
        friction = safe_float(self.cond["friction"], 0.22, "Friction coefficient")
        residual_pressure = safe_float(self.cond["residual_contact_pressure"], 0.3, "Residual contact pressure")
        contact_beta = safe_float(self.mesh_inputs["contact_beta"], 0.001, "Contact regularization beta")
        return {
            "literature_basis": [
                {
                    "id": "Chang2019_OceanEngineering",
                    "focus": "coupled tensile, torsional, and compressive loads; water-pressure-induced stiffness reduction",
                    "implementation_hint": "report axial-torsional coupling and compression/pressure softening metrics in result_summary.json",
                },
                {
                    "id": "Menard2023_MarineStructures",
                    "focus": "periodic homogenized 3D FE cell for cyclic bending with contact, friction, and residual pressure",
                    "implementation_hint": "use helical-period job domain, periodic boundary conditions, beam/surface armour modelling, and slip-state calibration",
                },
            ],
            "recommended_backend_sequence": [
                "validate bending moment-curvature loop",
                "calibrate friction and residual contact pressure using slip-zone stiffness and dissipated energy",
                "add axial-torsional stiffness matrix under coupled tension/torsion",
                "add compressive pressure sweep and bird-caging risk metric",
                "extract local stresses/displacements for fatigue-relevant components",
            ],
            "contact_model": {
                "normal": "penalty_or_augmented_lagrange",
                "tangential": "coulomb_regularized",
                "friction_coefficient": friction,
                "residual_contact_pressure_mpa": residual_pressure,
                "regularization_beta": contact_beta,
            },
            "contact_interfaces": [
                {
                    "name": "inner_armour_to_inner_sheath",
                    "master": "inner_armour_helical_beams_or_surfaces",
                    "slave": "inner_sheath_outer_surface",
                    "priority": "high",
                },
                {
                    "name": "inner_armour_to_bedding",
                    "master": "inner_armour_helical_beams_or_surfaces",
                    "slave": "bedding_inner_surface",
                    "priority": "high",
                },
                {
                    "name": "outer_armour_to_bedding",
                    "master": "outer_armour_helical_beams_or_surfaces",
                    "slave": "bedding_outer_surface",
                    "priority": "high",
                },
                {
                    "name": "outer_armour_to_outer_sheath",
                    "master": "outer_armour_helical_beams_or_surfaces",
                    "slave": "outer_sheath_inner_surface",
                    "priority": "high",
                },
                {
                    "name": "armour_cross_layer_interaction",
                    "master": "outer_armour_layer",
                    "slave": "inner_armour_layer",
                    "priority": "medium",
                },
            ],
            "contact_interface_defaults": {
                "normal": "penalty_or_augmented_lagrange",
                "tangential": "regularized_coulomb",
                "friction_coefficient": friction,
                "residual_contact_pressure_mpa": residual_pressure,
                "regularization_beta": contact_beta,
            },
            "periodic_cell": {
                "effective_length_mm": safe_float(self.cond["eff_length"], 234.2, "Effective length"),
                "strategy": self.mesh_value("model_strategy"),
                "armour_representation": self.mesh_value("armour_model"),
                "note": "234.2 mm is consistent with the helical-period style benchmark used in the literature notes.",
            },
        }

    def collect_study_scope(self) -> dict:
        return {
            "project_goal": "local behavior evaluation framework for submarine power cable",
            "enabled_assessments": {
                key: bool(widget.isChecked())
                for key, widget in self.study_checks.items()
            },
            "primary_gui_output": "moment-curvature hysteresis loop",
            "backend_note": "Abaqus backend may add extra CSV/JSON outputs for enabled non-bending assessments.",
        }

    def collect_materials(self) -> List[dict]:
        rows = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = name_item.text().strip() if name_item else f"Layer {row + 1}"
            rows.append({
                "index": row + 1,
                "name": name,
                "elastic_modulus_GPa": table_float(self.table, row, 1, 1.0, f"{name} E"),
                "poisson_ratio": table_float(self.table, row, 2, 0.3, f"{name} nu"),
                "density_kg_m3": table_float(self.table, row, 3, 0.0, f"{name} density"),
            })
        return rows

    def compute_equivalent_properties(self, materials: List[dict], dg: Dict[str, float]) -> dict:
        # GUI-side estimate only. Abaqus should compute final stiffness from the full model.
        e_copper_pa = materials[0]["elastic_modulus_GPa"] * 1e9
        r_cond_m = dg["conductor_radius_mm"] / 1000.0
        core_center_m = dg["core_center_radius_mm"] / 1000.0
        area_cond = math.pi * r_cond_m ** 2
        local_i = math.pi * r_cond_m ** 4 / 4.0
        # Improved over original: includes parallel-axis contribution for 3 off-center cores.
        i_three_core_about_center = 3.0 * (local_i + area_cond * core_center_m ** 2)
        ei_core = e_copper_pa * i_three_core_about_center
        return {
            "method": "3_copper_cores_with_parallel_axis_estimate_GUI_only",
            "core_equivalent_I_m4": i_three_core_about_center,
            "core_equivalent_EI_N_m2": ei_core,
            "warning": "Approximation only. Backend Abaqus result is authoritative.",
        }

    # ---------------- Actions ----------------
    def validate_inputs_dialog(self) -> None:
        try:
            payload = self.build_payload()
            msg = (
                "Inputs are valid.\n\n"
                f"Outer sheath radius: {payload['derived_geometry_mm']['outer_sheath_outer_radius_mm']:.3f} mm\n"
                f"Inner armour center radius: {payload['derived_geometry_mm']['inner_armour_center_radius_mm']:.3f} mm\n"
                f"Outer armour center radius: {payload['derived_geometry_mm']['outer_armour_center_radius_mm']:.3f} mm\n"
                f"Estimated EI: {payload['equivalent_properties']['core_equivalent_EI_N_m2']:.6g} N.m^2\n"
                f"Enabled assessments: {', '.join(k for k, v in payload['study_scope']['enabled_assessments'].items() if v)}"
            )
            self.set_badge(self.lbl_model_status, "Model: valid", "good")
            QMessageBox.information(self, "Validation complete", msg)
        except Exception as exc:
            self.set_badge(self.lbl_model_status, "Model: error", "error")
            QMessageBox.critical(self, "Validation error", str(exc))

    def export_json_dialog(self) -> None:
        try:
            payload = self.build_payload()
            path, _ = QFileDialog.getSaveFileName(self, "Save Abaqus input JSON", "input_data.json", "JSON Files (*.json)")
            if path:
                write_json(Path(path), payload)
                QMessageBox.information(self, "Saved", f"JSON saved:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))

    def selected_mode(self) -> str:
        if self.radio_package.isChecked():
            return "LOCAL_FOLDER"
        if self.radio_local.isChecked():
            return "LOCAL_COMMAND"
        if self.radio_remote.isChecked():
            return "REMOTE_SSH"
        return "FAST"

    def remote_config(self) -> dict:
        return {
            "local_command": self.local_command_input.text().strip(),
            "remote_target": self.remote_target_input.text().strip(),
            "remote_root": self.remote_root_input.text().strip(),
            "remote_command": self.remote_command_input.text().strip(),
        }

    def run_analysis(self) -> None:
        try:
            self.save_settings()
            payload = self.build_payload()
            job_root = Path(self.job_root_input.text().strip()).expanduser()
            mode = self.selected_mode()
            self.console.clear()
            self.log(f"[SYS] Starting mode: {mode}")
            self.set_badge(self.lbl_model_status, "Model: valid", "good")
            self.set_badge(self.lbl_result_status, "Result: running", "busy")
            self.progress.setValue(0)
            self.btn_run.setEnabled(False)
            self.curve.setData([], [])
            self.worker = AnalysisWorker(payload, mode, job_root, self.remote_config())
            self.worker.log_sig.connect(self.log)
            self.worker.progress_sig.connect(self.progress.setValue)
            self.worker.plot_sig.connect(self.update_plot)
            self.worker.metrics_sig.connect(self.update_metrics)
            self.worker.summary_sig.connect(self.update_summary_panel)
            self.worker.finished_sig.connect(self.analysis_finished)
            self.worker.start()
        except Exception as exc:
            self.set_badge(self.lbl_model_status, "Model: error", "error")
            self.set_badge(self.lbl_result_status, "Result: stopped", "error")
            QMessageBox.critical(self, "Run error", str(exc))
            self.btn_run.setEnabled(True)

    def collect_settings(self) -> dict:
        def widget_value(widget):
            if isinstance(widget, QLineEdit):
                return widget.text()
            if isinstance(widget, QSpinBox):
                return widget.value()
            if isinstance(widget, QComboBox):
                return widget.currentText()
            return None

        return {
            "version": APP_VERSION,
            "ui": {"language": self.ui_language},
            "geometry": {key: widget_value(widget) for key, widget in self.inputs.items()},
            "analysis_conditions": {key: widget_value(widget) for key, widget in self.cond.items()},
            "study_scope": {key: widget.isChecked() for key, widget in self.study_checks.items()},
            "mesh": {key: widget_value(widget) for key, widget in self.mesh_inputs.items()},
            "backend": {
                "mode": self.selected_mode(),
                "job_root": self.job_root_input.text().strip(),
                "local_command": self.local_command_input.text().strip(),
                "remote_target": self.remote_target_input.text().strip(),
                "remote_root": self.remote_root_input.text().strip(),
                "remote_command": self.remote_command_input.text().strip(),
            },
        }

    def apply_settings_data(self, settings: dict) -> None:
        def set_widget(widget, value):
            if value is None:
                return
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, QComboBox):
                idx = widget.findText(str(value))
                if idx < 0:
                    legacy_labels = {
                        "periodic_homogenized_cell": "Periodic homogenized cell",
                        "full_3d_segment": "Full 3D segment",
                        "axisymmetric_tension_torsion": "Axisymmetric tension/torsion",
                        "beam_with_contact_surface": "Beam + contact surface",
                        "solid_wire": "Solid wire",
                        "analytical_equivalent": "Analytical equivalent",
                    }
                    idx = widget.findText(legacy_labels.get(str(value), ""))
                if idx >= 0:
                    widget.setCurrentIndex(idx)

        for key, value in settings.get("geometry", {}).items():
            if key in self.inputs:
                set_widget(self.inputs[key], value)
        for key, value in settings.get("analysis_conditions", {}).items():
            if key in self.cond:
                set_widget(self.cond[key], value)
        for key, value in settings.get("study_scope", {}).items():
            if key in self.study_checks:
                self.study_checks[key].setChecked(bool(value))
        for key, value in settings.get("mesh", {}).items():
            if key in self.mesh_inputs:
                set_widget(self.mesh_inputs[key], value)

        backend = settings.get("backend", {})
        if backend.get("job_root"):
            self.job_root_input.setText(str(backend["job_root"]))
        if backend.get("local_command"):
            self.local_command_input.setText(normalize_local_backend_command(str(backend["local_command"])))
        if backend.get("remote_target"):
            self.remote_target_input.setText(str(backend["remote_target"]))
        if backend.get("remote_root"):
            self.remote_root_input.setText(str(backend["remote_root"]))
        if backend.get("remote_command"):
            self.remote_command_input.setText(str(backend["remote_command"]))

        mode = backend.get("mode", "FAST")
        mode_buttons = {
            "FAST": self.radio_fast,
            "LOCAL_FOLDER": self.radio_package,
            "LOCAL_COMMAND": self.radio_local,
            "REMOTE_SSH": self.radio_remote,
        }
        mode_buttons.get(mode, self.radio_fast).setChecked(True)
        language = settings.get("ui", {}).get("language", "EN")
        self.ui_language = "KO" if language == "KO" else "EN"
        self.apply_language()

    def load_settings(self) -> None:
        try:
            self.apply_settings_data(read_json(SETTINGS_PATH, {}))
        except Exception as exc:
            self.log(f"[SETTINGS] Could not load settings: {exc}")

    def save_settings(self) -> None:
        try:
            write_json(SETTINGS_PATH, self.collect_settings())
        except Exception as exc:
            self.log(f"[SETTINGS] Could not save settings: {exc}")

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)

    def analysis_finished(self, job_dir: str) -> None:
        self.btn_run.setEnabled(True)
        if job_dir:
            self.last_job_dir = job_dir
            self.log(f"[SYS] Job folder: {job_dir}")
            self.set_badge(self.lbl_result_status, "Result: ready", "good")
            self.refresh_job_history()
        else:
            self.set_badge(self.lbl_result_status, "Result: error", "error")

    def load_result_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open result_data.csv", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            self.load_result_bundle(Path(path), source="MANUAL_CSV_LOAD")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "CSV load error", str(exc))

    def load_result_bundle(self, csv_path: Path, source: str = "RESULT_LOAD") -> None:
        k, m = read_result_csv(csv_path)
        metrics = make_metrics(k, m, source=source)
        self.update_plot(k, m)
        self.update_metrics(metrics)
        summary = read_json(csv_path.with_name("result_summary.json"), metrics)
        if isinstance(summary, dict):
            summary.setdefault("source", metrics.get("source", source))
            summary.setdefault("num_points", metrics["num_points"])
            summary.setdefault("max_abs_moment_kn_m", metrics["max_abs_moment_kn_m"])
            summary.setdefault("hysteresis_loss_kj_per_m_proxy", metrics["hysteresis_loss_kj_per_m_proxy"])
        self.update_summary_panel(summary)
        self.set_badge(self.lbl_result_status, "Result: loaded", "good")
        self.log(f"[RESULT] Loaded {csv_path}")

    def refresh_job_history(self) -> None:
        if not hasattr(self, "job_history_combo"):
            return
        roots = [DEFAULT_JOB_ROOT]
        try:
            configured = Path(self.job_root_input.text().strip()).expanduser()
            if configured not in roots:
                roots.append(configured)
        except Exception:
            pass

        jobs: List[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for csv_path in root.glob("*/result_data.csv"):
                jobs.append(csv_path.parent)
        jobs = sorted(set(jobs), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:25]

        self.job_history_paths = jobs
        self.job_history_combo.clear()
        if not jobs:
            self.job_history_combo.addItem(self.ui_text("No result jobs found"))
            return
        for job in jobs:
            stamp = datetime.fromtimestamp(job.stat().st_mtime).strftime("%m-%d %H:%M")
            self.job_history_combo.addItem(f"{stamp} | {job.name}")

    def load_selected_job(self) -> None:
        index = self.job_history_combo.currentIndex() if hasattr(self, "job_history_combo") else -1
        if index < 0 or index >= len(self.job_history_paths):
            QMessageBox.information(self, "Recent Jobs", "No result job is selected.")
            return
        try:
            self.load_result_bundle(self.job_history_paths[index] / "result_data.csv", source="RECENT_JOB_LOAD")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Recent job load error", str(exc))

    def load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open key,value CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            aliases = {
                "Radius of Conductor": "r_cond",
                "Radius of Insulation": "r_insu",
                "Radius of Core": "roc",
                "Centre of Core": "coc",
                "Center of Core": "coc",
                "Thickness of Inner Sheath": "tis",
                "Number of Inner Armour": "no_ia",
                "Radius of Inner Armour": "r_ia",
                "Number of Outer Armour": "no_oa",
                "Radius of Outer Armour": "r_oa",
                "Thickness of Outer Sheath": "tos",
                "Length": "eff_length",
                "Helix Angle of Inner Armour": "inner_lay_angle",
                "Helix Angle of Outer Armour": "outer_lay_angle",
            }
            updated = 0
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 2:
                        continue
                    raw_key, value = row[0].strip(), row[1].strip()
                    if not raw_key or not value:
                        continue
                    key = raw_key if raw_key in self.inputs else aliases.get(raw_key)
                    target = self.inputs if key in self.inputs else self.cond if key in self.cond else None
                    if target:
                        widget = target[key]
                        if isinstance(widget, QLineEdit):
                            widget.setText(str(parse_csv_number(value)))
                        elif isinstance(widget, QSpinBox):
                            widget.setValue(int(round(parse_csv_number(value))))
                        updated += 1
            QMessageBox.information(self, "CSV loaded", f"Updated {updated} fields.")
        except Exception as exc:
            QMessageBox.critical(self, "CSV load error", str(exc))

    # ---------------- Plot / geometry ----------------
    def update_plot(self, k: np.ndarray, m: np.ndarray) -> None:
        self.current_k = k
        self.current_m = m
        self.curve.setData(k, m)
        self.plot_canvas.autoRange()

    def update_metrics(self, data: dict) -> None:
        self.current_metrics = dict(data)
        self.lbl_peak.value_label.setText(f"{data['max_abs_moment_kn_m']:.4g} kN.m")
        self.lbl_loss.value_label.setText(f"{data['hysteresis_loss_kj_per_m_proxy']:.4g}")
        self.lbl_points.value_label.setText(str(data["num_points"]))
        self.update_compare_panel()

    def update_compare_panel(self) -> None:
        if not hasattr(self, "lbl_compare_count"):
            return
        source = str(self.current_metrics.get("source", "FAST")).replace("_GUI_APPROXIMATION", "")
        self.lbl_compare_primary.value_label.setText(source[:14] if source else "FAST")
        if not self.compare_metrics:
            self.lbl_compare_count.value_label.setText(self.ui_text("None"))
            self.lbl_compare_peak_delta.value_label.setText("-")
            self.lbl_compare_loss_delta.value_label.setText("-")
            return

        latest = self.compare_metrics[-1]
        count_text = f"{len(self.compare_metrics)} CSV"
        self.lbl_compare_count.value_label.setText(count_text)

        primary_peak = float(self.current_metrics.get("max_abs_moment_kn_m", 0.0))
        compare_peak = float(latest.get("max_abs_moment_kn_m", 0.0))
        primary_loss = float(self.current_metrics.get("hysteresis_loss_kj_per_m_proxy", 0.0))
        compare_loss = float(latest.get("hysteresis_loss_kj_per_m_proxy", 0.0))

        def pct_delta(new: float, base: float) -> str:
            if abs(base) < 1e-12:
                return "-"
            return f"{((new - base) / abs(base)) * 100.0:+.1f}%"

        self.lbl_compare_peak_delta.value_label.setText(pct_delta(compare_peak, primary_peak))
        self.lbl_compare_loss_delta.value_label.setText(pct_delta(compare_loss, primary_loss))

    def export_plot_png(self) -> None:
        if not hasattr(self, "plot_canvas"):
            return
        default = str(PROJECT_DIR / "moment_curvature_result.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save plot image", default, "PNG Images (*.png)")
        if not path:
            return
        ok = self.plot_canvas.grab().save(path, "PNG")
        if ok:
            self.log(f"[RESULT] Plot image saved: {path}")
            QMessageBox.information(self, "Plot exported", f"Saved:\n{path}")
        else:
            QMessageBox.critical(self, "Plot export error", "Could not save the PNG image.")

    def compare_result_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Compare result_data.csv", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            k, m = read_result_csv(Path(path))
            metrics = make_metrics(k, m, source=Path(path).parent.name or "COMPARE_CSV")
            color_cycle = ["#e08f3e", "#10b981", "#d946ef", "#f43f5e"]
            color = color_cycle[len(self.compare_items) % len(color_cycle)]
            item = self.plot_canvas.plot(
                k,
                m,
                pen=pg.mkPen(color=color, width=2.2, style=Qt.DashLine),
                name=Path(path).parent.name,
            )
            self.compare_items.append(item)
            self.compare_metrics.append(metrics)
            self.plot_canvas.autoRange()
            self.log(f"[RESULT] Comparison curve added: {path}")
            self.update_compare_panel()
            compare_text = (
                f"결과: 비교 {len(self.compare_items)}개"
                if self.ui_language == "KO"
                else f"Result: +{len(self.compare_items)} compare"
            )
            self.lbl_result_status.setProperty("en_text", f"Result: +{len(self.compare_items)} compare")
            self.lbl_result_status.setText(compare_text)
            self.lbl_result_status.setStyleSheet(
                "color: #1d4ed8; background-color: #eff6ff; border: 1px solid #bfdbfe; "
                "border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 650;"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Compare CSV error", str(exc))

    def clear_compare_curves(self) -> None:
        for item in self.compare_items:
            try:
                self.plot_canvas.removeItem(item)
            except Exception:
                pass
        self.compare_items.clear()
        self.compare_metrics.clear()
        self.plot_canvas.autoRange()
        self.update_compare_panel()
        self.set_badge(self.lbl_result_status, "Result: ready", "good" if len(self.current_k) else "neutral")
        self.log("[RESULT] Comparison curves cleared.")

    def set_plot_focus(self, enabled: bool) -> None:
        self.btn_focus_plot.setProperty("en_text", "Show Details" if enabled else "Focus Plot")
        self.btn_focus_plot.setText(self.ui_text("Show Details" if enabled else "Focus Plot"))
        self.plot_canvas.setMinimumHeight(700 if enabled else 520)
        for widget_name in ["metric_panel", "compare_panel", "summary_text", "history_box"]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setVisible(not enabled)
        QTimer.singleShot(0, self.plot_canvas.autoRange)

    def update_summary_panel(self, data: dict) -> None:
        if not hasattr(self, "summary_text"):
            return
        self.last_summary_data = data if isinstance(data, dict) else {}
        self.summary_text.setPlainText(self.format_summary(data))

    def format_summary(self, data: dict) -> str:
        if not data:
            return "결과 요약이 없습니다." if self.ui_language == "KO" else "No result summary loaded."

        def value(path, default="-"):
            node = data
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return node

        enabled = value(["study_scope", "enabled_assessments"], {})
        if isinstance(enabled, dict):
            enabled_text = ", ".join(key for key, flag in enabled.items() if flag) or "none"
        else:
            enabled_text = "-"

        mesh_status = value(["mesh_status", "status"], value(["mesh_status"], "-"))
        derived = data.get("derived_placeholder_metrics", {})
        if self.ui_language == "KO":
            lines = [
                f"출처: {data.get('source', '-')}",
                f"상태: {data.get('status', 'loaded')}",
                f"계산 시각: {data.get('computed_at', '-')}",
                f"최대 |M|: {float(data.get('max_abs_moment_kn_m', 0.0)):.6g} kN.m",
                f"루프 손실: {float(data.get('hysteresis_loss_kj_per_m_proxy', 0.0)):.6g}",
                f"데이터 수: {data.get('num_points', '-')}",
                f"메시 상태: {mesh_status}",
                f"활성 연구 범위: {enabled_text}",
            ]
        else:
            lines = [
                f"Source: {data.get('source', '-')}",
                f"Status: {data.get('status', 'loaded')}",
                f"Computed: {data.get('computed_at', '-')}",
                f"Peak |M|: {float(data.get('max_abs_moment_kn_m', 0.0)):.6g} kN.m",
                f"Loop loss: {float(data.get('hysteresis_loss_kj_per_m_proxy', 0.0)):.6g}",
                f"Points: {data.get('num_points', '-')}",
                f"Mesh status: {mesh_status}",
                f"Enabled scope: {enabled_text}",
            ]

        readiness = data.get("backend_readiness", {})
        if isinstance(readiness, dict):
            status_lines = []
            for key in [
                "bending_stick_slip",
                "contact_friction",
                "torsion",
                "tension_bending_coupling",
                "compression_bird_caging",
                "pressure_effect",
            ]:
                item = readiness.get(key)
                if isinstance(item, dict) and item.get("requested"):
                    status_lines.append(f"- {key}: {item.get('status', '-')}")
            if status_lines:
                heading = "백엔드 준비도:" if self.ui_language == "KO" else "Backend readiness:"
                lines.extend(["", heading] + status_lines)

        if derived:
            if self.ui_language == "KO":
                lines.extend([
                    "",
                    "연구 지표:",
                    f"- 슬립 강성: {float(derived.get('bending_stiffness_slip_N_m2', 0.0)):.6g} N.m^2",
                    f"- 압력 연화: {float(derived.get('pressure_softening_factor', 0.0)):.4g}",
                    f"- bird-caging 위험: {float(derived.get('bird_caging_risk_index', 0.0)):.4g}",
                    f"- 비틀림 지표: {float(derived.get('torsion_proxy_N_m2', 0.0)):.6g} N.m^2",
                ])
            else:
                lines.extend([
                    "",
                    "Research proxies:",
                    f"- slip stiffness: {float(derived.get('bending_stiffness_slip_N_m2', 0.0)):.6g} N.m^2",
                    f"- pressure softening: {float(derived.get('pressure_softening_factor', 0.0)):.4g}",
                    f"- bird-caging risk: {float(derived.get('bird_caging_risk_index', 0.0)):.4g}",
                    f"- torsion proxy: {float(derived.get('torsion_proxy_N_m2', 0.0)):.6g} N.m^2",
                ])

        note = data.get("note")
        if note:
            lines.extend(["", f"{'메모' if self.ui_language == 'KO' else 'Note'}: {note}"])
        return "\n".join(lines)

    def trigger_rebuild(self) -> None:
        if hasattr(self, "lbl_model_status"):
            self.set_badge(self.lbl_model_status, "Model: edited", "warn")
        if hasattr(self, "debounce"):
            self.debounce.start(120)

    def toggle_view_mode(self) -> None:
        self.view_mode = "3D" if self.view_mode == "2D" else "2D"
        if self.view_mode == "2D":
            self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        else:
            self.view_solid.setCameraPosition(distance=250, elevation=35, azimuth=45)
        self.rebuild_solid_geometry()

    def reset_solid_view(self) -> None:
        if self.view_mode == "2D":
            self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        else:
            self.view_solid.setCameraPosition(distance=250, elevation=35, azimuth=45)

    def reset_mesh_view(self) -> None:
        self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)

    def set_mesh_iso_view(self) -> None:
        self.view_wire.setCameraPosition(distance=190, elevation=35, azimuth=45)

    def create_solid_mesh(self, r: float, cx: float, cy: float, z_front: float, color) -> gl.GLMeshItem:
        if self.view_mode == "2D":
            t = np.linspace(0, 2 * np.pi, 48, endpoint=False)
            verts = [[cx, cy, z_front]] + [[cx + r * np.cos(a), cy + r * np.sin(a), z_front] for a in t]
            faces = [[0, i, i + 1] for i in range(1, len(t))]
            faces.append([0, len(t), 1])
            return gl.GLMeshItem(vertexes=np.array(verts), faces=np.array(faces), faceColors=np.tile(color, (len(faces), 1)), smooth=False, shader=None)
        md = gl.MeshData.cylinder(rows=1, cols=48, radius=[r, r], length=50.0)
        item = gl.GLMeshItem(meshdata=md, smooth=True, color=color, shader="shaded")
        item.translate(cx, cy, z_front - 50.0)
        return item

    def rebuild_solid_geometry(self) -> None:
        for item in self.mesh_cache_solid:
            try:
                self.view_solid.removeItem(item)
            except Exception:
                pass
        self.mesh_cache_solid.clear()
        try:
            dg = self.parse_geometry()
            if self.layer_visible("outer_sheath"):
                self.add_solid(dg["outer_sheath_outer_radius_mm"], 0, 0, 0.0, [0.15, 0.15, 0.15, 0.88])
            if self.layer_visible("outer_armour"):
                for i in range(dg["outer_armour_wire_count"]):
                    a = 2 * np.pi * i / dg["outer_armour_wire_count"]
                    self.add_solid(
                        dg["outer_armour_wire_radius_mm"],
                        dg["outer_armour_center_radius_mm"] * np.cos(a),
                        dg["outer_armour_center_radius_mm"] * np.sin(a),
                        0.1,
                        [0.5, 0.6, 0.7, 1.0],
                    )
            if self.layer_visible("bedding"):
                self.add_solid(dg["bedding_outer_radius_mm"], 0, 0, 0.2, [0.4, 0.3, 0.2, 0.72])
            if self.layer_visible("inner_armour"):
                for i in range(dg["inner_armour_wire_count"]):
                    a = 2 * np.pi * i / dg["inner_armour_wire_count"]
                    self.add_solid(
                        dg["inner_armour_wire_radius_mm"],
                        dg["inner_armour_center_radius_mm"] * np.cos(a),
                        dg["inner_armour_center_radius_mm"] * np.sin(a),
                        0.3,
                        [0.4, 0.5, 0.6, 1.0],
                    )
            if self.layer_visible("inner_sheath"):
                self.add_solid(dg["inner_sheath_outer_radius_mm"], 0, 0, 0.4, [0.1, 0.1, 0.1, 0.82])
                self.add_solid(dg["inner_sheath_inner_radius_mm"], 0, 0, 0.5, [0.25, 0.25, 0.28, 0.72])
            if self.layer_visible("cores"):
                for i in range(3):
                    a = np.radians(120 * i)
                    cx = dg["core_center_radius_mm"] * np.cos(a)
                    cy = dg["core_center_radius_mm"] * np.sin(a)
                    self.add_solid(dg["core_outer_radius_mm"], cx, cy, 0.6, [0.6, 0.6, 0.65, 1.0])
                    self.add_solid(dg["insulation_radius_mm"], cx, cy, 0.7, [0.9, 0.9, 0.9, 0.9])
                    self.add_solid(dg["conductor_radius_mm"], cx, cy, 0.8, [0.85, 0.45, 0.15, 1.0])
        except Exception as exc:
            self.log(f"[GEOMETRY] {exc}")

    def add_solid(self, r, cx, cy, z, color) -> None:
        item = self.create_solid_mesh(r, cx, cy, z, color)
        self.view_solid.addItem(item)
        self.mesh_cache_solid.append(item)

    def estimate_mesh_elements(self, dg: dict) -> int:
        z_elem = int(self.mesh_inputs["z_elem"].value())
        core_div = int(self.mesh_inputs["c_elem_core"].value())
        armour_div = int(self.mesh_inputs["c_elem_armour"].value())
        core_solids = 3 * z_elem * core_div * 2
        sheath_solids = z_elem * core_div * 3
        armour_beams = z_elem * armour_div * (
            int(dg["inner_armour_wire_count"]) + int(dg["outer_armour_wire_count"])
        )
        return int(core_solids + sheath_solids + armour_beams)

    def update_mesh_readiness(self, dg: dict) -> None:
        if not hasattr(self, "lbl_mesh_ready"):
            return
        estimated = self.estimate_mesh_elements(dg)
        self.lbl_mesh_ready.value_label.setText(self.ui_text("Preview ready"))
        self.lbl_mesh_elements.value_label.setText(f"{estimated:,}")
        self.lbl_mesh_contacts.value_label.setText("5")

    def generate_mesh_preview(self) -> None:
        for item in self.mesh_cache_wire:
            try:
                self.view_wire.removeItem(item)
            except Exception:
                pass
        self.mesh_cache_wire.clear()
        try:
            dg = self.parse_geometry()
            def add_wire(r, cx, cy, rows, cols, edge_color):
                md = gl.MeshData.cylinder(rows=rows, cols=cols, radius=[r, r], length=80.0)
                item = gl.GLMeshItem(meshdata=md, drawEdges=True, edgeColor=edge_color, color=(0, 0, 0, 0), smooth=False, shader=None)
                item.translate(cx, cy, -40.0)
                self.view_wire.addItem(item)
                self.mesh_cache_wire.append(item)
            add_wire(dg["outer_sheath_outer_radius_mm"], 0, 0, self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_core"].value(), (0.54, 0.70, 1.0, 0.62))
            for i in range(dg["inner_armour_wire_count"]):
                a = 2 * np.pi * i / dg["inner_armour_wire_count"]
                add_wire(dg["inner_armour_wire_radius_mm"], dg["inner_armour_center_radius_mm"] * np.cos(a), dg["inner_armour_center_radius_mm"] * np.sin(a), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.82, 0.82, 0.84, 0.86))
            for i in range(dg["outer_armour_wire_count"]):
                a = 2 * np.pi * i / dg["outer_armour_wire_count"]
                add_wire(dg["outer_armour_wire_radius_mm"], dg["outer_armour_center_radius_mm"] * np.cos(a), dg["outer_armour_center_radius_mm"] * np.sin(a), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.63, 0.72, 0.92, 0.86))
            self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)
            self.update_mesh_readiness(dg)
        except Exception as exc:
            QMessageBox.critical(self, "Mesh preview error", str(exc))

    # ---------------- Misc ----------------
    def log(self, message: str) -> None:
        if hasattr(self, "console"):
            self.console.append(message)

    def update_telemetry(self) -> None:
        self.lbl_hw.setText(f"HW: CPU {psutil.cpu_percent():.0f}% | RAM {psutil.virtual_memory().percent:.0f}%")

    def apply_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #eef2f6;
                color: #18212d;
                font-family: "Segoe UI", "Malgun Gothic", Arial;
            }
            QWidget {
                color: #18212d;
                font-size: 13px;
            }
            QLabel {
                color: #243244;
                font-size: 13px;
            }
            QFrame#Sidebar {
                background-color: #f6f8fb;
                border-right: 1px solid #d7dee8;
            }
            QFrame#ContentPane {
                background-color: #eef2f6;
            }
            QFrame#WorkspaceFrame {
                background-color: transparent;
                border: none;
            }
            QLabel#SidebarBrand {
                color: #132033;
                font-size: 24px;
                font-weight: 750;
                padding-top: 2px;
            }
            QLabel#SidebarSub {
                color: #64748b;
                font-size: 12px;
                padding-bottom: 12px;
            }
            QLabel#TeamLogo {
                background-color: #ffffff;
                border: 1px solid #d9e1ea;
                border-radius: 8px;
                padding: 8px;
                margin-bottom: 6px;
            }
            QLabel#SidebarSection {
                color: #738196;
                font-size: 11px;
                font-weight: 700;
                padding: 8px 8px 4px 8px;
            }
            QLabel#SidebarStatus {
                color: #405066;
                background-color: #ffffff;
                border: 1px solid #d9e1ea;
                border-radius: 8px;
                padding: 9px 10px;
                font-size: 12px;
            }
            QLabel#AppTitle {
                color: #111827;
                font-size: 22px;
                font-weight: 750;
            }
            QLabel#AppSubtitle {
                color: #65758b;
                font-size: 12px;
            }
            QLabel#TopbarMeta {
                color: #405066;
                background-color: #ffffff;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 650;
            }
            QPushButton#LangToggle {
                color: #0f3a72;
                background-color: #dfeafb;
                border: 1px solid #b9cdea;
                border-radius: 8px;
                padding: 6px 8px;
                font-size: 12px;
                font-weight: 750;
            }
            QPushButton#LangToggle:hover {
                background-color: #d2e4fb;
                border-color: #9dbde8;
            }
            QPushButton#NavButton {
                background-color: transparent;
                color: #334155;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 8px 10px;
                text-align: left;
                font-size: 13px;
                font-weight: 650;
            }
            QPushButton#NavButton:hover {
                background-color: #e8eef6;
                border-color: #d6deea;
            }
            QPushButton#NavButton:checked {
                background-color: #dfeafb;
                color: #0f3a72;
                border: 1px solid #b9cdea;
            }
            QFrame#Card {
                background-color: #ffffff;
                border-radius: 8px;
                border: 1px solid #d7dee8;
                padding: 8px;
            }
            QFrame#MetricBox {
                background-color: #ffffff;
                border-radius: 8px;
                border: 1px solid #d7dee8;
                border-left: 4px solid #1f6feb;
                padding: 8px;
            }
            QFrame#MetricStrip {
                background-color: transparent;
                border: none;
            }
            QFrame#CollapsibleSection {
                background-color: transparent;
                border: none;
                margin-bottom: 4px;
            }
            QPushButton#SectionToggle {
                background-color: #f8fafc;
                color: #1f2937;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                padding: 8px 10px;
                text-align: left;
                font-size: 13px;
                font-weight: 750;
            }
            QPushButton#SectionToggle:hover {
                background-color: #eef4fb;
                border-color: #b8c7da;
            }
            QScrollArea#PanelScroll {
                background-color: transparent;
                border: none;
            }
            QScrollArea#PanelScroll > QWidget > QWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                background: #eef2f6;
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #b7c2d0;
                border-radius: 5px;
                min-height: 34px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QGroupBox {
                color: #1f2937;
                background-color: #ffffff;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                margin-top: 10px;
                padding: 12px;
                font-weight: 650;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #fbfcfe;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                padding: 7px 9px;
                color: #111827;
                font-size: 13px;
                font-weight: 500;
                selection-background-color: #bcd7ff;
            }
            QLineEdit:hover, QSpinBox:hover, QComboBox:hover {
                border-color: #98a7bb;
                background-color: #ffffff;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #1f6feb;
                background-color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QPushButton {
                background-color: #ffffff;
                color: #1f2937;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                font-size: 13px;
                font-weight: 650;
                padding: 8px 11px;
            }
            QPushButton:hover {
                background-color: #f5f8fc;
                border-color: #9fb0c4;
            }
            QPushButton:pressed {
                background-color: #e8eef6;
                padding-top: 9px;
                padding-left: 12px;
            }
            QPushButton#RunBtn {
                background-color: #1f6feb;
                color: #ffffff;
                border: 1px solid #1f6feb;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#RunBtn:hover {
                background-color: #185fc9;
                border-color: #185fc9;
            }
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f7f9fc;
                color: #172033;
                font-size: 12px;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                gridline-color: #e5eaf1;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
            }
            QHeaderView::section {
                background-color: #edf2f8;
                color: #1f2937;
                font-weight: 700;
                border: none;
                border-right: 1px solid #d7dee8;
                border-bottom: 1px solid #d7dee8;
                padding: 7px;
            }
            QTextEdit {
                background-color: #0f172a;
                color: #dbeafe;
                font-family: Consolas, "Cascadia Mono", monospace;
                border: 1px solid #233148;
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
            }
            QTextEdit#SummaryText {
                background-color: #fbfcfe;
                color: #253247;
                font-family: "Segoe UI", "Malgun Gothic", Arial;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                padding: 10px;
                font-size: 12px;
                line-height: 1.35;
            }
            QProgressBar {
                background-color: #edf2f8;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                text-align: center;
                color: #1f2937;
                font-weight: 650;
                min-height: 18px;
            }
            QProgressBar::chunk {
                background-color: #1f6feb;
                border-radius: 6px;
            }
            QRadioButton, QCheckBox {
                font-size: 13px;
                font-weight: 500;
                color: #243244;
                padding: 3px;
            }
            QRadioButton::indicator, QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
        """)

def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    pg.setConfigOptions(antialias=True)
    window = SCLASRemoteGUI()
    window.show()
    smoke_ms = os.environ.get("SCLAS_GUI_SMOKE_EXIT_MS", "").strip()
    if smoke_ms:
        QTimer.singleShot(max(int(smoke_ms), 1), app.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
