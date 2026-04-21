from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.config import monitor_config_from_dict
from app.gui.main_window import default_keywords_text
from app.types import AIConfig, DEFAULT_KEYWORDS


class DefaultKeywordConsistencyTests(unittest.TestCase):
    def test_sample_config_keywords_match_default_keywords(self) -> None:
        sample_path = Path(__file__).resolve().parent.parent / "window_ocr_monitor.sample.json"
        with sample_path.open("r", encoding="utf-8") as handle:
            sample = json.load(handle)

        self.assertEqual(sample["keywords"], DEFAULT_KEYWORDS)

    def test_main_window_default_keyword_text_matches_default_keywords(self) -> None:
        self.assertEqual(default_keywords_text(), ",".join(DEFAULT_KEYWORDS))

    def test_sample_config_ai_defaults_match_ai_config_defaults(self) -> None:
        sample_path = Path(__file__).resolve().parent.parent / "window_ocr_monitor.sample.json"
        with sample_path.open("r", encoding="utf-8") as handle:
            sample = json.load(handle)

        config = monitor_config_from_dict(sample)
        self.assertEqual(config.ai, AIConfig())


if __name__ == "__main__":
    unittest.main()
