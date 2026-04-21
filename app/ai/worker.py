from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.ai.models import AIAnalysisRequest, AIAnalysisResult, AISecretSettings
from app.ai.service import AIAnalysisService


class AIAnalysisWorker(QThread):
    log_message = pyqtSignal(str)
    analysis_finished = pyqtSignal(object)
    analysis_failed = pyqtSignal(str)

    def __init__(
        self,
        request: AIAnalysisRequest,
        secrets: AISecretSettings,
        service_factory=None,
    ) -> None:
        super().__init__()
        self._request = request
        self._secrets = secrets
        self._service_factory = service_factory or (lambda secrets: AIAnalysisService(secrets))

    def run(self) -> None:
        try:
            service = self._service_factory(self._secrets)
            result: AIAnalysisResult = service.analyze(self._request, log_callback=self.log_message.emit)
            self.analysis_finished.emit(result)
        except Exception as exc:
            self.analysis_failed.emit(str(exc))
