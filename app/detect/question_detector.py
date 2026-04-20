from __future__ import annotations

from dataclasses import replace
from datetime import datetime

try:
    import cv2
except ImportError:
    cv2 = None

import numpy as np

from app.detect.text_utils import (
    build_question_fingerprint,
    build_text_key,
    extract_keyword_hits,
    is_similar_question,
    normalize_text,
)
from app.types import DetectorFrameOutput, MonitorConfig, OcrFrameResult, QuestionEvent


def _resize_for_diff(image: np.ndarray) -> np.ndarray:
    if cv2 is None:
        raise RuntimeError("OpenCV 未安装，无法执行图像差分。")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)


def calculate_change_ratio(previous: np.ndarray | None, current: np.ndarray) -> float:
    if previous is None:
        return 1.0
    prev_small = _resize_for_diff(previous)
    curr_small = _resize_for_diff(current)
    diff = cv2.absdiff(prev_small, curr_small)
    return float((diff > 20).mean())


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    if cv2 is None:
        raise RuntimeError("OpenCV 未安装，无法执行 OCR 预处理。")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    scale = 1.0
    if gray.shape[0] < 220:
        scale = 2.0
    elif gray.shape[0] < 420:
        scale = 1.5

    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class QuestionDetector:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self.state = "idle"
        self._forced_refresh_frame_limit = max(1, int(1000 / max(100, self.config.poll_interval_ms)))
        self._frames_since_ocr = self._forced_refresh_frame_limit
        self._previous_question_frame: np.ndarray | None = None
        self._previous_status_frame: np.ndarray | None = None
        self._last_ocr_result = OcrFrameResult(
            question_text="",
            status_text="",
            question_key="",
            status_key="",
            keyword_hits=[],
            is_question_candidate=False,
            confidence_hint=0.0,
            fingerprint="",
        )
        self._candidate_result: OcrFrameResult | None = None
        self._candidate_count = 0
        self._active_result: OcrFrameResult | None = None
        self._clear_count = 0

    def process(self, question_image: np.ndarray, status_image: np.ndarray, ocr_backend) -> DetectorFrameOutput:
        question_change_ratio = calculate_change_ratio(self._previous_question_frame, question_image)
        status_change_ratio = calculate_change_ratio(self._previous_status_frame, status_image)
        should_force_refresh = self.state == "alerted" and self._frames_since_ocr >= self._forced_refresh_frame_limit

        should_run_ocr = (
            not self._last_ocr_result.question_text
            or question_change_ratio >= self.config.change_threshold
            or status_change_ratio >= self.config.change_threshold
            or self.state != "alerted"
            or should_force_refresh
        )

        if should_run_ocr:
            question_text = normalize_text(ocr_backend.recognize(preprocess_for_ocr(question_image)))
            status_text = normalize_text(ocr_backend.recognize(preprocess_for_ocr(status_image)))
            ocr_result = self._build_ocr_result(question_text, status_text)
            self._last_ocr_result = ocr_result
            self._frames_since_ocr = 0
        else:
            ocr_result = self._last_ocr_result
            self._frames_since_ocr += 1

        event = self.handle_ocr_result(ocr_result)

        self._previous_question_frame = question_image.copy()
        self._previous_status_frame = status_image.copy()

        return DetectorFrameOutput(
            ocr_result=ocr_result,
            event=event,
            state=self.state,
            question_change_ratio=question_change_ratio,
            status_change_ratio=status_change_ratio,
            ran_ocr=should_run_ocr,
        )

    def handle_ocr_result(self, ocr_result: OcrFrameResult) -> QuestionEvent | None:
        if ocr_result.is_question_candidate:
            self._clear_count = 0

            if self._active_result and self._is_same_question(self._active_result, ocr_result):
                self.state = "alerted"
                self._candidate_result = None
                self._candidate_count = 0
                self._active_result = replace(self._active_result, status_text=ocr_result.status_text)
                return None

            if self._candidate_result and self._is_same_question(self._candidate_result, ocr_result):
                self._candidate_count += 1
                self._candidate_result = ocr_result
            else:
                self._candidate_result = ocr_result
                self._candidate_count = 1

            self.state = "candidate"
            if self._candidate_count >= max(1, self.config.stable_frames):
                self.state = "alerted"
                self._active_result = ocr_result
                self._candidate_result = None
                self._candidate_count = 0
                return QuestionEvent(
                    kind="appeared",
                    fingerprint=ocr_result.fingerprint,
                    question_text=ocr_result.question_text,
                    status_text=ocr_result.status_text,
                    timestamp=datetime.now(),
                )
            return None

        self._candidate_result = None
        self._candidate_count = 0

        if self.state == "alerted" and self._active_result is not None:
            self.state = "clearing"
            self._clear_count = 1
            return None

        if self.state == "clearing" and self._active_result is not None:
            self._clear_count += 1
            if self._clear_count >= max(1, self.config.clear_frames):
                cleared_result = self._active_result
                self.state = "idle"
                self._clear_count = 0
                self._active_result = None
                return QuestionEvent(
                    kind="cleared",
                    fingerprint=cleared_result.fingerprint,
                    question_text=cleared_result.question_text,
                    status_text=cleared_result.status_text,
                    timestamp=datetime.now(),
                )
            return None

        self.state = "idle"
        self._clear_count = 0
        return None

    def _build_ocr_result(self, question_text: str, status_text: str) -> OcrFrameResult:
        question_key = build_text_key(question_text)
        status_key = build_text_key(status_text)
        keyword_hits = extract_keyword_hits(status_text, self.config.keywords)
        is_candidate = len(question_key) >= 8 and bool(keyword_hits)
        fingerprint = build_question_fingerprint(question_key, keyword_hits) if is_candidate else ""
        confidence_hint = min(1.0, len(question_key) / 48.0) if question_key else 0.0

        return OcrFrameResult(
            question_text=question_text,
            status_text=status_text,
            question_key=question_key,
            status_key=status_key,
            keyword_hits=keyword_hits,
            is_question_candidate=is_candidate,
            confidence_hint=confidence_hint,
            fingerprint=fingerprint,
        )

    def _is_same_question(self, left: OcrFrameResult, right: OcrFrameResult) -> bool:
        if left.fingerprint and left.fingerprint == right.fingerprint:
            return True
        return is_similar_question(left.question_key, right.question_key)
