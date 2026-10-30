from __future__ import annotations

from typing import Any

import pytest
import requests

from frontend.api_client import APIClient, APIClientError


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.payload = payload
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        return self.payload


def valid_ask_payload() -> dict[str, Any]:
    return {
        "status": "success",
        "mode": "demo",
        "answer": "The query returned 1 row(s).",
        "explanation": "Counts rows.",
        "sql": "SELECT COUNT(*) AS count FROM orders",
        "columns": ["count"],
        "rows": [[18]],
        "row_count_returned": 1,
        "truncated": False,
        "attempts": 1,
        "elapsed_ms": 2,
        "warnings": [],
    }


def test_ask_response_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frontend.api_client.requests.request",
        lambda *_args, **_kwargs: FakeResponse(200, valid_ask_payload()),
    )
    result = APIClient("http://localhost:8000").ask("retail_demo", "Count orders")
    assert result.rows == [[18]]
    assert result.sql.startswith("SELECT")


def test_csv_upload_uses_existing_backend_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def upload_response(method: str, url: str, **kwargs: Any) -> FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse(
            201,
            {
                "name": "sales",
                "source_filename": "sales.csv",
                "row_count": 1,
                "columns": [{"name": "amount", "source_name": "amount", "type": "INTEGER"}],
            },
        )

    monkeypatch.setattr("frontend.api_client.requests.request", upload_response)
    table = APIClient("http://localhost:8000").upload_table(
        "dataset-id", "sales.csv", b"amount\n10\n"
    )
    assert table.name == "sales"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v1/datasets/dataset-id/tables")
    assert captured["files"]["file"] == ("sales.csv", b"amount\n10\n", "text/csv")


def test_malformed_success_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frontend.api_client.requests.request",
        lambda *_args, **_kwargs: FakeResponse(200, {"status": "success"}),
    )
    with pytest.raises(APIClientError) as caught:
        APIClient("http://localhost:8000").ask("retail_demo", "Count orders")
    assert caught.value.code == "INVALID_API_RESPONSE"


def test_api_error_envelope_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frontend.api_client.requests.request",
        lambda *_args, **_kwargs: FakeResponse(
            422,
            {
                "status": "error",
                "error": {"code": "SQL_POLICY_DENIED", "message": "Query rejected."},
            },
        ),
    )
    with pytest.raises(APIClientError) as caught:
        APIClient("http://localhost:8000").ask("retail_demo", "Delete rows")
    assert caught.value.code == "SQL_POLICY_DENIED"
    assert caught.value.status_code == 422
    assert str(caught.value) == "Query rejected."


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (requests.Timeout(), "REQUEST_TIMEOUT"),
        (requests.ConnectionError(), "BACKEND_UNAVAILABLE"),
    ],
)
def test_transport_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    exception: requests.RequestException,
    expected_code: str,
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise exception

    monkeypatch.setattr("frontend.api_client.requests.request", fail)
    with pytest.raises(APIClientError) as caught:
        APIClient("http://localhost:8000").health()
    assert caught.value.code == expected_code
    assert "traceback" not in caught.value.message.casefold()
