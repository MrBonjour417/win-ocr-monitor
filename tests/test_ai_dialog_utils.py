from __future__ import annotations

import unittest
import zlib

from app.gui.ai_analysis_dialog import _strip_png_iccp_chunk


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    length = len(payload).to_bytes(4, "big")
    crc = zlib.crc32(chunk_type + payload).to_bytes(4, "big")
    return length + chunk_type + payload + crc


class AiDialogUtilsTests(unittest.TestCase):
    def test_strip_png_iccp_chunk_removes_iccp_only(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"iCCP", b"profile-data") + _png_chunk(b"IEND", b"")

        cleaned = _strip_png_iccp_chunk(png)

        self.assertNotIn(b"iCCP", cleaned)
        self.assertIn(b"IEND", cleaned)

    def test_strip_png_iccp_chunk_leaves_non_png_unchanged(self) -> None:
        data = b"not-a-png"

        self.assertEqual(_strip_png_iccp_chunk(data), data)


if __name__ == "__main__":
    unittest.main()
