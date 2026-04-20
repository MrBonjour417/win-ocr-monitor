from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.types import Rect


ROI_COLORS = {
    "question_roi": QColor(0, 200, 255, 220),
    "status_roi": QColor(0, 255, 120, 220),
}


class RoiCanvas(QWidget):
    roi_defined = pyqtSignal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_pixmap: QPixmap | None = None
        self._display_pixmap: QPixmap | None = None
        self._display_scale = 1.0
        self._screen_offset = (0, 0)
        self._selection_target: str | None = None
        self._rois: dict[str, Rect | None] = {
            "question_roi": None,
            "status_roi": None,
        }
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None

        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(480, 270)

    def sizeHint(self) -> QSize:
        if self._display_pixmap is not None:
            return self._display_pixmap.size()
        return QSize(480, 270)

    def set_capture(self, pixmap: QPixmap, screen_offset: tuple[int, int], max_size: QSize | None = None) -> None:
        self._source_pixmap = pixmap
        self._screen_offset = screen_offset
        self._display_scale = self._calculate_display_scale(pixmap.size(), max_size)

        if self._display_scale >= 0.999:
            self._display_pixmap = pixmap
        else:
            scaled_size = QSize(
                max(1, int(round(pixmap.width() * self._display_scale))),
                max(1, int(round(pixmap.height() * self._display_scale))),
            )
            self._display_pixmap = pixmap.scaled(
                scaled_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        self.setFixedSize(self._display_pixmap.size())
        self.update()

    def set_rois(self, question_roi: Rect | None, status_roi: Rect | None) -> None:
        self._rois["question_roi"] = question_roi
        self._rois["status_roi"] = status_roi
        self.update()

    def set_selection_target(self, target: str | None) -> None:
        self._selection_target = target
        self.update()

    def is_interacting(self) -> bool:
        return self._selection_target is not None or self._drag_start is not None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._display_pixmap is None or self._selection_target is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_end = self._drag_start
            self.grabMouse()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is None:
            return
        self._drag_end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None:
            return

        self._drag_end = event.position().toPoint()
        rect = self._normalized_drag()
        self._drag_start = None
        self._drag_end = None
        self.releaseMouse()
        self.update()

        if self._selection_target is None or rect.width() < 5 or rect.height() < 5:
            return

        source_rect = self._map_display_rect_to_source(rect)
        roi = Rect(
            x=self._screen_offset[0] + source_rect.x(),
            y=self._screen_offset[1] + source_rect.y(),
            w=source_rect.width(),
            h=source_rect.height(),
        )
        target = self._selection_target
        self._selection_target = None
        self.roi_defined.emit(target, roi)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(38, 42, 48))

        if self._display_pixmap is not None:
            painter.drawPixmap(0, 0, self._display_pixmap)
        else:
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "先选择目标窗口并点击“截图校准”。",
            )
            painter.end()
            return

        for name, roi in self._rois.items():
            if roi is None:
                continue
            color = ROI_COLORS.get(name, QColor(255, 255, 255))
            local = self._map_source_rect_to_display(
                QRect(
                    roi.x - self._screen_offset[0],
                    roi.y - self._screen_offset[1],
                    roi.w,
                    roi.h,
                )
            )
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 50))
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            painter.drawRect(local)
            painter.drawText(local.left() + 4, max(18, local.top() - 6), name)

        if self._drag_start is not None and self._drag_end is not None:
            live_rect = self._normalized_drag()
            target = self._selection_target or "roi"
            color = ROI_COLORS.get(target, QColor(255, 230, 120))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 60))
            painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(live_rect)

        if self._selection_target:
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(12, 24, f"当前正在框选：{self._selection_target}")

        painter.end()

    def _normalized_drag(self) -> QRect:
        if self._drag_start is None or self._drag_end is None:
            return QRect()
        x1, y1 = self._drag_start.x(), self._drag_start.y()
        x2, y2 = self._drag_end.x(), self._drag_end.y()
        return QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _calculate_display_scale(self, pixmap_size: QSize, max_size: QSize | None) -> float:
        if max_size is None or max_size.width() <= 0 or max_size.height() <= 0:
            return 1.0

        width_scale = max_size.width() / pixmap_size.width()
        height_scale = max_size.height() / pixmap_size.height()
        return min(1.0, width_scale, height_scale)

    def _map_display_rect_to_source(self, rect: QRect) -> QRect:
        if self._source_pixmap is None or self._display_scale <= 0:
            return rect

        source_x = int(round(rect.x() / self._display_scale))
        source_y = int(round(rect.y() / self._display_scale))
        source_w = max(1, int(round(rect.width() / self._display_scale)))
        source_h = max(1, int(round(rect.height() / self._display_scale)))

        max_width = self._source_pixmap.width() - source_x
        max_height = self._source_pixmap.height() - source_y
        return QRect(
            source_x,
            source_y,
            max(1, min(source_w, max_width)),
            max(1, min(source_h, max_height)),
        )

    def _map_source_rect_to_display(self, rect: QRect) -> QRect:
        if self._display_scale >= 0.999:
            return rect

        return QRect(
            int(round(rect.x() * self._display_scale)),
            int(round(rect.y() * self._display_scale)),
            max(1, int(round(rect.width() * self._display_scale))),
            max(1, int(round(rect.height() * self._display_scale))),
        )
