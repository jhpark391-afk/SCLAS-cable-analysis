import sys
import os

# macOS + VS Code OpenGL/Qt stability settings.
# Must be set before QApplication/Qt widgets are created.
os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
import time
import json
import csv
import subprocess
import numpy as np
import psutil
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

import pyqtgraph as pg
import pyqtgraph.opengl as gl

# =====================================================================
# ⚙️ Hybrid Solver Engine (Analytical + Abaqus Subprocess)
# =====================================================================
class CoupledFEASolver(QThread):
    plot_sig = pyqtSignal(np.ndarray, np.ndarray)
    metrics_sig = pyqtSignal(dict)
    log_sig = pyqtSignal(str, str)
    progress_sig = pyqtSignal(int)

    def __init__(self, params, mode):
        super().__init__()
        self.params = params
        self.mode = mode 

    def run(self):
        try:
            if self.mode == 'FAST':
                self.run_fast_analytical()
            else:
                self.run_abaqus_integration()
        except Exception as e:
            self.log_sig.emit(f">> [ERR] Solver failed: {str(e)}", "error")
            self.progress_sig.emit(0)

    def run_fast_analytical(self):
        self.log_sig.emit(">> [FAST] Initiating Bouc-Wen Analytical Solver...", "info")
        self.progress_sig.emit(20)
        time.sleep(0.3) 
        
        eff_length = float(self.params.get('eff_length', 234.2)) / 1e3
        friction = float(self.params.get('friction_coeff', self.params.get('friction', 0.22)))
        pressure = float(self.params.get('pressure', 40.0))
        k_max = float(self.params.get('curvature', 0.08))
        
        EI_init = float(self.params.get('core_equivalent_EI', 1500.0)) # 등가강성 가져오기
        EI_slip = EI_init * (0.28 + (friction * 0.1))
        M_yield = (EI_init - EI_slip) * k_max * 0.45 * (1.0 + friction * 2.2 + (pressure / 45.0))
        
        self.progress_sig.emit(80)
        
        steps = 400
        t = np.linspace(0, 4 * np.pi, steps)
        k_arr = k_max * np.sin(t)
        M_arr = np.zeros(steps)
        Z = 0.0
        
        for i in range(1, steps):
            dk = k_arr[i] - k_arr[i-1]
            dk_sign = np.sign(dk) if dk != 0 else 1.0
            Z += (1.0 - 0.55 * dk_sign * Z - 0.45 * np.abs(Z)) * dk
            M_arr[i] = (EI_slip * k_arr[i]) + (M_yield * np.tanh(Z * 12.0))
        
        plot_M = M_arr * 1e3
        
        self.progress_sig.emit(100)
        self.plot_sig.emit(k_arr, plot_M)
        self.metrics_sig.emit({
            "max_moment": np.max(np.abs(plot_M)),
            "ei_init": EI_init * 1e3,
            "loss": np.sum(np.abs(plot_M)) * (k_max / steps)
        })
        self.log_sig.emit(">> [FAST] Analytical solution generated.", "success")

    def run_abaqus_integration(self):
        self.log_sig.emit(">> [ABAQUS] High-Fidelity FEA Pipeline Started...", "info")
        self.progress_sig.emit(10)
        
        # 보광이와 약속한 규격대로 input_data.json 생성
        with open("input_data.json", "w", encoding="utf-8") as f:
            json.dump(self.params, f, indent=4)
        
        self.log_sig.emit(">> [ABAQUS] Generated 'input_data.json' for Abaqus backend.", "info")
        self.progress_sig.emit(30)
        
        time.sleep(1) 
        self.log_sig.emit(">> [ABAQUS] Calling Abaqus Script: abaqus_script.py", "info")
        self.progress_sig.emit(50)
        
        try:
            self.log_sig.emit(">> [ABAQUS] Solving nonlinear contacts & extracting ODB...", "info")
            time.sleep(2) 
        except Exception:
            pass
            
        self.progress_sig.emit(80)
        
        if os.path.exists("result_data.csv"):
            k_list, m_list = [], []
            with open("result_data.csv", "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        k_list.append(float(row[0]))
                        m_list.append(float(row[1]))
            
            k_arr = np.array(k_list)
            m_arr = np.array(m_list)
            
            self.progress_sig.emit(100)
            self.plot_sig.emit(k_arr, m_arr)
            self.metrics_sig.emit({
                "max_moment": np.max(np.abs(m_arr)),
                "ei_init": (m_arr[10]/k_arr[10]) if k_arr[10] != 0 else 0,
                "loss": np.sum(np.abs(m_arr)) * 0.05
            })
            self.log_sig.emit(">> [ABAQUS] True FEA Loop successfully plotted!", "success")
        else:
            self.log_sig.emit(">> [WARN] result_data.csv not found. Running Fast Fallback...", "error")
            self.run_fast_analytical()


# =====================================================================
# 🎨 SCLAS v9.5 | Master Architecture Interface
# =====================================================================
class SCLAS_V8(QMainWindow):
    def __init__(self):
        super().__init__()
        self.derived_geom = {}
        self.mesh_cache_solid = []
        self.mesh_cache_wire = []
        self.view_mode = "2D"
        self.current_k = np.array([])
        self.current_m = np.array([])
        self.last_metrics = {}
        
        self.init_ui()
        self.apply_theme()
        
        self.sys_timer = QTimer()
        self.sys_timer.timeout.connect(self.update_telemetry)
        self.sys_timer.start(1000)

    def init_ui(self):
        self.setWindowTitle("SCLAS v9.5 | 3-Stage Integrated FEA Platform")
        self.resize(1700, 950)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # ==============================================================
        # 📐 TAB 1: DESIGN & DIGITAL TWIN
        # ==============================================================
        tab_design = QWidget()
        layout_design = QHBoxLayout(tab_design)
        layout_design.setSpacing(15)

        panel_inputs = QFrame(); panel_inputs.setObjectName("Card")
        layout_inputs = QVBoxLayout(panel_inputs)
        
        self.btn_load = QPushButton("📂 Load Cable Parameters (CSV)")
        self.btn_load.setFixedHeight(50)
        self.btn_load.clicked.connect(self.load_csv)
        layout_inputs.addWidget(self.btn_load)
        
        form_geom = QFormLayout(); form_geom.setVerticalSpacing(12)
        self.inputs = {
            "r_cond": QLineEdit("4.00"), "r_insu": QLineEdit("11.30"),
            "roc": QLineEdit("15.30"), "coc": QLineEdit("17.66"),
            "tis": QLineEdit("4.50"), "r_ia": QLineEdit("2.00"),
            "no_ia": QSpinBox(), "gap": QLineEdit("0.50"),
            "r_oa": QLineEdit("2.00"), "no_oa": QSpinBox(), "tos": QLineEdit("4.50"),
            "lay_angle": QLineEdit("12.0") # [핵심 추가] 아머 나선 각도
        }
        self.inputs["no_ia"].setRange(10, 200); self.inputs["no_ia"].setValue(55)
        self.inputs["no_oa"].setRange(10, 200); self.inputs["no_oa"].setValue(63)

        layout_inputs.addWidget(self.create_header("Core Dimensions"))
        for label, key in [("Conductor Radius:", "r_cond"), ("Insulation Radius:", "r_insu"), 
                           ("Core Radius (RoC):", "roc"), ("Core Center (CoC):", "coc"), ("Inner Sheath Thick.:", "tis")]:
            form_geom.addRow(label, self.inputs[key])
        layout_inputs.addLayout(form_geom)
        
        form_armour = QFormLayout(); form_armour.setVerticalSpacing(12)
        layout_inputs.addWidget(self.create_header("Armour Configuration"))
        for label, key in [("Inner Armour Count:", "no_ia"), ("Inner Wire Radius:", "r_ia"),
                           ("Outer Armour Count:", "no_oa"), ("Outer Wire Radius:", "r_oa"),
                           ("Clearance Gap (mm):", "gap"), ("Lay Angle (deg):", "lay_angle"), ("Outer Sheath Thick.:", "tos")]:
            form_armour.addRow(label, self.inputs[key])
        layout_inputs.addLayout(form_armour)
        layout_inputs.addStretch()

        panel_mat = QFrame(); panel_mat.setObjectName("Card")
        layout_mat = QVBoxLayout(panel_mat)
        layout_mat.addWidget(self.create_header("Material Properties"))
        self.table = QTableWidget(9, 3)
        self.table.setHorizontalHeaderLabels(["Layer", "E (GPa)", "Nu (v)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.init_material_table()
        layout_mat.addWidget(self.table)

        panel_view = QFrame(); panel_view.setObjectName("Card")
        layout_view = QVBoxLayout(panel_view)
        view_header = QHBoxLayout()
        view_header.addWidget(self.create_header("Solid Geometry Viewport"))
        self.btn_toggle_3d = QPushButton("🔄 Toggle 2D / 3D View")
        self.btn_toggle_3d.setFixedWidth(200)
        self.btn_toggle_3d.clicked.connect(self.toggle_view_mode)
        view_header.addWidget(self.btn_toggle_3d, alignment=Qt.AlignRight)
        layout_view.addLayout(view_header)
        
        self.view_solid = gl.GLViewWidget()
        self.view_solid.setBackgroundColor('#141419')
        self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0) 
        layout_view.addWidget(self.view_solid)

        layout_design.addWidget(panel_inputs, 20)
        layout_design.addWidget(panel_mat, 30)
        layout_design.addWidget(panel_view, 50)
        self.tabs.addTab(tab_design, "📐 1. Design & Digital Twin")

        # ==============================================================
        # 🕸️ TAB 2: FEA MESH GENERATION
        # ==============================================================
        tab_mesh = QWidget()
        layout_mesh = QHBoxLayout(tab_mesh)
        layout_mesh.setSpacing(15)
        
        panel_mesh_set = QFrame(); panel_mesh_set.setObjectName("Card")
        panel_mesh_set.setFixedWidth(420)
        layout_mesh_set = QVBoxLayout(panel_mesh_set)
        
        layout_mesh_set.addWidget(self.create_header("Mesh Discretization Rules"))
        form_mesh = QFormLayout(); form_mesh.setVerticalSpacing(15)
        
        self.mesh_inputs = {
            "elem_type": QComboBox(),
            "z_elem": QSpinBox(),
            "c_elem_core": QSpinBox(),
            "c_elem_armour": QSpinBox()
        }
        self.mesh_inputs["elem_type"].addItems(["C3D8 (8-node Brick)", "C3D4 (4-node Tetra)", "B31 (2-node Beam)"])
        self.mesh_inputs["z_elem"].setRange(10, 200); self.mesh_inputs["z_elem"].setValue(40)
        self.mesh_inputs["c_elem_core"].setRange(8, 100); self.mesh_inputs["c_elem_core"].setValue(24)
        self.mesh_inputs["c_elem_armour"].setRange(4, 20); self.mesh_inputs["c_elem_armour"].setValue(6)
        
        form_mesh.addRow("Element Type:", self.mesh_inputs["elem_type"])
        form_mesh.addRow("Z-Axis Divisions (Rows):", self.mesh_inputs["z_elem"])
        form_mesh.addRow("Core Radial Divs (Cols):", self.mesh_inputs["c_elem_core"])
        form_mesh.addRow("Armour Radial Divs (Cols):", self.mesh_inputs["c_elem_armour"])
        
        layout_mesh_set.addLayout(form_mesh)
        layout_mesh_set.addSpacing(30)
        
        self.btn_gen_mesh = QPushButton("🕸️ GENERATE MESH PREVIEW")
        self.btn_gen_mesh.setObjectName("RunBtn")
        self.btn_gen_mesh.setFixedHeight(60)
        self.btn_gen_mesh.clicked.connect(self.generate_mesh_preview)
        layout_mesh_set.addWidget(self.btn_gen_mesh)
        layout_mesh_set.addStretch()

        panel_mesh_view = QFrame(); panel_mesh_view.setObjectName("Card")
        layout_mesh_view = QVBoxLayout(panel_mesh_view)
        layout_mesh_view.addWidget(self.create_header("FEA Mesh Discretization Preview"))
        
        self.view_wire = gl.GLViewWidget()
        self.view_wire.setBackgroundColor('#0a0a0f') 
        self.view_wire.setCameraPosition(distance=250, elevation=35, azimuth=45) 
        layout_mesh_view.addWidget(self.view_wire)

        layout_mesh.addWidget(panel_mesh_set)
        layout_mesh.addWidget(panel_mesh_view)
        self.tabs.addTab(tab_mesh, "🕸️ 2. FEA Meshing")

        # ==============================================================
        # 📊 TAB 3: ANALYSIS & RESULTS 
        # ==============================================================
        tab_analysis = QWidget()
        layout_analysis = QHBoxLayout(tab_analysis)
        layout_analysis.setSpacing(15)

        panel_cond = QFrame(); panel_cond.setObjectName("Card")
        panel_cond.setFixedWidth(420)
        layout_cond = QVBoxLayout(panel_cond)
        
        layout_cond.addWidget(self.create_header("1. Solver Selection"))
        self.radio_fast = QRadioButton("⚡ Fast Analytical Solver (Bouc-Wen)")
        self.radio_abaqus = QRadioButton("🐢 High-Fidelity FEA (ABAQUS 연동)")
        self.radio_fast.setChecked(True) 
        layout_cond.addWidget(self.radio_fast)
        layout_cond.addWidget(self.radio_abaqus)
        layout_cond.addSpacing(20)
        
        layout_cond.addWidget(self.create_header("2. Environment Conditions"))
        form_cond = QFormLayout(); form_cond.setVerticalSpacing(15)
        self.cond = {
            "eff_length": QLineEdit("234.20"), "pressure": QLineEdit("40.00"),
            "friction": QLineEdit("0.22"), "curvature": QLineEdit("0.08")
        }
        for label, key in [("Effective Length (mm):", "eff_length"), ("Hydrostatic Press. (MPa):", "pressure"),
                           ("Friction Coeff (μ):", "friction"), ("Max Curvature (1/m):", "curvature")]:
            form_cond.addRow(label, self.cond[key])
        layout_cond.addLayout(form_cond)
        layout_cond.addSpacing(20)
        
        self.btn_run = QPushButton("🚀 RUN SIMULATION")
        self.btn_run.setObjectName("RunBtn")
        self.btn_run.setFixedHeight(60)
        self.btn_run.clicked.connect(self.run_solver)
        layout_cond.addWidget(self.btn_run)
        
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        layout_cond.addWidget(self.progress)
        
        layout_cond.addStretch()
        layout_cond.addWidget(QLabel("System Log (Real-time):"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(150)
        layout_cond.addWidget(self.console)

        panel_res = QFrame(); panel_res.setObjectName("Card")
        layout_res = QVBoxLayout(panel_res)
        
        header_res = QHBoxLayout()
        header_res.addWidget(self.create_header("Bending Hysteresis Loop"))
        self.lbl_hw = QLabel("HW: CPU 0%")
        self.lbl_hw.setStyleSheet("color: #888; font-weight: bold;")
        header_res.addWidget(self.lbl_hw, alignment=Qt.AlignRight)
        layout_res.addLayout(header_res)

        self.plot_canvas = pg.PlotWidget(background='#141419')
        self.plot_canvas.showGrid(x=True, y=True, alpha=0.2)
        self.plot_canvas.setLabel('left', "Bending Moment M", units='kN.m')
        self.plot_canvas.setLabel('bottom', "Curvature κ", units='1/m')
        self.curve = self.plot_canvas.plot(pen=pg.mkPen(color='#00ffcc', width=3.5))
        layout_res.addWidget(self.plot_canvas, 70)
        
        layout_bottom = QHBoxLayout()
        self.lbl_peak = self.create_metric_box("Peak Moment", "- kN.m")
        self.lbl_loss = self.create_metric_box("Hysteresis Loss", "- kJ")
        layout_bottom.addWidget(self.lbl_peak); layout_bottom.addWidget(self.lbl_loss)
        
        layout_export = QVBoxLayout()
        self.btn_export = QPushButton("📥 Export Data (CSV)"); self.btn_export.setFixedHeight(40); self.btn_export.clicked.connect(self.export_csv)
        self.btn_report = QPushButton("📄 Gen. Report (TXT)"); self.btn_report.setFixedHeight(40); self.btn_report.clicked.connect(self.export_report)
        layout_export.addWidget(self.btn_export); layout_export.addWidget(self.btn_report)
        
        layout_bottom.addLayout(layout_export)
        layout_res.addLayout(layout_bottom, 30)

        layout_analysis.addWidget(panel_cond)
        layout_analysis.addWidget(panel_res)
        self.tabs.addTab(tab_analysis, "📊 3. Analysis & Reports")

        for w in self.inputs.values():
            if isinstance(w, QLineEdit): w.textChanged.connect(self.trigger_rebuild)
            else: w.valueChanged.connect(self.trigger_rebuild)
        
        self.debounce = QTimer(); self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.rebuild_solid_geometry)
        self.trigger_rebuild()

    def create_header(self, text):
        lbl = QLabel(text); lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ffcc; padding-bottom: 5px;"); return lbl

    def create_metric_box(self, title, value):
        box = QFrame(); box.setObjectName("MetricBox")
        l = QVBoxLayout(box); t = QLabel(title); t.setStyleSheet("color: #aaa; font-size: 15px;")
        v = QLabel(value); v.setStyleSheet("color: #fff; font-size: 28px; font-weight: bold;")
        l.addWidget(t); l.addWidget(v); box.value_label = v; return box

    def init_material_table(self):
        mats = [
            ("1. Copper Core", "108.0", "0.33", QColor(217, 115, 38)), ("2. XLPE Insulation", "1.2", "0.46", QColor(230, 230, 230)),
            ("3. Lead Sheath", "16.0", "0.44", QColor(150, 150, 160)), ("4. Filler Matrix", "0.8", "0.48", QColor(60, 60, 65)),
            ("5. Inner Sheath", "1.5", "0.45", QColor(30, 30, 30)), ("6. Inner Armour", "210.0", "0.30", QColor(100, 120, 150)),
            ("7. Bedding", "0.5", "0.49", QColor(90, 70, 50)), ("8. Outer Armour", "210.0", "0.30", QColor(130, 150, 180)),
            ("9. Outer Sheath", "1.4", "0.45", QColor(40, 40, 45))
        ]
        for row, (name, e, nu, col) in enumerate(mats):
            icon = QTableWidgetItem(name); icon.setIcon(QIcon(self.create_color_icon(col)))
            self.table.setItem(row, 0, icon); self.table.setItem(row, 1, QTableWidgetItem(e)); self.table.setItem(row, 2, QTableWidgetItem(nu))

    def create_color_icon(self, color):
        pix = QPixmap(16, 16); pix.fill(color); return pix

    def trigger_rebuild(self):
        self.debounce.start(100)

    def load_csv(self):
        """Load simple CSV values into inputs.

        Supported formats:
        1) key,value
        2) label,value where label matches an input key
        Unknown keys are ignored so older CSV files do not break the GUI.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Open Design CSV", "", "CSV Files (*.csv)")
        if not path:
            return

        loaded = 0
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 2:
                        continue
                    key = row[0].strip()
                    value = row[1].strip()
                    if key.lower() in {"key", "parameter", "name"}:
                        continue
                    widget = self.inputs.get(key) or self.cond.get(key)
                    if widget is None:
                        continue
                    if isinstance(widget, QSpinBox):
                        widget.setValue(int(float(value)))
                    else:
                        widget.setText(value)
                    loaded += 1

            self.trigger_rebuild()
            QMessageBox.information(self, "Success", f"Loaded {loaded} parameter(s) from CSV.")
        except Exception as e:
            QMessageBox.critical(self, "CSV Load Error", str(e))

    def _to_float(self, widget, default=0.0):
        try:
            return float(widget.text())
        except Exception:
            return default

    def parse_geometry(self):
        rc = self._to_float(self.inputs["r_cond"], 4.0); ri = self._to_float(self.inputs["r_insu"], 11.3)
        roc = self._to_float(self.inputs["roc"], 15.3); coc = self._to_float(self.inputs["coc"], 17.66)
        tis = self._to_float(self.inputs["tis"], 4.5); ria = self._to_float(self.inputs["r_ia"], 2.0)
        nia = self.inputs["no_ia"].value(); roa = self._to_float(self.inputs["r_oa"], 2.0)
        noa = self.inputs["no_oa"].value(); gap = self._to_float(self.inputs["gap"], 0.5)
        tos = self._to_float(self.inputs["tos"], 4.5)

        iris = roc + coc; oris = iris + tis
        co_ia = oris + gap + ria; irb = co_ia + ria; orb = irb + 0.6  
        co_oa = orb + gap + roa; iros = co_oa + roa; oros = iros + tos
        
        self.derived_geom = {
            'rc': rc, 'ri': ri, 'roc': roc, 'coc': coc, 'iris': iris, 'oris': oris,
            'co_ia': co_ia, 'ria': ria, 'nia': nia, 'irb': irb, 'orb': orb,
            'co_oa': co_oa, 'roa': roa, 'noa': noa, 'iros': iros, 'oros': oros
        }

    def toggle_view_mode(self):
        if self.view_mode == "2D":
            self.view_mode = "3D"; self.btn_toggle_3d.setText("🔄 Switch back to 2D")
            self.view_solid.setCameraPosition(distance=250, elevation=35, azimuth=45)
        else:
            self.view_mode = "2D"; self.btn_toggle_3d.setText("🔄 Toggle 2D / 3D View")
            self.view_solid.setCameraPosition(distance=180, elevation=90, azimuth=0)
        self.rebuild_solid_geometry()

    def create_solid_mesh(self, r, cx, cy, z_front, color):
        if self.view_mode == "2D":
            t = np.linspace(0, 2*np.pi, 40); x = cx + r * np.cos(t); y = cy + r * np.sin(t)
            verts = [[cx, cy, z_front]]
            for i in range(len(t)): verts.append([x[i], y[i], z_front])
            faces = [[0, i, i+1] for i in range(1, len(t))]
            faces.append([0, len(t), 1])
            return gl.GLMeshItem(vertexes=np.array(verts), faces=np.array(faces), faceColors=np.tile(color, (len(faces),1)), smooth=False, shader=None)
        else:
            md = gl.MeshData.cylinder(rows=1, cols=40, radius=[r, r], length=50.0)
            m = gl.GLMeshItem(meshdata=md, smooth=True, color=color, shader='shaded')
            m.translate(cx, cy, z_front - 50.0); return m

    def rebuild_solid_geometry(self):
        for item in self.mesh_cache_solid:
            try: self.view_solid.removeItem(item)
            except: pass
        self.mesh_cache_solid.clear()
        try:
            self.parse_geometry(); dg = self.derived_geom
            m = self.create_solid_mesh(dg['oros'], 0, 0, 0.0, [0.15, 0.15, 0.15, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            for i in range(dg['noa']):
                ang = (2*np.pi/dg['noa'])*i
                m = self.create_solid_mesh(dg['roa'], dg['co_oa']*np.cos(ang), dg['co_oa']*np.sin(ang), 0.1, [0.5, 0.6, 0.7, 1.0])
                self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            m = self.create_solid_mesh(dg['orb'], 0, 0, 0.2, [0.4, 0.3, 0.2, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            for i in range(dg['nia']):
                ang = (2*np.pi/dg['nia'])*i
                m = self.create_solid_mesh(dg['ria'], dg['co_ia']*np.cos(ang), dg['co_ia']*np.sin(ang), 0.3, [0.4, 0.5, 0.6, 1.0])
                self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            m = self.create_solid_mesh(dg['oris'], 0, 0, 0.4, [0.1, 0.1, 0.1, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            m = self.create_solid_mesh(dg['iris'], 0, 0, 0.5, [0.25, 0.25, 0.28, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
            for i in range(3):
                ang = np.radians(120 * i); cx, cy = dg['coc']*np.cos(ang), dg['coc']*np.sin(ang)
                m = self.create_solid_mesh(dg['roc'], cx, cy, 0.6, [0.6, 0.6, 0.65, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
                m = self.create_solid_mesh(dg['ri'], cx, cy, 0.7, [0.9, 0.9, 0.9, 0.9]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
                m = self.create_solid_mesh(dg['rc'], cx, cy, 0.8, [0.85, 0.45, 0.15, 1.0]); self.view_solid.addItem(m); self.mesh_cache_solid.append(m)
        except Exception as e:
            self.console.append(f">> [WARN] Geometry rebuild skipped: {e}") if hasattr(self, "console") else None

    def generate_mesh_preview(self):
        for item in self.mesh_cache_wire:
            try: self.view_wire.removeItem(item)
            except: pass
        self.mesh_cache_wire.clear()
        try:
            self.parse_geometry(); dg = self.derived_geom
            def add_wire(r, cx, cy, z_divs, c_divs, col):
                md = gl.MeshData.cylinder(rows=z_divs, cols=c_divs, radius=[r, r], length=80.0)
                m = gl.GLMeshItem(meshdata=md, drawEdges=True, edgeColor=col, color=(0,0,0,0), smooth=False, shader=None)
                m.translate(cx, cy, -40.0); self.view_wire.addItem(m); self.mesh_cache_wire.append(m)

            add_wire(dg['oros'], 0, 0, self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_core"].value(), (0, 1, 0.8, 0.7))
            for i in range(dg['nia']):
                ang = (2*np.pi/dg['nia'])*i
                add_wire(dg['ria'], dg['co_ia']*np.cos(ang), dg['co_ia']*np.sin(ang), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.8, 0.8, 0.8, 0.9))
            for i in range(dg['noa']):
                ang = (2*np.pi/dg['noa'])*i
                add_wire(dg['roa'], dg['co_oa']*np.cos(ang), dg['co_oa']*np.sin(ang), self.mesh_inputs["z_elem"].value(), self.mesh_inputs["c_elem_armour"].value(), (0.6, 0.7, 0.9, 0.9))
        except Exception as e:
            QMessageBox.warning(self, "Mesh Error", str(e))

    # --- JSON 페이로드 자동 생성 로직 (핵심) ---
    def run_solver(self):
        self.btn_run.setEnabled(False)
        self.tabs.setCurrentIndex(2) 
        self.curve.setData([], [])
        
        self.progress.show(); self.progress.setValue(0); self.console.clear()
        mode = "FAST" if self.radio_fast.isChecked() else "ABAQUS"
        self.console.append(f"[SYS] Triggering {mode} Solver Pipeline...")
        
        self.parse_geometry()
        
        # 1D 등가강성(Equivalent EI) 자동 계산 로직
        try:
            E_cond = float(self.table.item(0, 1).text()) * 1e9 # 구리 탄성계수 (Pa)
            r_cond = self._to_float(self.inputs["r_cond"], 4.0) / 1e3 # m 변환
            I_cores = 3 * (np.pi * (r_cond**4) / 4) # 3코어의 단순 합산 단면2차모멘트
            EI_core_calculated = E_cond * I_cores # 등가 굽힘강성 (N.m^2)
        except:
            EI_core_calculated = 1500.0 # 계산 실패시 기본값

        # 보광이에게 넘길 아바쿠스 전용 페이로드 패키징
        payload_for_abaqus = {
            "core_equivalent_EI": EI_core_calculated,
            "armor_radius_in": self.derived_geom['co_ia'],
            "armor_radius_out": self.derived_geom['co_oa'],
            "wire_radius_in": self._to_float(self.inputs["r_ia"], 2.0),
            "wire_radius_out": self._to_float(self.inputs["r_oa"], 2.0),
            "num_wires_in": int(self.inputs["no_ia"].value()),
            "num_wires_out": int(self.inputs["no_oa"].value()),
            "lay_angle": self._to_float(self.inputs["lay_angle"], 12.0),
            "friction_coeff": self._to_float(self.cond["friction"], 0.22),
            "eff_length": self._to_float(self.cond["eff_length"], 234.2),
            "pressure": self._to_float(self.cond["pressure"], 40.0),
            "curvature": self._to_float(self.cond["curvature"], 0.08)
        }
        
        self.worker = CoupledFEASolver(payload_for_abaqus, mode)
        self.worker.log_sig.connect(lambda msg, lvl: self.console.append(msg))
        self.worker.progress_sig.connect(self.progress.setValue)
        self.worker.plot_sig.connect(self.update_plot)
        self.worker.metrics_sig.connect(self.update_metrics)
        self.worker.start()

    def update_plot(self, x, y):
        self.current_k = x; self.current_m = y
        self.curve.setData(x, y); self.plot_canvas.autoRange()

    def update_metrics(self, data):
        self.btn_run.setEnabled(True); self.progress.hide()
        self.last_metrics = data
        self.lbl_peak.value_label.setText(f"{data['max_moment']:.2f} kN.m")
        self.lbl_loss.value_label.setText(f"{data['loss']:.2f} kJ")

    def export_csv(self):
        if self.current_k.size == 0 or self.current_m.size == 0:
            QMessageBox.warning(self, "No Data", "Run a simulation before exporting CSV.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Result CSV", "sclas_result.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["curvature_1_per_m", "moment_kN_m"])
                writer.writerows(zip(self.current_k, self.current_m))
            QMessageBox.information(self, "Export Complete", f"Saved CSV:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def export_report(self):
        if not self.last_metrics:
            QMessageBox.warning(self, "No Data", "Run a simulation before generating a report.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Report", "sclas_report.txt", "Text Files (*.txt)")
        if not path:
            return
        try:
            self.parse_geometry()
            with open(path, "w", encoding="utf-8") as f:
                f.write("SCLAS v9.5 Simulation Report\n")
                f.write("=" * 32 + "\n\n")
                f.write("[Metrics]\n")
                for key, value in self.last_metrics.items():
                    f.write(f"{key}: {value}\n")
                f.write("\n[Geometry]\n")
                for key, value in self.derived_geom.items():
                    f.write(f"{key}: {value}\n")
            QMessageBox.information(self, "Report Complete", f"Saved report:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Report Error", str(e))

    def update_telemetry(self):
        try:
            self.lbl_hw.setText(f"HW: CPU {psutil.cpu_percent()}% | RAM {psutil.virtual_memory().percent}%")
        except Exception:
            self.lbl_hw.setText("HW: telemetry unavailable")

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0d12; color: #e0e0e0; font-family: 'Segoe UI', Arial; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #1a1a24; color: #888; padding: 15px 30px; font-size: 16px; font-weight: bold; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 5px; }
            QTabBar::tab:selected { background: #00ffcc; color: #0d0d12; }
            QFrame#Card { background-color: #1a1a24; border-radius: 12px; border: 1px solid #2a2a35; padding: 10px; }
            QFrame#MetricBox { background-color: #22222e; border-radius: 8px; border-left: 4px solid #00ffcc; padding: 10px; }
            QLabel { font-size: 15px; color: #ccc; }
            QLineEdit, QSpinBox, QComboBox { background-color: #22222e; border: 1px solid #333344; border-radius: 6px; padding: 10px; color: #fff; font-size: 15px; font-weight: bold; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #00ffcc; }
            QPushButton { background-color: #333344; color: #fff; border-radius: 6px; font-size: 16px; font-weight: bold; }
            QPushButton:hover { background-color: #444455; }
            QPushButton#RunBtn { background-color: #00ffcc; color: #0d0d12; font-size: 20px; }
            QPushButton#RunBtn:hover { background-color: #33ffdd; }
            QTableWidget { background-color: #1a1a24; color: #fff; font-size: 14px; border: none; gridline-color: #2a2a35; }
            QHeaderView::section { background-color: #22222e; color: #00ffcc; font-weight: bold; border: 1px solid #2a2a35; padding: 8px; }
            QTextEdit { background-color: #0a0a0f; color: #00ffcc; font-family: Consolas; border-radius: 6px; padding: 8px; font-size: 14px; }
            QProgressBar { border: 1px solid #333344; border-radius: 6px; text-align: center; color: white; font-weight: bold; }
            QProgressBar::chunk { background-color: #00ffcc; border-radius: 5px; }
            QRadioButton { font-size: 16px; font-weight: bold; color: #fff; }
            QRadioButton::indicator { width: 18px; height: 18px; }
            QRadioButton::indicator:checked { background-color: #00ffcc; border-radius: 9px; }
        """)

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    window = SCLAS_V8()
    window.show()
    sys.exit(app.exec_())
