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
import html
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
from PyQt5.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
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
    QSplitter,
    QSplashScreen,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg
import pyqtgraph.opengl as gl

from sclas_backend_gui_bridge import (
    BACKEND_JOB_FOLDER_PRESETS,
    BACKEND_JSON_PRESETS,
    GUI_COMBO_ALIASES,
    auto_armour_count,
    backend_payload_gui_values,
    core_center_from_outer_radius,
)
from sclas_inp_mesh_preview import PART_COLORS, build_inp_mesh_preview, format_inp_mesh_summary
from sclas_job_filters import candidate_job_dirs

APP_VERSION = "12.0-abaqus-quality-summary"
CONTRACT_VERSION = "sclas-abaqus-contract-v1"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_JOB_ROOT = PROJECT_DIR / "jobs" / "SCLAS_jobs"
SETTINGS_PATH = PROJECT_DIR / "settings.json"
BACKEND_RUNNER_TEMPLATE = APP_DIR / "abaqus_runner.py"
ODB_EXTRACTOR_TEMPLATE = APP_DIR / "sclas_odb_extractor.py"
TEAM_LOGO_PATH = PROJECT_DIR / "assets" / "helix_logo.png"
TEAM_ICON_PATH = PROJECT_DIR / "assets" / "helix_icon.png"
FONT_DIR = PROJECT_DIR / "assets" / "fonts"
APP_FONT_FAMILY = "Noto Sans KR"
UI_FONT_QSS = "'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', Arial"
SYMBOL_FONT_FAMILY = "Cambria Math"
SYMBOL_FONT_QSS = "'Euclid', 'Euclid Symbol', 'Cambria Math', 'Segoe UI Symbol', 'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', Arial"
MONO_FONT_QSS = "'Cascadia Mono', Consolas, 'Noto Sans KR', 'Malgun Gothic', monospace"


def qss_font_stack(*families: str) -> str:
    return ", ".join(f"'{family}'" for family in families if family)


def load_project_symbol_fonts() -> str:
    """Load bundled math fonts from assets/fonts and return the preferred family."""
    preferred = ""
    if FONT_DIR.exists():
        for pattern in ("*.ttf", "*.otf", "*.ttc"):
            for font_path in sorted(FONT_DIR.glob(pattern)):
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                if font_id < 0:
                    continue
                for family in QFontDatabase.applicationFontFamilies(font_id):
                    lowered = family.lower()
                    if not preferred or "euclid" in lowered:
                        preferred = family
                    if "euclid" in lowered:
                        return preferred
    return preferred or "Cambria Math"


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
    if ODB_EXTRACTOR_TEMPLATE.exists():
        shutil.copy2(ODB_EXTRACTOR_TEMPLATE, job_dir / "sclas_odb_extractor.py")
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

