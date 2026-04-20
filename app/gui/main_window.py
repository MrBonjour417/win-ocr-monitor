from __future__ import annotations

import json
import os
from datetime import datetime

import cv2
import numpy as np
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.alert.notifier import AlertManager
from app.capture.window import capture_window, get_window_rect, list_windows, save_snapshot_bundle
from app.config import monitor_config_from_dict, monitor_config_to_dict
from app.detect.monitor import MonitorThread
from app.gui.roi_selector import RoiCanvas
from app.types import DEFAULT_KEYWORDS, FrameCapture, MonitorConfig, QuestionEvent, Rect


def _ndarray_to_pixmap(image_bgr: np.ndarray) -> QPixmap:
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    height, width, channels = image_rgb.shape
    qimage = QImage(image_rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage)


def default_keywords_text() -> str:
    return ",".join(DEFAULT_KEYWORDS)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Window OCR Monitor - 通用窗口 OCR 监控器")
        self.setMinimumSize(960, 680)
        self.resize(self._recommended_window_size())

        self._question_roi: Rect | None = None
        self._status_roi: Rect | None = None
        self._reference_size: tuple[int, int] = (0, 0)
        self._current_config_path = ""
        self._monitor_thread: MonitorThread | None = None
        self._last_capture: FrameCapture | None = None
        self._calibration_timer = QTimer(self)
        self._calibration_timer.setInterval(500)
        self._calibration_timer.timeout.connect(self._refresh_live_calibration_preview)

        self._build_ui()
        self._setup_tray()
        self._refresh_windows()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        target_group = QGroupBox("1. 选择目标窗口")
        target_layout = QHBoxLayout(target_group)
        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(240)
        refresh_button = QPushButton("刷新窗口列表")
        refresh_button.clicked.connect(self._refresh_windows)
        target_layout.addWidget(QLabel("窗口："))
        target_layout.addWidget(self._window_combo, 1)
        target_layout.addWidget(refresh_button)
        root.addWidget(target_group)

        center_splitter = QSplitter(Qt.Orientation.Horizontal)
        center_splitter.setChildrenCollapsible(False)
        root.addWidget(center_splitter, 1)

        left_panel = QWidget()
        left_column = QVBoxLayout(left_panel)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(8)

        calibrate_group = QGroupBox("2. 截图校准与 ROI")
        calibrate_layout = QVBoxLayout(calibrate_group)

        button_row = QHBoxLayout()
        self._capture_button = QPushButton("截图校准")
        self._capture_button.clicked.connect(self._capture_for_calibration)
        question_button = QPushButton("框选题目区域")
        question_button.clicked.connect(lambda: self._set_selection_target("question_roi"))
        status_button = QPushButton("框选状态区域")
        status_button.clicked.connect(lambda: self._set_selection_target("status_roi"))
        button_row.addWidget(self._capture_button)
        button_row.addWidget(question_button)
        button_row.addWidget(status_button)
        button_row.addStretch()
        calibrate_layout.addLayout(button_row)

        self._canvas = RoiCanvas()
        self._canvas.roi_defined.connect(self._on_roi_defined)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setWidget(self._canvas)
        calibrate_layout.addWidget(self._canvas_scroll, 1)

        self._roi_table = QTableWidget(0, 2)
        self._roi_table.setHorizontalHeaderLabels(["ROI", "Rect"])
        self._roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._roi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._roi_table.setFixedHeight(120)
        calibrate_layout.addWidget(self._roi_table)
        left_column.addWidget(calibrate_group, 1)
        center_splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_column = QVBoxLayout(right_panel)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(8)

        settings_group = QGroupBox("3. 监控设置")
        settings_layout = QFormLayout(settings_group)

        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(200, 5000)
        self._poll_spin.setSingleStep(100)
        self._poll_spin.setValue(800)
        settings_layout.addRow("采样间隔 (ms)", self._poll_spin)

        self._stable_spin = QSpinBox()
        self._stable_spin.setRange(1, 10)
        self._stable_spin.setValue(2)
        settings_layout.addRow("稳定帧阈值", self._stable_spin)

        self._clear_spin = QSpinBox()
        self._clear_spin.setRange(1, 10)
        self._clear_spin.setValue(2)
        settings_layout.addRow("清空帧阈值", self._clear_spin)

        self._change_spin = QDoubleSpinBox()
        self._change_spin.setRange(0.001, 0.200)
        self._change_spin.setDecimals(3)
        self._change_spin.setSingleStep(0.005)
        self._change_spin.setValue(0.015)
        settings_layout.addRow("变化阈值", self._change_spin)

        self._keyword_edit = QLineEdit(default_keywords_text())
        settings_layout.addRow("状态关键词 / Preset", self._keyword_edit)

        sound_row = QHBoxLayout()
        self._sound_path = QLineEdit()
        sound_browse = QPushButton("选择声音")
        sound_browse.clicked.connect(self._browse_sound)
        sound_row.addWidget(self._sound_path, 1)
        sound_row.addWidget(sound_browse)
        settings_layout.addRow("自定义声音", sound_row)

        snapshot_row = QHBoxLayout()
        self._snapshot_dir = QLineEdit(os.path.abspath(os.path.join(os.getcwd(), "snapshots")))
        snapshot_browse = QPushButton("选择目录")
        snapshot_browse.clicked.connect(self._browse_snapshot_dir)
        snapshot_row.addWidget(self._snapshot_dir, 1)
        snapshot_row.addWidget(snapshot_browse)
        settings_layout.addRow("截图留档目录", snapshot_row)

        right_column.addWidget(settings_group, 0)

        status_group = QGroupBox("4. 运行状态")
        status_layout = QGridLayout(status_group)
        self._state_label = QLabel("idle")
        self._fingerprint_label = QLabel("-")
        self._last_alert_label = QLabel("-")
        self._window_status_label = QLabel("未启动")
        self._change_label = QLabel("-")

        status_layout.addWidget(QLabel("检测状态"), 0, 0)
        status_layout.addWidget(self._state_label, 0, 1)
        status_layout.addWidget(QLabel("最近指纹"), 1, 0)
        status_layout.addWidget(self._fingerprint_label, 1, 1)
        status_layout.addWidget(QLabel("最近提醒"), 2, 0)
        status_layout.addWidget(self._last_alert_label, 2, 1)
        status_layout.addWidget(QLabel("变化比例"), 3, 0)
        status_layout.addWidget(self._change_label, 3, 1)
        status_layout.addWidget(QLabel("窗口状态"), 4, 0)
        status_layout.addWidget(self._window_status_label, 4, 1)
        right_column.addWidget(status_group, 0)

        text_group = QGroupBox("5. OCR 调试")
        text_layout = QVBoxLayout(text_group)
        text_layout.addWidget(QLabel("题目区域 OCR"))
        self._question_text = QPlainTextEdit()
        self._question_text.setReadOnly(True)
        self._question_text.setMinimumHeight(140)
        text_layout.addWidget(self._question_text)
        text_layout.addWidget(QLabel("状态区域 OCR"))
        self._status_text = QPlainTextEdit()
        self._status_text.setReadOnly(True)
        self._status_text.setMinimumHeight(140)
        text_layout.addWidget(self._status_text)
        right_column.addWidget(text_group, 2)

        log_group = QGroupBox("6. 日志")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMinimumHeight(220)
        self._log_text.document().setMaximumBlockCount(300)
        log_layout.addWidget(self._log_text)
        right_column.addWidget(log_group, 3)

        right_column.addStretch(1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_panel)
        right_scroll.setMinimumWidth(420)
        center_splitter.addWidget(right_scroll)
        center_splitter.setStretchFactor(0, 3)
        center_splitter.setStretchFactor(1, 3)
        center_splitter.setSizes([700, 520])

        controls_group = QGroupBox("7. 控制")
        controls_layout = QGridLayout(controls_group)
        save_button = QPushButton("保存配置")
        save_button.clicked.connect(self._save_config)
        load_button = QPushButton("加载配置")
        load_button.clicked.connect(self._load_config)
        test_button = QPushButton("测试提醒")
        test_button.clicked.connect(self._test_alert)
        export_button = QPushButton("导出当前调试截图")
        export_button.clicked.connect(self._export_debug_snapshot)
        self._start_button = QPushButton("开始监控")
        self._start_button.clicked.connect(self._start_monitoring)
        self._stop_button = QPushButton("停止监控")
        self._stop_button.clicked.connect(self._stop_monitoring)
        self._stop_button.setEnabled(False)

        controls_layout.addWidget(save_button, 0, 0)
        controls_layout.addWidget(load_button, 0, 1)
        controls_layout.addWidget(test_button, 0, 2)
        controls_layout.addWidget(export_button, 1, 0)
        controls_layout.addWidget(self._start_button, 1, 1)
        controls_layout.addWidget(self._stop_button, 1, 2)
        controls_layout.setColumnStretch(0, 1)
        controls_layout.setColumnStretch(1, 1)
        controls_layout.setColumnStretch(2, 1)
        root.addWidget(controls_group)

    def _setup_tray(self) -> None:
        self._tray_icon: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._alert_manager = AlertManager(None)
            return

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self._tray_icon = QSystemTrayIcon(QIcon(icon), self)
        self._tray_icon.setToolTip("Window OCR Monitor")
        self._tray_icon.show()
        self._alert_manager = AlertManager(self._tray_icon)

    def _refresh_windows(self) -> None:
        current_title = self._selected_window_title()
        self._window_combo.clear()
        for hwnd, title in sorted(list_windows(), key=lambda item: item[1].lower()):
            self._window_combo.addItem(f"{title}  [hwnd={hwnd}]", hwnd)
        if current_title:
            self._select_window_by_title(current_title)

    def _selected_window_title(self) -> str:
        text = self._window_combo.currentText().strip()
        if "[hwnd=" in text:
            return text.split("[hwnd=", 1)[0].rstrip()
        return text

    def _select_window_by_title(self, title: str) -> None:
        wanted = title.strip().lower()
        if not wanted:
            return
        for index in range(self._window_combo.count()):
            item_text = self._window_combo.itemText(index)
            base = item_text.split("[hwnd=", 1)[0].rstrip().lower()
            if base == wanted:
                self._window_combo.setCurrentIndex(index)
                return

    def _capture_for_calibration(self) -> None:
        if not self._update_calibration_capture(show_errors=True):
            return

        if not self._calibration_timer.isActive():
            self._calibration_timer.start()
            self._append_log("[Capture] 已启动实时校准预览。")

        self._capture_button.setText("截图校准（预览中）")

    def _refresh_live_calibration_preview(self) -> None:
        if self._canvas.is_interacting():
            return
        self._update_calibration_capture(show_errors=False)

    def _update_calibration_capture(self, show_errors: bool) -> bool:
        hwnd = self._window_combo.currentData()
        if not hwnd:
            if show_errors:
                QMessageBox.warning(self, "未选择窗口", "请先选择需要监控的窗口。")
            return False

        frame_bgr = capture_window(hwnd)
        rect = get_window_rect(hwnd)
        if frame_bgr is None or rect is None:
            if show_errors:
                QMessageBox.warning(self, "截图失败", "无法抓取目标窗口，请确认窗口未最小化。")
            return False

        self._last_capture = FrameCapture(frame_bgr=frame_bgr, window_rect=rect, captured_at=datetime.now())
        self._reference_size = (rect.w, rect.h)
        self._canvas.set_capture(
            _ndarray_to_pixmap(frame_bgr),
            (rect.x, rect.y),
            self._calibration_preview_size(),
        )
        self._sync_canvas_rois()

        if show_errors:
            self._append_log(f"[Capture] 已抓取窗口截图：{rect.w}x{rect.h}")

        return True

    def _set_selection_target(self, target: str) -> None:
        if self._last_capture is None:
            QMessageBox.information(self, "先截图", "请先点击“截图校准”获取目标窗口画面。")
            return
        self._canvas.set_selection_target(target)
        self._append_log(f"[ROI] 请在截图上框选 {target}")

    def _on_roi_defined(self, target: str, roi: Rect) -> None:
        if target == "question_roi":
            self._question_roi = roi
        elif target == "status_roi":
            self._status_roi = roi
        self._sync_canvas_rois()
        self._refresh_roi_table()
        self._append_log(f"[ROI] 已更新 {target}: ({roi.x}, {roi.y}, {roi.w}, {roi.h})")

    def _sync_canvas_rois(self) -> None:
        self._canvas.set_rois(self._question_roi, self._status_roi)

    def _refresh_roi_table(self) -> None:
        self._roi_table.setRowCount(0)
        for name, roi in (("question_roi", self._question_roi), ("status_roi", self._status_roi)):
            if roi is None:
                continue
            row = self._roi_table.rowCount()
            self._roi_table.insertRow(row)
            self._roi_table.setItem(row, 0, QTableWidgetItem(name))
            self._roi_table.setItem(row, 1, QTableWidgetItem(f"{roi.x},{roi.y}  {roi.w}x{roi.h}"))

    def _browse_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择提醒声音", "", "Wave (*.wav)")
        if path:
            self._sound_path.setText(path)

    def _browse_snapshot_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择截图留档目录")
        if path:
            self._snapshot_dir.setText(path)

    def _build_config(self) -> MonitorConfig:
        keywords = [
            token.strip()
            for raw in self._keyword_edit.text().replace("，", ",").split(",")
            for token in [raw]
            if token.strip()
        ]

        return MonitorConfig(
            window_title=self._selected_window_title(),
            question_roi=self._question_roi,
            status_roi=self._status_roi,
            poll_interval_ms=self._poll_spin.value(),
            stable_frames=self._stable_spin.value(),
            clear_frames=self._clear_spin.value(),
            change_threshold=self._change_spin.value(),
            keywords=keywords,
            sound_path=self._sound_path.text().strip(),
            snapshot_dir=self._snapshot_dir.text().strip() or "snapshots",
            reference_width=self._reference_size[0],
            reference_height=self._reference_size[1],
        )

    def _apply_config(self, config: MonitorConfig) -> None:
        self._question_roi = config.question_roi
        self._status_roi = config.status_roi
        self._reference_size = (config.reference_width, config.reference_height)

        self._poll_spin.setValue(config.poll_interval_ms)
        self._stable_spin.setValue(config.stable_frames)
        self._clear_spin.setValue(config.clear_frames)
        self._change_spin.setValue(config.change_threshold)
        self._keyword_edit.setText(",".join(config.keywords))
        self._sound_path.setText(config.sound_path)
        self._snapshot_dir.setText(config.snapshot_dir)
        self._select_window_by_title(config.window_title)
        self._sync_canvas_rois()
        self._refresh_roi_table()

    def _save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存配置",
            self._current_config_path or os.path.abspath(os.path.join(os.getcwd(), "window_ocr_monitor.json")),
            "JSON (*.json)",
        )
        if not path:
            return

        try:
            config = self._build_config()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(monitor_config_to_dict(config), handle, ensure_ascii=False, indent=2)
            self._current_config_path = path
            self._append_log(f"[Config] 已保存配置到 {path}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def _load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "加载配置",
            self._current_config_path or os.path.abspath(os.getcwd()),
            "JSON (*.json)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._apply_config(monitor_config_from_dict(data))
            self._current_config_path = path
            self._append_log(f"[Config] 已加载配置：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "加载失败", str(exc))

    def _start_monitoring(self) -> None:
        if self._monitor_thread is not None:
            return

        hwnd = self._window_combo.currentData()
        if not hwnd:
            QMessageBox.warning(self, "未选择窗口", "请先选择需要监控的窗口。")
            return

        config = self._build_config()
        if not config.has_required_rois():
            QMessageBox.warning(self, "ROI 未完成", "请先完成题目区域和状态区域的框选。")
            return

        if config.reference_width <= 0 or config.reference_height <= 0:
            QMessageBox.warning(self, "未校准", "请先点击“截图校准”以记录窗口尺寸。")
            return

        os.makedirs(config.snapshot_dir, exist_ok=True)
        if self._calibration_timer.isActive():
            self._calibration_timer.stop()
            self._capture_button.setText("截图校准")
        self._monitor_thread = MonitorThread(hwnd, config)
        self._monitor_thread.status_updated.connect(self._handle_status_update)
        self._monitor_thread.question_event.connect(self._handle_question_event)
        self._monitor_thread.frame_captured.connect(self._handle_frame_capture)
        self._monitor_thread.log_message.connect(self._append_log)
        self._monitor_thread.finished.connect(self._on_monitor_finished)
        self._monitor_thread.start()

        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._window_status_label.setText("监控线程已启动")
        self._append_log("[Monitor] 开始监控目标窗口。")

    def _stop_monitoring(self) -> None:
        if self._monitor_thread is None:
            return
        self._monitor_thread.stop()
        self._monitor_thread.wait(3000)
        self._monitor_thread = None
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._window_status_label.setText("已停止")
        self._append_log("[Monitor] 已停止监控。")

    def _on_monitor_finished(self) -> None:
        self._monitor_thread = None
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)

    def _handle_status_update(self, status) -> None:
        self._state_label.setText(status.state)
        self._fingerprint_label.setText(status.fingerprint or "-")
        self._last_alert_label.setText(status.last_alert_at or "-")
        self._window_status_label.setText(status.message or "-")
        self._change_label.setText(
            f"Q {status.question_change_ratio:.3f} / S {status.status_change_ratio:.3f} / OCR {'Y' if status.ran_ocr else 'N'}"
        )
        self._question_text.setPlainText(status.question_text)
        self._status_text.setPlainText(status.status_text)

    def _handle_question_event(self, event: QuestionEvent) -> None:
        if event.kind == "appeared":
            self._alert_manager.alert(event, self._sound_path.text().strip())
            self._last_alert_label.setText(event.timestamp.strftime("%H:%M:%S"))
            self._append_log(
                f"[Alert] 新内容提醒已触发，指纹 {event.fingerprint[:8]}，整窗截图：{event.screenshot_path}"
            )
        elif event.kind == "cleared":
            self._append_log("[Monitor] 监控内容已消失。")

    def _handle_frame_capture(self, capture: FrameCapture) -> None:
        self._last_capture = capture

    def _test_alert(self) -> None:
        event = QuestionEvent(
            kind="appeared",
            fingerprint="manualtest",
            question_text="测试提醒：请确认声音、通知和日志是否正常。",
            status_text="确认 提交",
            timestamp=datetime.now(),
        )
        self._alert_manager.alert(event, self._sound_path.text().strip())
        self._append_log("[Alert] 已触发测试提醒。")

    def _export_debug_snapshot(self) -> None:
        if self._last_capture is None:
            QMessageBox.information(self, "暂无截图", "请先完成截图校准或启动监控后再导出。")
            return

        config = self._build_config()
        paths = save_snapshot_bundle(
            window_title=config.window_title or "Window OCR Monitor",
            snapshot_dir=config.snapshot_dir,
            frame_bgr=self._last_capture.frame_bgr,
            window_rect=self._last_capture.window_rect,
            question_roi=config.question_roi,
            status_roi=config.status_roi,
            fingerprint="manual_export",
        )
        self._append_log(f"[Export] 已导出调试截图到 {paths['snapshot_dir']}")
        QMessageBox.information(self, "导出完成", f"截图已保存到：\n{paths['snapshot_dir']}")

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.appendPlainText(f"[{stamp}] {text}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_canvas_preview()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._calibration_timer.stop()
        self._stop_monitoring()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        super().closeEvent(event)

    def _recommended_window_size(self) -> QSize:
        screen = QApplication.primaryScreen()
        if screen is None:
            return QSize(1080, 760)

        available = screen.availableGeometry()
        width = max(960, min(1180, int(available.width() * 0.72)))
        height = max(680, min(820, int(available.height() * 0.76)))
        return QSize(width, height)

    def _calibration_preview_size(self) -> QSize:
        viewport = self._canvas_scroll.viewport().size()
        width = max(640, viewport.width() - 16)
        height = max(360, viewport.height() - 16)
        return QSize(width, height)

    def _refresh_canvas_preview(self) -> None:
        if self._last_capture is None:
            return

        self._canvas.set_capture(
            _ndarray_to_pixmap(self._last_capture.frame_bgr),
            (self._last_capture.window_rect.x, self._last_capture.window_rect.y),
            self._calibration_preview_size(),
        )
        self._sync_canvas_rois()
