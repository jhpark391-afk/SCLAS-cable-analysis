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
from PyQt5.QtGui import QColor, QIcon, QPixmap
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg
import pyqtgraph.opengl as gl

APP_VERSION = "10.4-literature-informed"
CONTRACT_VERSION = "sclas-abaqus-contract-v1"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_JOB_ROOT = PROJECT_DIR / "jobs" / "SCLAS_jobs"
SETTINGS_PATH = PROJECT_DIR / "settings.json"
BACKEND_RUNNER_TEMPLATE = APP_DIR / "abaqus_runner.py"


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
        self.write_result_files(k, m_kn_m, source="FAST_GUI_APPROXIMATION")
        self.progress_sig.emit(100)
        self.plot_sig.emit(k, m_kn_m)
        self.metrics_sig.emit(make_metrics(k, m_kn_m, source="FAST_GUI_APPROXIMATION"))
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
        self.plot_sig.emit(k, m)
        self.metrics_sig.emit(make_metrics(k, m, source="ABAQUS_BACKEND"))
        self.progress_sig.emit(100)
        self.log_sig.emit("[RESULT] Loaded result_data.csv successfully.")
        self.finished_sig.emit(str(self.job_dir))

    def write_result_files(self, k: np.ndarray, m_knm: np.ndarray, source: str) -> None:
        result_csv = self.job_dir / "result_data.csv"
        with result_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["curvature_1_per_m", "moment_kn_m"])
            for ki, mi in zip(k, m_knm):
                writer.writerow([f"{ki:.12g}", f"{mi:.12g}"])
        write_json(self.job_dir / "result_summary.json", make_metrics(k, m_knm, source=source))


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
  "max_abs_moment_kn_m": 123.4,
  "torsion_stiffness_proxy": 12.3,
  "tension_bending_coupling_index": 0.002,
  "bird_caging_risk_index": 0.018,
  "odb_path": "...",
  "status": "completed"
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
        self.last_job_dir = ""
        self.setWindowTitle(f"SCLAS {APP_VERSION} | Cable GUI Frontend + Abaqus Remote Contract")
        self.resize(1540, 860)
        self.init_ui()
        self.apply_theme()
        self.load_settings()

        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self.update_telemetry)
        self.sys_timer.start(1000)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.rebuild_solid_geometry)
        self.trigger_rebuild()

    # ---------------- UI builders ----------------
    def init_ui(self) -> None:
        main = QWidget()
        root = QVBoxLayout(main)
        root.setContentsMargins(14, 14, 14, 14)
        self.setCentralWidget(main)
        self.tabs = QTabWidget()
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs)
        self.build_design_tab()
        self.build_mesh_tab()
        self.build_analysis_tab()

    def build_design_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setSpacing(15)

        panel_inputs = QFrame(); panel_inputs.setObjectName("Card")
        left = QVBoxLayout(panel_inputs)
        left.addWidget(self.header("Cable Geometry Inputs"))
        self.btn_load_csv = QPushButton("Load key,value CSV")
        self.btn_load_csv.setFixedHeight(42)
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

        form = QFormLayout(); form.setVerticalSpacing(10)
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
            form.addRow(label, self.inputs[key])
        left.addLayout(form)
        left.addStretch()

        panel_mat = QFrame(); panel_mat.setObjectName("Card")
        mid = QVBoxLayout(panel_mat)
        mid.addWidget(self.header("Material Table"))
        self.table = QTableWidget(9, 4)
        self.table.setHorizontalHeaderLabels(["Layer", "E_GPa", "Nu", "Density_kg_m3"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.init_material_table()
        mid.addWidget(self.table)

        panel_view = QFrame(); panel_view.setObjectName("Card")
        right = QVBoxLayout(panel_view)
        header = QHBoxLayout()
        header.addWidget(self.header("Digital Twin View"))
        self.btn_toggle = QPushButton("Toggle 2D / 3D")
        self.btn_toggle.clicked.connect(self.toggle_view_mode)
        header.addWidget(self.btn_toggle)
        right.addLayout(header)
        self.view_solid = gl.GLViewWidget()
        self.view_solid.setBackgroundColor("#141419")
        self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        right.addWidget(self.view_solid)

        layout.addWidget(panel_inputs, 22)
        layout.addWidget(panel_mat, 30)
        layout.addWidget(panel_view, 48)
        self.tabs.addTab(tab, "1 Design")

        for w in self.inputs.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self.trigger_rebuild)
            else:
                w.valueChanged.connect(self.trigger_rebuild)

    def build_mesh_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setSpacing(14)
        panel = QFrame(); panel.setObjectName("Card"); panel.setFixedWidth(500)
        left = QVBoxLayout(panel)
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
        for key in ["elem_type", "model_strategy", "armour_model", "contact_beta"]:
            self.mesh_inputs[key].setMinimumWidth(250)
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
        self.btn_mesh.clicked.connect(self.generate_mesh_preview)
        left.addWidget(self.btn_mesh)
        note = QLabel("Visual request only. Abaqus backend owns actual mesh generation.")
        note.setWordWrap(True)
        left.addWidget(note)
        left.addStretch()

        viewer = QFrame(); viewer.setObjectName("Card")
        right = QVBoxLayout(viewer)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)
        right.addWidget(self.header("Preview Only"))
        self.view_wire = gl.GLViewWidget()
        self.view_wire.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_wire.setMinimumHeight(620)
        self.view_wire.setBackgroundColor("#0a0a0f")
        self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)
        right.addWidget(self.view_wire, 1)
        layout.addWidget(panel)
        layout.addWidget(viewer, 1)
        self.tabs.addTab(tab, "2 Mesh")

    def build_analysis_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setSpacing(15)

        left_panel = QFrame(); left_panel.setObjectName("Card"); left_panel.setMinimumWidth(480)
        left = QVBoxLayout(left_panel)
        left.addWidget(self.header("Analysis Conditions"))
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
        form = QFormLayout()
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
        left.addLayout(form)

        scope_box = QGroupBox("Research Scope / Local Behavior")
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
            scope_layout.addWidget(check)
        left.addWidget(scope_box)

        left.addWidget(self.header("Backend Mode"))
        self.radio_fast = QRadioButton("FAST GUI preview")
        self.radio_package = QRadioButton("Export job package only")
        self.radio_local = QRadioButton("Run local/shared-folder command")
        self.radio_remote = QRadioButton("Run remote computer via SSH/scp")
        self.radio_fast.setChecked(True)
        for r in [self.radio_fast, self.radio_package, self.radio_local, self.radio_remote]:
            left.addWidget(r)

        remote_box = QGroupBox("Remote / Backend Settings")
        remote_form = QFormLayout(remote_box)
        self.job_root_input = QLineEdit(str(DEFAULT_JOB_ROOT))
        self.local_command_input = QLineEdit("python3 abaqus_runner.py input_data.json")
        self.remote_target_input = QLineEdit("user@remote-host")
        self.remote_root_input = QLineEdit("~/SCLAS_jobs")
        self.remote_command_input = QLineEdit("abaqus cae noGUI=abaqus_runner.py -- input_data.json")
        remote_form.addRow("Local job root", self.job_root_input)
        remote_form.addRow("Local command", self.local_command_input)
        remote_form.addRow("SSH target", self.remote_target_input)
        remote_form.addRow("Remote job root", self.remote_root_input)
        remote_form.addRow("Remote command", self.remote_command_input)
        left.addWidget(remote_box)

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
        buttons.addWidget(self.btn_validate, 0, 0)
        buttons.addWidget(self.btn_json, 0, 1)
        buttons.addWidget(self.btn_run, 1, 0, 1, 2)
        buttons.addWidget(self.btn_load_result, 2, 0, 1, 2)
        left.addLayout(buttons)

        self.progress = QProgressBar(); self.progress.setValue(0)
        left.addWidget(self.progress)
        self.lbl_hw = QLabel("HW: CPU - | RAM -")
        left.addWidget(self.lbl_hw)
        left.addWidget(QLabel("System log"))
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setMaximumHeight(130)
        left.addWidget(self.console)
        left.addStretch()

        result_panel = QFrame(); result_panel.setObjectName("Card")
        right = QVBoxLayout(result_panel)
        right.addWidget(self.header("Moment-Curvature Result"))
        self.plot_canvas = pg.PlotWidget(background="#141419")
        self.plot_canvas.showGrid(x=True, y=True, alpha=0.2)
        self.plot_canvas.setLabel("left", "Bending Moment M", units="kN.m")
        self.plot_canvas.setLabel("bottom", "Curvature kappa", units="1/m")
        self.curve = self.plot_canvas.plot(pen=pg.mkPen(color="#00ffcc", width=3.2))
        right.addWidget(self.plot_canvas, 70)
        metric_layout = QHBoxLayout()
        self.lbl_peak = self.metric_box("Peak |M|", "-")
        self.lbl_loss = self.metric_box("Loop loss proxy", "-")
        self.lbl_points = self.metric_box("Points", "-")
        metric_layout.addWidget(self.lbl_peak)
        metric_layout.addWidget(self.lbl_loss)
        metric_layout.addWidget(self.lbl_points)
        right.addLayout(metric_layout)

        left_scroll = QScrollArea()
        left_scroll.setObjectName("PanelScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_panel)
        left_scroll.setFixedWidth(520)

        layout.addWidget(left_scroll)
        layout.addWidget(result_panel)
        self.tabs.addTab(tab, "3 Analysis")

    def header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ffcc; padding: 4px 0;")
        return label

    def metric_box(self, title: str, value: str) -> QFrame:
        box = QFrame(); box.setObjectName("MetricBox")
        layout = QVBoxLayout(box)
        title_label = QLabel(title); title_label.setStyleSheet("color: #aaa; font-size: 14px;")
        value_label = QLabel(value); value_label.setStyleSheet("color: white; font-size: 25px; font-weight: bold;")
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
                "regularization_beta": safe_float(self.mesh_inputs["contact_beta"], 0.001, "Contact regularization beta"),
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
            QMessageBox.information(self, "Validation complete", msg)
        except Exception as exc:
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
            self.progress.setValue(0)
            self.btn_run.setEnabled(False)
            self.curve.setData([], [])
            self.worker = AnalysisWorker(payload, mode, job_root, self.remote_config())
            self.worker.log_sig.connect(self.log)
            self.worker.progress_sig.connect(self.progress.setValue)
            self.worker.plot_sig.connect(self.update_plot)
            self.worker.metrics_sig.connect(self.update_metrics)
            self.worker.finished_sig.connect(self.analysis_finished)
            self.worker.start()
        except Exception as exc:
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
            self.local_command_input.setText(str(backend["local_command"]))
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

    def load_result_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open result_data.csv", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            k, m = read_result_csv(Path(path))
            self.update_plot(k, m)
            self.update_metrics(make_metrics(k, m, source="MANUAL_CSV_LOAD"))
            self.log(f"[RESULT] Loaded {path}")
        except Exception as exc:
            QMessageBox.critical(self, "CSV load error", str(exc))

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
        self.lbl_peak.value_label.setText(f"{data['max_abs_moment_kn_m']:.4g} kN.m")
        self.lbl_loss.value_label.setText(f"{data['hysteresis_loss_kj_per_m_proxy']:.4g}")
        self.lbl_points.value_label.setText(str(data["num_points"]))

    def trigger_rebuild(self) -> None:
        if hasattr(self, "debounce"):
            self.debounce.start(120)

    def toggle_view_mode(self) -> None:
        self.view_mode = "3D" if self.view_mode == "2D" else "2D"
        if self.view_mode == "2D":
            self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        else:
            self.view_solid.setCameraPosition(distance=250, elevation=35, azimuth=45)
        self.rebuild_solid_geometry()

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
            self.add_solid(dg["outer_sheath_outer_radius_mm"], 0, 0, 0.0, [0.15, 0.15, 0.15, 1.0])
            for i in range(dg["outer_armour_wire_count"]):
                a = 2 * np.pi * i / dg["outer_armour_wire_count"]
                self.add_solid(dg["outer_armour_wire_radius_mm"], dg["outer_armour_center_radius_mm"] * np.cos(a), dg["outer_armour_center_radius_mm"] * np.sin(a), 0.1, [0.5, 0.6, 0.7, 1.0])
            self.add_solid(dg["bedding_outer_radius_mm"], 0, 0, 0.2, [0.4, 0.3, 0.2, 1.0])
            for i in range(dg["inner_armour_wire_count"]):
                a = 2 * np.pi * i / dg["inner_armour_wire_count"]
                self.add_solid(dg["inner_armour_wire_radius_mm"], dg["inner_armour_center_radius_mm"] * np.cos(a), dg["inner_armour_center_radius_mm"] * np.sin(a), 0.3, [0.4, 0.5, 0.6, 1.0])
            self.add_solid(dg["inner_sheath_outer_radius_mm"], 0, 0, 0.4, [0.1, 0.1, 0.1, 1.0])
            self.add_solid(dg["inner_sheath_inner_radius_mm"], 0, 0, 0.5, [0.25, 0.25, 0.28, 1.0])
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
            add_wire(dg["outer_sheath_outer_radius_mm"], 0, 0, self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_core"].value(), (0, 1, 0.8, 0.7))
            for i in range(dg["inner_armour_wire_count"]):
                a = 2 * np.pi * i / dg["inner_armour_wire_count"]
                add_wire(dg["inner_armour_wire_radius_mm"], dg["inner_armour_center_radius_mm"] * np.cos(a), dg["inner_armour_center_radius_mm"] * np.sin(a), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.8, 0.8, 0.8, 0.9))
            for i in range(dg["outer_armour_wire_count"]):
                a = 2 * np.pi * i / dg["outer_armour_wire_count"]
                add_wire(dg["outer_armour_wire_radius_mm"], dg["outer_armour_center_radius_mm"] * np.cos(a), dg["outer_armour_center_radius_mm"] * np.sin(a), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.6, 0.7, 0.9, 0.9))
            self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)
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
            QMainWindow { background-color: #0d0d12; color: #e0e0e0; font-family: Arial; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #1a1a24; color: #999; min-width: 126px; min-height: 42px; padding: 8px 18px; font-size: 14px; font-weight: bold; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 5px; }
            QTabBar::tab:selected { background: #00ffcc; color: #0d0d12; }
            QFrame#Card { background-color: #1a1a24; border-radius: 12px; border: 1px solid #2a2a35; padding: 8px; }
            QFrame#MetricBox { background-color: #22222e; border-radius: 8px; border-left: 4px solid #00ffcc; padding: 8px; }
            QScrollArea#PanelScroll { background-color: transparent; border: none; }
            QScrollArea#PanelScroll > QWidget > QWidget { background-color: transparent; }
            QScrollBar:vertical { background: #111118; width: 10px; margin: 0; border-radius: 5px; }
            QScrollBar::handle:vertical { background: #333344; border-radius: 5px; min-height: 32px; }
            QScrollBar::handle:vertical:hover { background: #444455; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QGroupBox { color: #ddd; border: 1px solid #333344; border-radius: 8px; margin-top: 10px; padding: 10px; font-weight: bold; }
            QLabel { font-size: 14px; color: #ccc; }
            QLineEdit, QSpinBox, QComboBox { background-color: #22222e; border: 1px solid #333344; border-radius: 6px; padding: 8px; color: #fff; font-size: 14px; font-weight: bold; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #00ffcc; }
            QPushButton { background-color: #333344; color: #fff; border-radius: 6px; font-size: 15px; font-weight: bold; padding: 8px; }
            QPushButton:hover { background-color: #444455; }
            QPushButton:disabled { background-color: #202028; color: #666; }
            QPushButton#RunBtn { background-color: #00ffcc; color: #0d0d12; font-size: 18px; }
            QPushButton#RunBtn:hover { background-color: #33ffdd; }
            QTableWidget { background-color: #1a1a24; color: #fff; font-size: 13px; border: none; gridline-color: #2a2a35; }
            QHeaderView::section { background-color: #22222e; color: #00ffcc; font-weight: bold; border: 1px solid #2a2a35; padding: 7px; }
            QTextEdit { background-color: #0a0a0f; color: #00ffcc; font-family: Menlo, Consolas; border-radius: 6px; padding: 8px; font-size: 13px; }
            QProgressBar { border: 1px solid #333344; border-radius: 6px; text-align: center; color: white; font-weight: bold; }
            QProgressBar::chunk { background-color: #00ffcc; border-radius: 5px; }
            QRadioButton { font-size: 14px; font-weight: bold; color: #fff; padding: 2px; }
        """)


def main() -> int:
    app = QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = SCLASRemoteGUI()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
