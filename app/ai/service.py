from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from app.ai.client import OpenAICompatibleVisionClient
from app.ai.models import AIAnalysisRequest, AIAnalysisResult, AIModelResponse, AISecretSettings


class AIAnalysisService:
    def __init__(
        self,
        secrets: AISecretSettings,
        client_factory=None,
    ) -> None:
        self._secrets = secrets
        self._client_factory = client_factory or (lambda secrets: OpenAICompatibleVisionClient(secrets))

    def analyze(self, request: AIAnalysisRequest, log_callback=None) -> AIAnalysisResult:
        started_at = datetime.now()
        log_lines: list[str] = []

        def log(message: str) -> None:
            line = f"[{datetime.now():%H:%M:%S}] {message}"
            log_lines.append(line)
            if log_callback is not None:
                log_callback(line)

        source_image_path = self._pick_source_image(request)
        image_paths = [source_image_path]
        included_status_image = False

        if request.config.include_status_context and request.status_image_path and Path(request.status_image_path).exists():
            image_paths.append(request.status_image_path)
            included_status_image = True
            log(f"[AI] 附加状态区域截图：{request.status_image_path}")
        elif request.config.include_status_context:
            log("[AI] 已启用状态区域上下文，但未找到有效的 status_roi.png，已忽略。")

        log(f"[AI] 开始分析快照：{request.snapshot_dir}")
        log(f"[AI] 主图像：{source_image_path}")
        log(f"[AI] 超时设置：{request.config.wait_timeout_sec}s")

        if request.config.same_model:
            log(f"[AI] 单模型模式：{request.config.main_model}")
            main_result = self._run_model(
                model_name=request.config.main_model,
                prompt=request.config.prompt,
                image_paths=image_paths,
                timeout_sec=request.config.wait_timeout_sec,
                role_name="主模型",
                log=log,
            )
            verify_result = AIModelResponse(
                model_name=request.config.main_model,
                status="skipped",
                text="与主模型相同，未单独调用",
            )
            final_status = self._single_model_status(main_result)
        else:
            log(
                "[AI] 双模型模式："
                f"主模型={request.config.main_model}，验证模型={request.config.verify_model}"
            )
            main_result, verify_result = self._run_dual_models(request, image_paths, log)
            final_status = self._dual_model_status(main_result, verify_result)

        finished_at = datetime.now()
        log(f"[AI] 分析完成，最终状态：{final_status}")

        result = AIAnalysisResult(
            request=request,
            started_at=started_at,
            finished_at=finished_at,
            final_status=final_status,
            source_image_path=source_image_path,
            included_status_image=included_status_image,
            main_result=main_result,
            verify_result=verify_result,
            log_lines=log_lines,
        )
        result.result_path, result.log_path = self._persist_result(result)
        return result

    def _pick_source_image(self, request: AIAnalysisRequest) -> str:
        candidates = [
            request.question_image_path,
            request.screenshot_path,
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        raise RuntimeError("未找到可用于 AI 分析的快照图片。")

    def _run_dual_models(self, request: AIAnalysisRequest, image_paths: list[str], log) -> tuple[AIModelResponse, AIModelResponse]:
        future_map = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_map[
                executor.submit(
                    self._run_model,
                    request.config.main_model,
                    request.config.prompt,
                    image_paths,
                    request.config.wait_timeout_sec,
                    "主模型",
                    log,
                )
            ] = "main"
            future_map[
                executor.submit(
                    self._run_model,
                    request.config.verify_model,
                    request.config.prompt,
                    image_paths,
                    request.config.wait_timeout_sec,
                    "验证模型",
                    log,
                )
            ] = "verify"

            main_result: AIModelResponse | None = None
            verify_result: AIModelResponse | None = None
            for future in as_completed(future_map):
                role = future_map[future]
                result = future.result()
                if role == "main":
                    main_result = result
                else:
                    verify_result = result

        return main_result or AIModelResponse(model_name=request.config.main_model), verify_result or AIModelResponse(
            model_name=request.config.verify_model
        )

    def _run_model(
        self,
        model_name: str,
        prompt: str,
        image_paths: list[str],
        timeout_sec: int,
        role_name: str,
        log,
    ) -> AIModelResponse:
        started_at = datetime.now()
        log(f"[AI] {role_name}开始请求：{model_name}")
        try:
            client = self._client_factory(self._secrets)
            text = client.analyze(model_name, prompt, image_paths, timeout_sec).strip()
            duration = (datetime.now() - started_at).total_seconds()
            log(f"[AI] {role_name}请求成功：{model_name}，耗时 {duration:.2f}s")
            return AIModelResponse(
                model_name=model_name,
                status="success",
                text=text,
                duration_sec=duration,
            )
        except Exception as exc:
            duration = (datetime.now() - started_at).total_seconds()
            status = "timeout" if self._looks_like_timeout(exc) else "error"
            log(f"[AI] {role_name}请求失败：{model_name}，状态={status}，耗时 {duration:.2f}s，错误={exc}")
            log(traceback.format_exc().rstrip())
            return AIModelResponse(
                model_name=model_name,
                status=status,
                error=str(exc),
                duration_sec=duration,
            )

    def _single_model_status(self, main_result: AIModelResponse) -> str:
        if main_result.status == "success":
            return "单模型完成"
        if main_result.status == "timeout":
            return "主模型超时"
        return "主模型失败"

    def _dual_model_status(self, main_result: AIModelResponse, verify_result: AIModelResponse) -> str:
        failures: list[str] = []
        if main_result.status != "success":
            failures.append("主模型超时" if main_result.status == "timeout" else "主模型失败")
        if verify_result.status != "success":
            failures.append("验证模型超时" if verify_result.status == "timeout" else "验证模型失败")
        if failures:
            return "；".join(failures)
        if self._normalize_text(main_result.text) == self._normalize_text(verify_result.text):
            return "一致"
        return "不一致，待人工确认"

    def _persist_result(self, result: AIAnalysisResult) -> tuple[str, str]:
        snapshot_dir = Path(result.request.snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        run_token = result.finished_at.strftime("%Y%m%d_%H%M%S_%f")

        result_path = snapshot_dir / f"ai_result_{run_token}.json"
        log_path = snapshot_dir / f"ai_log_{run_token}.txt"

        result_path.write_text(
            json.dumps(
                {
                    "started_at": result.started_at.isoformat(timespec="seconds"),
                    "finished_at": result.finished_at.isoformat(timespec="seconds"),
                    "final_status": result.final_status,
                    "source_image_path": result.source_image_path,
                    "included_status_image": result.included_status_image,
                    "timeout_sec": result.request.config.wait_timeout_sec,
                    "same_model": result.request.config.same_model,
                    "main_model": result.request.config.main_model,
                    "verify_model": result.request.config.verify_model,
                    "prompt": result.request.config.prompt,
                    "main_result": {
                        "model_name": result.main_result.model_name,
                        "status": result.main_result.status,
                        "text": result.main_result.text,
                        "error": result.main_result.error,
                        "duration_sec": result.main_result.duration_sec,
                    },
                    "verify_result": {
                        "model_name": result.verify_result.model_name if result.verify_result else "",
                        "status": result.verify_result.status if result.verify_result else "",
                        "text": result.verify_result.text if result.verify_result else "",
                        "error": result.verify_result.error if result.verify_result else "",
                        "duration_sec": result.verify_result.duration_sec if result.verify_result else 0.0,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log_path.write_text("\n".join(result.log_lines) + "\n", encoding="utf-8")
        return str(result_path), str(log_path)

    def _looks_like_timeout(self, exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        return "timeout" in exc.__class__.__name__.lower() or "timed out" in str(exc).lower()

    def _normalize_text(self, value: str) -> str:
        return " ".join(value.split()).strip()
