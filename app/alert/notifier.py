from __future__ import annotations

import os
import winsound

from PyQt6.QtWidgets import QSystemTrayIcon

from app.types import QuestionEvent


class AlertManager:
    def __init__(self, tray_icon: QSystemTrayIcon | None) -> None:
        self._tray_icon = tray_icon
        self._default_sound = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "assets",
            "default_alert.wav",
        )

    def alert(self, event: QuestionEvent, sound_path: str = "") -> None:
        self.play_sound(sound_path)
        self.show_notification(event)

    def play_sound(self, sound_path: str = "") -> None:
        target = sound_path.strip() if sound_path else self._default_sound
        if target and os.path.exists(target):
            winsound.PlaySound(target, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

    def show_notification(self, event: QuestionEvent) -> None:
        if self._tray_icon is None or not QSystemTrayIcon.isSystemTrayAvailable():
            return

        lines = [line for line in event.question_text.splitlines() if line.strip()]
        preview = lines[0] if lines else "检测到新的监控内容，请尽快查看目标窗口。"
        message = preview[:80]
        if event.screenshot_path:
            message = f"{message}\n截图：{event.screenshot_path}"

        self._tray_icon.showMessage(
            "窗口监控提醒",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            10000,
        )
