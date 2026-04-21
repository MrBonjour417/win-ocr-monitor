from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCloseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ai.models import AIAnalysisRequest, AIAnalysisResult, AISecretSettings
from app.ai.worker import AIAnalysisWorker


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _load_pixmap_without_iccp_warning(image_path: str) -> QPixmap:
    raw = _read_image_bytes(image_path)
    if raw is None:
        return QPixmap()

    pixmap = QPixmap()
    pixmap.loadFromData(_strip_png_iccp_chunk(raw))
    return pixmap


def _read_image_bytes(image_path: str) -> bytes | None:
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _strip_png_iccp_chunk(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        return data

    chunks: list[bytes] = [_PNG_SIGNATURE]
    offset = len(_PNG_SIGNATURE)
    data_length = len(data)

    while offset + 12 <= data_length:
        chunk_start = offset
        chunk_len = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + chunk_len
        if chunk_end > data_length:
            return data
        if chunk_type != b"iCCP":
            chunks.append(data[chunk_start:chunk_end])
        offset = chunk_end

    if offset != data_length:
        return data

    return b"".join(chunks)


class AiAnalysisDialog(QDialog):
    def __init__(self, request_provider, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 分析结果")
        self.setMinimumSize(720, 620)
        self.resize(self._recommended_dialog_size())

        self._request_provider = request_provider
        self._worker: AIAnalysisWorker | None = None
        self._current_result: AIAnalysisResult | None = None
        self._preview_pixmap: QPixmap | None = None

        self._build_ui()
        self._start_analysis()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._content_scroll = QScrollArea()
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._content_scroll, 1)

        content = QWidget()
        self._content_scroll.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        image_group = QGroupBox("截图")
        image_layout = QVBoxLayout(image_group)
        self._image_label = QLabel("暂无截图")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setWordWrap(False)
        image_layout.addWidget(self._image_label)
        content_layout.addWidget(image_group, 0)

        meta_group = QGroupBox("元信息")
        meta_layout = QVBoxLayout(meta_group)
        self._meta_label = QLabel("模型：- | 超时：- | 状态图：-")
        self._meta_label.setWordWrap(True)
        self._state_label = QLabel("状态：待开始")
        self._state_label.setWordWrap(True)
        meta_layout.addWidget(self._meta_label)
        meta_layout.addWidget(self._state_label)
        content_layout.addWidget(meta_group, 0)

        result_group = QGroupBox("结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.addWidget(QLabel("主模型结果"))
        self._main_result_edit = QPlainTextEdit()
        self._main_result_edit.setReadOnly(True)
        self._main_result_edit.setMinimumHeight(130)
        result_layout.addWidget(self._main_result_edit)
        result_layout.addWidget(QLabel("验证结果"))
        self._verify_result_edit = QPlainTextEdit()
        self._verify_result_edit.setReadOnly(True)
        self._verify_result_edit.setMinimumHeight(110)
        result_layout.addWidget(self._verify_result_edit)
        content_layout.addWidget(result_group, 0)

        log_group = QGroupBox("AI 查询日志")
        log_layout = QVBoxLayout(log_group)
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(200)
        log_layout.addWidget(self._log_edit)
        content_layout.addWidget(log_group, 1)

        button_row = QHBoxLayout()
        self._copy_result_button = QPushButton("复制结果")
        self._copy_result_button.clicked.connect(self._copy_results)
        self._copy_log_button = QPushButton("复制日志")
        self._copy_log_button.clicked.connect(self._copy_logs)
        self._reanalyze_button = QPushButton("重新分析")
        self._reanalyze_button.clicked.connect(self._start_analysis)
        self._close_button = QPushButton("关闭")
        self._close_button.clicked.connect(self.close)

        button_row.addWidget(self._copy_result_button)
        button_row.addWidget(self._copy_log_button)
        button_row.addWidget(self._reanalyze_button)
        button_row.addStretch(1)
        button_row.addWidget(self._close_button)
        layout.addLayout(button_row)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_image_preview()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "分析进行中", "当前仍在等待 AI 返回结果，请稍后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)

    def _start_analysis(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        try:
            request, secrets = self._request_provider()
        except Exception as exc:
            QMessageBox.critical(self, "无法开始分析", str(exc))
            return

        self._current_result = None
        self._main_result_edit.clear()
        self._verify_result_edit.clear()
        self._log_edit.clear()
        self._update_meta(request, "分析中")
        self._set_preview_image(self._preview_candidate(request))

        self._copy_result_button.setEnabled(False)
        self._copy_log_button.setEnabled(False)
        self._reanalyze_button.setEnabled(False)
        self._close_button.setEnabled(False)

        self._worker = AIAnalysisWorker(request, secrets)
        self._worker.log_message.connect(self._append_log)
        self._worker.analysis_finished.connect(self._handle_finished)
        self._worker.analysis_failed.connect(self._handle_failed)
        self._worker.finished.connect(self._handle_worker_finished)
        self._worker.start()

    def _preview_candidate(self, request: AIAnalysisRequest) -> str:
        if request.question_image_path:
            return request.question_image_path
        return request.screenshot_path

    def _handle_finished(self, result: AIAnalysisResult) -> None:
        self._current_result = result
        self._update_meta(result.request, result.final_status)
        self._set_preview_image(result.source_image_path)
        self._main_result_edit.setPlainText(result.main_result.text or result.main_result.error or "-")
        if result.verify_result is not None:
            self._verify_result_edit.setPlainText(result.verify_result.text or result.verify_result.error or "-")
        else:
            self._verify_result_edit.setPlainText("-")
        self._log_edit.setPlainText("\n".join(result.log_lines))
        self._copy_result_button.setEnabled(True)
        self._copy_log_button.setEnabled(True)

    def _handle_failed(self, message: str) -> None:
        self._state_label.setText(f"状态：分析失败 - {message}")
        self._append_log(f"[AI] 分析流程失败：{message}")
        self._copy_log_button.setEnabled(True)

    def _handle_worker_finished(self) -> None:
        self._reanalyze_button.setEnabled(True)
        self._close_button.setEnabled(True)
        self._worker = None

    def _append_log(self, message: str) -> None:
        self._log_edit.appendPlainText(message)

    def _copy_results(self) -> None:
        if self._current_result is None:
            return
        verify_text = self._verify_result_edit.toPlainText().strip() or "-"
        content = "\n".join(
            [
                f"最终状态：{self._current_result.final_status}",
                "",
                "主模型结果：",
                self._main_result_edit.toPlainText().strip() or "-",
                "",
                "验证结果：",
                verify_text,
            ]
        )
        QApplication.clipboard().setText(content)

    def _copy_logs(self) -> None:
        QApplication.clipboard().setText(self._log_edit.toPlainText())

    def _update_meta(self, request: AIAnalysisRequest, status_text: str) -> None:
        if request.config.same_model:
            models_text = request.config.main_model
        else:
            models_text = f"{request.config.main_model} / {request.config.verify_model}"
        status_context = "是" if request.config.include_status_context else "否"
        self._meta_label.setText(
            f"模型：{models_text} | 超时：{request.config.wait_timeout_sec}s | 附带状态图：{status_context}"
        )
        self._state_label.setText(f"状态：{status_text}")

    def _set_preview_image(self, image_path: str) -> None:
        pixmap = _load_pixmap_without_iccp_warning(image_path)
        self._preview_pixmap = pixmap if not pixmap.isNull() else None
        self._refresh_image_preview()

    def _refresh_image_preview(self) -> None:
        if self._preview_pixmap is None:
            self._image_label.setText("暂无截图")
            self._image_label.setPixmap(QPixmap())
            self._image_label.setMinimumSize(0, 220)
            self._image_label.setMaximumSize(16777215, 16777215)
            return

        target_size = self._preview_target_size()
        scaled = self._preview_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.setFixedSize(scaled.size())
        self._image_label.setText("")

    def _preview_target_size(self) -> QSize:
        viewport = self._content_scroll.viewport().size()
        width = max(360, viewport.width() - 48)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            max_height = 420
        else:
            max_height = max(240, min(460, int(screen.availableGeometry().height() * 0.38)))
        return QSize(width, max_height)

    def _recommended_dialog_size(self) -> QSize:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return QSize(920, 820)

        available = screen.availableGeometry()
        width = max(720, min(1020, int(available.width() * 0.62)))
        height = max(620, min(860, int(available.height() * 0.82)))
        return QSize(width, height)
