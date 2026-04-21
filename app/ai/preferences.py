from __future__ import annotations

import json
from pathlib import Path

from app.types import AIConfig


def default_ai_preferences_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".window_ocr_monitor.ai.json"


def load_ai_preferences(path: str | Path | None = None) -> AIConfig:
    target = Path(path) if path else default_ai_preferences_path()
    if not target.exists():
        return AIConfig()

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return AIConfig()

    fallback = AIConfig()
    return AIConfig(
        enabled=bool(data.get("enabled", fallback.enabled)),
        prompt=str(data.get("prompt", fallback.prompt)),
        main_model=str(data.get("main_model", fallback.main_model)).strip() or fallback.main_model,
        verify_model=str(data.get("verify_model", fallback.verify_model)).strip() or fallback.verify_model,
        same_model=bool(data.get("same_model", fallback.same_model)),
        wait_timeout_sec=max(5, int(data.get("wait_timeout_sec", fallback.wait_timeout_sec))),
        include_status_context=bool(data.get("include_status_context", fallback.include_status_context)),
    )


def save_ai_preferences(config: AIConfig, path: str | Path | None = None) -> str:
    target = Path(path) if path else default_ai_preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": config.enabled,
        "prompt": config.prompt,
        "main_model": config.main_model,
        "verify_model": config.verify_model,
        "same_model": config.same_model,
        "wait_timeout_sec": config.wait_timeout_sec,
        "include_status_context": config.include_status_context,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
