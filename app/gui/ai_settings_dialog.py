from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key", self._api_key_edit)

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

    def _update_same_model_state(self) -> None:
        same_model = self._same_model_yes.isChecked()
        self._verify_model_edit.setEnabled(not same_model)
        self._sync_verify_model_if_needed()

    def _sync_verify_model_if_needed(self) -> None:
        if self._same_model_yes.isChecked():
            self._verify_model_edit.setText(self._main_model_edit.text().strip())

    def accept(self) -> None:
        base_url = self._base_url_edit.text().strip()
        main_model = self._main_model_edit.text().strip()
        verify_model = self._verify_model_edit.text().strip()
        prompt = self._prompt_edit.toPlainText().strip()

        if not base_url:
            QMessageBox.warning(self, "缺少 BASE_URL", "请输入可用的 BASE_URL。")
            return
        if not main_model:
            QMessageBox.warning(self, "缺少主模型", "请输入主模型名称。")
            return
        if not self._same_model_yes.isChecked() and not verify_model:
            QMessageBox.warning(self, "缺少验证模型", "当前为双模型模式，请填写验证模型名称。")
            return
        if not prompt:
            QMessageBox.warning(self, "缺少 Prompt", "请输入至少一条通用分析 Prompt。")
            return

        same_model = self._same_model_yes.isChecked()
        self._ai_config = AIConfig(
            enabled=self._ai_config.enabled,
            prompt=prompt,
            main_model=main_model,
            verify_model=main_model if same_model else verify_model,
            same_model=same_model,
            wait_timeout_sec=self._timeout_spin.value(),
            include_status_context=self._include_status_checkbox.isChecked(),
        )
        self._secrets = AISecretSettings(
            base_url=base_url,
            api_key=self._api_key_edit.text().strip(),
            env_path=self._secrets.env_path,
        )
        save_ai_secret_settings(self._secrets)
        super().accept()
