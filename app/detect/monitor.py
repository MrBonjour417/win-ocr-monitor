from __future__ import annotations

import traceback
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from app.capture.window import (
    capture_window,
    crop_roi_from_frame,
    get_window_rect,
    get_window_title,
    save_snapshot_bundle,
)
from app.detect.ocr_backend import WindowsOcrBackend
from app.detect.question_detector import QuestionDetector
from app.types import FrameCapture, MonitorConfig, MonitorStatus


class MonitorThread(QThread):
    status_updated = pyqtSignal(object)
    question_event = pyqtSignal(object)
    frame_captured = pyqtSignal(object)
    log_message = pyqtSignal(str)

    def __init__(self, hwnd: int, config: MonitorConfig) -> None:
        super().__init__()
        self._hwnd = hwnd
        self._config = config
        self._running = False
        self._last_alert_at = ""

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True

        try:
            ocr_backend = WindowsOcrBackend()
        except Exception as exc:
            self.status_updated.emit(MonitorStatus(state="error", message=str(exc)))
            self.log_message.emit(f"[OCR] 初始化失败：{exc}")
            return

        detector = QuestionDetector(self._config)
        self.log_message.emit(f"[Monitor] 使用 OCR 后端：{ocr_backend.backend_name}")

        while self._running:
            try:
                window_title = get_window_title(self._hwnd)
                window_rect = get_window_rect(self._hwnd)
                if not window_title or window_rect is None:
                    self.status_updated.emit(
                        MonitorStatus(
                            state="error",
                            message="目标窗口不可用，请重新选择需要监控的窗口。",
                            last_alert_at=self._last_alert_at,
                        )
                    )
                    self._sleep_interval()
                    continue

                if (
                    self._config.reference_width > 0
                    and self._config.reference_height > 0
                    and (window_rect.w != self._config.reference_width or window_rect.h != self._config.reference_height)
                ):
                    self.status_updated.emit(
                        MonitorStatus(
                            state="paused",
                            window_title=window_title,
                            message=(
                                f"当前窗口尺寸为 {window_rect.w}x{window_rect.h}，"
                                f"与校准尺寸 {self._config.reference_width}x{self._config.reference_height} 不一致，请重新截图校准。"
                            ),
                            last_alert_at=self._last_alert_at,
                        )
                    )
                    self._sleep_interval()
                    continue

                frame_bgr = capture_window(self._hwnd)
                if frame_bgr is None:
                    self.status_updated.emit(
                        MonitorStatus(
                            state="error",
                            window_title=window_title,
                            message="无法抓取目标窗口画面，请确认窗口未最小化。",
                            last_alert_at=self._last_alert_at,
                        )
                    )
                    self._sleep_interval()
                    continue

                self.frame_captured.emit(
                    FrameCapture(frame_bgr=frame_bgr, window_rect=window_rect, captured_at=datetime.now())
                )

                question_crop = crop_roi_from_frame(frame_bgr, window_rect, self._config.question_roi)
                status_crop = crop_roi_from_frame(frame_bgr, window_rect, self._config.status_roi)
                if question_crop is None or status_crop is None:
                    self.status_updated.emit(
                        MonitorStatus(
                            state="error",
                            window_title=window_title,
                            message="ROI 超出当前窗口范围，请重新截图校准。",
                            last_alert_at=self._last_alert_at,
                        )
                    )
                    self._sleep_interval()
                    continue

                output = detector.process(question_crop, status_crop, ocr_backend)
                self.status_updated.emit(
                    MonitorStatus(
                        state=output.state,
                        window_title=window_title,
                        question_text=output.ocr_result.question_text,
                        status_text=output.ocr_result.status_text,
                        keyword_hits=output.ocr_result.keyword_hits,
                        fingerprint=output.ocr_result.fingerprint[:12],
                        last_alert_at=self._last_alert_at,
                        question_change_ratio=output.question_change_ratio,
                        status_change_ratio=output.status_change_ratio,
                        ran_ocr=output.ran_ocr,
                        message="监控中",
                    )
                )

                if output.event is not None:
                    event = output.event
                    if event.kind == "appeared":
                        paths = save_snapshot_bundle(
                            window_title=window_title,
                            snapshot_dir=self._config.snapshot_dir,
                            frame_bgr=frame_bgr,
                            window_rect=window_rect,
                            question_roi=self._config.question_roi,
                            status_roi=self._config.status_roi,
                            fingerprint=event.fingerprint,
                        )
                        event.screenshot_path = paths["full_path"]
                        event.question_image_path = paths["question_path"]
                        event.status_image_path = paths["status_path"]
                        event.snapshot_dir = paths["snapshot_dir"]
                        self._last_alert_at = event.timestamp.strftime("%H:%M:%S")
                        self.log_message.emit(
                            f"[Alert] 识别到新内容：{event.fingerprint[:8]}，截图已保存到 {event.snapshot_dir}"
                        )
                    elif event.kind == "cleared":
                        self.log_message.emit("[Monitor] 当前监控内容已清空。")

                    self.question_event.emit(event)
            except Exception:
                self.status_updated.emit(
                    MonitorStatus(
                        state="error",
                        message="监控线程发生异常，请查看日志。",
                        last_alert_at=self._last_alert_at,
                    )
                )
                self.log_message.emit(traceback.format_exc())

            self._sleep_interval()

    def _sleep_interval(self) -> None:
        remaining_ms = max(100, self._config.poll_interval_ms)
        while self._running and remaining_ms > 0:
            step = min(100, remaining_ms)
            self.msleep(step)
            remaining_ms -= step
