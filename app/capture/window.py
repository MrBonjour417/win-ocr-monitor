from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
from datetime import datetime

import cv2
import numpy as np
import win32con
import win32gui
import win32ui

from app.types import Rect


def _safe_delete_bitmap(bitmap) -> None:
    if bitmap is None:
        return
    try:
        handle = bitmap.GetHandle()
    except Exception:
        return
    if handle:
        try:
            ctypes.windll.gdi32.DeleteObject(handle)
        except Exception:
            pass


def _safe_delete_dc(dc) -> None:
    if dc is None:
        return
    try:
        dc.DeleteDC()
    except Exception:
        pass


def _safe_release_dc(hwnd: int, hwnd_dc: int) -> None:
    if not hwnd_dc:
        return
    try:
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        pass


def list_windows() -> list[tuple[int, str]]:
    results: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd: int, _lparam: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            results.append((hwnd, title))
        return True

    ctypes.windll.user32.EnumWindows(_callback, 0)
    return results


def get_window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        return win32gui.GetWindowText(hwnd).strip()
    except Exception:
        return ""


def get_window_rect(hwnd: int) -> Rect | None:
    if not hwnd:
        return None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None

    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return Rect(left, top, width, height)


def capture_window(hwnd: int) -> np.ndarray | None:
    rect = get_window_rect(hwnd)
    if rect is None:
        return None

    render_full_content = getattr(win32con, "PW_RENDERFULLCONTENT", 2)
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None

    src_dc = None
    mem_dc = None
    bitmap = None
    try:
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, rect.w, rect.h)
        mem_dc.SelectObject(bitmap)

        print_window = ctypes.windll.user32.PrintWindow
        print_window.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        print_window.restype = wintypes.BOOL
        if not print_window(hwnd, mem_dc.GetSafeHdc(), render_full_content):
            return None

        bits = bitmap.GetBitmapBits(True)
        bgra = np.frombuffer(bits, dtype=np.uint8).reshape(rect.h, rect.w, 4)
        return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
    except win32ui.error:
        return None
    finally:
        _safe_delete_bitmap(bitmap)
        _safe_delete_dc(mem_dc)
        _safe_delete_dc(src_dc)
        _safe_release_dc(hwnd, hwnd_dc)


def crop_roi_from_frame(frame_bgr: np.ndarray, window_rect: Rect, roi_rect: Rect | None) -> np.ndarray | None:
    if roi_rect is None:
        return None

    x1 = roi_rect.x - window_rect.x
    y1 = roi_rect.y - window_rect.y
    x2 = x1 + roi_rect.w
    y2 = y1 + roi_rect.h

    if x1 < 0 or y1 < 0 or x2 > frame_bgr.shape[1] or y2 > frame_bgr.shape[0]:
        return None

    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop.copy()


def safe_filename(text: str) -> str:
    cleaned = []
    for ch in text.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("._") or "capture"


def save_png(path: str, image: np.ndarray) -> bool:
    try:
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            return False
        with open(path, "wb") as handle:
            handle.write(encoded.tobytes())
        return True
    except Exception:
        return False


def _draw_roi_annotations(
    image: np.ndarray,
    window_rect: Rect,
    question_roi: Rect | None,
    status_roi: Rect | None,
) -> np.ndarray:
    annotated = image.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX

    if question_roi is not None:
        qx = question_roi.x - window_rect.x
        qy = question_roi.y - window_rect.y
        cv2.rectangle(annotated, (qx, qy), (qx + question_roi.w, qy + question_roi.h), (0, 200, 255), 2)
        cv2.putText(annotated, "question_roi", (qx + 4, max(18, qy - 8)), font, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

    if status_roi is not None:
        sx = status_roi.x - window_rect.x
        sy = status_roi.y - window_rect.y
        cv2.rectangle(annotated, (sx, sy), (sx + status_roi.w, sy + status_roi.h), (0, 255, 120), 2)
        cv2.putText(annotated, "status_roi", (sx + 4, max(18, sy - 8)), font, 0.6, (0, 255, 120), 2, cv2.LINE_AA)

    return annotated


def save_snapshot_bundle(
    window_title: str,
    snapshot_dir: str,
    frame_bgr: np.ndarray,
    window_rect: Rect,
    question_roi: Rect | None,
    status_roi: Rect | None,
    fingerprint: str,
) -> dict[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fingerprint_suffix = safe_filename(fingerprint[:8] if fingerprint else "manual")
    folder_name = f"{timestamp}_{safe_filename(window_title)}_{fingerprint_suffix}"
    output_dir = os.path.abspath(os.path.join(snapshot_dir, folder_name))
    os.makedirs(output_dir, exist_ok=True)

    annotated = _draw_roi_annotations(frame_bgr, window_rect, question_roi, status_roi)
    full_path = os.path.join(output_dir, "window_annotated.png")
    save_png(full_path, annotated)

    question_path = ""
    question_crop = crop_roi_from_frame(frame_bgr, window_rect, question_roi)
    if question_crop is not None:
        question_path = os.path.join(output_dir, "question_roi.png")
        save_png(question_path, question_crop)

    status_path = ""
    status_crop = crop_roi_from_frame(frame_bgr, window_rect, status_roi)
    if status_crop is not None:
        status_path = os.path.join(output_dir, "status_roi.png")
        save_png(status_path, status_crop)

    return {
        "snapshot_dir": output_dir,
        "full_path": full_path,
        "question_path": question_path,
        "status_path": status_path,
    }
