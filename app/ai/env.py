from __future__ import annotations

from pathlib import Path

from app.ai.models import AISecretSettings
from app.types import APP_ENV_AI_API_KEY_KEY, APP_ENV_AI_BASE_URL_KEY, DEFAULT_AI_BASE_URL


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def load_ai_secret_settings(env_path: str | Path | None = None) -> AISecretSettings:
    path = Path(env_path) if env_path else default_env_path()
    values = _read_env_values(path)
    return AISecretSettings(
        base_url=values.get(APP_ENV_AI_BASE_URL_KEY, DEFAULT_AI_BASE_URL).strip() or DEFAULT_AI_BASE_URL,
        api_key=values.get(APP_ENV_AI_API_KEY_KEY, "").strip(),
        env_path=str(path),
    )


def save_ai_secret_settings(settings: AISecretSettings, env_path: str | Path | None = None) -> str:
    path = Path(env_path) if env_path else Path(settings.env_path or default_env_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    serialized = {
        APP_ENV_AI_BASE_URL_KEY: settings.base_url.strip() or DEFAULT_AI_BASE_URL,
        APP_ENV_AI_API_KEY_KEY: settings.api_key.strip(),
    }
    updated_lines = _update_env_lines(existing_lines, serialized)
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return str(path)


def _read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_wrapping_quotes(value.strip())
    return values


def _update_env_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    pending = dict(updates)
    updated_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated_lines.append(line)
            continue

        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in pending:
            updated_lines.append(f"{key}={_quote_env_value(pending.pop(key))}")
        else:
            updated_lines.append(line)

    for key, value in pending.items():
        updated_lines.append(f"{key}={_quote_env_value(value)}")

    return updated_lines


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
