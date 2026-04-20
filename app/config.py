from __future__ import annotations

from app.types import DEFAULT_KEYWORDS, MonitorConfig, Rect


def monitor_config_to_dict(config: MonitorConfig) -> dict:
    return {
        "window_title": config.window_title,
        "question_roi": config.question_roi.to_dict() if config.question_roi else None,
        "status_roi": config.status_roi.to_dict() if config.status_roi else None,
        "poll_interval_ms": config.poll_interval_ms,
        "stable_frames": config.stable_frames,
        "clear_frames": config.clear_frames,
        "change_threshold": config.change_threshold,
        "keywords": list(config.keywords),
        "sound_path": config.sound_path,
        "snapshot_dir": config.snapshot_dir,
        "window_size": {
            "w": config.reference_width,
            "h": config.reference_height,
        }
        if config.reference_width > 0 and config.reference_height > 0
        else None,
    }


def monitor_config_from_dict(data: dict) -> MonitorConfig:
    window_size = data.get("window_size") or {}
    keywords = [str(x).strip() for x in data.get("keywords", []) if str(x).strip()]

    return MonitorConfig(
        window_title=str(data.get("window_title", "")),
        question_roi=Rect.from_dict(data.get("question_roi")),
        status_roi=Rect.from_dict(data.get("status_roi")),
        poll_interval_ms=int(data.get("poll_interval_ms", 800)),
        stable_frames=int(data.get("stable_frames", 2)),
        clear_frames=int(data.get("clear_frames", 2)),
        change_threshold=float(data.get("change_threshold", 0.015)),
        keywords=keywords or list(DEFAULT_KEYWORDS),
        sound_path=str(data.get("sound_path", "")),
        snapshot_dir=str(data.get("snapshot_dir", "snapshots")),
        reference_width=int(window_size.get("w", 0) or 0),
        reference_height=int(window_size.get("h", 0) or 0),
    )
