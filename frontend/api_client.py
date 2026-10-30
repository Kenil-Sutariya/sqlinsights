from __future__ import annotations

from typing import Any

import requests
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas import AskResponse, DatasetSchema, DatasetSummary, TableInfo


class APIClientError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class APIClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, str]:
        payload = self._request("GET", "/health")
        if not isinstance(payload, dict) or not isinstance(payload.get("mode"), str):
            raise APIClientError("INVALID_API_RESPONSE", "The API returned invalid health data.")
        return {"status": str(payload.get("status", "unknown")), "mode": payload["mode"]}

    def list_datasets(self) -> list[DatasetSummary]:
        return self._validate(
            TypeAdapter(list[DatasetSummary]), self._request("GET", "/api/v1/datasets")
        )

    def create_dataset(self, name: str) -> DatasetSummary:
        return self._validate(
            DatasetSummary,
            self._request("POST", "/api/v1/datasets", json={"name": name}),
        )

    def schema(self, dataset_id: str) -> DatasetSchema:
        return self._validate(
            DatasetSchema,
            self._request("GET", f"/api/v1/datasets/{dataset_id}/schema"),
        )

    def upload_table(self, dataset_id: str, filename: str, content: bytes) -> TableInfo:
        return self._validate(
            TableInfo,
            self._request(
                "POST",
                f"/api/v1/datasets/{dataset_id}/tables",
                files={"file": (filename, content, "text/csv")},
            ),
        )

    def ask(self, dataset_id: str, question: str) -> AskResponse:
        return self._validate(
            AskResponse,
            self._request(
                "POST",
                "/api/v1/ask",
                json={"dataset_id": dataset_id, "question": question},
            ),
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise APIClientError(
                "REQUEST_TIMEOUT", "The local API did not respond before the request timed out."
            ) from exc
        except requests.RequestException as exc:
            raise APIClientError(
                "BACKEND_UNAVAILABLE",
                "The local API is unavailable. Start or restart the FastAPI server.",
            ) from exc

        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise APIClientError(
                "INVALID_API_RESPONSE",
                "The API returned an unexpected response.",
                response.status_code,
            ) from exc

        if response.ok:
            return payload

        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error.get("code"), str) else "API_ERROR"
        message = (
            error.get("message")
            if isinstance(error.get("message"), str)
            else "The API could not complete the request."
        )
        raise APIClientError(code, message, response.status_code)

    @staticmethod
    def _validate(model: Any, payload: Any) -> Any:
        try:
            if isinstance(model, TypeAdapter):
                return model.validate_python(payload)
            return model.model_validate(payload)
        except ValidationError as exc:
            raise APIClientError(
                "INVALID_API_RESPONSE", "The API response did not match the expected contract."
            ) from exc
