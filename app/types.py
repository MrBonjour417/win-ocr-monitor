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

APP_ENV_AI_BASE_URL_KEY = "WINDOW_OCR_MONITOR_AI_BASE_URL"
APP_ENV_AI_API_KEY_KEY = "WINDOW_OCR_MONITOR_AI_API_KEY"

DEFAULT_AI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_AI_MAIN_MODEL = "gpt-5.4"
DEFAULT_AI_VERIFY_MODEL = DEFAULT_AI_MAIN_MODEL
DEFAULT_AI_TIMEOUT_SEC = 20
RECOMMENDED_AI_MODELS = [
    "gpt-5.4",
    "gpt-5.4-mini",
    "qwen3.5-plus",
]
DEFAULT_AI_PROMPT = """你是一个通用的桌面截图分析助手。

请基于我提供的截图内容，完成以下任务：
1. 简要概括截图中的主要内容或事件。
2. 提取可见的关键信息，例如标题、状态、按钮、时间、提示语或其它重要文本。
3. 给出一个简短结论，说明此时更像是提醒、确认、告警、任务处理，还是普通信息展示。

要求：
- 只依据截图中可见的信息回答，不要臆测隐藏内容。
- 如果文字不清晰或内容不足，请明确说明“不确定”。
- 不要编造不存在的字段。
- 输出使用中文，尽量简洁清晰。
"""


def default_ai_prompt() -> str:
    return DEFAULT_AI_PROMPT


def recommended_ai_models_tooltip() -> str:
    models = "、".join(RECOMMENDED_AI_MODELS)
    return f"推荐模型：{models}"


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
class AIConfig:
    enabled: bool = False
    prompt: str = field(default_factory=default_ai_prompt)
    main_model: str = DEFAULT_AI_MAIN_MODEL
    verify_model: str = DEFAULT_AI_VERIFY_MODEL
    same_model: bool = True
    wait_timeout_sec: int = DEFAULT_AI_TIMEOUT_SEC
    include_status_context: bool = False


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
    ai: AIConfig = field(default_factory=AIConfig)

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
