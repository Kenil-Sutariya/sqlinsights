from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        return self.payload


def fake_backend(method: str, url: str, **_kwargs: Any) -> FakeResponse:
    if url.endswith("/health"):
        return FakeResponse({"status": "ok", "mode": "demo"})
    if url.endswith("/api/v1/datasets") and method == "GET":
        return FakeResponse(
            [
                {
                    "id": "retail_demo",
                    "name": "Retail Demo",
                    "table_count": 3,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "protected": True,
                }
            ]
        )
    if url.endswith("/api/v1/datasets/retail_demo/schema"):
        return FakeResponse(
            {
                "id": "retail_demo",
                "name": "Retail Demo",
                "tables": [
                    {
                        "name": "products",
                        "source_filename": "products.csv",
                        "row_count": 2,
                        "columns": [
                            {"name": "product_name", "source_name": "product_name", "type": "TEXT"},
                            {"name": "revenue", "source_name": "revenue", "type": "REAL"},
                        ],
                    }
                ],
            }
        )
    if url.endswith("/api/v1/ask") and method == "POST":
        return FakeResponse(
            {
                "status": "success",
                "mode": "demo",
                "answer": "The query returned 2 row(s).",
                "explanation": "Ranks products by calculated revenue.",
                "sql": "SELECT product_name, revenue FROM products ORDER BY revenue DESC LIMIT 5",
                "columns": ["product_name", "revenue"],
                "rows": [["Laptop Stand", 250.0], ["Keyboard", 175.0]],
                "row_count_returned": 2,
                "truncated": False,
                "attempts": 1,
                "elapsed_ms": 3,
                "warnings": [],
            }
        )
    raise AssertionError(f"Unexpected fake request: {method} {url}")


def test_dashboard_runs_demo_question_and_renders_actual_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("frontend.api_client.requests.request", fake_backend)
    app_path = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    at = AppTest.from_file(app_path, default_timeout=15).run()
    assert not at.exception
    assert at.title[0].value == "SQLInsights"
    assert at.selectbox(key="dataset_selector").value == "retail_demo"

    at.button(key="sample_Top 5 products by revenue").click().run()

    assert not at.exception
    assert any("SELECT product_name" in element.value for element in at.code)
    result_tables = [frame.value for frame in at.dataframe if "revenue" in frame.value.columns]
    assert any(frame["revenue"].tolist() == [250.0, 175.0] for frame in result_tables)
    assert at.session_state["last_result"]["rows"] == [
        ["Laptop Stand", 250.0],
        ["Keyboard", 175.0],
    ]
    assert at.get("plotly_chart")
