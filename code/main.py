import sys
import numpy as np
import json
import psutil
import csv
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

# Hardware-accelerated 3D/2D Graphics Engines
import pyqtgraph as pg
import pyqtgraph.opengl as gl

# =====================================================================
# ⚙️ Bouc-Wen Nonlinear Hysteresis Solver Kernel
# =====================================================================
class CoupledFEASolver(QThread):
    plot_sig = pyqtSignal(np.ndarray, np.ndarray)
    metrics_sig = pyqtSignal(dict)
    log_sig = pyqtSignal(str, str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            self.log_sig.emit(">> [SYS] Initiating structural mechanics solver...", "info")
            
            # Parameters
            eff_length = float(self.params.get('eff_length', 234.2)) / 1e3
            friction = float(self.params.get('friction', 0.22))
            pressure = float(self.params.get('pressure', 40.0))
            k_max = float(self.params.get('curvature', 0.08))
            
            # Material Binding
            E_cond = float(self.params.get('E_cond', 108.0)) * 1e9
            E_armour = float(self.params.get('E_armour', 210.0)) * 1e9
            
            n_in = int(self.params.get('no_ia', 55))
            n_out = int(self.params.get('no_oa', 63))
            R_in = float(self.params.get('co_ia', 39.46)) / 1e3
            R_out = float(self.params.get('co_oa', 44.06)) / 1e3
            
            # Geometric Stiffness (m^4)
            I_cores = 3 * (np.pi * (0.0115**4) / 4)
            I_armour_in = n_in * (np.pi * (0.002**4) / 64) + n_in * (np.pi * (0.002**2) / 4) * (R_in**2)
            I_armour_out = n_out * (np.pi * (0.002**4) / 64) + n_out * (np.pi * (0.002**2) / 4) * (R_out**2)
            
            EI_init = (E_cond * I_cores) + E_armour * (I_armour_in + I_armour_out)
            EI_slip = EI_init * (0.28 + (friction * 0.1))
            M_yield = (EI_init - EI_slip) * k_max * 0.45 * (1.0 + friction * 2.2 + (pressure / 45.0))
            
            # Bouc-Wen Iteration
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
            
            scale_factor = 1e3
            plot_M = M_arr * scale_factor
            
            self.plot_sig.emit(k_arr, plot_M)
            self.metrics_sig.emit({
                "max_moment": np.max(np.abs(plot_M)),
                "ei_init": EI_init * scale_factor,
                "ei_slip": EI_slip * scale_factor,
                "loss": np.sum(np.abs(plot_M)) * (k_max / steps)
            })
            self.log_sig.emit(">> [SYS] Analysis complete.", "success")
        except Exception as e:
            self.log_sig.emit(f">> [ERR] Solver failed: {str(e)}", "error")

# =====================================================================
# 🎨 SCLAS v8.1 | Professional Engineering Interface
# =====================================================================
class SCLAS_V8(QMainWindow):
    def __init__(self):
        super().__init__()
        self.derived_geom = {}
        self.mesh_cache = []
        self.init_ui()
        self.apply_theme()
        
        self.sys_timer = QTimer()
        self.sys_timer.timeout.connect(self.update_telemetry)
        self.sys_timer.start(1000)

    def init_ui(self):
        self.setWindowTitle("SCLAS v8.1 | Integrated Cable Analysis Platform")
        self.resize(1650, 950)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # ==============================================================
        # 📐 TAB 1: DESIGN & CROSS-SECTION
        # ==============================================================
        tab_design = QWidget()
        layout_design = QHBoxLayout(tab_design)
        layout_design.setSpacing(15)

        # --- Panel 1: Geometry Inputs ---
        panel_inputs = QFrame(); panel_inputs.setObjectName("Card")
        layout_inputs = QVBoxLayout(panel_inputs)
        
        self.btn_load = QPushButton("📂 Load Cable Parameters (CSV)")
        self.btn_load.setFixedHeight(50)
        self.btn_load.clicked.connect(self.load_csv)
        layout_inputs.addWidget(self.btn_load)
        
        form_geom = QFormLayout()
        form_geom.setVerticalSpacing(15)
        
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
            "tos": QLineEdit("4.50")
        }
        self.inputs["no_ia"].setRange(10, 200); self.inputs["no_ia"].setValue(55)
        self.inputs["no_oa"].setRange(10, 200); self.inputs["no_oa"].setValue(63)

        layout_inputs.addWidget(self.create_header("Core Dimensions"))
        form_geom.addRow("Conductor Radius (mm):", self.inputs["r_cond"])
        form_geom.addRow("Insulation Radius (mm):", self.inputs["r_insu"])
        form_geom.addRow("Radius of Core (RoC):", self.inputs["roc"])
        form_geom.addRow("Center of Core (CoC):", self.inputs["coc"])
        form_geom.addRow("Inner Sheath Thick.:", self.inputs["tis"])
        
        layout_inputs.addLayout(form_geom)
        layout_inputs.addSpacing(15)
        
        form_armour = QFormLayout()
        form_armour.setVerticalSpacing(15)
        layout_inputs.addWidget(self.create_header("Armour Configuration"))
        form_armour.addRow("Inner Armour Count:", self.inputs["no_ia"])
        form_armour.addRow("Inner Wire Radius:", self.inputs["r_ia"])
        form_armour.addRow("Outer Armour Count:", self.inputs["no_oa"])
        form_armour.addRow("Outer Wire Radius:", self.inputs["r_oa"])
        form_armour.addRow("Clearance Gap (mm):", self.inputs["gap"])
        form_armour.addRow("Outer Sheath Thick.:", self.inputs["tos"])
        
        layout_inputs.addLayout(form_armour)
        layout_inputs.addStretch()

        # --- Panel 2: Material Table ---
        panel_mat = QFrame(); panel_mat.setObjectName("Card")
        layout_mat = QVBoxLayout(panel_mat)
        layout_mat.addWidget(self.create_header("Material Properties (Editable)"))
        
        self.table = QTableWidget(9, 3)
        self.table.setHorizontalHeaderLabels(["Layer", "E (GPa)", "Nu (v)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.init_material_table()
        layout_mat.addWidget(self.table)

        # --- Panel 3: Cross-Section Viewport ---
        panel_view = QFrame(); panel_view.setObjectName("Card")
        layout_view = QVBoxLayout(panel_view)
        layout_view.addWidget(self.create_header("Digital Cross-Section Preview"))
        
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor('#141419')
        # [혁신] 카메라를 평면에 고정시켜 왜곡 없는 완벽한 단면 CAD 뷰 생성 (Grid 제거)
        self.view.setCameraPosition(distance=180, elevation=90, azimuth=0) 
        layout_view.addWidget(self.view)

        layout_design.addWidget(panel_inputs, 20)
        layout_design.addWidget(panel_mat, 30)
        layout_design.addWidget(panel_view, 50)
        self.tabs.addTab(tab_design, "📐 1. Design & Cross-Section")

        # ==============================================================
        # 📊 TAB 2: ANALYSIS & RESULTS
        # ==============================================================
        tab_analysis = QWidget()
        layout_analysis = QHBoxLayout(tab_analysis)
        layout_analysis.setSpacing(15)

        # --- Panel 1: Analysis Conditions ---
        panel_cond = QFrame(); panel_cond.setObjectName("Card")
        panel_cond.setFixedWidth(400)
        layout_cond = QVBoxLayout(panel_cond)
        
        layout_cond.addWidget(self.create_header("Analysis Conditions"))
        form_cond = QFormLayout()
        form_cond.setVerticalSpacing(15)
        
        self.cond = {
            "eff_length": QLineEdit("234.20"),
            "pressure": QLineEdit("40.00"),
            "friction": QLineEdit("0.22"),
            "curvature": QLineEdit("0.08")
        }
        form_cond.addRow("Effective Length (mm):", self.cond["eff_length"])
        form_cond.addRow("Hydrostatic Pressure (MPa):", self.cond["pressure"])
        form_cond.addRow("Friction Coefficient (μ):", self.cond["friction"])
        form_cond.addRow("Max Curvature (1/m):", self.cond["curvature"])
        
        layout_cond.addLayout(form_cond)
        layout_cond.addSpacing(30)
        
        self.btn_run = QPushButton("🚀 RUN SIMULATION")
        self.btn_run.setObjectName("RunBtn")
        self.btn_run.setFixedHeight(60)
        self.btn_run.clicked.connect(self.run_solver)
        layout_cond.addWidget(self.btn_run)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(200)
        layout_cond.addStretch()
        layout_cond.addWidget(QLabel("System Log:"))
        layout_cond.addWidget(self.console)

        # --- Panel 2: Result Plot & Metrics ---
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
        
        # Metrics Row
        layout_metrics = QHBoxLayout()
        self.lbl_peak = self.create_metric_box("Peak Bending Moment", "- kN.m")
        self.lbl_loss = self.create_metric_box("Hysteresis Loss Energy", "- kJ")
        self.lbl_stiff = self.create_metric_box("Initial Stiffness", "- kN.m²")
        layout_metrics.addWidget(self.lbl_peak)
        layout_metrics.addWidget(self.lbl_loss)
        layout_metrics.addWidget(self.lbl_stiff)
        layout_res.addLayout(layout_metrics, 30)

        layout_analysis.addWidget(panel_cond)
        layout_analysis.addWidget(panel_res)
        self.tabs.addTab(tab_analysis, "📊 2. Analysis & Results")

        # Connect signals for Real-Time Update
        for w in self.inputs.values():
            if isinstance(w, QLineEdit): w.textChanged.connect(self.trigger_rebuild)
            else: w.valueChanged.connect(self.trigger_rebuild)
        
        self.debounce = QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.rebuild_cross_section)
        
        self.trigger_rebuild()

    def create_header(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ffcc; padding-bottom: 5px;")
        return lbl

    def create_metric_box(self, title, value):
        box = QFrame(); box.setObjectName("MetricBox")
        l = QVBoxLayout(box)
        t = QLabel(title); t.setStyleSheet("color: #aaa; font-size: 15px;")
        v = QLabel(value); v.setStyleSheet("color: #fff; font-size: 26px; font-weight: bold;")
        l.addWidget(t); l.addWidget(v)
        box.value_label = v
        return box

    def init_material_table(self):
        # Name, E, Nu, Color mapping for the legend
        mats = [
            ("1. Copper Core", "108.0", "0.33", QColor(217, 115, 38)),
            ("2. XLPE Insulation", "1.2", "0.46", QColor(230, 230, 230)),
            ("3. Lead Sheath", "16.0", "0.44", QColor(150, 150, 160)),
            ("4. Filler Matrix", "0.8", "0.48", QColor(60, 60, 65)),
            ("5. Inner Sheath", "1.5", "0.45", QColor(30, 30, 30)),
            ("6. Inner Armour", "210.0", "0.30", QColor(100, 120, 150)),
            ("7. Bedding", "0.5", "0.49", QColor(90, 70, 50)),
            ("8. Outer Armour", "210.0", "0.30", QColor(130, 150, 180)),
            ("9. Outer Sheath", "1.4", "0.45", QColor(40, 40, 45))
        ]
        for row, (name, e, nu, col) in enumerate(mats):
            icon = QTableWidgetItem(name)
            icon.setIcon(QIcon(self.create_color_icon(col)))
            icon.setFlags(icon.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, icon)
            self.table.setItem(row, 1, QTableWidgetItem(e))
            self.table.setItem(row, 2, QTableWidgetItem(nu))

    def create_color_icon(self, color):
        pix = QPixmap(16, 16); pix.fill(color); return pix

    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Design CSV", "", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    for row in csv.reader(f):
                        if not row or len(row) < 2: continue
                        k, v = row[0].strip(), row[1].strip().replace('(', '-').replace(')', '')
                        if not v: continue
                        if "Radius of Conductor" in k: self.inputs["r_cond"].setText(v)
                        elif "Radius of Insulation" in k: self.inputs["r_insu"].setText(v)
                        elif "Radius of Core" in k: self.inputs["roc"].setText(v)
                        elif "Centre of Core" in k: self.inputs["coc"].setText(v)
                        elif "Thickness of Inner Sheath" in k: self.inputs["tis"].setText(v)
                        elif "Radius of Inner Armour" in k: self.inputs["r_ia"].setText(v)
                        elif "Number of Inner Armour" in k: self.inputs["no_ia"].setValue(int(float(v)))
                        elif "Radius of Outer Armour" in k: self.inputs["r_oa"].setText(v)
                        elif "Number of Outer Armour" in k: self.inputs["no_oa"].setValue(int(float(v)))
                        elif "Thickness of Outer Sheath" in k: self.inputs["tos"].setText(v)
                self.trigger_rebuild()
                QMessageBox.information(self, "Success", "Cable parameters loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def trigger_rebuild(self):
        self.debounce.start(100)

    # [핵심] Z-Index를 활용한 완벽한 2D 단면 매핑 생성기
    def create_flat_circle(self, r, cx, cy, z, color):
        t = np.linspace(0, 2*np.pi, 60)
        x = cx + r * np.cos(t); y = cy + r * np.sin(t)
        verts = [[cx, cy, z]]
        for i in range(len(t)): verts.append([x[i], y[i], z])
        faces = []
        for i in range(1, len(t)): faces.append([0, i, i+1])
        faces.append([0, len(t), 1])
        return gl.GLMeshItem(vertexes=np.array(verts), faces=np.array(faces), faceColors=np.tile(color, (len(faces),1)), smooth=False, shader=None)

    def rebuild_cross_section(self):
        for item in self.mesh_cache:
            try: self.view.removeItem(item)
            except: pass
        self.mesh_cache.clear()

        try:
            # Get geometry
            rc = float(self.inputs["r_cond"].text())
            ri = float(self.inputs["r_insu"].text())
            roc = float(self.inputs["roc"].text())
            coc = float(self.inputs["coc"].text())
            tis = float(self.inputs["tis"].text())
            ria = float(self.inputs["r_ia"].text())
            nia = self.inputs["no_ia"].value()
            roa = float(self.inputs["r_oa"].text())
            noa = self.inputs["no_oa"].value()
            gap = float(self.inputs["gap"].text())
            tos = float(self.inputs["tos"].text())

            iris = roc + coc
            oris = iris + tis
            co_ia = oris + gap + ria
            irb = co_ia + ria
            orb = irb + 0.6  # Bedding thickness
            co_oa = orb + gap + roa
            iros = co_oa + roa
            oros = iros + tos

            self.derived_geom = {'co_ia': co_ia, 'co_oa': co_oa, 'no_ia': nia, 'no_oa': noa}

            # Z-Layers for perfect occlusion (겹침 방지)
            # 9. Outer Sheath
            m = self.create_flat_circle(oros, 0, 0, 0.0, [0.15, 0.15, 0.15, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
            # 8. Outer Armour (Dots)
            for i in range(noa):
                ang = (2*np.pi/noa)*i
                m = self.create_flat_circle(roa, co_oa*np.cos(ang), co_oa*np.sin(ang), 0.1, [0.5, 0.6, 0.7, 1.0])
                self.view.addItem(m); self.mesh_cache.append(m)
            # 7. Bedding
            m = self.create_flat_circle(orb, 0, 0, 0.2, [0.4, 0.3, 0.2, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
            # 6. Inner Armour (Dots)
            for i in range(nia):
                ang = (2*np.pi/nia)*i
                m = self.create_flat_circle(ria, co_ia*np.cos(ang), co_ia*np.sin(ang), 0.3, [0.4, 0.5, 0.6, 1.0])
                self.view.addItem(m); self.mesh_cache.append(m)
            # 5. Inner Sheath
            m = self.create_flat_circle(oris, 0, 0, 0.4, [0.1, 0.1, 0.1, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
            # 4. Fillers (Background of cores)
            m = self.create_flat_circle(iris, 0, 0, 0.5, [0.25, 0.25, 0.28, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
            
            # Cores Assembly
            for i in range(3):
                ang = np.radians(120 * i)
                cx, cy = coc*np.cos(ang), coc*np.sin(ang)
                # 3. Lead Sheath
                m = self.create_flat_circle(roc, cx, cy, 0.6, [0.6, 0.6, 0.65, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
                # 2. XLPE
                m = self.create_flat_circle(ri, cx, cy, 0.7, [0.9, 0.9, 0.9, 0.9]); self.view.addItem(m); self.mesh_cache.append(m)
                # 1. Copper
                m = self.create_flat_circle(rc, cx, cy, 0.8, [0.85, 0.45, 0.15, 1.0]); self.view.addItem(m); self.mesh_cache.append(m)
        except Exception: pass

    def run_solver(self):
        self.btn_run.setText("⏳ COMPUTING...")
        self.btn_run.setEnabled(False)
        
        # Move to Results tab
        self.tabs.setCurrentIndex(1)
        self.curve.setData([], [])
        
        payload = {k: v.text() for k,v in self.cond.items()}
        payload.update(self.derived_geom)
        try:
            payload["E_cond"] = self.table.item(0, 1).text()
            payload["E_armour"] = self.table.item(5, 1).text()
        except: pass

        self.worker = CoupledFEASolver(payload)
        self.worker.log_sig.connect(lambda msg, lvl: self.console.append(msg))
        self.worker.plot_sig.connect(self.update_plot)
        self.worker.metrics_sig.connect(self.update_metrics)
        self.worker.start()

    def update_plot(self, x, y):
        self.curve.setData(x, y)
        self.plot_canvas.autoRange()

    def update_metrics(self, data):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("🚀 RUN SIMULATION")
        self.lbl_peak.value_label.setText(f"{data['max_moment']:.2f} kN.m")
        self.lbl_loss.value_label.setText(f"{data['loss']:.2f} kJ")
        self.lbl_stiff.value_label.setText(f"{data['ei_init']:.1f} kN.m²")

    def update_telemetry(self):
        self.lbl_hw.setText(f"HW: CPU {psutil.cpu_percent()}% | RAM {psutil.virtual_memory().percent}%")

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0d12; color: #e0e0e0; font-family: 'Segoe UI', Arial; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #1a1a24; color: #888; padding: 15px 30px; font-size: 16px; font-weight: bold; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 5px; }
            QTabBar::tab:selected { background: #00ffcc; color: #0d0d12; }
            QFrame#Card { background-color: #1a1a24; border-radius: 12px; border: 1px solid #2a2a35; padding: 10px; }
            QFrame#MetricBox { background-color: #22222e; border-radius: 8px; border-left: 4px solid #00ffcc; padding: 10px; }
            QLabel { font-size: 16px; color: #ccc; }
            QLineEdit, QSpinBox { background-color: #22222e; border: 1px solid #333344; border-radius: 6px; padding: 10px; color: #fff; font-size: 16px; font-weight: bold; }
            QLineEdit:focus, QSpinBox:focus { border: 1px solid #00ffcc; }
            QPushButton { background-color: #333344; color: #fff; border-radius: 6px; font-size: 16px; font-weight: bold; }
            QPushButton:hover { background-color: #444455; }
            QPushButton#RunBtn { background-color: #00ffcc; color: #0d0d12; font-size: 20px; }
            QPushButton#RunBtn:hover { background-color: #33ffdd; }
            QTableWidget { background-color: #1a1a24; color: #fff; font-size: 15px; border: none; gridline-color: #2a2a35; }
            QHeaderView::section { background-color: #22222e; color: #00ffcc; font-weight: bold; border: 1px solid #2a2a35; padding: 8px; }
            QTextEdit { background-color: #0a0a0f; color: #00ffcc; font-family: Consolas; border-radius: 6px; padding: 8px; font-size: 14px; }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SCLAS_V8()
    window.show()
    sys.exit(app.exec_())