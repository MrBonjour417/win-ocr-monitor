from __future__ import annotations

import unittest

import numpy as np

from app.detect.question_detector import QuestionDetector
from app.types import MonitorConfig, OcrFrameResult


def _candidate(question: str, fingerprint: str) -> OcrFrameResult:
    return OcrFrameResult(
        question_text=question,
        status_text="单选 提交",
        question_key=question,
        status_key="单选提交",
        keyword_hits=["单选", "提交"],
        is_question_candidate=True,
        confidence_hint=1.0,
        fingerprint=fingerprint,
    )


def _empty() -> OcrFrameResult:
    return OcrFrameResult(
        question_text="",
        status_text="",
        question_key="",
        status_key="",
        keyword_hits=[],
        is_question_candidate=False,
        confidence_hint=0.0,
        fingerprint="",
    )


class QuestionDetectorStateTests(unittest.TestCase):
    def test_alerts_only_once_until_cleared(self) -> None:
        detector = QuestionDetector(MonitorConfig(stable_frames=2, clear_frames=2))

        self.assertIsNone(detector.handle_ocr_result(_candidate("第一题内容", "fp1")))
        appeared = detector.handle_ocr_result(_candidate("第一题内容", "fp1"))
        self.assertIsNotNone(appeared)
        self.assertEqual(appeared.kind, "appeared")

        self.assertIsNone(detector.handle_ocr_result(_candidate("第一题内容", "fp1")))
        self.assertEqual(detector.state, "alerted")

        self.assertIsNone(detector.handle_ocr_result(_empty()))
        cleared = detector.handle_ocr_result(_empty())
        self.assertIsNotNone(cleared)
        self.assertEqual(cleared.kind, "cleared")
        self.assertEqual(detector.state, "idle")

        self.assertIsNone(detector.handle_ocr_result(_candidate("第一题内容", "fp1")))
        appeared_again = detector.handle_ocr_result(_candidate("第一题内容", "fp1"))
        self.assertIsNotNone(appeared_again)
        self.assertEqual(appeared_again.kind, "appeared")

    def test_switches_to_new_question_without_full_clear(self) -> None:
        detector = QuestionDetector(MonitorConfig(stable_frames=2, clear_frames=2))

        detector.handle_ocr_result(_candidate("第一题内容", "fp1"))
        detector.handle_ocr_result(_candidate("第一题内容", "fp1"))
        self.assertEqual(detector.state, "alerted")

        self.assertIsNone(detector.handle_ocr_result(_candidate("第二题内容", "fp2")))
        appeared = detector.handle_ocr_result(_candidate("第二题内容", "fp2"))
        self.assertIsNotNone(appeared)
        self.assertEqual(appeared.kind, "appeared")
        self.assertEqual(appeared.fingerprint, "fp2")

    def test_process_refreshes_ocr_while_alerted(self) -> None:
        class FakeOcrBackend:
            def __init__(self, outputs: list[str]) -> None:
                self._outputs = iter(outputs)

            def recognize(self, _image) -> str:
                return next(self._outputs)

        detector = QuestionDetector(MonitorConfig(stable_frames=1, clear_frames=2, poll_interval_ms=800))
        backend = FakeOcrBackend(
            [
                "第一题内容这是一个足够长的测试题目",
                "单选 提交",
                "第二题内容这是另一个足够长的测试题目",
                "单选 提交",
            ]
        )
        image = np.zeros((40, 120, 3), dtype=np.uint8)

        first = detector.process(image, image, backend)
        self.assertTrue(first.ran_ocr)
        self.assertIsNotNone(first.event)
        self.assertEqual(first.event.kind, "appeared")

        second = detector.process(image, image, backend)
        self.assertFalse(second.ran_ocr)
        self.assertIsNone(second.event)

        third = detector.process(image, image, backend)
        self.assertTrue(third.ran_ocr)
        self.assertIsNotNone(third.event)
        self.assertEqual(third.event.kind, "appeared")
        self.assertEqual(third.ocr_result.question_text, "第二题内容这是另一个足够长的测试题目")


if __name__ == "__main__":
    unittest.main()
