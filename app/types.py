from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


DEFAULT_KEYWORDS = [
    "单选",
    "多选",
    "判断",
    "投票",
    "开始",
    "继续",
    "确认",
    "提交",
    "保存",
    "完成",
]


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: dict | None) -> Rect | None:
        if not data:
            return None
        return cls(
            x=int(data["x"]),
            y=int(data["y"]),
            w=int(data["w"]),
            h=int(data["h"]),
        )


@dataclass
class MonitorConfig:
    window_title: str = ""
    question_roi: Rect | None = None
    status_roi: Rect | None = None
    poll_interval_ms: int = 800
    stable_frames: int = 2
    clear_frames: int = 2
    change_threshold: float = 0.015
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    sound_path: str = ""
    snapshot_dir: str = "snapshots"
    reference_width: int = 0
    reference_height: int = 0

    def has_required_rois(self) -> bool:
        return self.question_roi is not None and self.status_roi is not None


@dataclass
class OcrFrameResult:
    question_text: str
    status_text: str
    question_key: str
    status_key: str
    keyword_hits: list[str]
    is_question_candidate: bool
    confidence_hint: float
    fingerprint: str


@dataclass
class QuestionEvent:
    kind: str
    fingerprint: str
    question_text: str
    status_text: str
    timestamp: datetime
    screenshot_path: str = ""
    question_image_path: str = ""
    status_image_path: str = ""
    snapshot_dir: str = ""


@dataclass
class DetectorFrameOutput:
    ocr_result: OcrFrameResult
    event: QuestionEvent | None
    state: str
    question_change_ratio: float
    status_change_ratio: float
    ran_ocr: bool


@dataclass
class MonitorStatus:
    state: str = "idle"
    window_title: str = ""
    question_text: str = ""
    status_text: str = ""
    keyword_hits: list[str] = field(default_factory=list)
    fingerprint: str = ""
    last_alert_at: str = ""
    question_change_ratio: float = 0.0
    status_change_ratio: float = 0.0
    ran_ocr: bool = False
    message: str = ""


@dataclass
class FrameCapture:
    frame_bgr: object
    window_rect: Rect
    captured_at: datetime
