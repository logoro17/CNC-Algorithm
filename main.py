import sys
import os
import math
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
    QWidget, QLabel, QPushButton, QComboBox, QFrame, QTextEdit,
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox,
    QDialogButtonBox, QSplitter, QFileDialog
)
from PyQt5.QtCore import Qt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

import gcode_engine 

SUPPORTED_EXTENSIONS = ('.gcode', '.ngc', '.nc', '.tap', '.g', '.cnc', '.txt')


# --- COMPONENT DRAG & DROP ZONE ---
class DropZoneWidget(QFrame):
    def __init__(self, callback_on_drop, parent=None):
        super().__init__(parent)
        self.callback_on_drop = callback_on_drop
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #3498db;
                border-radius: 8px;
                background-color: #ecf0f1;
                padding: 10px;
            }
        """)
        layout = QVBoxLayout(self)
        ext_str = ", ".join(SUPPORTED_EXTENSIONS)
        self.label = QLabel(f"DRAG & DROP FILE ({ext_str}) DI SINI")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 12px;")
        layout.addWidget(self.label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            filepath = urls[0].toLocalFile()
            if filepath: self.callback_on_drop(filepath)


# --- MODAL TOPOGRAPHY INSPECTION REPORT WINDOW ---
class TopographyReportDialog(QDialog):
    def __init__(self, raw_points, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PCB Spatial & Thermal Risk Topography Report")
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        self.figure, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        self.generate_topography(raw_points)

        btn_box = QHBoxLayout()
        self.btn_save = QPushButton("Save Inspection Plot")
        self.btn_save.clicked.connect(self.save_plot)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        btn_box.addWidget(self.btn_save)
        btn_box.addWidget(self.btn_close)
        layout.addLayout(btn_box)

    def generate_topography(self, points):
        self.ax.clear()
        if not points: return

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i+1]
            if p2.type == 1: # Cutting
                length = math.hypot(p2.x - p1.x, p2.y - p1.y)
                color = 'red' if length < 2.0 else ('yellow' if length < 5.0 else 'green')
                self.ax.plot([p1.x, p2.x], [p1.y, p2.y], color=color, linewidth=1.8)

        self.ax.set_title("PCB Topography: Red=Critical Pad, Yellow=Trace, Green=Safe Area", fontsize=10)
        self.ax.set_aspect('equal')
        self.ax.grid(True, linestyle=':', alpha=0.5)
        self.canvas.draw()

    def save_plot(self):
        self.figure.savefig("PCB_Topography_Report.png", dpi=300)


# --- ADVANCED ALGORITHM SETTINGS DIALOG ---
class AlgorithmSettingsDialog(QDialog):
    def __init__(self, alg_index, current_params, parent=None):
        super().__init__(parent)
        self.alg_index = alg_index
        self.params = current_params.copy()
        titles = ["Nearest Neighbor", "2-Opt Local Search", "Simulated Annealing", "Standard GA", "PCB-Aware Thermal GA"]
        self.setWindowTitle(f"Settings: {titles[alg_index]}")
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        if alg_index == 1:
            self.spin_max_iter = QSpinBox()
            self.spin_max_iter.setRange(10, 10000)
            self.spin_max_iter.setValue(self.params.get('2opt_max_iter', 1000))
            form_layout.addRow("Max Iterations:", self.spin_max_iter)

        elif alg_index == 2:
            self.spin_temp = QDoubleSpinBox()
            self.spin_temp.setRange(10.0, 100000.0)
            self.spin_temp.setValue(self.params.get('sa_temp', 1000.0))
            self.spin_cooling = QDoubleSpinBox()
            self.spin_cooling.setRange(0.800, 0.9999)
            self.spin_cooling.setDecimals(4)
            self.spin_cooling.setValue(self.params.get('sa_cooling', 0.995))
            form_layout.addRow("Initial Temp (T0):", self.spin_temp)
            form_layout.addRow("Cooling Rate:", self.spin_cooling)

        elif alg_index in (3, 4):
            self.spin_pop = QSpinBox()
            self.spin_pop.setRange(10, 2000)
            self.spin_pop.setValue(self.params.get('ga_pop', 50))
            self.spin_gen = QSpinBox()
            self.spin_gen.setRange(10, 10000)
            self.spin_gen.setValue(self.params.get('ga_gen', 200))
            self.spin_mut = QDoubleSpinBox()
            self.spin_mut.setRange(0.01, 1.0)
            self.spin_mut.setValue(self.params.get('ga_mut', 0.15))
            form_layout.addRow("Population Size:", self.spin_pop)
            form_layout.addRow("Generations:", self.spin_gen)
            form_layout.addRow("Mutation Rate:", self.spin_mut)

            if alg_index == 4:
                self.chk_thermal = QCheckBox("Enable Thermal Penalty (QFP)")
                self.chk_thermal.setChecked(self.params.get('ga_enable_thermal', True))
                self.combo_region = QComboBox()
                self.combo_region.addItems(["Disabled", "Smallest Region First", "Largest Region First", "Center-Out (Centroid)"])
                self.combo_region.setCurrentIndex(self.params.get('ga_region_strat', 0))
                self.spin_rad = QDoubleSpinBox()
                self.spin_rad.setValue(self.params.get('ga_thermal_rad', 2.0))
                self.spin_max_g0 = QSpinBox()
                self.spin_max_g0.setRange(500, 10000)
                self.spin_max_g0.setValue(self.params.get('sculpfun_max_g0', 3000))
                self.spin_accel = QSpinBox()
                self.spin_accel.setRange(100, 5000)
                self.spin_accel.setValue(self.params.get('sculpfun_accel', 500))

                form_layout.addRow(self.chk_thermal)
                form_layout.addRow("Region Strategy:", self.combo_region)
                form_layout.addRow("Thermal Radius (mm):", self.spin_rad)
                form_layout.addRow("Sculpfun G0 Limit:", self.spin_max_g0)
                form_layout.addRow("Sculpfun Accel:", self.spin_accel)
            

        layout.addLayout(form_layout)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if alg_index == 4:
            self.btn_reset = QPushButton("reset")
            self.btn_reset.setStyleSheet("color: red; font-weight: bold; padding: 2px 10px;")
            buttons.addButton(self.btn_reset, QDialogButtonBox.ResetRole)
            self.btn_reset.clicked.connect(self.reset_defaults)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset_defaults(self):
        if self.alg_index == 4:
            self.spin_pop.setValue(50)
            self.spin_gen.setValue(200)
            self.spin_mut.setValue(0.15)
            self.chk_thermal.setChecked(True)
            self.combo_region.setCurrentIndex(3)
            self.spin_rad.setValue(2.00)
            self.spin_max_g0.setValue(3000)
            self.spin_accel.setValue(500)

    def get_updated_params(self):
        if self.alg_index == 1:
            self.params['2opt_max_iter'] = self.spin_max_iter.value()
        elif self.alg_index == 2:
            self.params['sa_temp'] = self.spin_temp.value()
            self.params['sa_cooling'] = self.spin_cooling.value()
        elif self.alg_index in (3, 4):
            self.params['ga_pop'] = self.spin_pop.value()
            self.params['ga_gen'] = self.spin_gen.value()
            self.params['ga_mut'] = self.spin_mut.value()
            if self.alg_index == 4:
                self.params['ga_enable_thermal'] = self.chk_thermal.isChecked()
                self.params['ga_region_strat'] = self.combo_region.currentIndex()
                self.params['ga_thermal_rad'] = self.spin_rad.value()
                self.params['sculpfun_max_g0'] = self.spin_max_g0.value()
                self.params['sculpfun_accel'] = self.spin_accel.value()
        return self.params


# --- MAIN APPLICATION ---
class AutoLoadGCodeApp(QMainWindow):
    def __init__(self, default_gcode_path="complex_pcb_test.gcode"):
        super().__init__()
        self.setWindowTitle("Sculpfun C1 Mini - PCB CAM Optimizer")
        self.setGeometry(100, 100, 600, 720)

        self.engine = gcode_engine.GCodeOptimizer()
        self.current_filepath = ""
        self.last_optimized_points = []  # Tempat nyimpen hasil optimasi buat di-save

        self.alg_params = {
            '2opt_max_iter': 1000, 'sa_temp': 1000.0, 'sa_cooling': 0.995,
            'ga_pop': 50, 'ga_gen': 200, 'ga_mut': 0.15,
            'ga_enable_thermal': True, 'ga_region_strat': 3, 'ga_thermal_rad': 2.0,
            'sculpfun_max_g0': 3000, 'sculpfun_accel': 500
        }

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        main_layout = QVBoxLayout(self.main_widget)
        self.splitter = QSplitter(Qt.Vertical)
        
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        self.drop_zone = DropZoneWidget(callback_on_drop=self.auto_load_file)
        top_layout.addWidget(self.drop_zone)

        self.figure, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.figure)
        top_layout.addWidget(self.canvas)

        # BARIS 1 TOMBOL (Tools & Reset)
        tools_layout = QHBoxLayout()
        
        self.btn_reset = QPushButton("🔄 Reset")
        self.btn_reset.setStyleSheet("background-color: #e74c3c; color: white;")
        self.btn_reset.clicked.connect(self.reset_app)
        tools_layout.addWidget(self.btn_reset)

        self.btn_topo = QPushButton("🔍 Topography")
        self.btn_topo.clicked.connect(self.open_topography_report)
        tools_layout.addWidget(self.btn_topo)

        self.btn_settings = QPushButton("⚙ Settings")
        self.btn_settings.clicked.connect(self.open_algorithm_settings)
        tools_layout.addWidget(self.btn_settings)
        
        top_layout.addLayout(tools_layout)

        # BARIS 2 TOMBOL (Run & Save)
        run_layout = QHBoxLayout()

        self.combo_alg = QComboBox()
        self.combo_alg.addItems([" Nearest Neighbor", " 2-Opt Local Search", " Simulated Annealing", " Standard GA (TSP)", " PCB-Aware Thermal GA"])
        self.combo_alg.setCurrentIndex(4) # Default ke Algoritma ke-5
        run_layout.addWidget(self.combo_alg, stretch=3)

        self.btn_start = QPushButton("🚀 RUN OPTIMIZE")
        self.btn_start.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.btn_start.clicked.connect(self.run_optimization)
        run_layout.addWidget(self.btn_start, stretch=2)

        self.btn_save = QPushButton("💾 SAVE G-CODE")
        self.btn_save.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold;")
        self.btn_save.setEnabled(False) # Hanya aktif setelah Run
        self.btn_save.clicked.connect(self.save_gcode)
        run_layout.addWidget(self.btn_save, stretch=2)

        top_layout.addLayout(run_layout)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas;")
        bottom_layout.addWidget(self.log_console)

        self.splitter.addWidget(top_widget)
        self.splitter.addWidget(bottom_widget)
        self.splitter.setSizes([550, 170])
        main_layout.addWidget(self.splitter)

        if os.path.exists(default_gcode_path):
            self.auto_load_file(default_gcode_path)

    def log(self, text):
        self.log_console.append(text)

    def reset_app(self):
        """Reset seluruh state aplikasi, memory C++, dan kanvas."""
        self.engine = gcode_engine.GCodeOptimizer()
        self.current_filepath = ""
        self.last_optimized_points = []
        self.drop_zone.label.setText("DRAG & DROP FILE (.gcode) DI SINI")
        self.log_console.clear()
        self.ax.clear()
        self.ax.grid(True, linestyle=':', alpha=0.5)
        self.canvas.draw()
        self.btn_save.setEnabled(False)
        self.log("[SYSTEM] Aplikasi di-reset. Engine C++ cleared. Siap menerima file baru.")

    def open_topography_report(self):
        raw_pts = self.engine.getRawPoints()
        if not raw_pts:
            self.log("[ERROR] Load G-code file first.")
            return
        dialog = TopographyReportDialog(raw_pts, self)
        dialog.exec_()

    def open_algorithm_settings(self):
        alg_idx = self.combo_alg.currentIndex()
        dialog = AlgorithmSettingsDialog(alg_idx, self.alg_params, self)
        if dialog.exec_() == QDialog.Accepted:
            self.alg_params = dialog.get_updated_params()
            self.log(f"[CONFIG] Settings saved for {self.combo_alg.currentText()}")

    def apply_cpp_configs(self):
        alg_idx = self.combo_alg.currentIndex()
        if alg_idx == 1: self.engine.set2OptConfig(self.alg_params['2opt_max_iter'])
        elif alg_idx == 2: self.engine.setSAConfig(self.alg_params['sa_temp'], self.alg_params['sa_cooling'], 0.001)
        elif alg_idx in (3, 4):
            self.engine.setGAConfig(
                self.alg_params['ga_pop'], self.alg_params['ga_gen'], self.alg_params['ga_mut'],
                self.alg_params['ga_enable_thermal'], self.alg_params['ga_region_strat'],
                self.alg_params['ga_thermal_rad'], float(self.alg_params['sculpfun_max_g0']),
                float(self.alg_params['sculpfun_accel'])
            )

    def auto_load_file(self, filepath):
        if not os.path.exists(filepath): return
        self.current_filepath = filepath
        self.drop_zone.label.setText(f"FILE ACTIVE: {os.path.basename(filepath)}")
        self.engine.loadGCode(filepath)
        raw_points = self.engine.getRawPoints()
        self.draw_points(raw_points, title=f"Original Path ({os.path.basename(filepath)})")
        self.btn_save.setEnabled(False)
        self.log(f"[FILE LOADED] {os.path.basename(filepath)} | Points: {len(raw_points)}")

    def run_optimization(self):
        if not self.current_filepath: return
        alg_idx = self.combo_alg.currentIndex()
        alg_name = self.combo_alg.currentText()
        
        self.apply_cpp_configs()
        report = self.engine.runWithReport(alg_idx)
        
        # Simpan point hasil optimasi ke Python Memory
        self.last_optimized_points = self.engine.optimizePath(alg_idx)
        
        self.draw_points(self.last_optimized_points, title=f"Optimized: {alg_name}")
        self.btn_save.setEnabled(True) # Aktifkan tombol save
        
        saved_dist = report.originalDistance - report.optimizedDistance
        saved_pct = (saved_dist / report.originalDistance * 100) if report.originalDistance > 0 else 0

        self.log("="*55)
        self.log(f"[C++ ENGINE EXECUTED] {alg_name}")
        self.log(f"  ├─ Contours Grouped : {report.contourCount} items")
        self.log(f"  ├─ C++ Time Taken   : {report.timeTakenMs:.4f} ms")
        self.log(f"  ├─ Initial G0 Travel: {report.originalDistance:.2f} mm")
        self.log(f"  ├─ Optimized Travel : {report.optimizedDistance:.2f} mm")
        self.log(f"  └─ Travel Reduction : {saved_dist:.2f} mm (-{saved_pct:.1f}%)")
        self.log("="*55)

    def save_gcode(self):
        """Post-Processor untuk menerbitkan file G-code yang sudah dioptimasi."""
        if not self.last_optimized_points:
            self.log("[ERROR] Belum ada hasil optimasi yang bisa di-save!")
            return
            
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Optimized G-Code", "Optimized_Sculpfun.gcode", 
            "G-Code Files (*.gcode *.nc);;All Files (*)", options=options
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w') as f:
                alg_idx = self.combo_alg.currentIndex()
                alg_name = self.combo_alg.currentText().strip()
                f.write("(==================================================)\n")
                f.write("(       OPTIMIZED BY PCB-AWARE ENGINE v2.0         )\n")
                f.write(f"( Algorithm: {alg_name} )\n")
                f.write("(==================================================)\n")
                f.write("G21 (Units in mm)\n")
                f.write("G90 (Absolute Positioning)\n")
                
                # Jika bukan Algoritma 5, gunakan Hardcode M4 & F1000 lama
                if alg_idx != 4:
                    f.write("M4 (Enable Dynamic Laser Mode for GRBL $32=1)\n")
                    f.write("F1000 (Cutting Feedrate mm/min)\n\n")
                else:
                    f.write("\n") 

                for pt in self.last_optimized_points:
                    if pt.type == 0:
                        f.write(f"G00 X{pt.x:.3f} Y{pt.y:.3f}\n")
                    else:
                        if alg_idx == 4:
                            # Khusus Algoritma 5: Tarik state memori C++ secara dinamis
                            cmd = f"G01 X{pt.x:.3f} Y{pt.y:.3f}"
                            if hasattr(pt, 'm') and pt.m != -1: cmd += f" M{pt.m}"
                            if hasattr(pt, 's') and pt.s != -1.0: cmd += f" S{pt.s:.1f}"
                            if hasattr(pt, 'f') and pt.f != -1.0: cmd += f" F{pt.f:.1f}"
                            f.write(cmd + "\n")
                        else:
                            f.write(f"G01 X{pt.x:.3f} Y{pt.y:.3f}\n")

                f.write("\nM5 (Force Laser OFF)\n")
                f.write("G00 X0 Y0 (Return to Home)\n")
                f.write("M30 (End Program)\n")

            self.log(f"[SUCCESS] 💾 G-Code berhasil disimpan di: {file_path}")
        except Exception as e:
            self.log(f"[ERROR] Gagal menyimpan file: {str(e)}")

    def draw_points(self, points, title=""):
        self.ax.clear()
        if not points: return
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            if p2.type == 0:
                self.ax.plot([p1.x, p2.x], [p1.y, p2.y], color='red', linestyle='--', linewidth=0.8, alpha=0.6)
            else:
                self.ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#1f77b4', linewidth=1.5)
        self.ax.set_title(title, fontsize=10, fontweight='bold')
        self.ax.set_aspect('equal')
        self.ax.grid(True, linestyle=':', alpha=0.5)
        self.canvas.draw()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoLoadGCodeApp()
    window.show()
    sys.exit(app.exec_())