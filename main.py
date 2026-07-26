import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
    QWidget, QLabel, QPushButton, QComboBox, QFrame, QTextEdit,
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QDialogButtonBox,
    QSplitter
)
from PyQt5.QtCore import Qt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.lines import Line2D

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
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QFrame {
                    border: 2px dashed #2ecc71;
                    border-radius: 8px;
                    background-color: #e8f8f5;
                    padding: 10px;
                }
            """)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #3498db;
                border-radius: 8px;
                background-color: #ecf0f1;
                padding: 10px;
            }
        """)

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        urls = event.mimeData().urls()
        if urls:
            filepath = urls[0].toLocalFile()
            if filepath:
                self.callback_on_drop(filepath)
                event.acceptProposedAction()


# --- JENDELA SETTINGS MANUAL ALGORITHM ---
class AlgorithmSettingsDialog(QDialog):
    def __init__(self, alg_index, current_params, parent=None):
        super().__init__(parent)
        self.alg_index = alg_index
        self.params = current_params.copy()

        titles = [
            "Nearest Neighbor Settings",
            "2-Opt Local Search Settings",
            "Simulated Annealing Settings",
            "Genetic Algorithm (GA) Settings"
        ]
        self.setWindowTitle(titles[alg_index])
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        if alg_index == 0:  # Nearest Neighbor
            label = QLabel("Greedy strategy does not require hyperparameters.\nCalculations are strictly deterministic.")
            label.setWordWrap(True)
            form_layout.addRow(label)

        elif alg_index == 1:  # 2-Opt
            self.spin_max_iter = QSpinBox()
            self.spin_max_iter.setRange(10, 10000)
            self.spin_max_iter.setValue(self.params.get('2opt_max_iter', 1000))
            form_layout.addRow("Max Iterations:", self.spin_max_iter)

        elif alg_index == 2:  # Simulated Annealing
            self.spin_temp = QDoubleSpinBox()
            self.spin_temp.setRange(10.0, 100000.0)
            self.spin_temp.setValue(self.params.get('sa_temp', 1000.0))
            
            self.spin_cooling = QDoubleSpinBox()
            self.spin_cooling.setRange(0.800, 0.9999)
            self.spin_cooling.setDecimals(4)
            self.spin_cooling.setSingleStep(0.001)
            self.spin_cooling.setValue(self.params.get('sa_cooling', 0.995))

            self.spin_min_temp = QDoubleSpinBox()
            self.spin_min_temp.setRange(0.00001, 1.0)
            self.spin_min_temp.setDecimals(5)
            self.spin_min_temp.setValue(self.params.get('sa_min_temp', 0.001))

            form_layout.addRow("Initial Temp (T0):", self.spin_temp)
            form_layout.addRow("Cooling Rate (alpha):", self.spin_cooling)
            form_layout.addRow("Min Temp (Tmin):", self.spin_min_temp)

        elif alg_index == 3:  # Genetic Algorithm
            self.spin_pop = QSpinBox()
            self.spin_pop.setRange(10, 2000)
            self.spin_pop.setValue(self.params.get('ga_pop', 50))

            self.spin_gen = QSpinBox()
            self.spin_gen.setRange(10, 10000)
            self.spin_gen.setValue(self.params.get('ga_gen', 200))

            self.spin_mut = QDoubleSpinBox()
            self.spin_mut.setRange(0.01, 1.0)
            self.spin_mut.setDecimals(2)
            self.spin_mut.setSingleStep(0.05)
            self.spin_mut.setValue(self.params.get('ga_mut', 0.15))

            form_layout.addRow("Population Size:", self.spin_pop)
            form_layout.addRow("Generations:", self.spin_gen)
            form_layout.addRow("Mutation Rate:", self.spin_mut)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_updated_params(self):
        if self.alg_index == 1:
            self.params['2opt_max_iter'] = self.spin_max_iter.value()
        elif self.alg_index == 2:
            self.params['sa_temp'] = self.spin_temp.value()
            self.params['sa_cooling'] = self.spin_cooling.value()
            self.params['sa_min_temp'] = self.spin_min_temp.value()
        elif self.alg_index == 3:
            self.params['ga_pop'] = self.spin_pop.value()
            self.params['ga_gen'] = self.spin_gen.value()
            self.params['ga_mut'] = self.spin_mut.value()
        return self.params


