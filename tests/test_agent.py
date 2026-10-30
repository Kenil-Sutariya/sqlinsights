from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import APITimeoutError, AuthenticationError

from backend.app.agent.graph import SQLAgent
from backend.app.agent.models import AgentSchema, SQLProposal
from backend.app.agent.providers import OpenAISQLProvider
from backend.app.errors import AppError
from backend.app.services.dataset_store import DEMO_ID, DatasetStore
from backend.app.services.query_executor import QueryExecutor


class SequenceProvider:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        question: str,
        schema: AgentSchema,
        retry_feedback: str | None = None,
    ) -> SQLProposal:
        self.calls.append(
            {
                "question": question,
                "schema": schema,
                "retry_feedback": retry_feedback,
            }
        )
        output = self.outputs[len(self.calls) - 1]
        if isinstance(output, Exception):
            raise output
        return output


@pytest.fixture
def seeded_store(tmp_path: Path) -> DatasetStore:
    project_root = Path(__file__).resolve().parents[1]
    store = DatasetStore(tmp_path / "data", 5)
    store.seed_demo(project_root / "sample_data")
    return store


def make_agent(
    store: DatasetStore,
    provider: SequenceProvider,
    *,
    timeout_seconds: float = 5.0,
) -> SQLAgent:
    return SQLAgent(
        store=store,
        executor=QueryExecutor(store, timeout_seconds=timeout_seconds),
        provider=provider,
        mode="llm",
    )


def proposal(sql: str, explanation: str = "A test query.") -> SQLProposal:
    return SQLProposal(disposition="query", sql=sql, explanation=explanation)


def test_graph_nodes_execute_valid_query_and_only_expose_active_schema(
    seeded_store: DatasetStore,
) -> None:
    other = seeded_store.create_dataset("Other")
    seeded_store.upload_table(other["id"], "private.csv", b"secret\nvalue\n")
    provider = SequenceProvider([proposal("SELECT COUNT(*) AS count FROM orders")])
    state = make_agent(seeded_store, provider).invoke_state(DEMO_ID, "Count the orders")

    assert state["trace"] == [
        "load_schema",
        "plan_sql",
        "validate_sql",
        "execute_sql",
        "format_result",
        "finish",
    ]
    response = state["final_response"]
    assert response.status == "success"
    assert response.rows == [[18]]
    assert response.row_count_returned == len(response.rows)
    assert response.sql == "SELECT COUNT(*) AS count FROM orders"
    assert response.attempts == 1
    schema = provider.calls[0]["schema"]
    assert [table.name for table in schema.tables] == ["customers", "products", "orders"]
    assert "private" not in schema.model_dump_json()
    assert "Berlin" not in schema.model_dump_json()


