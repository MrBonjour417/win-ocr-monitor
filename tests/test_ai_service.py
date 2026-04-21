from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from app.ai.env import load_ai_secret_settings, save_ai_secret_settings
from app.ai.models import AIAnalysisRequest, AISecretSettings
from app.ai.service import AIAnalysisService
from app.config import monitor_config_from_dict, monitor_config_to_dict
from app.types import AIConfig, DEFAULT_AI_BASE_URL, MonitorConfig


_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aR4QAAAAASUVORK5CYII="
)


class FakeVisionClient:
    def __init__(self, outputs: dict[str, str], calls: list[tuple[str, tuple[str, ...]]]) -> None:
        self._outputs = outputs
        self._calls = calls

    def analyze(self, model_name: str, prompt: str, image_paths: list[str], timeout_sec: int) -> str:
        self._calls.append((model_name, tuple(image_paths)))
        output = self._outputs.get(model_name)
        if isinstance(output, Exception):
            raise output
        return output or f"{model_name}:{timeout_sec}:{prompt[:8]}"


class AIServiceTests(unittest.TestCase):
    def test_connectivity_same_model_only_calls_once_without_images(self) -> None:
        calls: list[tuple[str, tuple[str, ...]]] = []
        service = AIAnalysisService(
            AISecretSettings(base_url=DEFAULT_AI_BASE_URL, api_key="test"),
            client_factory=lambda _secrets: FakeVisionClient({"gpt-5.4": "OK"}, calls),
        )

        results, log_lines = service.test_connectivity(
            AIConfig(
                enabled=True,
                main_model="gpt-5.4",
                verify_model="gpt-5.4",
                same_model=True,
                wait_timeout_sec=12,
            )
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("gpt-5.4", ()))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "success")
        self.assertIn("连通性测试完成", "\n".join(log_lines))

    def test_connectivity_dual_model_calls_both_models(self) -> None:
        calls: list[tuple[str, tuple[str, ...]]] = []
        service = AIAnalysisService(
            AISecretSettings(base_url=DEFAULT_AI_BASE_URL, api_key="test"),
            client_factory=lambda _secrets: FakeVisionClient(
                {"main-model": "OK", "verify-model": RuntimeError("401 unauthorized")},
                calls,
            ),
        )

        results, _ = service.test_connectivity(
            AIConfig(
                enabled=True,
                main_model="main-model",
                verify_model="verify-model",
                same_model=False,
                wait_timeout_sec=10,
            )
        )

        self.assertEqual(len(calls), 2)
        self.assertCountEqual([call[0] for call in calls], ["main-model", "verify-model"])
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(result.status for result in results), ["error", "success"])

    def test_same_model_only_calls_once_and_persists_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_dir = Path(temp_dir)
            question_path = snapshot_dir / "question_roi.png"
            question_path.write_bytes(_TINY_PNG)

            calls: list[tuple[str, tuple[str, ...]]] = []
            service = AIAnalysisService(
                AISecretSettings(base_url=DEFAULT_AI_BASE_URL, api_key="test"),
                client_factory=lambda _secrets: FakeVisionClient({"gpt-5.4": "分析完成"}, calls),
            )
            request = AIAnalysisRequest(
                snapshot_dir=str(snapshot_dir),
                question_image_path=str(question_path),
                fingerprint="same-model",
                config=AIConfig(
                    enabled=True,
                    main_model="gpt-5.4",
                    verify_model="gpt-5.4",
                    same_model=True,
                ),
            )

            result = service.analyze(request)

            self.assertEqual(len(calls), 1)
            self.assertEqual(result.final_status, "单模型完成")
            self.assertIsNotNone(result.verify_result)
            self.assertEqual(result.verify_result.status, "skipped")
            self.assertTrue(Path(result.result_path).exists())
            self.assertTrue(Path(result.log_path).exists())

    def test_dual_model_marks_inconsistent_and_includes_status_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_dir = Path(temp_dir)
            question_path = snapshot_dir / "question_roi.png"
            status_path = snapshot_dir / "status_roi.png"
            question_path.write_bytes(_TINY_PNG)
            status_path.write_bytes(_TINY_PNG)

            calls: list[tuple[str, tuple[str, ...]]] = []
            outputs = {
                "main-model": "结果 A",
                "verify-model": "结果 B",
            }
            service = AIAnalysisService(
                AISecretSettings(base_url=DEFAULT_AI_BASE_URL, api_key="test"),
                client_factory=lambda _secrets: FakeVisionClient(outputs, calls),
            )
            request = AIAnalysisRequest(
                snapshot_dir=str(snapshot_dir),
                question_image_path=str(question_path),
                status_image_path=str(status_path),
                fingerprint="dual-model",
                config=AIConfig(
                    enabled=True,
                    main_model="main-model",
                    verify_model="verify-model",
                    same_model=False,
                    include_status_context=True,
                ),
            )

            result = service.analyze(request)

            self.assertEqual(len(calls), 2)
            self.assertEqual(result.final_status, "不一致，待人工确认")
            self.assertTrue(result.included_status_image)
            for _, image_paths in calls:
                self.assertEqual(len(image_paths), 2)
                self.assertIn(str(question_path), image_paths)
                self.assertIn(str(status_path), image_paths)

    def test_env_round_trip_keeps_custom_ai_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("EXISTING_KEY=\"kept\"\n", encoding="utf-8")

            saved_path = save_ai_secret_settings(
                AISecretSettings(
                    base_url="https://example.test/v1",
                    api_key="secret-key",
                    env_path=str(env_path),
                )
            )
            loaded = load_ai_secret_settings(saved_path)

            self.assertEqual(loaded.base_url, "https://example.test/v1")
            self.assertEqual(loaded.api_key, "secret-key")
            self.assertIn("EXISTING_KEY", env_path.read_text(encoding="utf-8"))

    def test_monitor_config_round_trip_preserves_ai_config(self) -> None:
        original = MonitorConfig(
            window_title="Example",
            ai=AIConfig(
                enabled=True,
                prompt="自定义分析 prompt",
                main_model="main-model",
                verify_model="verify-model",
                same_model=False,
                wait_timeout_sec=35,
                include_status_context=True,
            ),
        )

        encoded = monitor_config_to_dict(original)
        decoded = monitor_config_from_dict(encoded)

        self.assertEqual(decoded.ai, original.ai)


if __name__ == "__main__":
    unittest.main()