# --- MAIN APPLICATION ---
class AutoLoadGCodeApp(QMainWindow):
    def __init__(self, default_gcode_path="cnc2.gcode"):
        super().__init__()
        self.setWindowTitle("C++ Driven Multi-Format CNC Path Optimizer")
        self.setGeometry(100, 100, 480, 640)

        self.engine = gcode_engine.GCodeOptimizer()
        self.current_filepath = ""

        # State parameter default
        self.alg_params = {
            '2opt_max_iter': 1000,
            'sa_temp': 1000.0,
            'sa_cooling': 0.995,
            'sa_min_temp': 0.001,
            'ga_pop': 50,
            'ga_gen': 200,
            'ga_mut': 0.15
        }

        # Main Central Layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        main_layout = QVBoxLayout(self.main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Create QSplitter Vertikal
        self.splitter = QSplitter(Qt.Vertical)
        
        # Styling Handle Splitter (garis pembatas yang bisa digeser)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #bdc3c7;
                height: 5px;
                margin: 2px 0px;
                border-radius: 2px;
            }
            QSplitter::handle:hover {
                background-color: #3498db;
            }
        """)

        # ==================== AREA ATAS ====================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Drag & Drop Zone
        self.drop_zone = DropZoneWidget(callback_on_drop=self.auto_load_file)
        top_layout.addWidget(self.drop_zone)

        # 2. Canvas Matplotlib
        self.figure, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.figure)
        top_layout.addWidget(self.canvas)

        # 3. Control Panel + Settings Button
        btn_layout = QHBoxLayout()

        self.combo_alg = QComboBox()
        self.combo_alg.addItems([
            " Nearest Neighbor",
            " 2-Opt Local Search",
            " Simulated Annealing",
            " Genetic Algorithm (GA)"
        ])
        self.combo_alg.setStyleSheet("padding: 6px; font-size: 12px;")
        btn_layout.addWidget(self.combo_alg, stretch=3)

        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setStyleSheet("""
            QPushButton {
                padding: 6px 12px; 
                font-weight: bold; 
                background-color: #34495e; 
                color: white; 
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2c3e50;
            }
        """)
        self.btn_settings.clicked.connect(self.open_algorithm_settings)
        btn_layout.addWidget(self.btn_settings, stretch=1)

        self.btn_start = QPushButton("Run")
        self.btn_start.setStyleSheet("padding: 8px; font-weight: bold; background-color: #27ae60; color: white;")
        self.btn_start.clicked.connect(self.run_optimization)
        btn_layout.addWidget(self.btn_start, stretch=2)

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setStyleSheet("padding: 8px; background-color: #e74c3c; color: white;")
        self.btn_reset.clicked.connect(self.reset_to_original)
        btn_layout.addWidget(self.btn_reset, stretch=2)

        top_layout.addLayout(btn_layout)

        # ==================== AREA BAWAH ====================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # 4. Console Log Terminal
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        bottom_layout.addWidget(self.log_console)

        # Tambahkan kedua widget ke QSplitter
        self.splitter.addWidget(top_widget)
        self.splitter.addWidget(bottom_widget)

        # Rasio awal ukuran (Area Atas: 600px, Console Bawah: 150px)
        self.splitter.setSizes([600, 150])

        # Masukkan Splitter ke Layout Utama Window
        main_layout.addWidget(self.splitter)

        if os.path.exists(default_gcode_path):
            self.auto_load_file(default_gcode_path)

    def log(self, text):
        self.log_console.append(text)

    def open_algorithm_settings(self):
        alg_idx = self.combo_alg.currentIndex()
        dialog = AlgorithmSettingsDialog(alg_idx, self.alg_params, self)
        if dialog.exec_() == QDialog.Accepted:
            self.alg_params = dialog.get_updated_params()
            self.log(f"[CONFIG UPDATED] Settings saved for {self.combo_alg.currentText()}")

    def apply_cpp_configs(self):
        alg_idx = self.combo_alg.currentIndex()
        if alg_idx == 1:
            if hasattr(self.engine, 'set2OptConfig'):
                self.engine.set2OptConfig(self.alg_params['2opt_max_iter'])
        elif alg_idx == 2:
            if hasattr(self.engine, 'setSAConfig'):
                self.engine.setSAConfig(
                    self.alg_params['sa_temp'], 
                    self.alg_params['sa_cooling'], 
                    self.alg_params['sa_min_temp']
                )
        elif alg_idx == 3:
            if hasattr(self.engine, 'setGAConfig'):
                self.engine.setGAConfig(
                    self.alg_params['ga_pop'], 
                    self.alg_params['ga_gen'], 
                    self.alg_params['ga_mut']
                )

    def auto_load_file(self, filepath):
        if not os.path.exists(filepath):
            self.log(f"[ERROR] File tidak ditemukan: {filepath}")
            return

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            self.log(f"[ERROR] Format file {ext} tidak didukung!")
            return

        self.current_filepath = filepath
        self.drop_zone.label.setText(f"FILE ACTIVE: {os.path.basename(filepath)}")
        
        self.engine.loadGCode(filepath)
        raw_points = self.engine.getRawPoints()
        
        self.draw_points(raw_points, title=f"Original Path ({os.path.basename(filepath)})")
        self.log(f"[FILE LOADED] {os.path.basename(filepath)} | Total Points: {len(raw_points)}")

    def run_optimization(self):
        if not self.current_filepath:
            self.log("[ERROR] Tidak ada file yang dimuat.")
            return
        
        algorithm_index = self.combo_alg.currentIndex()
        algorithm_name = self.combo_alg.currentText()
        
        self.apply_cpp_configs()

        report = self.engine.runWithReport(algorithm_index)
        optimized_points = self.engine.optimizePath(algorithm_index)
        
        self.draw_points(optimized_points, title=f"Optimized Path: {algorithm_name}")
        
        saved_dist = report.originalDistance - report.optimizedDistance
        saved_pct = (saved_dist / report.originalDistance * 100) if report.originalDistance > 0 else 0
        
        self.log("="*60)
        self.log(f"[C++ ENGINE EXECUTED] Algorithm: {algorithm_name}")
        if algorithm_index == 3:
            self.log(f"  ├─ GA Params        : Pop={self.alg_params['ga_pop']}, Gen={self.alg_params['ga_gen']}, Mut={self.alg_params['ga_mut']}")
        elif algorithm_index == 2:
            self.log(f"  ├─ SA Params        : T0={self.alg_params['sa_temp']}, Cooling={self.alg_params['sa_cooling']}")
        elif algorithm_index == 1:
            self.log(f"  ├─ 2-Opt Params     : MaxIter={self.alg_params['2opt_max_iter']}")
        self.log(f"  ├─ Contours Grouped : {report.contourCount} items")
        self.log(f"  ├─ C++ Execution    : {report.timeTakenMs:.4f} ms")
        self.log(f"  ├─ Initial G00 Dist : {report.originalDistance:.2f} mm")
        self.log(f"  ├─ Optimized Dist   : {report.optimizedDistance:.2f} mm")
        self.log(f"  └─ Travel Reduction : {saved_dist:.2f} mm (-{saved_pct:.1f}%)")
        self.log("="*60)

    def reset_to_original(self):
        if self.current_filepath:
            self.auto_load_file(self.current_filepath)

    def draw_points(self, points, title=""):
        self.ax.clear()
        if not points:
            self.canvas.draw()
            return

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            if p2.type == 0:
                self.ax.plot([p1.x, p2.x], [p1.y, p2.y], color='red', linestyle='--', linewidth=0.8, alpha=0.7)
            else:
                self.ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#1f77b4', linestyle='-', linewidth=1.5)

        self.ax.plot(points[0].x, points[0].y, 'go', markersize=6)

        #legend_elements = [
        #    Line2D([0], [0], color='#1f77b4', lw=1.5, label='Cutting Path (G01)'),
        #    Line2D([0], [0], color='red', lw=0.8, linestyle='--', label='Travel Path (G00)'),
        #    Line2D([0], [0], marker='o', color='w', label='Start Point', markerfacecolor='g', markersize=6)
        #]
        
        #self.ax.legend(handles=legend_elements, loc='upper right', fontsize=8)
        self.ax.set_title(title, fontsize=11, fontweight='bold')
        self.ax.set_aspect('equal')
        self.ax.grid(True, linestyle=':', alpha=0.6)
        self.canvas.draw()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoLoadGCodeApp(default_gcode_path="cnc2.gcode")
    window.show()
    sys.exit(app.exec_())
