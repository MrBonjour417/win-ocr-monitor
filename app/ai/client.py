from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from app.ai.models import AISecretSettings


class OpenAICompatibleVisionClient:
    def __init__(self, secrets: AISecretSettings) -> None:
        self._secrets = secrets

    def analyze(self, model_name: str, prompt: str, image_paths: list[str], timeout_sec: int) -> str:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 openai 依赖，请先安装 requirements.txt 中新增的包。") from exc

        client = OpenAI(
            api_key=self._secrets.api_key,
            base_url=self._secrets.base_url,
            timeout=timeout_sec,
        )
        message_content: list[dict] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            message_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self._image_to_data_url(image_path),
                    },
                }
            )

        result = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": message_content,
                }
            ],
        )
        choice = result.choices[0].message
        content = choice.content or ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        return str(content).strip()

    def _image_to_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{data}"
