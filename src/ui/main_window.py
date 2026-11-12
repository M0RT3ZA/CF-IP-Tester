from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.aggregator import Aggregator, SessionDatabase
from src.core.cdn_presets import (
    CDN_PRESETS,
    get_all_presets,
    get_combined_all_preset,
    get_preset,
    save_presets_to_directory,
)
from src.io.exporter import BenchmarkExporter, SortCriteria
from src.io.loader import TargetLoader
from src.models import AggregatedScore, ProbeResult, ProbeStatus, Target, TargetType
from src.ui.workers import BenchmarkWorker, FileLoaderWorker, IspDetectWorker


class NumericTableWidgetItem(QTableWidgetItem):
    """
    QTableWidgetItem specialization ensuring numeric sorting rather than lexicographical string comparison.
    """

    def __lt__(self, other: QTableWidgetItem) -> bool:
        v1 = self.data(Qt.ItemDataRole.UserRole)
        v2 = other.data(Qt.ItemDataRole.UserRole)
        if v1 is not None and v2 is not None:
            return float(v1) < float(v2)
        return super().__lt__(other)


class CopyableTableWidget(QTableWidget):
    """
    Enhanced QTableWidget supporting clipboard copying via Ctrl+C / Cmd+C
    for both single and multiple selections, as well as right-click context actions.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_C
        ):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self) -> None:
        selected_indexes = self.selectedIndexes()
        if not selected_indexes:
            return

        # Sort indexes by (row, column) to maintain exact tabular layout
        sorted_indexes = sorted(selected_indexes, key=lambda idx: (idx.row(), idx.column()))

        # Group cells by row
        rows_dict: dict[int, list[str]] = {}
        for idx in sorted_indexes:
            item = self.item(idx.row(), idx.column())
            text = item.text() if item else ""
            if idx.row() not in rows_dict:
                rows_dict[idx.row()] = []
            rows_dict[idx.row()].append(text)

        # Tab-separated columns and newline-separated rows
        lines = ["\t".join(cells) for cells in rows_dict.values()]
        full_text = "\n".join(lines)
        QApplication.clipboard().setText(full_text)

    def copy_endpoints_to_clipboard(self) -> None:
        """
        Extracts only the clean IP literal or domain from each selected row.
        """
        selected_rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        if not selected_rows:
            return

        endpoints: list[str] = []
        for row in selected_rows:
            item_ip = self.item(row, 1)
            item_target = self.item(row, 0)
            val_ip = item_ip.text().strip() if item_ip else ""
            val_target = item_target.text().strip() if item_target else ""
            endpoint = val_ip if val_ip and val_ip != "0.0.0.0" else val_target
            if endpoint:
                endpoints.append(endpoint)

        if endpoints:
            QApplication.clipboard().setText("\n".join(endpoints))

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)

        act_copy = menu.addAction("Copy Selected (Ctrl+C)")
        act_copy.triggered.connect(self.copy_selection_to_clipboard)

        act_copy_endpoints = menu.addAction("Copy IP / Domain Only")
        act_copy_endpoints.triggered.connect(self.copy_endpoints_to_clipboard)

        menu.addSeparator()

        act_select_all = menu.addAction("Select All (Ctrl+A)")
        act_select_all.triggered.connect(self.selectAll)

        menu.exec(self.viewport().mapToGlobal(pos))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CF IP Tester - Cloudflare Edge & Cross-ISP Benchmark Suite")
        self.resize(1240, 800)
        self.setMinimumSize(960, 600)

        self.db = SessionDatabase()
        self.loaded_targets: list[Target] = []
        self.current_results: list[ProbeResult] = []
        self.aggregated_scores: list[AggregatedScore] = []

        self.benchmark_worker: BenchmarkWorker | None = None
        self.isp_worker: IspDetectWorker | None = None
        self.loader_worker: FileLoaderWorker | None = None

        self._init_theme()
        self._init_ui()
        self._auto_discover_inputs()
        self._auto_detect_isp()

    def _init_theme(self) -> None:
        """
        Cross-platform dark engineering palette with high-contrast data rows and neutral accents.
        """
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #121418;
            }
            QWidget {
                color: #DCE1E8;
                font-family: 'Segoe UI', 'Roboto', 'Ubuntu', sans-serif;
                font-size: 13px;
            }
            QFrame#topControlFrame, QFrame#bottomControlFrame {
                background-color: #1A1D24;
                border: 1px solid #2B303C;
                border-radius: 6px;
            }
            QLabel {
                color: #9DA7B3;
                font-weight: 500;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #222630;
                border: 1px solid #363D4E;
                border-radius: 4px;
                padding: 4px 8px;
                color: #FFFFFF;
                selection-background-color: #2F54EB;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #4B70F5;
            }
            QPushButton {
                background-color: #262B36;
                border: 1px solid #3B4252;
                border-radius: 4px;
                padding: 5px 14px;
                color: #FFFFFF;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #313745;
                border: 1px solid #4C566A;
            }
            QPushButton:pressed {
                background-color: #1E222B;
            }
            QPushButton#primaryBtn {
                background-color: #1D39C4;
                border: 1px solid #2F54EB;
            }
            QPushButton#primaryBtn:hover {
                background-color: #2F54EB;
            }
            QPushButton#pauseBtn {
                background-color: #D48806;
                border: 1px solid #FAAD14;
            }
            QPushButton#pauseBtn:hover {
                background-color: #E09612;
            }
            QPushButton#abortBtn {
                background-color: #A8071A;
                border: 1px solid #CF1322;
            }
            QPushButton#abortBtn:hover {
                background-color: #CF1322;
            }
            QTabWidget::pane {
                border: 1px solid #2B303C;
                background-color: #171A21;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #1A1D24;
                color: #8C96A5;
                padding: 8px 18px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background-color: #171A21;
                color: #597EF7;
                border-bottom: 2px solid #597EF7;
            }
            QTableWidget {
                background-color: #171A21;
                alternate-background-color: #1C2029;
                gridline-color: #252A36;
                border: none;
                selection-background-color: #263859;
                selection-color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #1F242E;
                color: #A6B1C2;
                padding: 6px;
                border: 1px solid #282E3D;
                font-weight: 600;
            }
            QProgressBar {
                background-color: #222630;
                border: 1px solid #363D4E;
                border-radius: 4px;
                text-align: center;
                color: #FFFFFF;
                font-weight: 600;
            }
            QProgressBar::chunk {
                background-color: #2F54EB;
                border-radius: 3px;
            }
            QMenu {
                background-color: #1F242E;
                border: 1px solid #363D4E;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                color: #DCE1E8;
            }
            QMenu::item:selected {
                background-color: #2F54EB;
                color: #FFFFFF;
            }
            """
        )

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Top Control Bar
        top_frame = QFrame()
        top_frame.setObjectName("topControlFrame")
        top_layout = QVBoxLayout(top_frame)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(8)

        # Row 1: Target Ingestion & ISP Controls
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(8)

        self.btn_load_folder = QPushButton("Scan inputs/ Dir")
        self.btn_load_folder.clicked.connect(self._auto_discover_inputs)
        row1_layout.addWidget(self.btn_load_folder)

        self.btn_browse_files = QPushButton("Browse Files...")
        self.btn_browse_files.clicked.connect(self._on_browse_files)
        row1_layout.addWidget(self.btn_browse_files)

        self.btn_cdn_presets = QPushButton("CDN Presets ▼")
        self.btn_cdn_presets.setToolTip("Quick-load curated clean IP presets for Cloudflare, CloudFront, Fastly, Google, Azure, and Gcore.")
        self.btn_cdn_presets.setMenu(self._build_cdn_presets_menu())
        row1_layout.addWidget(self.btn_cdn_presets)

        self.lbl_targets_info = QLabel("Targets: 0 loaded")
        self.lbl_targets_info.setStyleSheet("color: #40A9FF; font-weight: bold;")
        row1_layout.addWidget(self.lbl_targets_info)

        row1_layout.addSpacing(16)

        row1_layout.addWidget(QLabel("Operator:"))
        self.txt_operator = QLineEdit()
        self.txt_operator.setPlaceholderText("e.g. Irancell, MCI, Shatel, TCI")
        self.txt_operator.setMinimumWidth(180)
        row1_layout.addWidget(self.txt_operator)

        self.btn_detect_isp = QPushButton("Auto-Detect ISP")
        self.btn_detect_isp.clicked.connect(self._auto_detect_isp)
        row1_layout.addWidget(self.btn_detect_isp)

        self.lbl_isp_meta = QLabel("")
        self.lbl_isp_meta.setStyleSheet("color: #8C96A5; font-size: 11px;")
        row1_layout.addWidget(self.lbl_isp_meta)

        row1_layout.addStretch()
        top_layout.addLayout(row1_layout)

        # Row 2: Benchmark Parameters & Sorting Selection
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(8)

        row2_layout.addWidget(QLabel("Concurrency:"))
        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 16)
        self.spin_concurrency.setValue(4)
        self.spin_concurrency.setToolTip(
            "Worker count for parallel probes. Default 4 prevents saturating host uplink."
        )
        row2_layout.addWidget(self.spin_concurrency)

        row2_layout.addSpacing(12)
        row2_layout.addWidget(QLabel("Payload:"))
        self.combo_payload = QComboBox()
        self.combo_payload.addItem("1 MB Payload", 1_000_000)
        self.combo_payload.addItem("5 MB Payload (Default)", 5_000_000)
        self.combo_payload.addItem("10 MB Payload", 10_000_000)
        self.combo_payload.setCurrentIndex(1)
        row2_layout.addWidget(self.combo_payload)

        row2_layout.addSpacing(12)
        row2_layout.addWidget(QLabel("Timeout (s):"))
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(3, 30)
        self.spin_timeout.setValue(7)
        row2_layout.addWidget(self.spin_timeout)

        row2_layout.addSpacing(12)
        row2_layout.addWidget(QLabel("Sort By:"))
        self.combo_sort = QComboBox()
        self.combo_sort.addItem("Fastest Download Speed First", SortCriteria.SPEED_FIRST)
        self.combo_sort.addItem("Lowest Ping First", SortCriteria.PING_FIRST)
        self.combo_sort.addItem("Best Universal Cross-ISP Score", SortCriteria.UNIVERSAL_SCORE)
        self.combo_sort.addItem("Target Services Viability (TG/YT/IG/X)", SortCriteria.SERVICES_FIRST)
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        row2_layout.addWidget(self.combo_sort)

        row2_layout.addSpacing(12)
        row2_layout.addWidget(QLabel("SNI / Host:"))
        self.txt_sni = QLineEdit()
        self.txt_sni.setText("speed.cloudflare.com")
        self.txt_sni.setPlaceholderText("speed.cloudflare.com or your proxy domain/SNI")
        self.txt_sni.setMinimumWidth(200)
        self.txt_sni.setToolTip(
            "TLS SNI and HTTP Host header sent during handshake and throughput test.\n"
            "Matches your Workers/Pages/CloudFront/Fastly domain or default CDN endpoint."
        )
        row2_layout.addWidget(self.txt_sni)

        row2_layout.addSpacing(12)
        self.chk_audit_services = QCheckBox("Audit Services (TG/YT/IG/X)")
        self.chk_audit_services.setChecked(True)
        self.chk_audit_services.setStyleSheet("color: #FAAD14; font-weight: bold;")
        self.chk_audit_services.setToolTip(
            "Actively checks application-layer reachability for Telegram, YouTube (204 No-Content),\n"
            "Instagram (Meta), and X (Twitter) to identify endpoints that work seamlessly across platforms."
        )
        row2_layout.addWidget(self.chk_audit_services)

        row2_layout.addStretch()
        top_layout.addLayout(row2_layout)
        main_layout.addWidget(top_frame)

        # 2. Main Tabbed Split View
        self.tab_widget = QTabWidget()
        self.tab_live = QWidget()
        self.tab_matrix = QWidget()
        self.tab_widget.addTab(self.tab_live, "Live Operator Test")
        self.tab_widget.addTab(self.tab_matrix, "Cross-ISP Comparison Matrix")
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Live Tab Layout
        live_layout = QVBoxLayout(self.tab_live)
        live_layout.setContentsMargins(4, 4, 4, 4)
        self.table_live = CopyableTableWidget()
        self.table_live.setAlternatingRowColors(True)
        self.table_live.setSortingEnabled(True)
        self.table_live.setColumnCount(12)
        self.table_live.setHorizontalHeaderLabels(
            [
                "Target",
                "Resolved IP",
                "CDN",
                "Location",
                "Type",
                "Operator",
                "Ping (ms)",
                "Speed (Mbps)",
                "Jitter (ms)",
                "Loss (%)",
                "Services (TG/YT/IG/X)",
                "Status",
            ]
        )
        self.table_live.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_live.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_live.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_live.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        self.table_live.setColumnWidth(0, 170)
        self.table_live.setColumnWidth(1, 150)
        self.table_live.setColumnWidth(2, 90)
        self.table_live.setColumnWidth(3, 165)
        self.table_live.setColumnWidth(4, 65)
        self.table_live.setColumnWidth(5, 105)
        self.table_live.setColumnWidth(6, 85)
        self.table_live.setColumnWidth(7, 105)
        self.table_live.setColumnWidth(8, 85)
        self.table_live.setColumnWidth(9, 75)
        self.table_live.setColumnWidth(10, 170)
        live_layout.addWidget(self.table_live)

        # Cross-ISP Matrix Tab Layout
        matrix_layout = QVBoxLayout(self.tab_matrix)
        matrix_layout.setContentsMargins(4, 4, 4, 4)

        matrix_top_bar = QHBoxLayout()
        self.lbl_matrix_info = QLabel("Comparison across all operators in data/sessions.db")
        matrix_top_bar.addWidget(self.lbl_matrix_info)
        matrix_top_bar.addStretch()

        self.btn_refresh_matrix = QPushButton("Refresh Matrix")
        self.btn_refresh_matrix.clicked.connect(self._refresh_matrix_view)
        matrix_top_bar.addWidget(self.btn_refresh_matrix)

        self.btn_clear_db = QPushButton("Reset DB History")
        self.btn_clear_db.clicked.connect(self._on_clear_db)
        matrix_top_bar.addWidget(self.btn_clear_db)

        matrix_layout.addLayout(matrix_top_bar)

        self.table_matrix = CopyableTableWidget()
        self.table_matrix.setAlternatingRowColors(True)
        self.table_matrix.setSortingEnabled(True)
        matrix_layout.addWidget(self.table_matrix)

        main_layout.addWidget(self.tab_widget, stretch=1)

        # 3. Bottom Execution & Export Bar
        bottom_frame = QFrame()
        bottom_frame.setObjectName("bottomControlFrame")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(10, 8, 10, 8)
        bottom_layout.setSpacing(10)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setMinimumWidth(220)
        bottom_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        bottom_layout.addWidget(self.progress_bar, stretch=1)

        self.lbl_speed_gauge = QLabel("Throughput: 0.0 Mbps")
        self.lbl_speed_gauge.setStyleSheet("color: #52C41A; font-weight: bold; min-width: 170px;")
        bottom_layout.addWidget(self.lbl_speed_gauge)

        bottom_layout.addSpacing(8)

        self.btn_start = QPushButton("Start Benchmark")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.clicked.connect(self._on_start_clicked)
        bottom_layout.addWidget(self.btn_start)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("pauseBtn")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        bottom_layout.addWidget(self.btn_pause)

        self.btn_abort = QPushButton("Abort")
        self.btn_abort.setObjectName("abortBtn")
        self.btn_abort.setEnabled(False)
        self.btn_abort.clicked.connect(self._on_abort_clicked)
        bottom_layout.addWidget(self.btn_abort)

        self.btn_export = QPushButton("Export Results")
        self.btn_export.setMenu(self._create_export_menu())
        bottom_layout.addWidget(self.btn_export)

        main_layout.addWidget(bottom_frame)

    def _create_export_menu(self) -> QMenu:
        menu = QMenu(self)
        act_txt = menu.addAction("Clean Proxy Panel List (.txt)")
        act_txt.triggered.connect(lambda: self._export_file("txt"))

        act_csv = menu.addAction("Structured Data (.csv)")
        act_csv.triggered.connect(lambda: self._export_file("csv"))

        act_xlsx = menu.addAction("Excel Spreadsheet (.xlsx)")
        act_xlsx.triggered.connect(lambda: self._export_file("xlsx"))

        act_xls = menu.addAction("Legacy Excel (.xls)")
        act_xls.triggered.connect(lambda: self._export_file("xls"))

        act_sqlite = menu.addAction("SQLite Database (.sqlite)")
        act_sqlite.triggered.connect(lambda: self._export_file("sqlite"))

        return menu

    def _build_cdn_presets_menu(self) -> QMenu:
        menu = QMenu(self)

        for preset in get_all_presets():
            act = menu.addAction(f"{preset.name} ({len(preset.endpoints)} IPs)")
            act.triggered.connect(lambda checked=False, k=preset.key: self._load_cdn_preset(k))

        menu.addSeparator()

        act_all = menu.addAction("All Major CDNs Combined")
        act_all.triggered.connect(lambda: self._load_cdn_preset("all_combined"))

        menu.addSeparator()

        act_gen = menu.addAction("Export All Presets into inputs/ Directory")
        act_gen.triggered.connect(self._on_export_presets_to_inputs)

        return menu

    def _load_cdn_preset(self, preset_key: str) -> None:
        if preset_key == "all_combined":
            preset = get_combined_all_preset()
        else:
            preset = get_preset(preset_key)

        if not preset:
            return

        targets: list[Target] = []
        for ep in preset.endpoints:
            t = Target.from_string(ep, source_file=f"preset:{preset.name}")
            if t:
                targets.append(t)

        self.loaded_targets = targets
        self.txt_sni.setText(preset.default_sni)
        self.lbl_targets_info.setText(f"Targets: {len(targets)} loaded ({preset.name})")
        self.lbl_status.setText(
            f"Loaded {len(targets)} clean IPs for {preset.name}. Default SNI set to {preset.default_sni}."
        )

    def _on_export_presets_to_inputs(self) -> None:
        generated = save_presets_to_directory("inputs")
        self.lbl_status.setText(f"Saved {len(generated)} preset files to inputs/ directory.")
        QMessageBox.information(
            self,
            "Presets Generated",
            f"Successfully created {len(generated)} preset files in inputs/ directory:\n\n"
            + "\n".join(f"- {p.name}" for p in generated)
            + "\n\nYou can now test them individually or click 'Scan inputs/ Dir'.",
        )

    def _auto_discover_inputs(self) -> None:
        inputs_dir = Path("inputs")
        if not inputs_dir.exists():
            inputs_dir.mkdir(parents=True, exist_ok=True)

        self.lbl_status.setText("Scanning inputs/ directory...")
        self.loader_worker = FileLoaderWorker(folder_path=inputs_dir, parent=self)
        self.loader_worker.loaded.connect(self._on_targets_loaded)
        self.loader_worker.start()

    def _on_browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Target Files",
            "",
            "All Supported (*.txt *.csv *.xlsx *.xls *.sqlite *.db);;Text Files (*.txt);;CSV Files (*.csv);;Spreadsheets (*.xlsx *.xls);;SQLite (*.sqlite *.db)",
        )
        if files:
            paths = [Path(f) for f in files]
            self.lbl_status.setText(f"Loading {len(paths)} file(s)...")
            self.loader_worker = FileLoaderWorker(file_paths=paths, parent=self)
            self.loader_worker.loaded.connect(self._on_targets_loaded)
            self.loader_worker.start()

    def _on_targets_loaded(self, targets: list[Target], sources: list[str]) -> None:
        self.loaded_targets = targets
        src_info = f"({', '.join(sources)})" if sources else ""
        self.lbl_targets_info.setText(f"Targets: {len(targets)} loaded {src_info}")
        self.lbl_status.setText(f"Ready. Loaded {len(targets)} targets from {len(sources)} source(s).")

    def _auto_detect_isp(self) -> None:
        self.btn_detect_isp.setEnabled(False)
        self.lbl_isp_meta.setText("Querying ISP metadata...")
        self.isp_worker = IspDetectWorker(parent=self)
        self.isp_worker.detected.connect(self._on_isp_detected)
        self.isp_worker.failed.connect(self._on_isp_failed)
        self.isp_worker.start()

    def _on_isp_detected(self, info: dict) -> None:
        self.btn_detect_isp.setEnabled(True)
        detected_isp = info.get("isp", "Unknown")
        asn = info.get("asn", "")
        ip = info.get("ip", "")
        is_vpn = info.get("is_vpn_or_dc", False)

        if detected_isp != "Unknown":
            self.txt_operator.setText(detected_isp)

        if is_vpn:
            self.lbl_isp_meta.setText(f"IP: {ip} | ASN: {asn} [WARNING: VPN/Proxy Active]")
            self.lbl_isp_meta.setStyleSheet("color: #FF7875; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_isp_meta.setText(f"IP: {ip} | ASN: {asn}")
            self.lbl_isp_meta.setStyleSheet("color: #8C96A5; font-size: 11px;")

    def _on_isp_failed(self, err_msg: str) -> None:
        self.btn_detect_isp.setEnabled(True)
        self.lbl_isp_meta.setText("ISP lookup failed (set manually)")
        self.lbl_isp_meta.setStyleSheet("color: #FAAD14; font-size: 11px;")

    def _on_start_clicked(self) -> None:
        if not self.loaded_targets:
            QMessageBox.warning(
                self,
                "No Targets Loaded",
                "Please load targets via 'Scan inputs/ Dir' or 'Browse Files...'",
            )
            return

        # Pre-flight check: Always query current ISP before initiating benchmark
        self.btn_start.setEnabled(False)
        self.lbl_status.setText("Checking and updating active ISP metadata...")
        self.lbl_isp_meta.setText("Verifying current network...")

        self.isp_worker = IspDetectWorker(parent=self)
        self.isp_worker.detected.connect(self._on_preflight_isp_detected)
        self.isp_worker.failed.connect(self._on_preflight_isp_failed)
        self.isp_worker.start()

    def _on_preflight_isp_detected(self, info: dict) -> None:
        self._on_isp_detected(info)

        detected_isp = info.get("isp", "Unknown")
        is_vpn = info.get("is_vpn_or_dc", False)
        org = info.get("org", "") or detected_isp

        if is_vpn:
            reply = QMessageBox.warning(
                self,
                "VPN / Proxy Detected",
                f"Warning: An active VPN, Proxy, or Datacenter tunnel was detected:\n\n"
                f"  Detected Provider: {org}\n"
                f"  IP: {info.get('ip', '')} | ASN: {info.get('asn', '')}\n\n"
                "Benchmarking through an active VPN distorts operator latency and bypasses "
                "ISP throttling. For authentic cross-ISP testing, disable your VPN.\n\n"
                "Do you still want to proceed with this test session?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.btn_start.setEnabled(True)
                self.lbl_status.setText("Benchmark cancelled. Please disable VPN and try again.")
                return

        self._start_benchmark_execution()

    def _on_preflight_isp_failed(self, err_msg: str) -> None:
        self._on_isp_failed(err_msg)
        operator_name = self.txt_operator.text().strip()
        if not operator_name or operator_name.lower() in ("default-isp", "unknown"):
            reply = QMessageBox.question(
                self,
                "Unidentified Network Operator",
                "Failed to auto-detect your ISP and no custom operator name is set.\n\n"
                "Do you want to proceed using 'Default-ISP' as the operator tag?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.btn_start.setEnabled(True)
                self.lbl_status.setText("Benchmark cancelled. Please specify your operator name.")
                return

        self._start_benchmark_execution()

    def _start_benchmark_execution(self) -> None:
        operator_name = self.txt_operator.text().strip()
        if not operator_name:
            operator_name = "Default-ISP"
            self.txt_operator.setText(operator_name)

        # Prepare UI for live execution
        self.current_results.clear()
        self.table_live.setRowCount(0)
        self.progress_bar.setValue(0)
        self.lbl_speed_gauge.setText("Throughput: 0.0 Mbps")

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("Pause")
        self.btn_abort.setEnabled(True)
        self.btn_load_folder.setEnabled(False)
        self.btn_browse_files.setEnabled(False)
        self.btn_cdn_presets.setEnabled(False)

        payload_bytes = self.combo_payload.currentData()
        timeout_s = self.spin_timeout.value()
        concurrency = self.spin_concurrency.value()
        sni_host = self.txt_sni.text().strip() or "speed.cloudflare.com"

        # Auto-configure download test path according to target endpoint
        if "cloudflare.com" in sni_host:
            download_path = "/__down?bytes={bytes}"
        else:
            download_path = "/"

        self.benchmark_worker = BenchmarkWorker(
            targets=self.loaded_targets,
            operator_name=operator_name,
            concurrency=concurrency,
            payload_bytes=payload_bytes,
            download_timeout_s=float(timeout_s),
            sni_host=sni_host,
            download_path=download_path,
            audit_services=self.chk_audit_services.isChecked(),
            parent=self,
        )

        self.benchmark_worker.target_started.connect(self._on_target_started)
        self.benchmark_worker.result_ready.connect(self._on_result_ready)
        self.benchmark_worker.progress_updated.connect(self._on_progress_updated)
        self.benchmark_worker.throughput_sample.connect(self._on_throughput_sample)
        self.benchmark_worker.finished.connect(self._on_benchmark_finished)
        self.benchmark_worker.aborted.connect(self._on_benchmark_aborted)

        # Record test run in local SQLite database
        self.db.create_run(
            run_id=self.benchmark_worker._run_id,
            operator_name=operator_name,
            target_count=len(self.loaded_targets),
        )

        self.lbl_status.setText(f"Testing {len(self.loaded_targets)} targets on [{operator_name}]...")
        self.benchmark_worker.start()

    def _on_pause_clicked(self) -> None:
        if not self.benchmark_worker:
            return

        if self.benchmark_worker.is_paused:
            self.benchmark_worker.resume()
            self.btn_pause.setText("Pause")
            self.lbl_status.setText("Benchmark resumed.")
        else:
            self.benchmark_worker.pause()
            self.btn_pause.setText("Resume")
            self.lbl_status.setText("Benchmark paused.")

    def _on_abort_clicked(self) -> None:
        if self.benchmark_worker:
            self.lbl_status.setText("Aborting benchmark...")
            self.btn_abort.setEnabled(False)
            self.benchmark_worker.abort()

    def _on_target_started(self, host: str) -> None:
        self.lbl_status.setText(f"Probing: {host}...")

    def _on_result_ready(self, result: ProbeResult) -> None:
        self.current_results.append(result)
        self._insert_live_row(result)

    def _insert_live_row(self, r: ProbeResult) -> None:
        row = self.table_live.rowCount()
        self.table_live.insertRow(row)

        item_target = QTableWidgetItem(r.target.host)
        item_ip = QTableWidgetItem(r.resolved_ip)

        item_cdn = QTableWidgetItem(r.cdn_name or "Custom")
        item_cdn.setForeground(QColor("#40A9FF"))
        item_cdn.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        item_loc = QTableWidgetItem(r.location or "Unknown")
        item_loc.setForeground(QColor("#B5F5EC") if r.location and r.location != "Unknown" else QColor("#8C96A5"))
        item_loc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        item_type = QTableWidgetItem(getattr(r.target.target_type, "value", str(r.target.target_type)))
        item_op = QTableWidgetItem(r.operator_name)

        item_ping = NumericTableWidgetItem(f"{r.ping_ms:.2f}" if r.ping_ms > 0 else "TIMEOUT")
        item_ping.setData(Qt.ItemDataRole.UserRole, r.ping_ms if r.ping_ms > 0 else 9999.0)

        item_speed = NumericTableWidgetItem(f"{r.download_mbps:.2f}")
        item_speed.setData(Qt.ItemDataRole.UserRole, r.download_mbps)

        item_jitter = NumericTableWidgetItem(f"{r.jitter_ms:.2f}")
        item_jitter.setData(Qt.ItemDataRole.UserRole, r.jitter_ms)

        item_loss = NumericTableWidgetItem(f"{r.packet_loss_pct:.1f}%")
        item_loss.setData(Qt.ItemDataRole.UserRole, r.packet_loss_pct)

        item_services = NumericTableWidgetItem(r.services_badges or "-- -- -- -")
        item_services.setData(Qt.ItemDataRole.UserRole, r.services_passed)
        item_services.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if r.services_passed == 4:
            item_services.setForeground(QColor("#52C41A"))
        elif r.services_passed >= 2:
            item_services.setForeground(QColor("#FAAD14"))
        elif r.services_passed > 0:
            item_services.setForeground(QColor("#FF7875"))
        else:
            item_services.setForeground(QColor("#595959"))

        item_status = QTableWidgetItem(getattr(r.status, "value", str(r.status)))

        # Apply functional color-coding based on probe outcome
        if r.status == ProbeStatus.SUCCESS or getattr(r.status, "value", str(r.status)) == "SUCCESS":
            item_status.setForeground(QColor("#52C41A"))
            item_speed.setForeground(QColor("#52C41A"))
        elif r.status in (ProbeStatus.TIMEOUT, ProbeStatus.BLOCKED) or str(r.status) in ("TIMEOUT", "BLOCKED"):
            item_status.setForeground(QColor("#F5222D"))
        elif r.status == ProbeStatus.UNREACHABLE or str(r.status) == "UNREACHABLE":
            item_status.setForeground(QColor("#FAAD14"))
        else:
            item_status.setForeground(QColor("#8C96A5"))

        self.table_live.setItem(row, 0, item_target)
        self.table_live.setItem(row, 1, item_ip)
        self.table_live.setItem(row, 2, item_cdn)
        self.table_live.setItem(row, 3, item_loc)
        self.table_live.setItem(row, 4, item_type)
        self.table_live.setItem(row, 5, item_op)
        self.table_live.setItem(row, 6, item_ping)
        self.table_live.setItem(row, 7, item_speed)
        self.table_live.setItem(row, 8, item_jitter)
        self.table_live.setItem(row, 9, item_loss)
        self.table_live.setItem(row, 10, item_services)
        self.table_live.setItem(row, 11, item_status)

        # Auto-scroll to latest inserted row during active benchmark
        self.table_live.scrollToBottom()

    def _on_progress_updated(self, current: int, total: int) -> None:
        pct = int((current / max(total, 1)) * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{current} / {total} ({pct}%)")

    def _on_throughput_sample(self, speed_mbps: float) -> None:
        self.lbl_speed_gauge.setText(f"Throughput: {speed_mbps:.2f} Mbps")

    def _on_benchmark_finished(self, results: list[ProbeResult], run_id: str) -> None:
        success_count = sum(1 for r in results if r.status == ProbeStatus.SUCCESS)
        self.db.save_probe_results(run_id, results)
        self.db.complete_run(run_id, success_count)

        self._reset_controls()
        self.lbl_status.setText(
            f"Finished. {success_count}/{len(results)} endpoints reachable on [{self.txt_operator.text()}]."
        )
        self._refresh_matrix_view()

    def _on_benchmark_aborted(self) -> None:
        self._reset_controls()
        self.lbl_status.setText("Benchmark aborted by user.")
        self._refresh_matrix_view()

    def _reset_controls(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_abort.setEnabled(False)
        self.btn_load_folder.setEnabled(True)
        self.btn_browse_files.setEnabled(True)
        self.btn_cdn_presets.setEnabled(True)

    def _on_sort_changed(self) -> None:
        criteria: SortCriteria = self.combo_sort.currentData()
        if self.tab_widget.currentIndex() == 0:
            # Sort live table: col 7 is speed, col 6 is ping, col 10 is services
            if criteria == SortCriteria.PING_FIRST or str(criteria) == "PING_FIRST":
                self.table_live.sortItems(6, Qt.SortOrder.AscendingOrder)
            elif criteria == SortCriteria.SERVICES_FIRST or str(criteria) == "SERVICES_FIRST":
                self.table_live.sortItems(10, Qt.SortOrder.DescendingOrder)
            else:
                self.table_live.sortItems(7, Qt.SortOrder.DescendingOrder)
        else:
            self._refresh_matrix_view()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_matrix_view()

    def _refresh_matrix_view(self) -> None:
        """
        Builds the consolidated cross-ISP comparison matrix across all historic sessions.
        Highlights endpoints that pass on 100% of tested ISPs and aligns table sorting with criteria.
        """
        all_results = self.db.get_all_latest_results()
        if not all_results:
            self.table_matrix.setRowCount(0)
            self.table_matrix.setColumnCount(0)
            self.lbl_matrix_info.setText("No test sessions recorded yet in data/sessions.db.")
            return

        operators = self.db.get_all_tested_operators()
        self.aggregated_scores = Aggregator.compute_cross_isp_scores(all_results)
        criteria: SortCriteria = self.combo_sort.currentData()
        sorted_scores = BenchmarkExporter.sort_aggregated_scores(
            self.aggregated_scores, criteria
        )

        total_isps = len(operators)
        self.lbl_matrix_info.setText(
            f"Compared across {total_isps} operator(s): {', '.join(operators)}"
        )

        # Build dynamic columns: Fixed base metrics + one column per operator
        base_headers = [
            "Target",
            "Resolved IP",
            "CDN",
            "Location",
            "Type",
            "Coverage",
            "Services (TG/YT/IG/X)",
            "Min Speed (Mbps)",
            "Harmonic Speed (Mbps)",
            "Avg Ping (ms)",
            "Universal Score",
        ]
        all_headers = base_headers + [f"ISP: {op}" for op in operators]

        self.table_matrix.setSortingEnabled(False)
        self.table_matrix.setColumnCount(len(all_headers))
        self.table_matrix.setHorizontalHeaderLabels(all_headers)
        self.table_matrix.setRowCount(len(sorted_scores))

        # Build lookup table for fast per-operator result binding
        op_lookup: dict[tuple[str, str, str], ProbeResult] = {}
        for r in all_results:
            op_lookup[(r.target.host, r.resolved_ip, r.operator_name)] = r

        for row, s in enumerate(sorted_scores):
            is_universal_winner = s.successful_isps_count == total_isps and total_isps > 0

            item_target = QTableWidgetItem(s.target_repr)
            item_ip = QTableWidgetItem(s.resolved_ip)

            item_cdn = QTableWidgetItem(s.cdn_name or "Custom")
            item_cdn.setForeground(QColor("#40A9FF"))
            item_cdn.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_loc = QTableWidgetItem(s.location or "Unknown")
            item_loc.setForeground(QColor("#B5F5EC") if s.location and s.location != "Unknown" else QColor("#8C96A5"))
            item_loc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_type = QTableWidgetItem(s.ip_version)

            item_cov = NumericTableWidgetItem(s.isp_coverage)
            item_cov.setData(Qt.ItemDataRole.UserRole, s.successful_isps_count)

            item_services = NumericTableWidgetItem(s.services_badges or "-- -- -- -")
            item_services.setData(Qt.ItemDataRole.UserRole, s.services_passed)
            item_services.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if s.services_passed == 4:
                item_services.setForeground(QColor("#52C41A"))
            elif s.services_passed >= 2:
                item_services.setForeground(QColor("#FAAD14"))
            elif s.services_passed > 0:
                item_services.setForeground(QColor("#FF7875"))
            else:
                item_services.setForeground(QColor("#595959"))

            item_min_spd = NumericTableWidgetItem(f"{s.min_speed_mbps:.2f}")
            item_min_spd.setData(Qt.ItemDataRole.UserRole, s.min_speed_mbps)

            item_harm_spd = NumericTableWidgetItem(f"{s.harmonic_mean_speed_mbps:.2f}")
            item_harm_spd.setData(Qt.ItemDataRole.UserRole, s.harmonic_mean_speed_mbps)

            item_ping = NumericTableWidgetItem(f"{s.avg_ping_ms:.2f}" if s.avg_ping_ms < 9000 else "N/A")
            item_ping.setData(Qt.ItemDataRole.UserRole, s.avg_ping_ms)

            item_score = NumericTableWidgetItem(f"{s.universal_score:.2f}")
            item_score.setData(Qt.ItemDataRole.UserRole, s.universal_score)

            if is_universal_winner:
                # Highlight universal champions with gold accent
                highlight_brush = QColor("#FAAD14")
                item_cov.setForeground(QColor("#52C41A"))
                item_score.setForeground(highlight_brush)
                item_target.setForeground(highlight_brush)

            self.table_matrix.setItem(row, 0, item_target)
            self.table_matrix.setItem(row, 1, item_ip)
            self.table_matrix.setItem(row, 2, item_cdn)
            self.table_matrix.setItem(row, 3, item_loc)
            self.table_matrix.setItem(row, 4, item_type)
            self.table_matrix.setItem(row, 5, item_cov)
            self.table_matrix.setItem(row, 6, item_services)
            self.table_matrix.setItem(row, 7, item_min_spd)
            self.table_matrix.setItem(row, 8, item_harm_spd)
            self.table_matrix.setItem(row, 9, item_ping)
            self.table_matrix.setItem(row, 10, item_score)

            # Populate dynamic per-operator result columns
            for col_idx, op in enumerate(operators, start=len(base_headers)):
                probe = op_lookup.get((s.target_repr, s.resolved_ip, op))
                if probe:
                    if probe.status == ProbeStatus.SUCCESS or getattr(probe.status, "value", str(probe.status)) == "SUCCESS":
                        txt = f"{probe.download_mbps:.1f} Mbps ({probe.ping_ms:.0f}ms)"
                        item_op_res = NumericTableWidgetItem(txt)
                        item_op_res.setData(Qt.ItemDataRole.UserRole, probe.download_mbps)
                        item_op_res.setForeground(QColor("#52C41A"))
                    else:
                        status_str = getattr(probe.status, "value", str(probe.status))
                        item_op_res = NumericTableWidgetItem(status_str)
                        item_op_res.setData(Qt.ItemDataRole.UserRole, 0.0)
                        item_op_res.setForeground(QColor("#F5222D"))
                else:
                    item_op_res = NumericTableWidgetItem("Not Tested")
                    item_op_res.setData(Qt.ItemDataRole.UserRole, -1.0)
                    item_op_res.setForeground(QColor("#595959"))

                self.table_matrix.setItem(row, col_idx, item_op_res)

        self.table_matrix.setSortingEnabled(True)

        # Ensure table column visual sort indicator matches chosen criteria
        if criteria == SortCriteria.SPEED_FIRST or str(criteria) == "SPEED_FIRST":
            self.table_matrix.sortItems(8, Qt.SortOrder.DescendingOrder)
        elif criteria == SortCriteria.PING_FIRST or str(criteria) == "PING_FIRST":
            self.table_matrix.sortItems(9, Qt.SortOrder.AscendingOrder)
        elif criteria == SortCriteria.SERVICES_FIRST or str(criteria) == "SERVICES_FIRST":
            self.table_matrix.sortItems(6, Qt.SortOrder.DescendingOrder)
        else:
            self.table_matrix.sortItems(10, Qt.SortOrder.DescendingOrder)

    def _on_clear_db(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Database History",
            "Are you sure you want to clear all recorded test runs in data/sessions.db?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_database()
            self._refresh_matrix_view()
            self.lbl_status.setText("Database history cleared.")

    def _export_file(self, fmt: str) -> None:
        is_matrix_tab = self.tab_widget.currentIndex() == 1
        all_latest = self.db.get_all_latest_results()
        aggregated = Aggregator.compute_cross_isp_scores(all_latest)

        raw_criteria = self.combo_sort.currentData()
        try:
            criteria = SortCriteria(raw_criteria) if raw_criteria else SortCriteria.SPEED_FIRST
        except (ValueError, TypeError):
            criteria = SortCriteria.SPEED_FIRST

        sort_label = str(getattr(criteria, "value", criteria))

        # Extract endpoints and results strictly based on the active tab's visual rows
        if is_matrix_tab:
            if not aggregated:
                QMessageBox.warning(self, "Export Failed", "No cross-ISP benchmark sessions available to export.")
                return

            ordered_endpoints: list[str] = []
            seen: set[str] = set()
            for row in range(self.table_matrix.rowCount()):
                item_cov = self.table_matrix.item(row, 5)
                cov_val = item_cov.data(Qt.ItemDataRole.UserRole) if item_cov else 0
                if cov_val and cov_val > 0:
                    item_target = self.table_matrix.item(row, 0)
                    item_ip = self.table_matrix.item(row, 1)
                    item_cdn = self.table_matrix.item(row, 2)
                    item_loc = self.table_matrix.item(row, 3)
                    val_ip = item_ip.text().strip() if item_ip else ""
                    val_target = item_target.text().strip() if item_target else ""
                    val_cdn = item_cdn.text().strip() if item_cdn else ""
                    val_loc = item_loc.text().strip() if item_loc else ""
                    ep = val_ip if val_ip and val_ip != "0.0.0.0" else val_target
                    loc_tag = f" ({val_loc})" if val_loc and val_loc != "Unknown" else ""
                    tag = f" # {val_cdn}{loc_tag}" if val_cdn else (f" # {val_loc}" if loc_tag else "")
                    entry = f"{ep}{tag}"
                    if ep and ep not in seen:
                        seen.add(ep)
                        ordered_endpoints.append(entry)
            results_to_export = all_latest
        else:
            results_to_export = self.current_results or all_latest
            if not results_to_export:
                QMessageBox.warning(self, "Export Failed", "No benchmark results available to export.")
                return

            ordered_endpoints = []
            seen = set()
            for row in range(self.table_live.rowCount()):
                item_status = self.table_live.item(row, 11)
                if item_status and item_status.text() == ProbeStatus.SUCCESS.value:
                    item_target = self.table_live.item(row, 0)
                    item_ip = self.table_live.item(row, 1)
                    item_cdn = self.table_live.item(row, 2)
                    item_loc = self.table_live.item(row, 3)
                    val_ip = item_ip.text().strip() if item_ip else ""
                    val_target = item_target.text().strip() if item_target else ""
                    val_cdn = item_cdn.text().strip() if item_cdn else ""
                    val_loc = item_loc.text().strip() if item_loc else ""
                    ep = val_ip if val_ip and val_ip != "0.0.0.0" else val_target
                    loc_tag = f" ({val_loc})" if val_loc and val_loc != "Unknown" else ""
                    tag = f" # {val_cdn}{loc_tag}" if val_cdn else (f" # {val_loc}" if loc_tag else "")
                    entry = f"{ep}{tag}"
                    if ep and ep not in seen:
                        seen.add(ep)
                        ordered_endpoints.append(entry)

        default_name = f"cf_bench_results.{fmt}"
        filters = {
            "txt": "Clean Proxy Panel List (*.txt)",
            "csv": "Comma-Separated Values (*.csv)",
            "xlsx": "Excel Spreadsheet (*.xlsx)",
            "xls": "Legacy Excel (*.xls)",
            "sqlite": "SQLite Database (*.sqlite)",
        }

        save_path, _ = QFileDialog.getSaveFileName(
            self, f"Export as .{fmt.upper()}", default_name, filters.get(fmt, "All Files (*)")
        )

        if not save_path:
            return

        try:
            if fmt == "txt":
                if is_matrix_tab:
                    count = BenchmarkExporter.export_clean_txt(
                        save_path,
                        aggregated=aggregated,
                        criteria=criteria,
                        ordered_endpoints=ordered_endpoints,
                    )
                else:
                    count = BenchmarkExporter.export_clean_txt(
                        save_path,
                        results=results_to_export,
                        criteria=criteria,
                        ordered_endpoints=ordered_endpoints,
                    )
                self._show_export_success_dialog(
                    f"Successfully exported {count} clean endpoints sorted by {sort_label} to:\n{save_path}",
                    save_path,
                )
            elif fmt == "csv":
                if is_matrix_tab:
                    count = BenchmarkExporter.export_matrix_csv(
                        save_path,
                        aggregated=aggregated,
                        operators=self.db.get_all_tested_operators(),
                        criteria=criteria,
                        all_results=all_latest,
                    )
                else:
                    count = BenchmarkExporter.export_csv(save_path, results_to_export, criteria)
                self._show_export_success_dialog(
                    f"Successfully exported {count} sorted records to:\n{save_path}",
                    save_path,
                )
            elif fmt == "xlsx":
                BenchmarkExporter.export_xlsx(save_path, results_to_export, aggregated, criteria)
                self._show_export_success_dialog(
                    f"Exported formatted workbook sorted by {sort_label} to:\n{save_path}",
                    save_path,
                )
            elif fmt == "xls":
                BenchmarkExporter.export_xls(save_path, results_to_export, aggregated, criteria)
                self._show_export_success_dialog(
                    f"Exported legacy spreadsheet sorted by {sort_label} to:\n{save_path}",
                    save_path,
                )
            elif fmt == "sqlite":
                BenchmarkExporter.export_sqlite(save_path, results_to_export, aggregated, criteria)
                self._show_export_success_dialog(
                    f"Exported relational schema sorted by {sort_label} to:\n{save_path}",
                    save_path,
                )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to export file: {exc}")

    def _show_export_success_dialog(self, message: str, file_path: str) -> None:
        """
        Displays success dialog with an action to reveal the exported file in Windows Explorer / system file manager.
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Export Complete")
        msg_box.setText(message)
        btn_open = msg_box.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton(QMessageBox.StandardButton.Ok)
        msg_box.exec()

        if msg_box.clickedButton() == btn_open:
            self._reveal_file_in_file_manager(file_path)

    @staticmethod
    def _reveal_file_in_file_manager(file_path: str | Path) -> None:
        """
        Opens the system file manager (Windows File Explorer, macOS Finder, or Linux) with the file highlighted.
        """
        p = Path(file_path).resolve()
        if sys.platform == "win32":
            import subprocess
            subprocess.run(["explorer", f"/select,{str(p)}"], check=False)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", "-R", str(p)], check=False)
        else:
            import subprocess
            subprocess.run(["xdg-open", str(p.parent)], check=False)


    def closeEvent(self, event) -> None:
        """
        Gracefully terminates all background worker threads before widget teardown.
        """
        if self.benchmark_worker and self.benchmark_worker.isRunning():
            self.benchmark_worker.abort()
            self.benchmark_worker.wait(1500)
        if self.loader_worker and self.loader_worker.isRunning():
            self.loader_worker.terminate()
            self.loader_worker.wait(500)
        if self.isp_worker and self.isp_worker.isRunning():
            self.isp_worker.terminate()
            self.isp_worker.wait(500)
        super().closeEvent(event)


def launch() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
