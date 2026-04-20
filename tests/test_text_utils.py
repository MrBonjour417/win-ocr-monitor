from __future__ import annotations

import unittest

from app.detect.text_utils import build_question_fingerprint, build_text_key, extract_keyword_hits, normalize_text


class TextUtilsTests(unittest.TestCase):
    def test_normalize_text_collapses_whitespace(self) -> None:
        raw = "  单选题  \n\n  请  选择  正确答案  "
        self.assertEqual(normalize_text(raw), "单选题\n请选择正确答案")

    def test_normalize_text_removes_spaces_between_cjk_chars(self) -> None:
        raw = "作 业 提 交 时 间\n单 选 题 何 忆 卫"
        self.assertEqual(normalize_text(raw), "作业提交时间\n单选题何忆卫")

    def test_normalize_text_keeps_english_word_spaces(self) -> None:
        self.assertEqual(normalize_text("Open AI OCR test"), "Open AI OCR test")

    def test_build_text_key_normalizes_digits_and_punctuation(self) -> None:
        text = "第12题：剩余时间 01:23，A. 北京"
        self.assertEqual(build_text_key(text), "第#题剩余时间##a北京")

    def test_extract_keyword_hits(self) -> None:
        text = "单选\n提交答案\n剩余时间 00:20"
        hits = extract_keyword_hits(text, ["单选", "多选", "提交答案", "截止"])
        self.assertEqual(hits, ["单选", "提交答案"])

    def test_fingerprint_is_stable_for_same_key(self) -> None:
        left = build_question_fingerprint("这是同一道题", ["单选", "提交"])
        right = build_question_fingerprint("这是同一道题", ["提交", "单选"])
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
