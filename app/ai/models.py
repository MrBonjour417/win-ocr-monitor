from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.types import AIConfig, DEFAULT_AI_BASE_URL


@dataclass
class AISecretSettings:
    base_url: str = DEFAULT_AI_BASE_URL
    api_key: str = ""
    env_path: str = ""


@dataclass
class AIAnalysisRequest:
    snapshot_dir: str
    screenshot_path: str = ""
    question_image_path: str = ""
    status_image_path: str = ""
    fingerprint: str = ""
    config: AIConfig = field(default_factory=AIConfig)


@dataclass
class AIModelResponse:
    model_name: str
    status: str = "pending"
    text: str = ""
    error: str = ""
    duration_sec: float = 0.0


@dataclass
class AIAnalysisResult:
    request: AIAnalysisRequest
    started_at: datetime
    finished_at: datetime
    final_status: str
    source_image_path: str
    included_status_image: bool
    main_result: AIModelResponse
    verify_result: AIModelResponse | None
    log_lines: list[str]
    result_path: str = ""
    log_path: str = ""
