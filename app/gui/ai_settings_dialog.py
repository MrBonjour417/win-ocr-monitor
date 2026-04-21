from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ai.service import AIAnalysisService
from app.ai.models import AISecretSettings
from app.ai.env import save_ai_secret_settings
from app.types import AIConfig, recommended_ai_models_tooltip


class AiSettingsDialog(QDialog):
    def __init__(self, ai_config: AIConfig, secrets: AISecretSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 查询设置")
        self.setMinimumSize(560, 520)

        self._ai_config = replace(ai_config)
        self._secrets = replace(secrets)

        self._build_ui()
        self._load_state()

    def ai_config(self) -> AIConfig:
        return replace(self._ai_config)

    def secret_settings(self) -> AISecretSettings:
        return replace(self._secrets)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._base_url_edit = QLineEdit()
        form.addRow("BASE_URL", self._base_url_edit)

        api_key_row = QWidget()
        api_key_layout = QHBoxLayout(api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.setSpacing(6)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(self._api_key_edit, 1)

        self._toggle_api_key_button = QToolButton()
        self._toggle_api_key_button.setCheckable(True)
        self._toggle_api_key_button.setText("显示")
        self._toggle_api_key_button.toggled.connect(self._update_api_key_visibility)
        api_key_layout.addWidget(self._toggle_api_key_button)
        form.addRow("API Key", api_key_row)

        self._main_model_edit = QLineEdit()
        self._main_model_edit.textChanged.connect(self._sync_verify_model_if_needed)
        form.addRow("主模型", self._main_model_edit)

        verify_model_row = QWidget()
        verify_model_layout = QGridLayout(verify_model_row)
        verify_model_layout.setContentsMargins(0, 0, 0, 0)
        verify_model_layout.setHorizontalSpacing(6)

        self._verify_model_edit = QLineEdit()
        verify_model_layout.addWidget(self._verify_model_edit, 0, 0)
        form.addRow("验证模型", verify_model_row)

        same_model_row = QWidget()
        same_model_layout = QHBoxLayout(same_model_row)
        same_model_layout.setContentsMargins(0, 0, 0, 0)
        same_model_layout.setSpacing(8)

        self._same_model_yes = QRadioButton("是")
        self._same_model_no = QRadioButton("否")
        self._same_model_yes.toggled.connect(self._update_same_model_state)

        help_button = QToolButton()
        help_button.setText("?")
        help_button.setAutoRaise(True)
        help_button.setToolTip(recommended_ai_models_tooltip())

        same_model_layout.addWidget(self._same_model_yes)
        same_model_layout.addWidget(self._same_model_no)
        same_model_layout.addWidget(help_button)
        same_model_layout.addStretch(1)
        form.addRow("主模型与验证模型是否相同", same_model_row)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setSingleStep(5)
        form.addRow("回答等待时间 (秒)", self._timeout_spin)

        self._include_status_checkbox = QCheckBox("发送 status_roi.png 作为附加上下文")
        form.addRow("是否附带状态区域截图", self._include_status_checkbox)

        layout.addWidget(form_widget)

        layout.addWidget(QLabel("Prompt"))
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText("请输入用于截图分析的提示词。")
        layout.addWidget(self._prompt_edit, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._test_connectivity_button = button_box.addButton("测试 AI 连通性", QDialogButtonBox.ButtonRole.ActionRole)
        self._test_connectivity_button.clicked.connect(self._test_connectivity)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_state(self) -> None:
        self._base_url_edit.setText(self._secrets.base_url)
        self._api_key_edit.setText(self._secrets.api_key)
        self._main_model_edit.setText(self._ai_config.main_model)
        self._verify_model_edit.setText(self._ai_config.verify_model)
        self._same_model_yes.setChecked(self._ai_config.same_model)
        self._same_model_no.setChecked(not self._ai_config.same_model)
        self._timeout_spin.setValue(self._ai_config.wait_timeout_sec)
        self._include_status_checkbox.setChecked(self._ai_config.include_status_context)
        self._prompt_edit.setPlainText(self._ai_config.prompt)
        self._update_same_model_state()
        self._update_api_key_visibility(self._toggle_api_key_button.isChecked())

    def _update_same_model_state(self) -> None:
        same_model = self._same_model_yes.isChecked()
        self._verify_model_edit.setEnabled(not same_model)
        self._sync_verify_model_if_needed()

    def _update_api_key_visibility(self, visible: bool) -> None:
        self._api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self._toggle_api_key_button.setText("隐藏" if visible else "显示")

    def _sync_verify_model_if_needed(self) -> None:
        if self._same_model_yes.isChecked():
            self._verify_model_edit.setText(self._main_model_edit.text().strip())

    def _collect_form_state(self, require_prompt: bool) -> tuple[AIConfig, AISecretSettings] | None:
        base_url = self._base_url_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        main_model = self._main_model_edit.text().strip()
        verify_model = self._verify_model_edit.text().strip()
        prompt = self._prompt_edit.toPlainText().strip()
        same_model = self._same_model_yes.isChecked()

        if not base_url:
            QMessageBox.warning(self, "缺少 BASE_URL", "请输入可用的 BASE_URL。")
            return None
        if not api_key:
            QMessageBox.warning(self, "缺少 API Key", "请输入可用的 API Key。")
            return None
        if not main_model:
            QMessageBox.warning(self, "缺少主模型", "请输入主模型名称。")
            return None
        if not same_model and not verify_model:
            QMessageBox.warning(self, "缺少验证模型", "当前为双模型模式，请填写验证模型名称。")
            return None
        if require_prompt and not prompt:
            QMessageBox.warning(self, "缺少 Prompt", "请输入至少一条通用分析 Prompt。")
            return None

        ai_config = AIConfig(
            enabled=self._ai_config.enabled,
            prompt=prompt or self._ai_config.prompt,
            main_model=main_model,
            verify_model=main_model if same_model else verify_model,
            same_model=same_model,
            wait_timeout_sec=self._timeout_spin.value(),
            include_status_context=self._include_status_checkbox.isChecked(),
        )
        secrets = AISecretSettings(
            base_url=base_url,
            api_key=api_key,
            env_path=self._secrets.env_path,
        )
        return ai_config, secrets

    def _test_connectivity(self) -> None:
        collected = self._collect_form_state(require_prompt=False)
        if collected is None:
            return

        ai_config, secrets = collected
        self._test_connectivity_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            service = AIAnalysisService(secrets)
            results, _log_lines = service.test_connectivity(ai_config)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "连通性测试失败",
                "请求在发送前就失败了。\n\n"
                f"错误信息：{exc}\n\n"
                "执行建议：\n"
                "1. 确认 openai 依赖已经安装。\n"
                "2. 确认 BASE_URL 格式正确，通常应包含 /v1。\n"
                "3. 确认当前网络能访问对应接口。",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._test_connectivity_button.setEnabled(True)

        success_count = sum(1 for result in results if result.status == "success")
        lines = []
        for index, result in enumerate(results, start=1):
            reply_preview = (result.text or result.error or "-").strip()
            lines.append(
                f"{index}. 模型：{result.model_name}\n"
                f"状态：{result.status}\n"
                f"耗时：{result.duration_sec:.2f}s\n"
                f"返回：{reply_preview}"
            )

        advice = self._build_connectivity_advice(results)
        message = "\n\n".join(lines + ["执行建议：", advice])
        if success_count == len(results):
            QMessageBox.information(self, "连通性测试成功", message)
        elif success_count > 0:
            QMessageBox.warning(self, "连通性测试部分成功", message)
        else:
            QMessageBox.critical(self, "连通性测试失败", message)

    def _build_connectivity_advice(self, results) -> str:
        combined_error = " ".join((result.error or "").lower() for result in results)
        advice_lines = []

        if any(result.status == "success" for result in results):
            advice_lines.append("当前至少有一个模型已成功响应，说明接口链路基本可用。")
        if "401" in combined_error or "403" in combined_error or "unauthorized" in combined_error:
            advice_lines.append("请优先检查 API Key 是否正确、是否过期，或者是否有调用权限。")
        if "404" in combined_error or "not found" in combined_error:
            advice_lines.append("请检查 BASE_URL 和模型名是否正确，尤其注意接口路径是否包含 /v1。")
        if "timeout" in combined_error or "timed out" in combined_error:
            advice_lines.append("如果经常超时，可以先把“回答等待时间”调大，再重试。")
        if not advice_lines:
            advice_lines.extend(
                [
                    "建议先用主模型测试通过，再开启正式监控。",
                    "如果是自建或中转接口，优先核对 BASE_URL、模型名和 API Key 三项是否匹配。",
                    "若返回内容异常但状态成功，通常说明模型可用，后续主要是 Prompt 调整问题。",
                ]
            )

        return "\n".join(f"- {line}" for line in advice_lines)

    def accept(self) -> None:
        collected = self._collect_form_state(require_prompt=True)
        if collected is None:
            return

        self._ai_config, self._secrets = collected
        save_ai_secret_settings(self._secrets)
        super().accept()