def test_empty_result_is_truthful(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider([proposal("SELECT order_id FROM orders WHERE 1 = 0")])
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Find impossible orders")
    assert response.status == "empty"
    assert response.answer == "No rows matched the query."
    assert response.rows == []
    assert response.row_count_returned == 0


def test_unknown_column_retries_once_then_succeeds(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider(
        [
            proposal("SELECT missing_column FROM orders"),
            proposal("SELECT COUNT(*) AS count FROM orders"),
        ]
    )
    state = make_agent(seeded_store, provider).invoke_state(DEMO_ID, "Count the orders")
    assert state["final_response"].status == "success"
    assert state["final_response"].rows == [[18]]
    assert state["final_response"].attempts == 2
    assert len(provider.calls) == 2
    assert provider.calls[1]["retry_feedback"] is not None
    assert state["trace"].count("plan_sql") == 2


def test_invalid_syntax_retries_once_then_succeeds(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider([proposal("SELECT ("), proposal("SELECT COUNT(*) FROM orders")])
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Count the orders")
    assert response.status == "success"
    assert response.attempts == 2
    assert response.rows == [[18]]


def test_malformed_provider_output_retries_at_most_once(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider(
        [
            {"disposition": "query", "sql": "SELECT 1"},
            {"not": "a proposal"},
        ]
    )
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Count the orders")
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "PROVIDER_MALFORMED_OUTPUT"
    assert response.attempts == 2
    assert len(provider.calls) == 2


def test_two_failed_queries_stop_after_two_model_calls(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider(
        [proposal("SELECT missing_one FROM orders"), proposal("SELECT missing_two FROM orders")]
    )
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Count the orders")
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "QUERY_EXECUTION_ERROR"
    assert response.attempts == 2
    assert len(provider.calls) == 2


def test_security_rejection_is_not_retried_and_database_is_unchanged(
    seeded_store: DatasetStore,
) -> None:
    db_path, _tables = seeded_store.query_target(DEMO_ID)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    provider = SequenceProvider([proposal("DELETE FROM orders")])
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Delete every order")
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "SQL_POLICY_DENIED"
    assert response.attempts == 1
    assert len(provider.calls) == 1
    assert after == before
    assert QueryExecutor(seeded_store).execute(DEMO_ID, "SELECT COUNT(*) FROM orders").rows == [
        [18]
    ]


def test_unknown_table_is_denied_without_retry(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider([proposal("SELECT * FROM private")])
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Show private data")
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "SQL_POLICY_DENIED"
    assert response.attempts == 1


def test_ambiguous_question_returns_clear_error_without_retry(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider(
        [
            SQLProposal(
                disposition="unsupported",
                sql="",
                explanation="The requested metric is ambiguous.",
            )
        ]
    )
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Show the best ones")
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "AMBIGUOUS_QUESTION"
    assert response.error.message == "The requested metric is ambiguous."
    assert response.attempts == 1


def test_provider_failure_is_not_retried(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider(
        [AppError("PROVIDER_UNAVAILABLE", "The provider is unavailable.", 503)]
    )
    response = make_agent(seeded_store, provider).ask(DEMO_ID, "Count the orders")
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "PROVIDER_UNAVAILABLE"
    assert len(provider.calls) == 1


def test_timeout_is_not_retried(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data", 5)
    dataset = store.create_dataset("Large")
    values = "\n".join(str(value) for value in range(2_000))
    store.upload_table(dataset["id"], "numbers.csv", f"value\n{values}\n".encode())
    provider = SequenceProvider(
        [proposal("SELECT COUNT(*) FROM numbers a CROSS JOIN numbers b CROSS JOIN numbers c")]
    )
    response = make_agent(store, provider, timeout_seconds=0.001).ask(
        dataset["id"], "Count combinations"
    )
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "QUERY_TIMEOUT"
    assert response.attempts == 1
    assert len(provider.calls) == 1


def test_missing_dataset_finishes_before_provider_call(seeded_store: DatasetStore) -> None:
    provider = SequenceProvider([proposal("SELECT 1")])
    response = make_agent(seeded_store, provider).ask(
        "00000000-0000-0000-0000-000000000000", "Count rows"
    )
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "DATASET_NOT_FOUND"
    assert response.attempts == 0
    assert provider.calls == []


def _schema() -> AgentSchema:
    return AgentSchema.model_validate(
        {
            "dataset_id": DEMO_ID,
            "name": "Retail Demo",
            "tables": [
                {
                    "name": "orders",
                    "row_count": 18,
                    "columns": [{"name": "order_id", "type": "TEXT"}],
                }
            ],
        }
    )


def test_openai_provider_requires_key_and_model() -> None:
    provider = OpenAISQLProvider(api_key="", model="")
    with pytest.raises(AppError) as caught:
        provider.generate("Count orders", _schema())
    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (
            AuthenticationError(
                "bad key",
                response=httpx2.Response(
                    401, request=httpx2.Request("POST", "https://api.openai.com/v1/responses")
                ),
                body=None,
            ),
            "PROVIDER_AUTH_FAILED",
        ),
        (
            APITimeoutError(httpx2.Request("POST", "https://api.openai.com/v1/responses")),
            "PROVIDER_TIMEOUT",
        ),
    ],
)
def test_openai_provider_maps_auth_and_timeout_errors(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    expected_code: str,
) -> None:
    class Responses:
        def parse(self, **_kwargs: Any) -> None:
            raise exception

    class Client:
        responses = Responses()

    monkeypatch.setattr("backend.app.agent.providers.OpenAI", lambda **_kwargs: Client())
    provider = OpenAISQLProvider(api_key="configured", model="configured")
    with pytest.raises(AppError) as caught:
        provider.generate("Count orders", _schema())
    assert caught.value.code == expected_code
    assert caught.value.retryable is False
