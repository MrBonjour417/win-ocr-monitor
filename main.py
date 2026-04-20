from __future__ import annotations

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication

try:
    from app.gui.main_window import MainWindow
except ModuleNotFoundError as exc:
    missing = exc.name or "unknown"
    ctypes.windll.user32.MessageBoxW(
        0,
        f"缺少依赖：{missing}\n请先安装requiremments.txt中列出的依赖。",
        "Window OCR Monitor",
        0x10,
    )
    raise SystemExit(1) from exc


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Window OCR Monitor")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
