from __future__ import annotations

import asyncio

import cv2
import numpy as np


class WindowsOcrBackend:
    def __init__(self, preferred_languages: tuple[str, ...] = ("zh-Hans", "en-US")) -> None:
        self._preferred_languages = preferred_languages
        self._language_name = "user-profile"

        try:
            import winrt.windows.foundation  # noqa: F401
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ImportError as exc:
            raise RuntimeError(
                "缺少 Windows OCR 依赖，请先安装 pyproject.toml 中列出的 winrt 包。"
            ) from exc

        self._Language = Language
        self._BitmapPixelFormat = BitmapPixelFormat
        self._SoftwareBitmap = SoftwareBitmap
        self._OcrEngine = OcrEngine
        self._DataWriter = DataWriter
        self._engine = self._build_engine()

    @property
    def backend_name(self) -> str:
        return f"Windows OCR ({self._language_name})"

    def _build_engine(self):
        engine = self._OcrEngine.try_create_from_user_profile_languages()
        if engine is not None:
            return engine

        for language_tag in self._preferred_languages:
            language = self._Language(language_tag)
            if self._OcrEngine.is_language_supported(language):
                self._language_name = language_tag
                engine = self._OcrEngine.try_create_from_language(language)
                if engine is not None:
                    return engine

        raise RuntimeError("无法创建 Windows OCR 引擎，请确认系统安装了中文或英文 OCR 语言包。")

    def recognize(self, image: np.ndarray) -> str:
        return asyncio.run(self._recognize_async(image))

    async def _recognize_async(self, image: np.ndarray) -> str:
        if image.ndim == 2:
            rgba = cv2.cvtColor(image, cv2.COLOR_GRAY2RGBA)
        elif image.shape[2] == 4:
            rgba = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        else:
            rgba = cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)

        rgba = np.ascontiguousarray(rgba)
        height, width = rgba.shape[:2]

        writer = self._DataWriter()
        writer.write_bytes(rgba.tobytes())

        bitmap = self._SoftwareBitmap(self._BitmapPixelFormat.RGBA8, width, height)
        bitmap.copy_from_buffer(writer.detach_buffer())

        result = await self._engine.recognize_async(bitmap)
        return getattr(result, "text", "") or ""