class VariableFormLabel(QWidget):
    TOKEN_MAP = {
        "r_cond": ("r", "cond"),
        "r_ins": ("r", "ins"),
        "R_core": ("R", "core"),
        "R_c": ("R", "c"),
        "t_is": ("t", "is"),
        "t_os": ("t", "os"),
        "r_ia": ("r", "ia"),
        "n_ia": ("n", "ia"),
        "r_oa": ("r", "oa"),
        "n_oa": ("n", "oa"),
        "t_bedding": ("t", "bedding"),
        "alpha_core": ("\u03b1", "core"),
        "alpha_ia": ("\u03b1", "ia"),
        "alpha_oa": ("\u03b1", "oa"),
        "\u03b1_core": ("\u03b1", "core"),
        "\u03b1_ia": ("\u03b1", "ia"),
        "\u03b1_oa": ("\u03b1", "oa"),
        "n_z": ("n", "z"),
        "n_theta": ("n", "\u03b8"),
        "n_r": ("n", "r"),
        "theta": ("\u03b8", ""),
        "mu": ("\u03bc", ""),
        "kappa": ("\u03ba", ""),
    }

    def __init__(self, text: str):
        super().__init__()
        self.setProperty("no_translate", True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(214)
        self.setMaximumHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        label = QLabel()
        label.setProperty("no_translate", True)
        label.setTextFormat(Qt.RichText)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        label.setMinimumHeight(30)
        label.setText(self.rich_text(text))
        layout.addWidget(label, 1)

    @classmethod
    def match_token(cls, text: str) -> Optional[Tuple[str, str, str, int, int]]:
        for token in sorted(cls.TOKEN_MAP, key=len, reverse=True):
            start = 0
            while True:
                index = text.find(token, start)
                if index < 0:
                    break
                end = index + len(token)
                before_ok = index == 0 or not cls.is_token_char(text[index - 1])
                after_ok = end == len(text) or not cls.is_token_char(text[end])
                if before_ok and after_ok:
                    symbol, subscript = cls.TOKEN_MAP[token]
                    return token, symbol, subscript, index, end
                start = index + 1
        return None

    @staticmethod
    def is_token_char(char: str) -> bool:
        return char.isalnum() or char == "_"

    @classmethod
    def rich_text(cls, text: str) -> str:
        token = cls.match_token(text)
        body_color = "#17202a"
        muted_color = "#64748b"
        symbol_color = "#0b5cad"
        if token is None:
            return (
                f"<span style='font-size:13px; font-weight:650; "
                f"color:{body_color};'>{html.escape(text)}</span>"
            )

        _token_text, symbol, subscript, token_start, token_end = token
        prefix = html.escape(text[:token_start].strip())
        suffix = html.escape(text[token_end:].strip())
        symbol = html.escape(symbol)
        subscript = html.escape(subscript)
        parts = []
        if prefix:
            parts.append(
                f"<span style='font-size:13px; font-weight:650; "
                f"color:{body_color};'>{prefix}</span>"
            )
        if subscript:
            parts.append(
                f"<span style='font-size:15px; font-weight:750; "
                f"color:{symbol_color};'>&nbsp;{symbol}</span>"
                f"<sub style='font-size:12px; font-weight:750; "
                f"color:{symbol_color};'>{subscript}</sub>"
            )
        else:
            parts.append(
                f"<span style='font-size:15px; font-weight:750; "
                f"color:{symbol_color};'>&nbsp;{symbol}</span>"
            )
        if suffix:
            parts.append(
                f"<span style='font-size:13px; font-weight:650; "
                f"color:{muted_color};'>&nbsp;{suffix}</span>"
            )
        return "".join(parts)

    def add_plain_label(self, layout: QHBoxLayout, text: str, color: str, weight: int) -> None:
        label = QLabel(text)
        label.setProperty("no_translate", True)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setStyleSheet(
            f"QLabel {{ font-family: {UI_FONT_QSS}; "
            f"font-size: 13px; font-weight: {weight}; color: {color}; letter-spacing: 0px; padding: 0px; }}"
        )
        layout.addWidget(label, 0, Qt.AlignVCenter)

    def add_symbol_label(self, layout: QHBoxLayout, symbol: str, subscript: str) -> None:
        symbol_label = QLabel()
        symbol_label.setProperty("no_translate", True)
        symbol_label.setTextFormat(Qt.RichText)
        if subscript:
            symbol_label.setText(
                "<span style=\"font-family:{0}; font-size:15px; font-weight:750; color:#0b5cad;\">{1}</span>"
                "<sub style=\"font-family:{0}; font-size:12px; font-weight:750; color:#0b5cad;\">{2}</sub>".format(
                    SYMBOL_FONT_QSS,
                    symbol,
                    subscript,
                )
            )
        else:
            symbol_label.setText(
                "<span style=\"font-family:{0}; font-size:14px; font-weight:750; color:#0b5cad;\">{1}</span>".format(
                    SYMBOL_FONT_QSS,
                    symbol,
                )
            )
        layout.addWidget(symbol_label, 0, Qt.AlignVCenter)


def build_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(560, 340)
    pixmap.fill(QColor("#f6f8fb"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(QColor("#d7dee8"))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(18, 18, 524, 304, 16, 16)

    logo_path = TEAM_ICON_PATH if TEAM_ICON_PATH.exists() else TEAM_LOGO_PATH
    logo = QPixmap(str(logo_path))
    if not logo.isNull():
        scaled_logo = logo.scaled(132, 132, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap((560 - scaled_logo.width()) // 2, 58, scaled_logo)

    painter.setPen(QColor("#111827"))
    title_font = QFont("Segoe UI", 24)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(0, 214, 560, 42, Qt.AlignCenter, "HELIX")

    painter.setPen(QColor("#475569"))
    subtitle_font = QFont("Segoe UI", 10)
    painter.setFont(subtitle_font)
    painter.drawText(
        0,
        252,
        560,
        26,
        Qt.AlignCenter,
        "Helical Element Localised Interaction eXamination",
    )

    painter.setPen(QColor("#1f6feb"))
    status_font = QFont("Segoe UI", 9)
    status_font.setBold(True)
    painter.setFont(status_font)
    painter.drawText(0, 286, 560, 26, Qt.AlignCenter, "Preparing GUI-Abaqus bridge")
    painter.end()
    return pixmap


def show_startup_splash(app: QApplication) -> Optional[QSplashScreen]:
    if os.environ.get("SCLAS_DISABLE_SPLASH", "").strip():
        return None
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return None
    if os.environ.get("SCLAS_GUI_SMOKE_EXIT_MS", "").strip():
        return None

    splash = QSplashScreen(build_splash_pixmap(), Qt.WindowStaysOnTopHint)
    splash.setWindowOpacity(0.0)
    splash.show()

    animation = QPropertyAnimation(splash, b"windowOpacity", splash)
    animation.setDuration(650)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start()

    start = time.time()
    while time.time() - start < 0.85:
        app.processEvents()
        time.sleep(0.02)
    splash._startup_animation = animation
    return splash


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
        self.active_mesh_key = ""
        self.last_summary_data: dict = {}
        self.last_job_dir = ""
        self.setWindowTitle("HELIX Cable Analysis")
        self.setMinimumSize(1100, 620)
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
        width = min(1680, max(1100, available.width() - 36))
        height = min(940, max(620, available.height() - 60))
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
            "Design": "설계",
            "Finite Element\nAnalysis Setting": "유한요소\n해석 설정",
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
            "Filler": "필러",
            "Core Section": "코어 단면",
            "Sheath / Bedding": "시스 / 베딩",
            "Armour Wires": "아머 와이어",
            "Helix Pitch Angle": "헬릭스 피치 각",
            "Material Properties": "재료 물성",
            "Material": "재료",
            "Layer Legend": "레이어 범례",
            "Section Preview": "단면 프리뷰",
            "Bedding thickness": "베딩 두께",
            "Reset View": "뷰 초기화",
            "Mesh Setting Guide": "메시 설정 가이드",
            "Abaqus element type": "아바쿠스 요소 타입",
            "Strategy": "전략",
            "Armour model": "아머 모델",
            "Periodic cell": "주기 셀",
            "Periodic homogenized cell": "주기 균질화 셀",
            "Full 3D segment": "전체 3D 세그먼트",
            "Axisymmetric": "축대칭",
            "Axisymmetric tension/torsion": "축대칭 인장/비틀림",
            "Solid wire": "솔리드 와이어",
            "Beam + contact": "빔 + 접촉",
            "Beam + contact surface": "빔 + 접촉면",
            "Analytical equiv.": "해석 등가",
            "Analytical equivalent": "해석적 등가 모델",
            "Contact beta": "접촉 beta",
            "Axial divisions": "축방향 분할",
            "Core divisions": "코어 분할",
            "Armour divisions": "아머 분할",
            "Axial z divisions": "축방향 z 분할",
            "Core/Sheath n_theta divisions": "코어/시스 n_theta 분할",
            "Armour wire n_theta divisions": "아머 와이어 n_theta 분할",
            "Inner sheath n_r divisions": "내부 시스 n_r 분할",
            "Bedding n_r divisions": "베딩 n_r 분할",
            "Outer sheath n_r divisions": "외부 시스 n_r 분할",
            "Filler n_z divisions": "필러 n_z 분할",
            "Import Abaqus INP": "Abaqus INP 불러오기",
            "Ready state": "준비 상태",
            "Est. elements": "예상 요소 수",
            "Contact pairs": "접촉 쌍",
            "Guide mode": "가이드 모드",
            "Preview ready": "프리뷰 준비됨",
            "INP imported": "INP 불러옴",
            "Mesh Guide / INP Preview": "메시 가이드 / INP 프리뷰",
            "Reset": "초기화",
            "Analysis Conditions": "해석 조건",
            "Conditions": "조건",
            "Effective length (mm)": "유효 길이 (mm)",
            "Cable external pressure (MPa)": "케이블 외압 (MPa)",
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
            "Diagnose selected": "선택 항목 진단",
            "Compare CurveV0": "CurveV0 비교",
            "Project Status": "프로젝트 상태",
            "Job Index": "작업 목록",
            "Load best": "추천 작업 불러오기",
            "Timeline": "진행 타임라인",
            "Intake": "결과 점검",
            "Acceptance": "통과 판정",
            "Session Brief": "세션 브리프",
            "Research Report": "연구 보고서",
            "Validate All": "전체 검증",
            "Handoff": "인수인계",
            "Open folder": "폴더 열기",
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
            "Curvature \u03ba": "곡률 \u03ba",
            "Layer": "레이어",
            "Density": "밀도",
            "Density (kg/m^3)": "밀도 (kg/m^3)",
        }

    def ui_text(self, text: str) -> str:
        if self.ui_language == "KO":
            return self.translations().get(text, text)
        return text

    def set_translated_metric_value(self, metric: QFrame, english_text: str) -> None:
        value_label = getattr(metric, "value_label", None)
        if value_label is None:
            return
        value_label.setProperty("metric_status_key", english_text)
        value_label.setText(self.ui_text(english_text))

    def refresh_translated_metric_values(self) -> None:
        for metric_name in ("lbl_mesh_ready",):
            metric = getattr(self, metric_name, None)
            value_label = getattr(metric, "value_label", None)
            if value_label is None:
                continue
            status_key = value_label.property("metric_status_key")
            if status_key:
                value_label.setText(self.ui_text(str(status_key)))

    def update_language_button(self) -> None:
        if not hasattr(self, "btn_language"):
            return
        if self.ui_language == "EN":
            self.btn_language.setText("English")
            self.btn_language.setToolTip("Current language: English. Click to switch to Korean.")
        else:
            self.btn_language.setText("한국어")
            self.btn_language.setToolTip("현재 언어: 한국어. 클릭하면 영어로 전환합니다.")

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
                prefix = "▾" if widget.isChecked() else "▸"
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

        self.update_language_button()
        if hasattr(self, "table"):
            self.style_material_headers()
        if hasattr(self, "plot_canvas"):
            self.plot_canvas.setLabel("left", self.ui_text("Bending Moment M"), units="kN.m")
            self.plot_canvas.setLabel("bottom", self.ui_text("Curvature \u03ba"), units="1/m")
        if hasattr(self, "mesh_inputs"):
            self.translate_combo_items(
                self.mesh_inputs["model_strategy"],
                [
                    ("Periodic cell", "Periodic homogenized cell"),
                    ("Full 3D segment", "Full 3D segment"),
                    ("Axisymmetric", "Axisymmetric tension/torsion"),
                ],
            )
            self.translate_combo_items(
                self.mesh_inputs["armour_model"],
                [
                    ("Solid wire", "Solid wire"),
                    ("Beam + contact", "Beam + contact surface"),
                    ("Analytical equiv.", "Analytical equivalent"),
                ],
            )
        if hasattr(self, "summary_text"):
            if self.last_summary_data:
                self.summary_text.setPlainText(self.format_summary(self.last_summary_data))
            else:
                self.summary_text.setPlainText(self.summary_placeholder_text())
        self.refresh_translated_metric_values()

    def translate_combo_items(self, combo: QComboBox, english_items: List[object]) -> None:
        current_index = combo.currentIndex()
        combo.blockSignals(True)
        combo.clear()
        for item in english_items:
            if isinstance(item, tuple):
                label, value = item
            else:
                label, value = item, item
            combo.addItem(self.ui_text(str(label)), value)
        combo.setCurrentIndex(max(0, min(current_index, combo.count() - 1)))
        combo.blockSignals(False)

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

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusIn and hasattr(self, "mesh_guide_label"):
            key = obj.property("mesh_key") if hasattr(obj, "property") else None
            if key:
                self.active_mesh_key = str(key)
                self.update_mesh_guide()
        return super().eventFilter(obj, event)

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
        self.lbl_model_status.setVisible(False)
        self.lbl_result_status = QLabel("Result: none")
        self.lbl_result_status.setObjectName("TopbarMeta")
        self.lbl_result_status.setVisible(False)
        self.btn_language = QPushButton("English")
        self.btn_language.setObjectName("LangToggle")
        self.btn_language.setFixedWidth(92)
        self.btn_language.setToolTip("Current language: English. Click to switch to Korean.")
        self.btn_language.setProperty("no_translate", True)
        self.btn_language.clicked.connect(self.toggle_language)
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

        nav_items = ["Design", "Finite Element\nAnalysis Setting", "Analysis\nResults"]
        for index, label in enumerate(nav_items):
            btn = QPushButton(label)
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

    def panel_splitter(self, first: QWidget, second: QWidget, sizes: List[int]) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("PanelSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(first)
        splitter.addWidget(second)
        splitter.setSizes(sizes)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        return splitter

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
        toggle.setMinimumHeight(38)
        toggle.setProperty("section_title", title)
        content.setVisible(expanded)

        def update_label(checked: bool) -> None:
            prefix = "▾" if checked else "▸"
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
                "filler": True,
                "cores": True,
            },
            "armour": {
                "outer_sheath": False,
                "outer_armour": True,
                "bedding": False,
                "inner_armour": True,
                "inner_sheath": False,
                "filler": False,
                "cores": False,
            },
            "core": {
                "outer_sheath": False,
                "outer_armour": False,
                "bedding": False,
                "inner_armour": False,
                "inner_sheath": False,
                "filler": True,
                "cores": True,
            },
            "sheath": {
                "outer_sheath": True,
                "outer_armour": False,
                "bedding": True,
                "inner_armour": False,
                "inner_sheath": True,
                "filler": True,
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
        panel_inputs.setMinimumWidth(360)
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
            "tis": QLineEdit("4.50"),
            "r_ia": QLineEdit("2.00"),
            "no_ia": QSpinBox(),
            "bedding_thickness": QLineEdit("0.60"),
            "r_oa": QLineEdit("2.00"),
            "no_oa": QSpinBox(),
            "tos": QLineEdit("4.50"),
            "core_lay_angle": QLineEdit("8.98"),
            "inner_lay_angle": QLineEdit("20.1"),
            "outer_lay_angle": QLineEdit("19.6"),
        }
        self.inputs["no_ia"].setRange(0, 300); self.inputs["no_ia"].setValue(55); self.inputs["no_ia"].setSpecialValueText("Auto")
        self.inputs["no_oa"].setRange(0, 300); self.inputs["no_oa"].setValue(63); self.inputs["no_oa"].setSpecialValueText("Auto")

        geometry_sections = [
            (
                "Core Section",
                [
                    ("Conductor radius r_cond (mm)", "r_cond"),
                    ("Insulation radius r_ins (mm)", "r_insu"),
                    ("Core outer radius R_core (mm)", "roc"),
                ],
            ),
            (
                "Sheath / Bedding",
                [
                    ("Inner sheath t_is (mm)", "tis"),
                    ("Bedding thickness t_bedding (mm)", "bedding_thickness"),
                    ("Outer sheath t_os (mm)", "tos"),
                ],
            ),
            (
                "Armour Wires",
                [
                    ("Inner armour wire radius r_ia (mm)", "r_ia"),
                    ("Inner armour wire number n_ia", "no_ia"),
                    ("Outer armour wire radius r_oa (mm)", "r_oa"),
                    ("Outer armour wire number n_oa", "no_oa"),
                ],
            ),
            (
                "Helix Pitch Angle",
                [
                    ("Core lay angle α_core (deg)", "core_lay_angle"),
                    ("Inner armour lay angle α_ia (deg)", "inner_lay_angle"),
                    ("Outer armour lay angle α_oa (deg)", "outer_lay_angle"),
                ],
            ),
        ]
        for idx, (section_title, _section_rows) in enumerate(geometry_sections):
            if section_title == "Helix Pitch Angle":
                geometry_sections[idx] = (
                    section_title,
                    [
                        ("Core helix pitch angle alpha_core (deg)", "core_lay_angle"),
                        ("Inner armour helix pitch angle alpha_ia (deg)", "inner_lay_angle"),
                        ("Outer armour helix pitch angle alpha_oa (deg)", "outer_lay_angle"),
                    ],
                )
        for section_title, section_rows in geometry_sections:
            section_box = QGroupBox(section_title)
            section_form = QFormLayout(section_box)
            section_form.setVerticalSpacing(8)
            section_form.setHorizontalSpacing(16)
            section_form.setLabelAlignment(Qt.AlignRight)
            section_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            section_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            for label, key in section_rows:
                self.inputs[key].setMinimumWidth(112)
                self.inputs[key].setToolTip(f"Edit {label}. The section preview updates automatically.")
                section_form.addRow(self.form_label(label), self.inputs[key])
            left.addWidget(section_box)

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
            btn.setToolTip("Apply a quick visibility preset to the section preview layers.")
            btn.clicked.connect(lambda checked=False, m=mode: self.apply_layer_preset(m))
            layer_layout.addWidget(btn, 1 + idx // 2, idx % 2)
        self.layer_checks = {
            "outer_sheath": QCheckBox("Outer sheath"),
            "outer_armour": QCheckBox("Outer armour"),
            "bedding": QCheckBox("Bedding"),
            "inner_armour": QCheckBox("Inner armour"),
            "inner_sheath": QCheckBox("Inner sheath"),
            "filler": QCheckBox("Filler"),
            "cores": QCheckBox("Three cores"),
        }
        for idx, check in enumerate(self.layer_checks.values()):
            check.setChecked(True)
            check.setToolTip("Toggle this layer in the section preview.")
            check.toggled.connect(self.trigger_rebuild)
            layer_layout.addWidget(check, 3 + idx // 2, idx % 2)
        left.addWidget(layer_box)
        left.addStretch()
        input_scroll = self.scroll_panel(panel_inputs, min_width=460)

        panel_mat = QFrame(); panel_mat.setObjectName("Card")
        panel_mat.setMinimumWidth(360)
        panel_mat.setMinimumHeight(360)
        mid = QVBoxLayout(panel_mat)
        mid.setContentsMargins(12, 10, 12, 12)
        self.table = QTableWidget(8, 5)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels([
            "Layer",
            "Material",
            "Young's modulus\nE (GPa)",
            "Poisson's ratio\n\u03bd (-)",
            "Density\n\u03c1 (kg/m^3)",
        ])
        self.style_material_headers()
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.horizontalHeader().setMinimumHeight(48)
        self.table.setMinimumHeight(300)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.init_material_table()
        mid.addWidget(self.table)
        material_section = self.collapsible_section("Material Properties", panel_mat, expanded=False)

        panel_view = QFrame(); panel_view.setObjectName("Card")
        panel_view.setMinimumWidth(380)
        panel_view.setMinimumHeight(300)
        right = QVBoxLayout(panel_view)
        right.setContentsMargins(18, 16, 18, 16)
        header = QHBoxLayout()
        header.addWidget(self.header("Section Preview"))
        self.btn_reset_solid = QPushButton("Reset View")
        self.btn_reset_solid.setToolTip("Return the section preview camera to the default top view.")
        self.btn_reset_solid.clicked.connect(self.reset_solid_view)
        header.addWidget(self.btn_reset_solid)
        right.addLayout(header)
        self.view_solid = gl.GLViewWidget()
        self.view_solid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_solid.setMinimumHeight(260)
        self.view_solid.setBackgroundColor("#f7f8fa")
        self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        preview_body = QHBoxLayout()
        preview_body.setContentsMargins(0, 0, 0, 0)
        preview_body.setSpacing(14)
        preview_body.addWidget(self.view_solid, 1)
        preview_body.addWidget(self.build_layer_legend(), 0)
        right.addLayout(preview_body, 1)

        workspace = QFrame()
        workspace.setObjectName("WorkspaceFrame")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(10)
        workspace_layout.addWidget(panel_view, 1)
        workspace_layout.addWidget(material_section, 0)

        layout.addWidget(self.panel_splitter(workspace, input_scroll, [900, 520]), 1)
        self.add_page(tab)

        for w in self.inputs.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self.trigger_rebuild)
            else:
                w.valueChanged.connect(self.trigger_rebuild)

    def build_mesh_tab(self) -> None:
        self.ensure_analysis_condition_widgets()
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        panel = QFrame(); panel.setObjectName("Card")
        panel.setMinimumWidth(360)
        left = QVBoxLayout(panel)
        left.setContentsMargins(18, 16, 18, 16)
        left.setSpacing(12)
        left.addWidget(self.header("Finite Element Analysis Setting"))

        setup_box = QGroupBox("Analysis Structure Setup")
        setup_form = QFormLayout(setup_box)
        setup_form.setLabelAlignment(Qt.AlignRight)
        setup_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        setup_form.setHorizontalSpacing(12)
        setup_form.setVerticalSpacing(9)
        setup_form.addRow(self.form_label("External pressure load (MPa)"), self.cond["pressure"])
        setup_form.addRow(self.form_label("Target curvature kappa (1/m)"), self.cond["curvature"])
        setup_form.addRow(self.form_label("Friction coefficient mu"), self.cond["friction"])
        left.addWidget(setup_box)

        left.addWidget(self.header("Mesh Setting Guide"))
        self.mesh_inputs = {
            "elem_type": QComboBox(),
            "model_strategy": QComboBox(),
            "armour_model": QComboBox(),
            "contact_beta": QLineEdit("0.001"),
            "z_elem": QSpinBox(),
            "c_elem_core": QSpinBox(),
            "c_elem_armour": QSpinBox(),
            "r_elem_inner_sheath": QSpinBox(),
            "r_elem_bedding": QSpinBox(),
            "r_elem_outer_sheath": QSpinBox(),
            "filler_z_elem": QSpinBox(),
        }
        self.mesh_inputs["elem_type"].addItems(["C3D8R", "C3D4", "B31"])
        self.mesh_inputs["model_strategy"].addItem("Full 3D segment", "Full 3D segment")
        self.mesh_inputs["armour_model"].addItem("Solid wire", "Solid wire")
        self.mesh_inputs["z_elem"].setRange(2, 500); self.mesh_inputs["z_elem"].setValue(40)
        self.mesh_inputs["c_elem_core"].setRange(4, 160); self.mesh_inputs["c_elem_core"].setValue(24)
        self.mesh_inputs["c_elem_armour"].setRange(4, 64); self.mesh_inputs["c_elem_armour"].setValue(8)
        self.mesh_inputs["r_elem_inner_sheath"].setRange(1, 50); self.mesh_inputs["r_elem_inner_sheath"].setValue(3)
        self.mesh_inputs["r_elem_bedding"].setRange(1, 50); self.mesh_inputs["r_elem_bedding"].setValue(1)
        self.mesh_inputs["r_elem_outer_sheath"].setRange(1, 50); self.mesh_inputs["r_elem_outer_sheath"].setValue(3)
        self.mesh_inputs["filler_z_elem"].setRange(2, 500); self.mesh_inputs["filler_z_elem"].setValue(40)
        mesh_tips = {
            "elem_type": "Abaqus element family requested in input_data.json.",
            "model_strategy": "Fixed backend strategy: full 3D segment.",
            "armour_model": "Fixed armour representation: solid wire.",
            "contact_beta": "Tangential contact regularization value for stick-slip stability.",
            "z_elem": "Axial n_z divisions along the cable length for core, sheath, bedding, and armour.",
            "c_elem_core": "Circumferential n_theta divisions for core, sheath, and bedding preview surfaces.",
            "c_elem_armour": "Circumferential n_theta divisions around each armour wire cross-section.",
            "r_elem_inner_sheath": "n_r divisions through the inner sheath thickness.",
            "r_elem_bedding": "n_r divisions through the bedding layer.",
            "r_elem_outer_sheath": "n_r divisions through the outer sheath thickness.",
            "filler_z_elem": "Axial n_z divisions for the special four-part filler profile.",
        }
        self.mesh_inputs["contact_beta"].setVisible(False)
        for key in ["elem_type", "model_strategy", "armour_model"]:
            self.mesh_inputs[key].setMinimumWidth(140)
            self.mesh_inputs[key].setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key in [
            "z_elem",
            "c_elem_core",
            "c_elem_armour",
            "r_elem_inner_sheath",
            "r_elem_bedding",
            "r_elem_outer_sheath",
            "filler_z_elem",
        ]:
            self.mesh_inputs[key].setMinimumWidth(112)
            self.mesh_inputs[key].setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key, tip in mesh_tips.items():
            self.mesh_inputs[key].setToolTip(tip)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.addRow(self.form_label("Abaqus element type"), self.mesh_inputs["elem_type"])
        form.addRow(self.form_label("Axial n_z divisions"), self.mesh_inputs["z_elem"])
        form.addRow(self.form_label("Core/Sheath n_theta divisions"), self.mesh_inputs["c_elem_core"])
        form.addRow(self.form_label("Armour wire n_theta divisions"), self.mesh_inputs["c_elem_armour"])
        form.addRow(self.form_label("Inner sheath n_r divisions"), self.mesh_inputs["r_elem_inner_sheath"])
        form.addRow(self.form_label("Bedding n_r divisions"), self.mesh_inputs["r_elem_bedding"])
        form.addRow(self.form_label("Outer sheath n_r divisions"), self.mesh_inputs["r_elem_outer_sheath"])
        form.addRow(self.form_label("Filler n_z divisions"), self.mesh_inputs["filler_z_elem"])
        left.addLayout(form)
        self.btn_import_inp_mesh = QPushButton("Import Abaqus INP")
        self.btn_import_inp_mesh.setFixedHeight(42)
        self.btn_import_inp_mesh.setToolTip("Read an Abaqus .inp file and render a part-colored end-section mesh preview.")
        self.btn_import_inp_mesh.clicked.connect(self.import_inp_mesh_dialog)
        left.addWidget(self.btn_import_inp_mesh)
        note = QLabel("Use this tab to set n_\u03b8, n_r, and n_z division guidance. The actual Abaqus mesh is checked by importing the generated INP.")
        note.setWordWrap(True)
        left.addWidget(note)
        self.inp_mesh_summary = QTextEdit()
        self.inp_mesh_summary.setObjectName("SummaryText")
        self.inp_mesh_summary.setReadOnly(True)
        self.inp_mesh_summary.setMaximumHeight(112)
        self.inp_mesh_summary.setPlainText("Import an Abaqus .inp file to inspect the actual generated mesh.")
        left.addWidget(self.inp_mesh_summary)
        left.addStretch()

        viewer = QFrame(); viewer.setObjectName("Card")
        right = QVBoxLayout(viewer)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)
        mesh_header = QHBoxLayout()
        mesh_header.addWidget(self.header("Mesh Guide / INP Preview"))
        mesh_header.addStretch()
        right.addLayout(mesh_header)
        self.mesh_guide_label = QLabel()
        self.mesh_guide_label.setObjectName("MeshGuide")
        self.mesh_guide_label.setFixedHeight(520)
        self.mesh_guide_label.setMinimumWidth(0)
        self.mesh_guide_label.setAlignment(Qt.AlignCenter)
        self.mesh_guide_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        right.addWidget(self.mesh_guide_label)
        self.view_wire = gl.GLViewWidget()
        self.view_wire.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_wire.setMinimumHeight(300)
        self.view_wire.setBackgroundColor("#1e1e1e")
        self.view_wire.setCameraPosition(distance=150, elevation=90, azimuth=0)
        self.view_wire.setVisible(False)
        right.addWidget(self.view_wire, 1)
        self.inp_mesh_legend = QLabel("")
        self.inp_mesh_legend.setObjectName("MeshLegend")
        self.inp_mesh_legend.setTextFormat(Qt.RichText)
        self.inp_mesh_legend.setWordWrap(True)
        self.inp_mesh_legend.setVisible(False)
        right.addWidget(self.inp_mesh_legend)
        viewer_scroll = self.scroll_panel(viewer)
        mesh_scroll = self.scroll_panel(panel, min_width=440)
        layout.addWidget(self.panel_splitter(viewer_scroll, mesh_scroll, [1020, 440]), 1)
        self.add_page(tab)
        for key, widget in self.mesh_inputs.items():
            widget.setProperty("mesh_key", key)
            widget.installEventFilter(self)
            if isinstance(widget, QSpinBox):
                widget.valueChanged.connect(lambda _value, k=key: self.activate_mesh_key(k))
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(lambda _index, k=key: self.activate_mesh_key(k))
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda _text, k=key: self.activate_mesh_key(k))
        for key in ["pressure", "curvature", "friction"]:
            self.cond[key].textChanged.connect(lambda _text: self.update_mesh_guide())
        self.update_mesh_guide()

    def ensure_analysis_condition_widgets(self) -> None:
        if hasattr(self, "cond"):
            return
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
            "pressure": "External pressure load passed to the Abaqus analysis request.",
            "residual_contact_pressure": "Residual normal contact pressure for stick-slip/friction calibration.",
            "friction": "Coulomb friction coefficient for armour-to-sheath and armour-to-bedding contact.",
            "curvature": "Target maximum curvature for the bending request and moment-curvature loop.",
            "twist": "Maximum twist requested for future coupled torsion studies.",
            "axial_strain": "Axial strain requested for tension-bending coupling studies.",
            "radial_compression": "Compression ratio used for bird-caging risk proxy.",
            "cycles": "Number of loading cycles in the preview/result request.",
            "steps": "Number of output samples in the result curve.",
        }
        self.cond["residual_contact_pressure"].setVisible(False)
        for key, tip in analysis_tips.items():
            self.cond[key].setToolTip(tip)

    def build_analysis_tab(self) -> None:
        self.ensure_analysis_condition_widgets()
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left_panel = QFrame(); left_panel.setObjectName("Card"); left_panel.setMinimumWidth(360)
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(18, 16, 18, 16)
        conditions_box = QFrame()
        form = QFormLayout(conditions_box)
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.addRow("Effective length (mm)", self.cond["eff_length"])
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
        remote_form.setLabelAlignment(Qt.AlignRight)
        remote_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        remote_form.setHorizontalSpacing(12)
        remote_form.setVerticalSpacing(9)
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
        self.plot_canvas.setLabel("bottom", "Curvature \u03ba", units="1/m")
        self.plot_canvas.getAxis("left").setTextPen("#a7a7a7")
        self.plot_canvas.getAxis("bottom").setTextPen("#a7a7a7")
        self.plot_canvas.getAxis("left").setPen("#555555")
        self.plot_canvas.getAxis("bottom").setPen("#555555")
        self.plot_legend = self.plot_canvas.addLegend(offset=(12, 12))
        self.curve = self.plot_canvas.plot(pen=pg.mkPen(color="#8ab4ff", width=2.8), name="Primary")
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

        self.input_preview_box = QGroupBox("Abaqus Input Preview")
        preview_layout = QVBoxLayout(self.input_preview_box)
        preview_toolbar = QHBoxLayout()
        self.btn_refresh_input_preview = QPushButton("Refresh Preview")
        self.btn_export_input_summary = QPushButton("Export Summary")
        self.btn_refresh_input_preview.setToolTip("Show the exact geometry, mesh, and analysis values that will be written to input_data.json.")
        self.btn_export_input_summary.setToolTip("Save a compact handoff summary of the current Abaqus input request.")
        self.btn_refresh_input_preview.clicked.connect(self.refresh_input_preview)
        self.btn_export_input_summary.clicked.connect(self.export_input_summary_dialog)
        preview_toolbar.addWidget(self.btn_refresh_input_preview)
        preview_toolbar.addWidget(self.btn_export_input_summary)
        preview_toolbar.addStretch()
        preview_layout.addLayout(preview_toolbar)
        self.input_preview_text = QTextEdit()
        self.input_preview_text.setObjectName("InputPreviewText")
        self.input_preview_text.setReadOnly(True)
        self.input_preview_text.setMaximumHeight(230)
        preview_layout.addWidget(self.input_preview_text)
        right.addWidget(self.input_preview_box)

        self.history_box = QGroupBox("Recent Jobs")
        history_layout = QGridLayout(self.history_box)
        self.job_history_combo = QComboBox()
        self.job_history_combo.setToolTip("Recent job folders containing result_data.csv.")
        self.btn_refresh_jobs = QPushButton("Refresh")
        self.btn_load_job = QPushButton("Load selected")
        self.btn_diagnose_job = QPushButton("Diagnose selected")
        self.btn_compare_curve_v0 = QPushButton("Compare CurveV0")
        self.btn_project_status = QPushButton("Project Status")
        self.btn_job_index = QPushButton("Job Index")
        self.btn_load_best_job = QPushButton("Load best")
        self.btn_progress_timeline = QPushButton("Timeline")
        self.btn_result_intake = QPushButton("Intake")
        self.btn_acceptance_gate = QPushButton("Acceptance")
        self.btn_session_brief = QPushButton("Session Brief")
        self.btn_research_report = QPushButton("Research Report")
        self.btn_validate_all = QPushButton("Validate All")
        self.btn_handoff_snapshot = QPushButton("Handoff")
        self.btn_open_job_folder = QPushButton("Open folder")
        self.external_job_preset_combo = QComboBox()
        self.btn_inspect_job_preset = QPushButton("Inspect preset")
        self.btn_inspect_job_folder = QPushButton("Inspect folder")
        self.external_job_preset_combo.addItems(list(BACKEND_JOB_FOLDER_PRESETS.keys()))
        self.btn_refresh_jobs.setToolTip("Scan the job root for recent SCLAS result folders.")
        self.btn_load_job.setToolTip("Load result_data.csv from the selected job folder.")
        self.btn_diagnose_job.setToolTip("Inspect selected job files with the offline Abaqus diagnostics tool.")
        self.btn_compare_curve_v0.setToolTip("Compare the latest endpoint sweep and continuous CurveV0 result folders.")
        self.btn_project_status.setToolTip("Show the overall HELIX/SCLAS project status and next action.")
        self.btn_job_index.setToolTip("Show a handoff inventory of recent real SCLAS job folders.")
        self.btn_load_best_job.setToolTip("Load the best current job candidate selected by the Job Index readiness score.")
        self.btn_progress_timeline.setToolTip("Show chronological progress across recent jobs, acceptance gates, and contact milestones.")
        self.btn_result_intake.setToolTip("Check the selected or latest copied Abaqus result folder before acceptance.")
        self.btn_acceptance_gate.setToolTip("Evaluate whether the latest Abaqus result is research-ready.")
        self.btn_session_brief.setToolTip("Show the one-page git, intake, acceptance, and next-action startup brief.")
        self.btn_research_report.setToolTip("Generate a compact engineering interpretation report for the selected or latest job.")
        self.btn_validate_all.setToolTip("Run self-check, result intake, research report, progress timeline, handoff snapshot, and next prompt generation.")
        self.btn_handoff_snapshot.setToolTip("Save and show a compact handoff snapshot for the next Codex session.")
        self.btn_open_job_folder.setToolTip("Open the selected job folder in Finder or Explorer.")
        self.external_job_preset_combo.setToolTip("Choose a known external Abaqus backend job folder.")
        self.btn_inspect_job_preset.setToolTip("Run offline diagnostics on the selected external backend folder.")
        self.btn_inspect_job_folder.setToolTip("Run offline diagnostics on any Abaqus job folder without copying large files into this repository.")
        self.btn_refresh_jobs.clicked.connect(self.refresh_job_history)
        self.btn_load_job.clicked.connect(self.load_selected_job)
        self.btn_diagnose_job.clicked.connect(self.diagnose_selected_job)
        self.btn_compare_curve_v0.clicked.connect(self.compare_curve_v0_jobs)
        self.btn_project_status.clicked.connect(self.show_project_status)
        self.btn_job_index.clicked.connect(self.show_job_index)
        self.btn_load_best_job.clicked.connect(self.load_best_job)
        self.btn_progress_timeline.clicked.connect(self.show_progress_timeline)
        self.btn_result_intake.clicked.connect(self.show_result_intake)
        self.btn_acceptance_gate.clicked.connect(self.show_acceptance_gate)
        self.btn_session_brief.clicked.connect(self.show_session_brief)
        self.btn_research_report.clicked.connect(self.show_research_report)
        self.btn_validate_all.clicked.connect(self.run_validation_suite)
        self.btn_handoff_snapshot.clicked.connect(self.show_handoff_snapshot)
        self.btn_open_job_folder.clicked.connect(self.open_selected_job_folder)
        self.btn_inspect_job_preset.clicked.connect(self.inspect_job_preset)
        self.btn_inspect_job_folder.clicked.connect(self.inspect_job_folder_dialog)
        history_layout.addWidget(self.job_history_combo, 0, 0, 1, 3)
        history_layout.addWidget(self.btn_refresh_jobs, 1, 0)
        history_layout.addWidget(self.btn_load_job, 1, 1)
        history_layout.addWidget(self.btn_diagnose_job, 1, 2)
        history_layout.addWidget(self.btn_open_job_folder, 2, 0, 1, 3)

        advanced_jobs_box = QFrame()
        advanced_jobs_layout = QGridLayout(advanced_jobs_box)
        advanced_jobs_layout.setContentsMargins(0, 0, 0, 0)
        advanced_jobs_layout.setHorizontalSpacing(8)
        advanced_jobs_layout.setVerticalSpacing(8)
        advanced_jobs_layout.addWidget(self.btn_compare_curve_v0, 0, 0)
        advanced_jobs_layout.addWidget(self.btn_project_status, 0, 1)
        advanced_jobs_layout.addWidget(self.btn_job_index, 0, 2)
        advanced_jobs_layout.addWidget(self.btn_load_best_job, 1, 0)
        advanced_jobs_layout.addWidget(self.btn_progress_timeline, 1, 1)
        advanced_jobs_layout.addWidget(self.btn_result_intake, 1, 2)
        advanced_jobs_layout.addWidget(self.btn_acceptance_gate, 2, 0)
        advanced_jobs_layout.addWidget(self.btn_handoff_snapshot, 2, 1)
        advanced_jobs_layout.addWidget(self.btn_session_brief, 2, 2)
        advanced_jobs_layout.addWidget(self.btn_research_report, 3, 0)
        advanced_jobs_layout.addWidget(self.btn_validate_all, 3, 1, 1, 2)
        advanced_jobs_layout.addWidget(self.external_job_preset_combo, 4, 0, 1, 2)
        advanced_jobs_layout.addWidget(self.btn_inspect_job_preset, 4, 2)
        advanced_jobs_layout.addWidget(self.btn_inspect_job_folder, 5, 0, 1, 3)
        history_layout.addWidget(self.collapsible_section("Advanced Diagnostics", advanced_jobs_box, expanded=False), 3, 0, 1, 3)
        right.addWidget(self.history_box)

        left_scroll = self.scroll_panel(left_panel, min_width=360)
        result_scroll = self.scroll_panel(result_panel)

        layout.addWidget(self.panel_splitter(result_scroll, left_scroll, [980, 430]), 1)
        self.add_page(tab)
        self.install_input_preview_autorefresh()
        self.refresh_input_preview()

    def header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-family: {UI_FONT_QSS}; font-size: 17px; font-weight: 750; "
            "color: #17202a; padding: 2px 0 8px 0; letter-spacing: 0px;"
        )
        return label

    def form_label(self, text: str) -> QWidget:
        return VariableFormLabel(text)

    def build_layer_legend(self) -> QGroupBox:
        legend = QGroupBox("Layer Legend")
        legend.setMinimumWidth(210)
        layout = QVBoxLayout(legend)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        entries = [
            ("#1d3270", "Conductor"),
            ("#dfcf75", "Insulation"),
            ("#87949a", "Core Shield"),
            ("#5f96a4", "Filler"),
            ("#76868d", "Inner Sheath"),
            ("#d39135", "Armour Wire"),
            ("#26333a", "Bedding"),
            ("#6b7d87", "Outer Sheath"),
        ]
        for color, text in entries:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background-color: {color}; border: 1px solid #46515c; border-radius: 3px;"
            )
            label = QLabel(text)
            label.setStyleSheet(f"font-family: {UI_FONT_QSS}; font-size: 12px; color: #17202a;")
            row.addWidget(swatch)
            row.addWidget(label, 1)
            layout.addLayout(row)
        layout.addStretch()
        return legend

    def style_material_headers(self) -> None:
        if not hasattr(self, "table"):
            return
        self.table.setHorizontalHeaderLabels([
            "Layer",
            "Material",
            "Young's modulus\nE (GPa)",
            "Poisson's ratio\n\u03bd (-)",
            "Density\n\u03c1 (kg/m^3)",
        ])
        default_font = QFont(APP_FONT_FAMILY, 9)
        default_font.setWeight(QFont.DemiBold)
        symbol_font = QFont(SYMBOL_FONT_FAMILY, 9)
        symbol_font.setWeight(QFont.DemiBold)
        for column in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(column)
            if item is None:
                continue
            if column in (2, 3, 4):
                item.setFont(symbol_font)
                item.setForeground(QBrush(QColor("#0b5cad")))
            else:
                item.setFont(default_font)
                item.setForeground(QBrush(QColor("#1f2937")))

    def metric_box(self, title: str, value: str) -> QFrame:
        box = QFrame(); box.setObjectName("MetricBox")
        layout = QVBoxLayout(box)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-family: {UI_FONT_QSS}; color: #5f6b7a; font-size: 13px; font-weight: 600;"
        )
        value_label = QLabel(value)
        value_label.setStyleSheet(
            f"font-family: {UI_FONT_QSS}; color: #132033; font-size: 23px; font-weight: 750;"
        )
        value_label.setProperty("no_translate", True)
        layout.addWidget(title_label); layout.addWidget(value_label)
        box.value_label = value_label
        return box

    def init_material_table(self) -> None:
        materials = [
            ("Outer sheath layer", "Outer Sheath", 1.4, 0.45, 1300, QColor("#6b7d87")),
            ("Filler region", "Filler", 0.8, 0.48, 1200, QColor("#5f96a4")),
            ("Core insulation", "Insulation", 1.2, 0.46, 940, QColor("#dfcf75")),
            ("Core conductor", "Conductor", 108.0, 0.33, 8960, QColor("#1d3270")),
            ("Inner / outer armour", "Armour Wire", 210.0, 0.30, 7850, QColor("#d39135")),
            ("Inner sheath layer", "Inner Sheath", 1.5, 0.45, 1300, QColor("#76868d")),
            ("Core shield layer", "Core Shield", 16.0, 0.44, 11340, QColor("#87949a")),
            ("Bedding layer", "Bedding", 0.5, 0.49, 1100, QColor("#26333a")),
        ]
        for row, (name, material, e, nu, density, color) in enumerate(materials):
            layer_item = QTableWidgetItem(name)
            layer_item.setIcon(QIcon(self.color_icon(color)))
            self.table.setItem(row, 0, layer_item)
            self.table.setItem(row, 1, QTableWidgetItem(material))
            self.table.setItem(row, 2, QTableWidgetItem(str(e)))
            self.table.setItem(row, 3, QTableWidgetItem(str(nu)))
            self.table.setItem(row, 4, QTableWidgetItem(str(density)))

    def color_icon(self, color: QColor) -> QPixmap:
        pix = QPixmap(16, 16)
        pix.fill(color)
        return pix

    # ---------------- Data model ----------------
    def parse_geometry(self) -> Dict[str, float]:
        rc = safe_float(self.inputs["r_cond"], 4.0, "Conductor radius")
        ri = safe_float(self.inputs["r_insu"], 11.3, "Insulation radius")
        roc = safe_float(self.inputs["roc"], 15.3, "Core outer radius")
        coc = core_center_from_outer_radius(roc)
        tis = safe_float(self.inputs["tis"], 4.5, "Inner sheath thickness")
        ria = safe_float(self.inputs["r_ia"], 2.0, "Inner armour wire radius")
        bedding_thickness = safe_float(self.inputs["bedding_thickness"], 0.6, "Bedding thickness")
        roa = safe_float(self.inputs["r_oa"], 2.0, "Outer armour wire radius")
        tos = safe_float(self.inputs["tos"], 4.5, "Outer sheath thickness")
        nia_input = int(self.inputs["no_ia"].value())
        noa_input = int(self.inputs["no_oa"].value())

        if not (0 < rc < ri <= roc):
            raise ValueError("Geometry must satisfy 0 < conductor_radius < insulation_radius <= core_outer_radius.")
        if min(coc, tis, ria, bedding_thickness, roa, tos) < 0:
            raise ValueError("Radii and thickness values must be non-negative.")

        iris = roc + coc
        oris = iris + tis
        gap = 0.0
        co_ia = oris + ria
        irb = co_ia + ria
        orb = irb + bedding_thickness
        co_oa = orb + roa
        iros = co_oa + roa
        oros = iros + tos
        nia_limit = auto_armour_count(ria, co_ia)
        noa_limit = auto_armour_count(roa, co_oa)
        self.inputs["no_ia"].blockSignals(True)
        self.inputs["no_oa"].blockSignals(True)
        self.inputs["no_ia"].setMaximum(max(1, nia_limit))
        self.inputs["no_oa"].setMaximum(max(1, noa_limit))
        if nia_input > nia_limit:
            self.inputs["no_ia"].setValue(nia_limit)
            nia_input = nia_limit
        if noa_input > noa_limit:
            self.inputs["no_oa"].setValue(noa_limit)
            noa_input = noa_limit
        self.inputs["no_ia"].setToolTip(f"Default 55. Maximum {nia_limit} from n <= pi/asin(r_wire/R_center). Use Auto for the formula value.")
        self.inputs["no_oa"].setToolTip(f"Default 63. Maximum {noa_limit} from n <= pi/asin(r_wire/R_center). Use Auto for the formula value.")
        self.inputs["no_ia"].blockSignals(False)
        self.inputs["no_oa"].blockSignals(False)
        nia = nia_input if nia_input > 0 else nia_limit
        noa = noa_input if noa_input > 0 else noa_limit

        self.derived_geom = {
            "conductor_radius_mm": rc,
            "insulation_radius_mm": ri,
            "core_outer_radius_mm": roc,
            "core_center_radius_mm": coc,
            "core_center_radius_input_mm": coc,
            "core_center_radius_source": "auto_2sqrt3_over_3_times_core_outer_radius",
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
            "inner_armour_wire_count_input": nia_input,
            "outer_armour_wire_count_input": noa_input,
            "inner_armour_wire_count_source": "user" if nia_input > 0 else "auto_from_wire_radius_and_center_radius",
            "outer_armour_wire_count_source": "user" if noa_input > 0 else "auto_from_wire_radius_and_center_radius",
            "inner_armour_wire_count_limit": nia_limit,
            "outer_armour_wire_count_limit": noa_limit,
            "clearance_gap_mm": gap,
            "bedding_thickness_mm": bedding_thickness,
            "filler_count": 3,
            "filler_outer_radius_mm": iris,
            "filler_profile_scale": roc / 15.3,
        }
        return self.derived_geom

    def mesh_value(self, key: str) -> str:
        if key == "model_strategy":
            return "full_3d_segment"
        if key == "armour_model":
            return "solid_wire"
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
        combo = self.mesh_inputs[key]
        text = combo.currentData() or combo.currentText()
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
                "density": "kg/m^3 in materials",
                "poisson_ratio": "nu, dimensionless",
                "moment_output_required": "kN.m",
            },
            "geometry_mm": {
                "conductor_radius_mm": safe_float(self.inputs["r_cond"], 4.0, "Conductor radius"),
                "insulation_radius_mm": safe_float(self.inputs["r_insu"], 11.3, "Insulation radius"),
                "core_outer_radius_mm": dg["core_outer_radius_mm"],
                "core_center_radius_mm": dg["core_center_radius_mm"],
                "inner_sheath_thickness_mm": safe_float(self.inputs["tis"], 4.5, "Inner sheath thickness"),
                "bedding_thickness_mm": safe_float(self.inputs["bedding_thickness"], 0.6, "Bedding thickness"),
                "clearance_gap_mm": 0.0,
                "outer_sheath_thickness_mm": safe_float(self.inputs["tos"], 4.5, "Outer sheath thickness"),
            },
            "derived_geometry_mm": dg,
            "armour": {
                "inner_wire_radius_mm": safe_float(self.inputs["r_ia"], 2.0, "Inner armour wire radius"),
                "outer_wire_radius_mm": safe_float(self.inputs["r_oa"], 2.0, "Outer armour wire radius"),
                "inner_wire_count": int(self.inputs["no_ia"].value()),
                "outer_wire_count": int(self.inputs["no_oa"].value()),
                "inner_wire_count_resolved": int(dg["inner_armour_wire_count"]),
                "outer_wire_count_resolved": int(dg["outer_armour_wire_count"]),
                "inner_wire_count_source": dg["inner_armour_wire_count_source"],
                "outer_wire_count_source": dg["outer_armour_wire_count_source"],
                "core_lay_angle_deg": safe_float(self.inputs["core_lay_angle"], 8.98, "Core lay angle"),
                "inner_lay_angle_deg": safe_float(self.inputs["inner_lay_angle"], 20.1, "Inner armour lay angle"),
                "outer_lay_angle_deg": safe_float(self.inputs["outer_lay_angle"], 19.6, "Outer armour lay angle"),
                "inner_armour_lay_angle_deg": safe_float(self.inputs["inner_lay_angle"], 20.1, "Inner armour lay angle"),
                "outer_armour_lay_angle_deg": safe_float(self.inputs["outer_lay_angle"], 19.6, "Outer armour lay angle"),
                "lay_angle_deg": 0.5 * (
                    safe_float(self.inputs["inner_lay_angle"], 20.1, "Inner armour lay angle")
                    + safe_float(self.inputs["outer_lay_angle"], 19.6, "Outer armour lay angle")
                ),
            },
            "materials": materials,
            "mesh": {
                "requested_element_type": self.mesh_inputs["elem_type"].currentText(),
                "solid_element_type": self.mesh_inputs["elem_type"].currentText(),
                "model_strategy": self.mesh_value("model_strategy"),
                "armour_model": self.mesh_value("armour_model"),
                "axial_divisions": int(self.mesh_inputs["z_elem"].value()),
                "core_circumferential_divisions": int(self.mesh_inputs["c_elem_core"].value()),
                "armour_circumferential_divisions": int(self.mesh_inputs["c_elem_armour"].value()),
                "inner_sheath_radial_divisions": int(self.mesh_inputs["r_elem_inner_sheath"].value()),
                "bedding_radial_divisions": int(self.mesh_inputs["r_elem_bedding"].value()),
                "outer_sheath_radial_divisions": int(self.mesh_inputs["r_elem_outer_sheath"].value()),
                "filler_divisions": int(self.mesh_inputs["filler_z_elem"].value()),
                "filler_z_divisions": int(self.mesh_inputs["filler_z_elem"].value()),
                "radial_divisions_per_layer": int(self.mesh_inputs["r_elem_bedding"].value()),
                "global_seed_size_mm": None,
                "local_refinement_factor": 1.0,
                "contact_regularization_beta": safe_float(self.mesh_inputs["contact_beta"], 0.001, "Contact regularization beta"),
                "coordinate_basis": "cylindrical_r_theta_z",
                "note": "GUI preview only. Abaqus backend decides final seed/mesh controls.",
            },
            "mesh_controls": {
                "coordinate_basis": "cylindrical_r_theta_z",
                "components": {
                    "Core": {
                        "r": {"mode": "disabled"},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_core"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "InnerSheath": {
                        "r": {"mode": "count", "count": int(self.mesh_inputs["r_elem_inner_sheath"].value())},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_core"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "Bedding": {
                        "r": {"mode": "count", "count": int(self.mesh_inputs["r_elem_bedding"].value())},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_core"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "OuterSheath": {
                        "r": {"mode": "count", "count": int(self.mesh_inputs["r_elem_outer_sheath"].value())},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_core"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "InnerArmour": {
                        "r": {"mode": "disabled"},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_armour"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "OuterArmour": {
                        "r": {"mode": "disabled"},
                        "theta": {"mode": "count", "count": int(self.mesh_inputs["c_elem_armour"].value())},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["z_elem"].value()), "size_mm": None},
                    },
                    "Filler": {
                        "r": {"mode": "special_profile"},
                        "theta": {"mode": "special_profile"},
                        "z": {"mode": "count", "count": int(self.mesh_inputs["filler_z_elem"].value()), "size_mm": None},
                    },
                },
            },
            "analysis_conditions": {
                "effective_length_mm": safe_float(self.cond["eff_length"], 234.2, "Effective length"),
                "external_pressure_mpa": safe_float(self.cond["pressure"], 40.0, "External pressure"),
                "hydrostatic_pressure_mpa": safe_float(self.cond["pressure"], 40.0, "External pressure"),
                "residual_contact_pressure_mpa": safe_float(self.cond["residual_contact_pressure"], 0.3, "Residual contact pressure"),
                "friction_coefficient": safe_float(self.cond["friction"], 0.22, "Friction coefficient"),
                "max_curvature_1_per_m": safe_float(self.cond["curvature"], 0.08, "Max curvature"),
                "curvature_unit": "1_per_m",
                "curve_factors": [-0.1, -0.05, 0.0, 0.05, 0.1],
                "max_twist_rad_per_m": safe_float(self.cond["twist"], 0.05, "Max twist"),
                "max_axial_strain": safe_float(self.cond["axial_strain"], 0.002, "Max axial strain"),
                "radial_compression_ratio": safe_float(self.cond["radial_compression"], 0.015, "Radial compression ratio"),
                "contact_regularization_beta": safe_float(self.mesh_inputs["contact_beta"], 0.001, "Contact regularization beta"),
                "loading_cycles": int(self.cond["cycles"].value()),
                "solver_steps": int(self.cond["steps"].value()),
                "run_mode": "export_job_only",
                "save_abaqus_files": True,
                "run_solver": False,
                "extract_odb": True,
            },
            "solver": {
                "step_time": 1.0,
                "max_wall_time_min": None,
                "initial_increment": 1.0e-5,
                "minimum_increment": 1.0e-11,
                "maximum_increment": 0.001,
                "max_num_increments": 10000,
                "nlgeom": False,
                "stabilization_enabled": True,
                "stabilization_factor": 0.0002,
            },
            "output_requests": {
                "history": ["UR2", "RM2"],
                "field": {
                    "U_UR": True,
                    "RF_RM": True,
                    "S": True,
                    "CPRESS": True,
                    "COPEN": True,
                    "CSLIP": True,
                    "CSHEAR": True,
                    "CSTATUS": False,
                },
            },
            "modeling": {
                "model_type": "full_3d",
                "model_label": "Full 3D",
                "equivalent_model_level": 1,
                "use_equivalent_properties": False,
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
            material_item = self.table.item(row, 1)
            name = name_item.text().strip() if name_item else f"Layer {row + 1}"
            material = material_item.text().strip() if material_item else ""
            rows.append({
                "index": row + 1,
                "name": name,
                "material": material,
                "elastic_modulus_GPa": table_float(self.table, row, 2, 1.0, f"{name} E"),
                "poisson_ratio": table_float(self.table, row, 3, 0.3, f"{name} nu"),
                "density_kg_m3": table_float(self.table, row, 4, 0.0, f"{name} density"),
            })
        return rows

    def compute_equivalent_properties(self, materials: List[dict], dg: Dict[str, float]) -> dict:
        # GUI-side estimate only. Abaqus should compute final stiffness from the full model.
        conductor = next(
            (
                material
                for material in materials
                if "conductor" in str(material.get("material", "")).lower()
                or "conductor" in str(material.get("name", "")).lower()
            ),
            materials[0],
        )
        e_copper_pa = conductor["elastic_modulus_GPa"] * 1e9
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
            self.refresh_input_preview(payload)
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
            self.refresh_input_preview(payload)
            path, _ = QFileDialog.getSaveFileName(self, "Save Abaqus input JSON", "input_data.json", "JSON Files (*.json)")
            if path:
                write_json(Path(path), payload)
                QMessageBox.information(self, "Saved", f"JSON saved:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))

    def install_input_preview_autorefresh(self) -> None:
        self.input_preview_timer = QTimer(self)
        self.input_preview_timer.setSingleShot(True)
        self.input_preview_timer.timeout.connect(self.refresh_input_preview)

        def connect_widget(widget):
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.schedule_input_preview_refresh)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self.schedule_input_preview_refresh)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.schedule_input_preview_refresh)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self.schedule_input_preview_refresh)

        for widget in list(self.inputs.values()) + list(self.mesh_inputs.values()) + list(self.cond.values()):
            connect_widget(widget)
        for widget in self.study_checks.values():
            connect_widget(widget)
        if hasattr(self, "table"):
            self.table.itemChanged.connect(self.schedule_input_preview_refresh)

    def schedule_input_preview_refresh(self, *args) -> None:
        if hasattr(self, "input_preview_timer"):
            self.input_preview_timer.start(250)

    def format_input_preview(self, payload: dict) -> str:
        dg = payload["derived_geometry_mm"]
        mesh = payload["mesh"]
        analysis = payload["analysis_conditions"]
        armour = payload["armour"]
        job_root = Path(self.job_root_input.text().strip()).expanduser()
        job_folder = job_root / str(payload["metadata"]["job_id"])
        enabled = [
            key for key, value in payload["study_scope"]["enabled_assessments"].items()
            if value
        ]
        return "\n".join([
            "Abaqus input_data.json preview",
            "",
            "[Package]",
            f"job_folder: {job_folder}",
            "contract: GUI writes input_data.json; Abaqus backend creates CAE/INP/results.",
            "",
            "[Geometry]",
            f"core_outer_radius_mm: {payload['geometry_mm']['core_outer_radius_mm']:.5g}",
            f"bedding_thickness_mm: {payload['geometry_mm']['bedding_thickness_mm']:.5g}",
            f"outer_sheath_outer_radius_mm: {dg['outer_sheath_outer_radius_mm']:.5g}",
            "",
            "[Armour]",
            f"inner_wire_count: {armour['inner_wire_count_resolved']} ({armour['inner_wire_count_source']})",
            f"outer_wire_count: {armour['outer_wire_count_resolved']} ({armour['outer_wire_count_source']})",
            f"inner_wire_count_limit: {dg['inner_armour_wire_count_limit']}",
            f"outer_wire_count_limit: {dg['outer_armour_wire_count_limit']}",
            f"inner_wire_radius_mm: {armour['inner_wire_radius_mm']:.5g}",
            f"outer_wire_radius_mm: {armour['outer_wire_radius_mm']:.5g}",
            "",
            "[Mesh Request]",
            f"element_type: {mesh['requested_element_type']}",
            f"strategy: {mesh['model_strategy']}",
            f"armour_model: {mesh['armour_model']}",
            f"axial_divisions: {mesh['axial_divisions']}",
            f"core_circumferential_divisions: {mesh['core_circumferential_divisions']}",
            f"armour_circumferential_divisions: {mesh['armour_circumferential_divisions']}",
            f"inner_sheath_radial_divisions: {mesh['inner_sheath_radial_divisions']}",
            f"bedding_radial_divisions: {mesh['bedding_radial_divisions']}",
            f"outer_sheath_radial_divisions: {mesh['outer_sheath_radial_divisions']}",
            f"filler_z_divisions: {mesh['filler_z_divisions']}",
            "",
            "[Analysis Conditions]",
            f"effective_length_mm: {analysis['effective_length_mm']:.5g}",
            f"external_pressure_mpa: {analysis['external_pressure_mpa']:.5g}",
            f"max_curvature_1_per_m: {analysis['max_curvature_1_per_m']:.5g}",
            f"max_twist_rad_per_m: {analysis['max_twist_rad_per_m']:.5g}",
            f"max_axial_strain: {analysis['max_axial_strain']:.5g}",
            f"radial_compression_ratio: {analysis['radial_compression_ratio']:.5g}",
            f"loading_cycles: {analysis['loading_cycles']}",
            f"solver_steps: {analysis['solver_steps']}",
            "",
            "[Backend Defaults Hidden From Jiho GUI Scope]",
            f"friction_coefficient: {analysis['friction_coefficient']:.5g}",
            f"residual_contact_pressure_mpa: {analysis['residual_contact_pressure_mpa']:.5g}",
            f"contact_regularization_beta: {analysis['contact_regularization_beta']:.5g}",
            "",
            "[Enabled Assessments]",
            ", ".join(enabled) if enabled else "none",
        ])

    def refresh_input_preview(self, payload: Optional[dict] = None) -> None:
        if not hasattr(self, "input_preview_text"):
            return
        try:
            if payload is None:
                payload = self.build_payload()
            self.input_preview_text.setPlainText(self.format_input_preview(payload))
        except Exception as exc:
            self.input_preview_text.setPlainText(f"Input preview unavailable:\n{exc}")

    def export_input_summary_dialog(self) -> None:
        try:
            payload = self.build_payload()
            text = self.format_input_preview(payload)
            default = str(Path(self.job_root_input.text().strip()).expanduser() / "abaqus_input_summary.txt")
            path, _ = QFileDialog.getSaveFileName(self, "Save Abaqus input summary", default, "Text Files (*.txt)")
            if path:
                Path(path).write_text(text + "\n", encoding="utf-8")
                QMessageBox.information(self, "Saved", f"Summary saved:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Summary export error", str(exc))

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
            self.refresh_input_preview(payload)
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
            jobs.extend(candidate_job_dirs(root, include_self_check=False, require_csv=True))
        jobs = sorted(set(jobs), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:25]

        self.job_history_paths = jobs
        self.job_history_combo.clear()
        if not jobs:
            self.job_history_combo.addItem(self.ui_text("No result jobs found"))
            return
        for job in jobs:
            stamp = datetime.fromtimestamp(job.stat().st_mtime).strftime("%m-%d %H:%M")
            self.job_history_combo.addItem(f"{stamp} | {job.name}")

    def selected_history_job(self) -> Optional[Path]:
        index = self.job_history_combo.currentIndex() if hasattr(self, "job_history_combo") else -1
        if index < 0 or index >= len(self.job_history_paths):
            return None
        return self.job_history_paths[index]

    def load_selected_job(self) -> None:
        job_dir = self.selected_history_job()
        if job_dir is None:
            QMessageBox.information(self, "Recent Jobs", "No result job is selected.")
            return
        try:
            self.load_result_bundle(job_dir / "result_data.csv", source="RECENT_JOB_LOAD")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Recent job load error", str(exc))

    def diagnose_selected_job(self) -> None:
        job_dir = self.selected_history_job()
        if job_dir is None:
            QMessageBox.information(self, "Recent Jobs", "No result job is selected.")
            return
        try:
            self.diagnose_job_folder(job_dir)
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Offline diagnostics error", str(exc))

    def open_selected_job_folder(self) -> None:
        job_dir = self.selected_history_job()
        if job_dir is None:
            QMessageBox.information(self, "Recent Jobs", "No result job is selected.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(job_dir.resolve()))):
            QMessageBox.warning(self, "Recent Jobs", f"Could not open folder:\n{job_dir}")
            return
        self.log(f"[JOBS] Opened folder: {job_dir}")

    def diagnose_job_folder(self, job_dir: Path) -> None:
        from sclas_offline_diagnostics import build_report, save_markdown_report, save_report

        report = build_report(job_dir)
        saved_path = save_report(report)
        saved_markdown_path = save_markdown_report(report)
        report["saved_report"] = str(saved_path)
        report["saved_markdown_report"] = str(saved_markdown_path)
        text = self.format_diagnostic_report(report)
        self.last_summary_data = {}
        self.summary_text.setPlainText(text)
        errors = sum(1 for item in report.get("issues", []) if item.get("severity") == "error")
        warnings = sum(1 for item in report.get("issues", []) if item.get("severity") == "warning")
        tone = "error" if errors else "warn" if warnings else "good"
        label = "Result: error" if errors else "Result: ready"
        self.set_badge(self.lbl_result_status, label, tone)
        self.log(f"[DIAG] Offline diagnostics: {job_dir} | errors={errors}, warnings={warnings}")
        self.log(f"[DIAG] Saved report: {saved_path}")
        self.log(f"[DIAG] Saved Markdown report: {saved_markdown_path}")

    def inspect_job_preset(self) -> None:
        label = self.external_job_preset_combo.currentText()
        job_dir = BACKEND_JOB_FOLDER_PRESETS.get(label)
        if job_dir is None:
            QMessageBox.information(self, "Backend job preset", "No backend job preset is selected.")
            return
        if not job_dir.exists():
            QMessageBox.warning(self, "Backend job preset missing", f"Preset folder not found:\n{job_dir}")
            return
        try:
            self.diagnose_job_folder(job_dir)
            self.log(f"[DIAG] Backend preset inspected: {label}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Backend preset diagnostics error", str(exc))

    def inspect_job_folder_dialog(self) -> None:
        default_dir = Path("C:/HELIX/Abaqus+_work/for_test")
        start_dir = str(default_dir if default_dir.exists() else PROJECT_DIR)
        folder = QFileDialog.getExistingDirectory(self, "Inspect Abaqus job folder", start_dir)
        if not folder:
            return
        try:
            self.diagnose_job_folder(Path(folder))
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Folder diagnostics error", str(exc))

    def compare_curve_v0_jobs(self) -> None:
        try:
            from sclas_curve_compare import compare, human_report, latest_job, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            endpoint = latest_job(job_root, "endpoint")
            continuous = latest_job(job_root, "continuous")
            report = compare(endpoint, continuous)
            saved_path = save_report(report)
            saved_markdown_path = save_markdown_report(report)
            report["saved_report"] = str(saved_path)
            report["saved_markdown_report"] = str(saved_markdown_path)
            endpoint_path = Path(endpoint["path"]) / "result_data.csv"
            continuous_path = Path(continuous["path"]) / "result_data.csv"
            self.clear_compare_curves()
            self.load_result_bundle(endpoint_path, source="CURVEV0_ENDPOINT")
            self.add_compare_curve(continuous_path, label="Continuous CurveV0")
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            status = report.get("status")
            tone = "good" if status == "aligned" else "warn" if status == "review" else "error"
            label = "Result: ready" if status in ("aligned", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[COMPARE] CurveV0 endpoint/continuous | status={0} | ratio={1}".format(
                    status,
                    report.get("peak_moment_ratio_continuous_over_endpoint", "-"),
                )
            )
            self.log(f"[COMPARE] Saved report: {saved_path}")
            self.log(f"[COMPARE] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "CurveV0 comparison error", str(exc))

    def show_project_status(self) -> None:
        try:
            from sclas_project_status import build_status, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            status = build_status(job_root)
            saved_path = save_report(status)
            status["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(status)
            status["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(status))
            has_blocked = any(flag.get("status") == "blocked" for flag in status.get("completion_flags", []))
            has_review = any(flag.get("status") == "review" for flag in status.get("completion_flags", []))
            tone = "error" if has_blocked else "warn" if has_review else "good"
            label = "Result: error" if has_blocked else "Result: ready"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[STATUS] Project status | latest={0} | next={1}".format(
                    status.get("latest_job", "-"),
                    status.get("recommended_next_action", "-"),
                )
            )
            self.log(f"[STATUS] Saved report: {saved_path}")
            self.log(f"[STATUS] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Project status error", str(exc))

    def show_job_index(self) -> None:
        try:
            from sclas_job_index import build_index, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            index = build_index(job_root, limit=15)
            saved_path = save_report(index)
            index["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(index)
            index["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(index))
            health_counts = index.get("health_counts", {})
            has_blocked = any(key in health_counts for key in ("BLOCKED", "ERROR"))
            has_review = "REVIEW" in health_counts
            tone = "error" if has_blocked else "warn" if has_review else "good"
            label = "Result: error" if has_blocked else "Result: ready"
            self.set_badge(self.lbl_result_status, label, tone)
            best_job = index.get("best_job") or {}
            self.log(
                "[INDEX] Job index | reported={0}/{1} | health={2} | best={3} score={4}".format(
                    index.get("reported_count", 0),
                    index.get("total_candidates", 0),
                    index.get("health_counts", {}),
                    best_job.get("name", "-"),
                    best_job.get("readiness_score", "-"),
                )
            )
            self.log(f"[INDEX] Saved report: {saved_path}")
            self.log(f"[INDEX] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Job index error", str(exc))

    def load_best_job(self) -> None:
        try:
            from sclas_job_index import build_index

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            index = build_index(job_root, limit=25)
            best_job = index.get("best_job") or {}
            best_path = best_job.get("path")
            if not best_path:
                QMessageBox.information(self, "Job Index", "No best job candidate is available.")
                return
            job_dir = Path(best_path)
            result_csv = job_dir / "result_data.csv"
            if not result_csv.exists():
                QMessageBox.information(self, "Job Index", f"Best job has no result_data.csv:\n{job_dir}")
                return
            self.load_result_bundle(result_csv, source="BEST_JOB_LOAD")
            self.log(
                "[INDEX] Loaded best job: {0} | score={1} | label={2}".format(
                    best_job.get("name", job_dir.name),
                    best_job.get("readiness_score", "-"),
                    best_job.get("readiness_label", "-"),
                )
            )
            self.refresh_job_history()
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Load best job error", str(exc))

    def show_progress_timeline(self) -> None:
        try:
            from sclas_progress_timeline import build_timeline, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            report = build_timeline(job_root, limit=20)
            saved_path = save_report(report)
            report["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(report)
            report["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            latest_status = report.get("latest_acceptance_status")
            tone = "good" if latest_status == "accepted" else "warn" if latest_status == "review" else "error"
            label = "Result: ready" if latest_status in ("accepted", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[TIMELINE] Progress timeline | reported={0}/{1} | latest_acceptance={2}".format(
                    report.get("reported_count", 0),
                    report.get("total_candidates", 0),
                    latest_status,
                )
            )
            self.log(f"[TIMELINE] Saved report: {saved_path}")
            self.log(f"[TIMELINE] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Progress timeline error", str(exc))

    def show_result_intake(self) -> None:
        try:
            from sclas_result_intake import build_intake, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            selected_job = self.selected_history_job()
            report = build_intake(job_root, job_dir=selected_job)
            saved_path = save_report(report)
            report["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(report)
            report["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            status = report.get("status")
            tone = "good" if status == "ready" else "warn" if status == "review" else "error"
            label = "Result: ready" if status in ("ready", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[INTAKE] Result intake | status={0} | job={1} | next={2}".format(
                    status,
                    report.get("job_dir", "-"),
                    report.get("recommended_next_action", "-"),
                )
            )
            self.log(f"[INTAKE] Saved report: {saved_path}")
            self.log(f"[INTAKE] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Result intake error", str(exc))

    def show_acceptance_gate(self) -> None:
        try:
            from sclas_acceptance_gate import build_gate, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            report = build_gate(job_root)
            saved_path = save_report(report)
            report["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(report)
            report["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            status = report.get("overall_status")
            tone = "good" if status == "accepted" else "warn" if status == "review" else "error"
            label = "Result: ready" if status in ("accepted", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[ACCEPT] Acceptance gate | status={0} | latest={1} | next={2}".format(
                    status,
                    report.get("latest_job", "-"),
                    report.get("recommended_next_action", "-"),
                )
            )
            self.log(f"[ACCEPT] Saved report: {saved_path}")
            self.log(f"[ACCEPT] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Acceptance gate error", str(exc))

    def show_research_report(self) -> None:
        try:
            from sclas_research_report import build_research_report, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            selected_job = self.selected_history_job()
            report = build_research_report(job_root, job_dir=selected_job)
            saved_path = save_report(report)
            report["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(report)
            report["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            status = report.get("status")
            tone = "good" if status == "research_ready" else "warn" if status == "needs_review" else "error"
            label = "Result: ready" if status in ("research_ready", "needs_review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[REPORT] Research report | status={0} | job={1} | curve={2}".format(
                    status,
                    report.get("job_dir", "-"),
                    report.get("curve_v0_comparison_status", "-"),
                )
            )
            self.log(f"[REPORT] Saved report: {saved_path}")
            self.log(f"[REPORT] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Research report error", str(exc))

    def show_session_brief(self) -> None:
        try:
            from sclas_session_brief import build_brief, default_report_path, human_report
            from sclas_session_brief import save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            brief = build_brief(job_root, limit=15)
            json_path = default_report_path("json")
            markdown_path = default_report_path("md")
            brief["saved_report"] = str(json_path)
            brief["saved_markdown_report"] = str(markdown_path)
            save_report(brief, json_path)
            save_markdown_report(brief, markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(brief))
            status = brief.get("status")
            tone = "good" if status == "research_candidate" else "warn" if status == "review" else "error"
            label = "Result: ready" if status in ("research_candidate", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[BRIEF] Session brief | status={0} | latest={1} | next={2}".format(
                    status,
                    brief.get("latest_job", "-"),
                    brief.get("mac_next_action", "-"),
                )
            )
            self.log(f"[BRIEF] Saved report: {json_path}")
            self.log(f"[BRIEF] Saved Markdown report: {markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Session brief error", str(exc))

    def show_handoff_snapshot(self) -> None:
        try:
            from sclas_handoff_snapshot import build_snapshot, human_report, save_markdown_report, save_report

            job_root = Path(self.job_root_input.text().strip()).expanduser()
            snapshot = build_snapshot(job_root, limit=15)
            saved_path = save_report(snapshot)
            snapshot["saved_report"] = str(saved_path)
            saved_markdown_path = save_markdown_report(snapshot)
            snapshot["saved_markdown_report"] = str(saved_markdown_path)
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(snapshot))
            focus = snapshot.get("handoff_focus", {})
            status = snapshot.get("project_status", {})
            has_blocked = any(
                flag.get("status") == "blocked"
                for flag in status.get("completion_flags", [])
            )
            tone = "error" if has_blocked else "good"
            label = "Result: error" if has_blocked else "Result: ready"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[HANDOFF] Snapshot | best={0} score={1} | next={2}".format(
                    focus.get("best_job", "-"),
                    focus.get("best_job_readiness_score", "-"),
                    focus.get("next_action", "-"),
                )
            )
            self.log(f"[HANDOFF] Saved report: {saved_path}")
            self.log(f"[HANDOFF] Saved Markdown report: {saved_markdown_path}")
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Handoff snapshot error", str(exc))

    def run_validation_suite(self) -> None:
        self.btn_validate_all.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from sclas_validation_suite import build_suite, human_report, save_markdown_report, save_report

            self.log("[VALIDATE] Running local validation suite...")
            job_root = Path(self.job_root_input.text().strip()).expanduser()
            report = build_suite(job_root, limit=15)
            suite_json = save_report(report)
            report["saved_report"] = str(suite_json)
            suite_md = save_markdown_report(report)
            report["saved_markdown_report"] = str(suite_md)
            if report.get("self_check", {}).get("status") == "failed":
                raise RuntimeError("sclas_self_check.py failed")
            self.last_summary_data = {}
            self.summary_text.setPlainText(human_report(report))
            acceptance = report.get("acceptance_gate", {})
            status = acceptance.get("overall_status")
            tone = "good" if status == "accepted" else "warn" if status == "review" else "error"
            label = "Result: ready" if status in ("accepted", "review") else "Result: error"
            self.set_badge(self.lbl_result_status, label, tone)
            self.log(
                "[VALIDATE] Complete | status={0} | suite={1}".format(report.get("status", "-"), suite_json)
            )
            self.refresh_job_history()
        except Exception as exc:
            self.set_badge(self.lbl_result_status, "Result: error", "error")
            QMessageBox.critical(self, "Validation suite error", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_validate_all.setEnabled(True)

    @staticmethod
    def counts_text(counts, limit: int = 4) -> str:
        if not isinstance(counts, dict) or not counts:
            return "-"
        ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return ", ".join(f"{key}={value}" for key, value in ordered[:limit])

    def format_diagnostic_report(self, report: dict) -> str:
        diagnostic_summary = report.get("diagnostic_summary", {})
        issue_counts = diagnostic_summary.get("issue_counts", {})
        first_issue = diagnostic_summary.get("first_blocking_issue") or {}
        sweep_shape = report.get("endpoint_sweep_shape", {})
        sweep_children = report.get("endpoint_sweep_children", {})
        continuous_shape = report.get("continuous_curve_v0_shape", {})
        sweep_mesh = sweep_children.get("mesh_quality_warning_details", {}) if isinstance(sweep_children, dict) else {}
        sweep_b31 = sweep_children.get("b31_beam_warning_details", {}) if isinstance(sweep_children, dict) else {}
        lines = [
            "Offline Abaqus Diagnostics",
            f"Job: {Path(report.get('job_dir', '-')).name}",
            f"Saved report: {report.get('saved_report', '-')}",
            f"Saved Markdown: {report.get('saved_markdown_report', '-')}",
            "",
            "[Recommended Next Action]",
            diagnostic_summary.get("recommended_next_action", "-"),
            "",
            "[Issue Counts]",
            f"errors: {issue_counts.get('error', 0)}",
            f"warnings: {issue_counts.get('warning', 0)}",
            f"info: {issue_counts.get('info', 0)}",
            f"first: [{first_issue.get('severity', '-')}] {first_issue.get('message', '-')}",
            "",
        ]
        if sweep_shape or sweep_children:
            lines.extend([
                "[CurveV0 Sweep]",
                f"shape_checks_passed: {sweep_shape.get('shape_checks_passed', '-')}",
                f"child_deep_validated: {sweep_children.get('all_children_deep_validated', '-')}",
                f"blocking_log_hits: {sweep_children.get('blocking_log_hits', '-')}",
                f"actual_warning_hits: {sweep_children.get('actual_warning_log_hits', '-')}",
                f"B31 warnings: {self.counts_text(sweep_b31.get('warning_sets'))}",
                f"distorted elements: {sweep_mesh.get('distorted_reported_element_count', '-')}",
                "",
            ])
        if continuous_shape:
            lines.extend([
                "[Continuous CurveV0]",
                f"shape_checks_passed: {continuous_shape.get('shape_checks_passed', '-')}",
                f"numeric_rows: {continuous_shape.get('numeric_rows', '-')}",
                f"near_zero_count: {continuous_shape.get('near_zero_count', '-')}",
                f"odd_symmetry_max_relative: {continuous_shape.get('odd_symmetry_max_relative_moment_sum', '-')}",
                f"max_abs_curvature_1_per_m: {continuous_shape.get('max_abs_curvature_1_per_m', '-')}",
                f"max_abs_moment_kn_m: {continuous_shape.get('max_abs_moment_kn_m', '-')}",
                "",
            ])
        for key, title in [
            ("result_data_csv", "Result CSV"),
            ("result_summary_json", "Summary JSON"),
            ("abaqus_mesh_manifest_json", "Mesh Manifest"),
            ("input_deck", "Input Deck"),
            ("solver_logs", "Solver Logs"),
        ]:
            section = report.get(key, {})
            lines.append(f"[{title}]")
            if key == "solver_logs":
                lines.append(f"files: {', '.join(section.get('files', [])) or '-'}")
                matches = section.get("matches", [])
                lines.append(f"matches: {len(matches)}")
                lines.append(f"actual_warning_match_count: {section.get('actual_warning_match_count', '-')}")
                lines.append(f"warning_categories: {self.counts_text(section.get('warning_categories'))}")
                solver_mesh = section.get("mesh_quality_warning_details", {})
                solver_b31 = section.get("b31_beam_warning_details", {})
                if isinstance(solver_mesh, dict):
                    lines.append(f"warning_sets: {self.counts_text(solver_mesh.get('warning_sets'))}")
                    lines.append(f"distorted_reported_element_count: {solver_mesh.get('distorted_reported_element_count', '-')}")
                if isinstance(solver_b31, dict):
                    lines.append(f"B31_warning_sets: {self.counts_text(solver_b31.get('warning_sets'))}")
                for match in matches[:5]:
                    lines.append(f"- {match.get('file')}:{match.get('line')} {match.get('text')}")
            elif key == "input_deck":
                lines.append(f"exists: {section.get('exists')}")
                lines.append(f"file: {section.get('file', '-')}")
                lines.append(f"coupling_count: {section.get('coupling_count', 0)}")
                lines.append(f"kinematic_count: {section.get('kinematic_count', 0)}")
                lines.append(f"coupling_after_end_assembly: {section.get('coupling_after_end_assembly', False)}")
            elif key == "abaqus_mesh_manifest_json":
                lines.append(f"exists: {section.get('exists')}")
                lines.append(f"status: {section.get('status', '-')}")
                lines.append(f"contact_pair_scaffold_status: {section.get('contact_pair_scaffold_status', '-')}")
                lines.append(f"boundary_condition_scaffold_status: {section.get('boundary_condition_scaffold_status', '-')}")
                lines.append(f"contact_bindings: {section.get('contact_bindings', 0)}")
                lines.append(f"beam_orientation: {section.get('beam_orientation_status', '-')}")
            elif key == "result_summary_json":
                lines.append(f"exists: {section.get('exists')}")
                lines.append(f"source: {section.get('source', '-')}")
                lines.append(f"status: {section.get('status', '-')}")
                lines.append(f"mesh_status: {section.get('mesh_status', '-')}")
                lines.append(f"curve_class: {section.get('abaqus_curve_class', '-')}")
                lines.append(f"research_curve: {section.get('abaqus_is_research_curve', '-')}")
                lines.append(f"enabled: {', '.join(section.get('enabled_assessments', [])) or '-'}")
            else:
                lines.append(f"exists: {section.get('exists')}")
                lines.append(f"header: {section.get('header', '-')}")
                lines.append(f"data_rows: {section.get('data_rows', 0)}")
            lines.append("")

        issues = report.get("issues", [])
        lines.append("[Issues]")
        if not issues:
            lines.append("none")
        for issue in issues[:12]:
            lines.append(f"- [{issue.get('severity')}] {issue.get('message')}")
            if issue.get("detail") not in (None, ""):
                lines.append(f"  detail: {issue.get('detail')}")
        if len(issues) > 12:
            lines.append(f"... {len(issues) - 12} more")
        return "\n".join(lines)

    def set_input_widget_value(self, widget, value) -> bool:
        if value is None:
            return False
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
            return True
        if isinstance(widget, QSpinBox):
            widget.setValue(int(round(float(value))))
            return True
        if isinstance(widget, QComboBox):
            text = str(value)
            idx = widget.findText(text)
            if idx < 0:
                idx = widget.findText(GUI_COMBO_ALIASES.get(text, ""))
            if idx >= 0:
                widget.setCurrentIndex(idx)
                return True
        return False

    def apply_backend_payload_to_gui(self, payload: dict) -> int:
        updated = 0
        gui_values = backend_payload_gui_values(payload)

        for key, value in gui_values["geometry"].items():
            if key in self.inputs:
                updated += int(self.set_input_widget_value(self.inputs[key], value))

        for key, value in gui_values["analysis_conditions"].items():
            if key in self.cond:
                updated += int(self.set_input_widget_value(self.cond[key], value))

        for key, value in gui_values["mesh"].items():
            if key in self.mesh_inputs:
                updated += int(self.set_input_widget_value(self.mesh_inputs[key], value))

        for material in gui_values["materials"]:
            if not isinstance(material, dict):
                continue
            row = int(material.get("index", 0)) - 1
            if row < 0 or row >= self.table.rowCount():
                continue
            if "name" in material:
                self.table.setItem(row, 0, QTableWidgetItem(str(material["name"])))
            if "material" in material:
                self.table.setItem(row, 1, QTableWidgetItem(str(material["material"])))
            if "elastic_modulus_GPa" in material:
                self.table.setItem(row, 2, QTableWidgetItem(str(material["elastic_modulus_GPa"])))
            if "poisson_ratio" in material:
                self.table.setItem(row, 3, QTableWidgetItem(str(material["poisson_ratio"])))
            if "density_kg_m3" in material:
                self.table.setItem(row, 4, QTableWidgetItem(str(material["density_kg_m3"])))
            updated += 1

        for key, value in gui_values["study_scope"].items():
            if key in self.study_checks:
                self.study_checks[key].setChecked(bool(value))
                updated += 1

        self.parse_geometry()
        self.trigger_rebuild()
        lines = [
            "Backend JSON Imported",
            f"job_id: {payload.get('metadata', {}).get('job_id', '-')}",
            f"core_outer_radius_mm: {self.derived_geom.get('core_outer_radius_mm', '-')}",
            f"bedding_thickness_mm: {self.derived_geom.get('bedding_thickness_mm', '-')}",
            f"inner_armour_wire_count: {self.derived_geom.get('inner_armour_wire_count', '-')} ({self.derived_geom.get('inner_armour_wire_count_source', '-')})",
            f"outer_armour_wire_count: {self.derived_geom.get('outer_armour_wire_count', '-')} ({self.derived_geom.get('outer_armour_wire_count_source', '-')})",
            f"pressure_mpa: {self.cond['pressure'].text()}",
            f"armour_model: {self.mesh_value('armour_model')}",
        ]
        self.last_summary_data = {}
        self.summary_text.setPlainText("\n".join(lines))
        return updated

    def load_backend_json_dialog(self) -> None:
        default_dir = Path("C:/HELIX/Abaqus+_work/for_test")
        start_dir = str(default_dir if default_dir.exists() else PROJECT_DIR)
        path, _ = QFileDialog.getOpenFileName(self, "Open backend input_data.json", start_dir, "JSON Files (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            updated = self.apply_backend_payload_to_gui(payload)
            self.set_badge(self.lbl_model_status, "Model: loaded", "good")
            self.log(f"[IMPORT] Backend JSON loaded: {path} | fields={updated}")
            QMessageBox.information(self, "Backend JSON loaded", f"Updated {updated} GUI fields.\n{path}")
        except Exception as exc:
            self.set_badge(self.lbl_model_status, "Model: error", "error")
            QMessageBox.critical(self, "Backend JSON load error", str(exc))

    def load_backend_preset(self) -> None:
        if not hasattr(self, "backend_preset_combo"):
            QMessageBox.information(
                self,
                "Backend preset",
                "Backend preset loading was removed from the Design tab. Use Import key,value CSV or the Analysis backend controls.",
            )
            return
        label = self.backend_preset_combo.currentText()
        preset_path = BACKEND_JSON_PRESETS.get(label)
        if preset_path is None:
            QMessageBox.information(self, "Backend preset", "No backend preset is selected.")
            return
        if not preset_path.exists():
            QMessageBox.warning(self, "Backend preset missing", f"Preset file not found:\n{preset_path}")
            return
        try:
            payload = json.loads(preset_path.read_text(encoding="utf-8-sig"))
            updated = self.apply_backend_payload_to_gui(payload)
            self.set_badge(self.lbl_model_status, "Model: loaded", "good")
            self.log(f"[IMPORT] Backend preset loaded: {label} | {preset_path} | fields={updated}")
            QMessageBox.information(self, "Backend preset loaded", f"Updated {updated} GUI fields.\n{preset_path}")
        except Exception as exc:
            self.set_badge(self.lbl_model_status, "Model: error", "error")
            QMessageBox.critical(self, "Backend preset load error", str(exc))

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
                "Bedding thickness": "bedding_thickness",
                "Bedding Thickness": "bedding_thickness",
                "Thickness of Bedding": "bedding_thickness",
                "Number of Inner Armour": "no_ia",
                "Radius of Inner Armour": "r_ia",
                "Number of Outer Armour": "no_oa",
                "Radius of Outer Armour": "r_oa",
                "Thickness of Outer Sheath": "tos",
                "Length": "eff_length",
                "Helix Angle of Core": "core_lay_angle",
                "Core Lay Angle": "core_lay_angle",
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
            self.add_compare_curve(Path(path))
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

    def add_compare_curve(self, csv_path: Path, label: str = "") -> dict:
        k, m = read_result_csv(csv_path)
        name = label or csv_path.parent.name or "COMPARE_CSV"
        metrics = make_metrics(k, m, source=name)
        color_cycle = ["#e08f3e", "#10b981", "#d946ef", "#f43f5e"]
        color = color_cycle[len(self.compare_items) % len(color_cycle)]
        item = self.plot_canvas.plot(
            k,
            m,
            pen=pg.mkPen(color=color, width=2.2, style=Qt.DashLine),
            name=name,
        )
        self.compare_items.append(item)
        self.compare_metrics.append(metrics)
        self.plot_canvas.autoRange()
        self.log(f"[RESULT] Comparison curve added: {csv_path}")
        self.update_compare_panel()
        return metrics

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
        quality = data.get("abaqus_result_quality", {})
        odb = data.get("odb_extraction", {})
        endpoint_validation = data.get("endpoint_sweep_validation", {})
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

        if isinstance(quality, dict) and quality:
            if self.ui_language == "KO":
                lines.extend([
                    "",
                    "Abaqus 결과 품질:",
                    f"- 곡선 등급: {quality.get('curve_class', '-')}",
                    f"- 연구용 곡선: {quality.get('is_research_curve', '-')}",
                    f"- 다음 단계: {quality.get('next_step', '-')}",
                ])
            else:
                lines.extend([
                    "",
                    "Abaqus result quality:",
                    f"- curve class: {quality.get('curve_class', '-')}",
                    f"- research curve: {quality.get('is_research_curve', '-')}",
                    f"- next step: {quality.get('next_step', '-')}",
                ])
        if isinstance(odb, dict) and odb:
            lines.extend([
                "",
                "ODB extraction:" if self.ui_language == "EN" else "ODB 추출:",
                f"- status: {odb.get('status', '-')}",
                f"- rows: {odb.get('rows_written', '-')}",
                f"- method: {odb.get('method', '-')}",
            ])
        if isinstance(endpoint_validation, dict) and endpoint_validation:
            lines.extend([
                "",
                "CurveV0 endpoint sweep:" if self.ui_language == "EN" else "CurveV0 엔드포인트 스윕:",
                f"- validated: {endpoint_validation.get('all_child_jobs_validated', '-')}",
                f"- rule: {endpoint_validation.get('aggregation_rule', '-')}",
            ])

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

        cal_status = data.get("calibration_status")
        if cal_status:
            if self.ui_language == "KO":
                lines.extend([
                    "",
                    "캘리브레이션 비교 보고서:",
                    f"- 상태: {cal_status}",
                    f"- 탄성 강성: {float(data.get('calibration_elastic_stiffness', 0.0)):.6g} kN.m^2",
                    f"- 슬립 강성: {float(data.get('calibration_slip_stiffness', 0.0)):.6g} kN.m^2",
                    f"- 이력 에너지 손실: {float(data.get('calibration_hysteresis_loss', 0.0)):.6g} kN",
                    f"- 고착-미끄러짐 전이 곡률: {float(data.get('calibration_transition_curvature', 0.0)):.6g} 1/m",
                ])
            else:
                lines.extend([
                    "",
                    "Calibration Report:",
                    f"- status: {cal_status}",
                    f"- elastic stiffness: {float(data.get('calibration_elastic_stiffness', 0.0)):.6g} kN.m^2",
                    f"- slip stiffness: {float(data.get('calibration_slip_stiffness', 0.0)):.6g} kN.m^2",
                    f"- hysteresis loss: {float(data.get('calibration_hysteresis_loss', 0.0)):.6g} kN",
                    f"- transition curvature: {float(data.get('calibration_transition_curvature', 0.0)):.6g} 1/m",
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
                self.add_solid(dg["outer_sheath_outer_radius_mm"], 0, 0, 0.0, [0.42, 0.49, 0.53, 0.92])
            if self.layer_visible("outer_armour"):
                for i in range(dg["outer_armour_wire_count"]):
                    a = 2 * np.pi * i / dg["outer_armour_wire_count"]
                    self.add_solid(
                        dg["outer_armour_wire_radius_mm"],
                        dg["outer_armour_center_radius_mm"] * np.cos(a),
                        dg["outer_armour_center_radius_mm"] * np.sin(a),
                        0.1,
                        [0.83, 0.57, 0.21, 1.0],
                    )
            if self.layer_visible("bedding"):
                self.add_solid(dg["bedding_outer_radius_mm"], 0, 0, 0.2, [0.15, 0.20, 0.23, 0.78])
            if self.layer_visible("inner_armour"):
                for i in range(dg["inner_armour_wire_count"]):
                    a = 2 * np.pi * i / dg["inner_armour_wire_count"]
                    self.add_solid(
                        dg["inner_armour_wire_radius_mm"],
                        dg["inner_armour_center_radius_mm"] * np.cos(a),
                        dg["inner_armour_center_radius_mm"] * np.sin(a),
                        0.3,
                        [0.83, 0.57, 0.21, 1.0],
                    )
            if self.layer_visible("inner_sheath"):
                self.add_solid(dg["inner_sheath_outer_radius_mm"], 0, 0, 0.4, [0.46, 0.53, 0.56, 0.88])
                self.add_solid(dg["inner_sheath_inner_radius_mm"], 0, 0, 0.5, [0.52, 0.58, 0.60, 0.72])
            if self.layer_visible("filler"):
                self.add_solid(dg["filler_outer_radius_mm"], 0, 0, 0.55, [0.37, 0.59, 0.64, 0.72])
            if self.layer_visible("cores"):
                for i in range(3):
                    a = np.radians(120 * i)
                    cx = dg["core_center_radius_mm"] * np.cos(a)
                    cy = dg["core_center_radius_mm"] * np.sin(a)
                    self.add_solid(dg["core_outer_radius_mm"], cx, cy, 0.6, [0.53, 0.58, 0.60, 1.0])
                    self.add_solid(dg["insulation_radius_mm"], cx, cy, 0.7, [0.87, 0.80, 0.46, 0.95])
                    self.add_solid(dg["conductor_radius_mm"], cx, cy, 0.8, [0.11, 0.20, 0.44, 1.0])
        except Exception as exc:
            self.log(f"[GEOMETRY] {exc}")

    def add_solid(self, r, cx, cy, z, color) -> None:
        item = self.create_solid_mesh(r, cx, cy, z, color)
        self.view_solid.addItem(item)
        self.mesh_cache_solid.append(item)

    def estimate_mesh_elements(self, dg: dict) -> int:
        z_elem = int(self.mesh_inputs["z_elem"].value())
        filler_z_elem = int(self.mesh_inputs["filler_z_elem"].value())
        core_div = int(self.mesh_inputs["c_elem_core"].value())
        armour_div = int(self.mesh_inputs["c_elem_armour"].value())
        core_solids = 3 * z_elem * core_div * 2
        filler_solids = 4 * filler_z_elem * core_div
        sheath_solids = z_elem * core_div * 3
        armour_beams = z_elem * armour_div * (
            int(dg["inner_armour_wire_count"]) + int(dg["outer_armour_wire_count"])
        )
        return int(core_solids + filler_solids + sheath_solids + armour_beams)

    def update_mesh_readiness(self, dg: dict) -> None:
        if not hasattr(self, "lbl_mesh_ready"):
            return
        estimated = self.estimate_mesh_elements(dg)
        self.set_translated_metric_value(self.lbl_mesh_ready, "Preview ready")
        self.lbl_mesh_elements.value_label.setText(f"{estimated:,}")
        self.lbl_mesh_contacts.value_label.setText("5")

    def activate_mesh_key(self, key: str) -> None:
        self.active_mesh_key = key
        self.update_mesh_guide()

    def update_mesh_guide(self) -> None:
        if not hasattr(self, "mesh_guide_label"):
            return
        target_width = self.mesh_guide_label.contentsRect().width()
        pixmap = self.build_mesh_condition_guide_pixmap(width=target_width)
        self.mesh_guide_label.setPixmap(pixmap)

    def build_mesh_condition_guide_pixmap(self, width: Optional[int] = None) -> QPixmap:
        width = int(width or 980)
        width = max(620, min(width, 1200))
        height = 520
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor("#f8fafc"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setPen(QPen(QColor("#d8e0ea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 12, 12)

        title_font = QFont("Segoe UI", 13)
        title_font.setBold(True)
        body_font = QFont("Segoe UI", 9)
        small_font = QFont("Segoe UI", 8)
        pressure_value = self.cond["pressure"].text() if hasattr(self, "cond") else "40.00"
        curvature_value = self.cond["curvature"].text() if hasattr(self, "cond") else "0.08"
        friction_value = self.cond["friction"].text() if hasattr(self, "cond") else "0.22"

        painter.setFont(title_font)
        painter.setPen(QColor("#17202a"))
        painter.drawText(22, 30, "Analysis Structure / Mesh / Contact Guide")
        painter.setFont(body_font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(22, 52, "Set load, curvature, friction, and n_\u03b8/n_r/n_z divisions before exporting the Abaqus request.")

        margin = 22
        gap = 14
        panel_w = (width - margin * 2 - gap * 2) // 3
        panel_h = 420
        top = 74
        panels = [
            (margin, top, "Mesh setting"),
            (margin + panel_w + gap, top, "Load condition"),
            (margin + 2 * (panel_w + gap), top, "Contact condition"),
        ]

        for x, y, heading in panels:
            painter.setPen(QPen(QColor("#dbe4ef"), 1))
            painter.setBrush(QColor("#fbfdff"))
            painter.drawRoundedRect(x, y, panel_w, panel_h, 10, 10)
            painter.setFont(title_font)
            painter.setPen(QColor("#17202a"))
            painter.drawText(x + 14, y + 28, heading)
            painter.setFont(body_font)

        # Mesh setting panel: n_z, n_theta, and n_r directions.
        x, y, _ = panels[0]
        cx = x + panel_w // 2
        cy = y + 155
        painter.setPen(QPen(QColor("#93c5fd"), 2))
        painter.setBrush(QColor("#e0f2fe"))
        painter.drawRoundedRect(x + 28, y + 52, panel_w - 56, 58, 24, 24)
        for i in range(10):
            xx = x + 48 + i * max(1, (panel_w - 96) // 9)
            painter.drawLine(xx, y + 58, xx, y + 104)
        painter.setPen(QColor("#0f3f7a"))
        painter.drawText(x + 34, y + 128, "n_z divisions: length-wise seed control")

        painter.setPen(QPen(QColor("#334155"), 2))
        painter.setBrush(QColor("#ecfeff"))
        painter.drawEllipse(cx - 70, cy + 10, 140, 140)
        painter.setBrush(QColor("#dbeafe"))
        painter.drawEllipse(cx - 48, cy + 32, 96, 96)
        painter.setBrush(QColor("#fef3c7"))
        painter.drawEllipse(cx - 24, cy + 56, 48, 48)
        painter.setPen(QPen(QColor("#f97316"), 1.5))
        for i in range(18):
            a = 2.0 * math.pi * i / 18
            painter.drawLine(
                int(cx),
                int(cy + 80),
                int(cx + 70 * math.cos(a)),
                int(cy + 80 + 70 * math.sin(a)),
            )
        painter.setPen(QPen(QColor("#ef4444"), 2.5))
        painter.drawArc(cx - 82, cy - 2, 164, 164, 20 * 16, 105 * 16)
        painter.setPen(QColor("#991b1b"))
        painter.drawText(x + 34, y + 330, "n_\u03b8 divisions: circumferential density")
        painter.setPen(QPen(QColor("#2563eb"), 2.5))
        painter.drawLine(cx, cy + 80, cx + 58, cy + 80)
        painter.setPen(QColor("#1d4ed8"))
        painter.drawText(x + 34, y + 354, "n_r divisions: layer-thickness density")

        # Load condition panel: pressure, curvature, endpoint actions.
        x, y, _ = panels[1]
        tube_x = x + 40
        tube_y = y + 120
        tube_w = panel_w - 80
        tube_h = 120
        painter.setPen(QPen(QColor("#9a6a2f"), 2))
        painter.setBrush(QColor("#d4a15f"))
        painter.drawRoundedRect(tube_x, tube_y, tube_w, tube_h, 36, 36)
        painter.setBrush(QColor("#f5d9a8"))
        painter.drawEllipse(tube_x - 22, tube_y, 44, tube_h)
        painter.setPen(QPen(QColor("#374151"), 1.6))
        for i in range(5):
            px = tube_x + 45 + i * max(1, (tube_w - 90) // 4)
            painter.drawLine(px, tube_y - 34, px, tube_y - 7)
            painter.drawLine(px, tube_y - 7, px - 5, tube_y - 16)
            painter.drawLine(px, tube_y - 7, px + 5, tube_y - 16)
        painter.drawText(tube_x + 8, tube_y - 44, "external pressure P")
        painter.drawText(tube_x + 8, tube_y + tube_h + 24, f"P = {pressure_value} MPa")
        painter.setPen(QPen(QColor("#ef4444"), 2.4))
        painter.drawArc(tube_x - 24, tube_y + 12, 62, 62, 40 * 16, 240 * 16)
        painter.drawArc(tube_x + tube_w - 38, tube_y + 42, 62, 62, 220 * 16, 240 * 16)
        painter.setPen(QColor("#991b1b"))
        painter.drawText(x + 34, y + 286, "curvature \u03ba and endpoint rotation")
        painter.drawText(x + 34, y + 310, f"\u03ba = {curvature_value} 1/m")
        painter.setPen(QColor("#475569"))
        painter.drawText(x + 34, y + 338, "These fields are part of the backend")
        painter.drawText(x + 34, y + 362, "analysis_conditions contract.")

        # Contact condition panel: interface definitions.
        x, y, _ = panels[2]
        base_x = x + 44
        base_y = y + 88
        painter.setPen(QPen(QColor("#94a3b8"), 1.4))
        layer_colors = ["#e5e7eb", "#d1d5db", "#fcd34d", "#d1d5db", "#e5e7eb"]
        for i, color in enumerate(layer_colors):
            painter.setBrush(QColor(color))
            painter.drawPie(base_x + i * 14, base_y + i * 18, panel_w - 90 - i * 28, 260 - i * 36, 100 * 16, 94 * 16)
        painter.setPen(QPen(QColor("#ef4444"), 3))
        painter.drawArc(base_x + 16, base_y + 28, panel_w - 122, 204, 103 * 16, 88 * 16)
        painter.drawArc(base_x + 44, base_y + 68, panel_w - 178, 132, 104 * 16, 84 * 16)
        painter.setFont(body_font)
        painter.setPen(QColor("#991b1b"))
        painter.drawText(x + 34, y + 292, "surface-to-surface contact")
        painter.setPen(QColor("#374151"))
        painter.drawText(x + 34, y + 318, "armour wire to bedding / sheath")
        painter.drawText(x + 34, y + 342, f"friction coefficient \u03bc = {friction_value}")

        painter.setFont(small_font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(22, height - 20, "Guide only. Import a generated Abaqus INP to inspect the actual backend mesh.")
        painter.end()
        return pixmap

    def build_mesh_guide_pixmap(self, width: Optional[int] = None) -> QPixmap:
        width = int(width or 820)
        width = max(420, min(width, 1100))
        height = 260
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor("#f8fafc"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        z_div = int(self.mesh_inputs["z_elem"].value()) if hasattr(self, "mesh_inputs") else 40
        filler_z_div = int(self.mesh_inputs["filler_z_elem"].value()) if hasattr(self, "mesh_inputs") else z_div
        core_div = int(self.mesh_inputs["c_elem_core"].value()) if hasattr(self, "mesh_inputs") else 24
        armour_div = int(self.mesh_inputs["c_elem_armour"].value()) if hasattr(self, "mesh_inputs") else 8
        r_inner = int(self.mesh_inputs["r_elem_inner_sheath"].value()) if hasattr(self, "mesh_inputs") else 3
        r_bedding = int(self.mesh_inputs["r_elem_bedding"].value()) if hasattr(self, "mesh_inputs") else 1
        r_outer = int(self.mesh_inputs["r_elem_outer_sheath"].value()) if hasattr(self, "mesh_inputs") else 3
        active_key = getattr(self, "active_mesh_key", "")
        active_z = active_key in {"z_elem", "filler_z_elem"}
        active_core_theta = active_key == "c_elem_core"
        active_armour_theta = active_key == "c_elem_armour"
        active_filler = active_key == "filler_z_elem"
        active_r_key = {
            "r_elem_inner_sheath": "inner",
            "r_elem_bedding": "bedding",
            "r_elem_outer_sheath": "outer",
        }.get(active_key, "")
        try:
            dg = self.parse_geometry()
        except Exception:
            dg = dict(getattr(self, "derived_geom", {}))

        painter.setPen(QColor("#d8e0ea"))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 12, 12)

        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#17202a"))
        painter.drawText(22, 30, "Mesh sizing guide")

        label_font = QFont("Segoe UI", 9)
        painter.setFont(label_font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(22, 50, "Draft guide for axial, circumferential, and radial division settings")

        # Axial guide: side-view cable with division lines from the length setting.
        x0, y0, side_w, side_h = 30, 102, min(300, width // 2 - 92), 54
        painter.setPen(QColor("#94a3b8"))
        painter.setBrush(QColor("#eaf2ff"))
        painter.drawRoundedRect(x0, y0, side_w, side_h, 26, 26)
        painter.setBrush(QColor("#dbeafe"))
        painter.drawEllipse(x0 - 18, y0, 36, side_h)
        painter.drawEllipse(x0 + side_w - 18, y0, 36, side_h)
        displayed_z_div = filler_z_div if active_filler else z_div
        line_count = min(displayed_z_div, 32)
        painter.setPen(QPen(QColor("#1d4ed8" if active_z else "#2f80ed"), 2.4 if active_z else 1.0))
        for i in range(1, line_count):
            x = x0 + int(side_w * i / line_count)
            painter.drawLine(x, y0 + 6, x, y0 + side_h - 6)
        painter.setPen(QColor("#0f3f7a"))
        z_label = "filler z direction" if active_filler else "z direction"
        painter.drawText(x0 + 6, y0 - 12, f"{z_label}: {displayed_z_div} divisions")
        painter.drawText(x0 + 8, y0 + side_h + 24, "smaller length size = more axial divisions")

        # Geometry-based section guide. This is generated from GUI values only,
        # not from an Abaqus .inp file.
        if dg:
            cx = int(width * 0.66)
            cy = 134
            max_r = max(float(dg.get("outer_sheath_outer_radius_mm", 60.0)), 1.0)
            scale = min((width - cx - 54) / max_r, 102.0 / max_r)

            def sx(x: float) -> int:
                return int(round(cx + x * scale))

            def sy(y: float) -> int:
                return int(round(cy - y * scale))

            def draw_circle(radius_mm: float, color: str, pen_width: float = 1.0) -> None:
                rr = int(round(radius_mm * scale))
                painter.setPen(QPen(QColor(color), pen_width))
                painter.drawEllipse(cx - rr, cy - rr, rr * 2, rr * 2)

            def draw_ring_mesh(
                inner_r: float,
                outer_r: float,
                radial_count: int,
                theta_count: int,
                color: str,
                radial_highlight: bool = False,
                theta_highlight: bool = False,
            ) -> None:
                radial_count = max(1, radial_count)
                theta_count = max(6, min(theta_count, 72))
                for j in range(radial_count + 1):
                    draw_circle(
                        inner_r + (outer_r - inner_r) * j / radial_count,
                        color,
                        2.5 if radial_highlight else 1.0,
                    )
                painter.setPen(QPen(QColor(color), 2.2 if theta_highlight else 1.0))
                for i in range(theta_count):
                    angle = 2.0 * math.pi * i / theta_count
                    painter.drawLine(
                        sx(inner_r * math.cos(angle)),
                        sy(inner_r * math.sin(angle)),
                        sx(outer_r * math.cos(angle)),
                        sy(outer_r * math.sin(angle)),
                    )

            def draw_wire_ring(center_r: float, wire_r: float, count: int, color: str, theta_highlight: bool = False) -> None:
                count = max(1, min(count, 96))
                spoke_count = max(4, min(armour_div, 16))
                painter.setPen(QPen(QColor(color), 2.0 if theta_highlight else 1.0))
                for i in range(count):
                    angle = 2.0 * math.pi * i / count
                    wx = center_r * math.cos(angle)
                    wy = center_r * math.sin(angle)
                    wr = int(round(wire_r * scale))
                    painter.drawEllipse(sx(wx) - wr, sy(wy) - wr, wr * 2, wr * 2)
                    for j in range(spoke_count):
                        theta = 2.0 * math.pi * j / spoke_count
                        painter.drawLine(
                            sx(wx),
                            sy(wy),
                            sx(wx + wire_r * math.cos(theta)),
                            sy(wy + wire_r * math.sin(theta)),
                        )

            draw_ring_mesh(
                float(dg["outer_sheath_inner_radius_mm"]),
                float(dg["outer_sheath_outer_radius_mm"]),
                r_outer,
                core_div,
                "#2f80ed",
                radial_highlight=active_r_key == "outer",
                theta_highlight=active_core_theta,
            )
            draw_wire_ring(
                float(dg["outer_armour_center_radius_mm"]),
                float(dg["outer_armour_wire_radius_mm"]),
                int(dg["outer_armour_wire_count"]),
                "#f06292",
                theta_highlight=active_armour_theta,
            )
            draw_ring_mesh(
                float(dg["inner_armour_outer_radius_mm"]),
                float(dg["bedding_outer_radius_mm"]),
                r_bedding,
                core_div,
                "#89bf68",
                radial_highlight=active_r_key == "bedding",
                theta_highlight=active_core_theta,
            )
            draw_wire_ring(
                float(dg["inner_armour_center_radius_mm"]),
                float(dg["inner_armour_wire_radius_mm"]),
                int(dg["inner_armour_wire_count"]),
                "#c084fc",
                theta_highlight=active_armour_theta,
            )
            draw_ring_mesh(
                float(dg["inner_sheath_inner_radius_mm"]),
                float(dg["inner_sheath_outer_radius_mm"]),
                r_inner,
                core_div,
                "#5fd4d4",
                radial_highlight=active_r_key == "inner",
                theta_highlight=active_core_theta,
            )
            draw_circle(float(dg["filler_outer_radius_mm"]), "#fbbf24", 2.6 if active_filler else 1.2)

            core_theta = max(8, min(core_div, 48))
            for i in range(3):
                angle = 2.0 * math.pi * i / 3.0 - math.pi / 2.0
                core_x = float(dg["core_center_radius_mm"]) * math.cos(angle)
                core_y = float(dg["core_center_radius_mm"]) * math.sin(angle)
                painter.setPen(QPen(QColor("#ff8a2a"), 2.0 if active_core_theta else 1.0))
                for radius_key in ["core_outer_radius_mm", "insulation_radius_mm", "conductor_radius_mm"]:
                    rr = int(round(float(dg[radius_key]) * scale))
                    painter.drawEllipse(sx(core_x) - rr, sy(core_y) - rr, rr * 2, rr * 2)
                for j in range(core_theta):
                    theta = 2.0 * math.pi * j / core_theta
                    painter.drawLine(
                        sx(core_x),
                        sy(core_y),
                        sx(core_x + float(dg["core_outer_radius_mm"]) * math.cos(theta)),
                        sy(core_y + float(dg["core_outer_radius_mm"]) * math.sin(theta)),
                    )

            painter.setPen(QColor("#17202a"))
            painter.drawText(cx - 132, 34, "GUI-value mesh request preview")
            painter.setPen(QColor("#475569"))
            painter.drawText(cx - 132, height - 28, f"core C={core_div} | armour C={armour_div} | R={r_inner}/{r_bedding}/{r_outer}")

        painter.end()
        return pixmap

    def generate_mesh_preview(self) -> None:
        for item in self.mesh_cache_wire:
            try:
                self.view_wire.removeItem(item)
            except Exception:
                pass
        self.mesh_cache_wire.clear()
        try:
            dg = self.parse_geometry()
            def add_segments(segments, edge_color, width=1.1):
                if not segments:
                    return
                points = []
                for start, end in segments:
                    points.append([start[0], start[1], 0.0])
                    points.append([end[0], end[1], 0.0])
                item = gl.GLLinePlotItem(
                    pos=np.array(points, dtype=float),
                    color=edge_color,
                    width=width,
                    mode="lines",
                    antialias=True,
                )
                self.view_wire.addItem(item)
                self.mesh_cache_wire.append(item)

            def circle_segments(cx, cy, radius, divisions):
                divisions = max(8, min(int(divisions), 96))
                points = []
                for i in range(divisions):
                    a0 = 2.0 * np.pi * i / divisions
                    a1 = 2.0 * np.pi * (i + 1) / divisions
                    points.append((
                        (cx + radius * np.cos(a0), cy + radius * np.sin(a0)),
                        (cx + radius * np.cos(a1), cy + radius * np.sin(a1)),
                    ))
                return points

            def add_ring_mesh(inner_radius, outer_radius, radial_divisions, theta_divisions, edge_color):
                theta_divisions = max(8, min(int(theta_divisions), 96))
                radial_divisions = max(1, int(radial_divisions))
                segments = []
                for j in range(radial_divisions + 1):
                    radius = inner_radius + (outer_radius - inner_radius) * j / radial_divisions
                    segments.extend(circle_segments(0.0, 0.0, radius, theta_divisions))
                for i in range(theta_divisions):
                    angle = 2.0 * np.pi * i / theta_divisions
                    segments.append((
                        (inner_radius * np.cos(angle), inner_radius * np.sin(angle)),
                        (outer_radius * np.cos(angle), outer_radius * np.sin(angle)),
                    ))
                add_segments(segments, edge_color)

            def add_wire_mesh(center_radius, wire_radius, count, circumferential_divisions, edge_color):
                count = max(1, min(int(count), 128))
                circumferential_divisions = max(6, min(int(circumferential_divisions), 32))
                segments = []
                for i in range(count):
                    angle = 2.0 * np.pi * i / count
                    cx = center_radius * np.cos(angle)
                    cy = center_radius * np.sin(angle)
                    segments.extend(circle_segments(cx, cy, wire_radius, circumferential_divisions))
                    for j in range(circumferential_divisions):
                        theta = 2.0 * np.pi * j / circumferential_divisions
                        segments.append((
                            (cx, cy),
                            (cx + wire_radius * np.cos(theta), cy + wire_radius * np.sin(theta)),
                        ))
                add_segments(segments, edge_color)

            def add_core_mesh(cx, cy, outer_radius, insulation_radius, conductor_radius, divisions, edge_color):
                divisions = max(8, min(int(divisions), 64))
                segments = []
                for radius in [outer_radius, insulation_radius, conductor_radius]:
                    segments.extend(circle_segments(cx, cy, radius, divisions))
                for j in range(divisions):
                    theta = 2.0 * np.pi * j / divisions
                    segments.append((
                        (cx, cy),
                        (cx + outer_radius * np.cos(theta), cy + outer_radius * np.sin(theta)),
                    ))
                add_segments(segments, edge_color)

            z_rows = self.mesh_inputs["z_elem"].value()
            filler_z_rows = self.mesh_inputs["filler_z_elem"].value()
            core_cols = self.mesh_inputs["c_elem_core"].value()
            armour_cols = self.mesh_inputs["c_elem_armour"].value()
            add_ring_mesh(
                dg["outer_sheath_inner_radius_mm"],
                dg["outer_sheath_outer_radius_mm"],
                self.mesh_inputs["r_elem_outer_sheath"].value(),
                core_cols,
                (0.18, 0.50, 0.93, 0.72),
            )
            add_wire_mesh(
                dg["outer_armour_center_radius_mm"],
                dg["outer_armour_wire_radius_mm"],
                dg["outer_armour_wire_count"],
                armour_cols,
                (0.94, 0.34, 0.52, 0.86),
            )
            add_ring_mesh(
                dg["inner_armour_outer_radius_mm"],
                dg["bedding_outer_radius_mm"],
                self.mesh_inputs["r_elem_bedding"].value(),
                core_cols,
                (0.50, 0.75, 0.36, 0.68),
            )
            add_wire_mesh(
                dg["inner_armour_center_radius_mm"],
                dg["inner_armour_wire_radius_mm"],
                dg["inner_armour_wire_count"],
                armour_cols,
                (0.72, 0.48, 0.92, 0.86),
            )
            add_ring_mesh(
                dg["inner_sheath_inner_radius_mm"],
                dg["inner_sheath_outer_radius_mm"],
                self.mesh_inputs["r_elem_inner_sheath"].value(),
                core_cols,
                (0.34, 0.82, 0.82, 0.72),
            )
            add_segments(circle_segments(0.0, 0.0, dg["filler_outer_radius_mm"], core_cols), (0.96, 0.75, 0.16, 0.62))
            for i in range(3):
                a = 2 * np.pi * i / 3.0 - np.pi / 2.0
                core_x = dg["core_center_radius_mm"] * np.cos(a)
                core_y = dg["core_center_radius_mm"] * np.sin(a)
                add_core_mesh(
                    core_x,
                    core_y,
                    dg["core_outer_radius_mm"],
                    dg["insulation_radius_mm"],
                    dg["conductor_radius_mm"],
                    core_cols,
                    (1.0, 0.52, 0.16, 0.82),
                )
            span = max(float(dg["outer_sheath_outer_radius_mm"]) * 2.25, 1.0)
            self.view_wire.setCameraPosition(distance=span, elevation=90, azimuth=0)
            self.update_mesh_readiness(dg)
            self.update_mesh_guide()
            if hasattr(self, "inp_mesh_summary"):
                self.inp_mesh_summary.setPlainText(
                    "Generated from GUI values only.\n"
                    f"Axial divisions: {z_rows}\n"
                    f"Filler n_z divisions: {filler_z_rows}\n"
                    f"Core/Sheath n_theta divisions: {core_cols}\n"
                    f"Armour wire n_theta divisions: {armour_cols}"
                )
            if hasattr(self, "inp_mesh_legend"):
                self.inp_mesh_legend.setVisible(False)
        except Exception as exc:
            QMessageBox.critical(self, "Mesh preview error", str(exc))

    def import_inp_mesh_dialog(self) -> None:
        start_dir = str(Path("C:/Users/user/Desktop") if Path("C:/Users/user/Desktop").exists() else PROJECT_DIR)
        path, _ = QFileDialog.getOpenFileName(self, "Open Abaqus input deck", start_dir, "Abaqus INP Files (*.inp);;All Files (*)")
        if not path:
            return
        try:
            self.render_inp_mesh_preview(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "INP mesh preview error", str(exc))

    def render_inp_mesh_preview(self, path: Path) -> None:
        for item in self.mesh_cache_wire:
            try:
                self.view_wire.removeItem(item)
            except Exception:
                pass
        self.mesh_cache_wire.clear()

        preview = build_inp_mesh_preview(path)
        min_x, min_y, max_x, max_y = preview.bounds_xy
        center_x = 0.5 * (min_x + max_x)
        center_y = 0.5 * (min_y + max_y)
        span = max(max_x - min_x, max_y - min_y, 1.0)

        for part, segments in preview.segments_by_part.items():
            if not segments:
                continue
            color = PART_COLORS.get(part, (0.72, 0.78, 0.88, 0.75))
            points = []
            for start, end in segments:
                points.append([start[0] - center_x, start[1] - center_y, 0.0])
                points.append([end[0] - center_x, end[1] - center_y, 0.0])
            item = gl.GLLinePlotItem(
                pos=np.array(points, dtype=float),
                color=color,
                width=1.4,
                mode="lines",
                antialias=True,
            )
            self.view_wire.addItem(item)
            self.mesh_cache_wire.append(item)

        self.view_wire.setVisible(True)
        self.view_wire.setCameraPosition(distance=span * 1.35, elevation=90, azimuth=0)
        if hasattr(self, "lbl_mesh_ready"):
            self.set_translated_metric_value(self.lbl_mesh_ready, "INP imported")
            self.lbl_mesh_elements.value_label.setText(
                f"{sum(part['elements'] for part in preview.part_summaries):,}"
            )
            self.lbl_mesh_contacts.value_label.setText(str(len(preview.part_summaries)))
        if hasattr(self, "inp_mesh_summary"):
            self.inp_mesh_summary.setPlainText(format_inp_mesh_summary(preview))
        if hasattr(self, "inp_mesh_legend"):
            self.inp_mesh_legend.setText(self.format_inp_mesh_legend(preview))
            self.inp_mesh_legend.setVisible(True)
        self.log(f"[INP] Mesh preview imported: {path}")

    def format_inp_mesh_legend(self, preview) -> str:
        items = []
        for part in sorted(preview.segments_by_part):
            color = PART_COLORS.get(part, (0.72, 0.78, 0.88, 0.75))
            r, g, b = [max(0, min(255, int(round(channel * 255)))) for channel in color[:3]]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            items.append(
                "<span style='white-space:nowrap; margin-right:12px;'>"
                f"<span style='background-color:{hex_color}; color:{hex_color};'>___</span> "
                f"{part}</span>"
            )
        if not items:
            return "No part-colored mesh segments found."
        return "Part colors: " + " ".join(items)

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
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
            }
            QWidget {
                color: #18212d;
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                font-size: 13px;
            }
            QLabel {
                color: #243244;
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                font-size: 13px;
            }
            QLabel#MeshLegend {
                color: #d7dde8;
                background-color: #252a32;
                border: 1px solid #3a4351;
                border-radius: 8px;
                padding: 8px 10px;
                font-size: 12px;
            }
            QLabel#MeshGuide {
                background-color: #f8fafc;
                border: 1px solid #d8e0ea;
                border-radius: 10px;
            }
            QPushButton, QLineEdit, QSpinBox, QComboBox, QCheckBox, QRadioButton,
            QGroupBox, QTableWidget, QHeaderView::section {
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                letter-spacing: 0px;
            }
            QTabWidget::pane {
                border: none;
                background-color: transparent;
            }
            QTabBar::tab {
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                font-size: 13px;
                font-weight: 650;
                color: #334155;
                background-color: #ffffff;
                border: 1px solid #d7dee8;
                border-radius: 7px;
                padding: 8px 13px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                color: #0f3a72;
                background-color: #dfeafb;
                border-color: #b9cdea;
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
                background-color: #ffffff;
                color: #18212d;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                padding: 9px 12px;
                text-align: left;
                font-size: 13px;
                font-weight: 750;
            }
            QPushButton#SectionToggle:hover {
                background-color: #f5f8fc;
                border-color: #9fb0c4;
                color: #0f3a72;
            }
            QSplitter#PanelSplitter {
                background-color: transparent;
            }
            QSplitter#PanelSplitter::handle {
                background-color: #dbe3ee;
                border: 1px solid #cfdae7;
                border-radius: 4px;
                margin: 38px 1px;
            }
            QSplitter#PanelSplitter::handle:hover {
                background-color: #9fb0c4;
                border-color: #8aa0ba;
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
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                font-size: 13px;
                font-weight: 750;
                color: #111827;
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
                font-size: 13px;
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
                font-size: 13px;
            }
            QTextEdit {
                background-color: #0f172a;
                color: #dbeafe;
                font-family: Consolas, "Cascadia Mono", "Noto Sans KR", monospace;
                border: 1px solid #233148;
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
            }
            QTextEdit#SummaryText {
                background-color: #fbfcfe;
                color: #253247;
                font-family: "Noto Sans KR", "Malgun Gothic", "Segoe UI", Arial;
                border: 1px solid #d7dee8;
                border-radius: 8px;
                padding: 10px;
                font-size: 12px;
                line-height: 1.35;
            }
            QTextEdit#InputPreviewText {
                background-color: #fbfcfe;
                color: #1f2937;
                font-family: "Cascadia Mono", Consolas, "Noto Sans KR", "Malgun Gothic", monospace;
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
    global SYMBOL_FONT_FAMILY, SYMBOL_FONT_QSS
    app = QApplication(sys.argv)
    SYMBOL_FONT_FAMILY = load_project_symbol_fonts()
    SYMBOL_FONT_QSS = qss_font_stack(
        SYMBOL_FONT_FAMILY,
        "Euclid",
        "Euclid Symbol",
        "Cambria Math",
        "Segoe UI Symbol",
        "Segoe UI Semibold",
        "Segoe UI",
        "Malgun Gothic",
        "Noto Sans",
        "Arial",
    )
    app.setFont(QFont(APP_FONT_FAMILY, 10))
    pg.setConfigOptions(antialias=True)
    splash = show_startup_splash(app)
    window = SCLASRemoteGUI()
    window.show()
    if splash is not None:
        splash.finish(window)
    smoke_ms = os.environ.get("SCLAS_GUI_SMOKE_EXIT_MS", "").strip()
    if smoke_ms:
        QTimer.singleShot(max(int(smoke_ms), 1), app.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
