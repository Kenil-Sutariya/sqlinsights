from __future__ import annotations

import operator
import time
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent.models import (
    AgentErrorInfo,
    AgentResponse,
    AgentSchema,
    SQLProposal,
)
from backend.app.agent.providers import SQLProvider
from backend.app.errors import AppError
from backend.app.services.dataset_store import DatasetStore
from backend.app.services.query_executor import QueryExecutor, QueryResult
from backend.app.services.schema import load_agent_schema
from backend.app.services.sql_policy import validate_sql

MAX_LLM_CALLS = 2
RECURSION_LIMIT = 12
RETRY_FEEDBACK = (
    "The previous proposal had invalid SQLite syntax or referenced columns that do not exist. "
    "Generate a different query using only the supplied schema."
)


class AgentState(TypedDict, total=False):
    dataset_id: str
    question: str
    mode: Literal["demo", "llm"]
    schema: AgentSchema
    proposal: SQLProposal | None
    validated_sql: str | None
    query_result: QueryResult
    attempts: int
    retry_feedback: str | None
    error: AgentErrorInfo | None
    formatted_response: AgentResponse
    final_response: AgentResponse
    trace: Annotated[list[str], operator.add]


class SQLAgent:
    def __init__(
        self,
        *,
        store: DatasetStore,
        executor: QueryExecutor,
        provider: SQLProvider,
        mode: str,
    ) -> None:
        if mode not in {"demo", "llm"}:
            raise ValueError("AI_MODE must be either 'demo' or 'llm'")
        self.store = store
        self.executor = executor
        self.provider = provider
        self.mode: Literal["demo", "llm"] = mode
        self.graph = self._build_graph()

    def ask(self, dataset_id: str, question: str) -> AgentResponse:
        started = time.monotonic()
        state = self.invoke_state(dataset_id, question)
        response = state["final_response"]
        elapsed_ms = max(0, round((time.monotonic() - started) * 1_000))
        return response.model_copy(update={"elapsed_ms": elapsed_ms})

    def invoke_state(self, dataset_id: str, question: str) -> AgentState:
        initial: AgentState = {
            "dataset_id": dataset_id,
            "question": question,
            "mode": self.mode,
            "attempts": 0,
            "retry_feedback": None,
            "error": None,
            "trace": [],
        }
        return self.graph.invoke(initial, config={"recursion_limit": RECURSION_LIMIT})

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("load_schema", self._load_schema)
        builder.add_node("plan_sql", self._plan_sql)
        builder.add_node("validate_sql", self._validate_sql)
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_node("format_result", self._format_result)
        builder.add_node("finish", self._finish)

        builder.add_edge(START, "load_schema")
        builder.add_conditional_edges(
            "load_schema",
            self._route_after_schema,
            {"plan_sql": "plan_sql", "finish": "finish"},
        )
        builder.add_conditional_edges(
            "plan_sql",
            self._route_after_plan,
            {"plan_sql": "plan_sql", "validate_sql": "validate_sql", "finish": "finish"},
        )
        builder.add_conditional_edges(
            "validate_sql",
            self._route_after_validation,
            {"plan_sql": "plan_sql", "execute_sql": "execute_sql", "finish": "finish"},
        )
        builder.add_conditional_edges(
            "execute_sql",
            self._route_after_execution,
            {"plan_sql": "plan_sql", "format_result": "format_result", "finish": "finish"},
        )
        builder.add_edge("format_result", "finish")
        builder.add_edge("finish", END)
        return builder.compile()

    def _load_schema(self, state: AgentState) -> AgentState:
        try:
            schema = AgentSchema.model_validate(load_agent_schema(self.store, state["dataset_id"]))
            return {"schema": schema, "error": None, "trace": ["load_schema"]}
        except AppError as exc:
            return {"error": _error_info(exc), "trace": ["load_schema"]}

    def _plan_sql(self, state: AgentState) -> AgentState:
        attempts = state.get("attempts", 0) + 1
        try:
            proposal = self.provider.generate(
                state["question"],
                state["schema"],
                state.get("retry_feedback"),
            )
            proposal = SQLProposal.model_validate(proposal)
            if proposal.disposition == "unsupported":
                raise AppError(
                    "AMBIGUOUS_QUESTION",
                    proposal.explanation or "The question cannot be answered from this schema.",
                    400,
                )
            return {
                "attempts": attempts,
                "proposal": proposal,
                "validated_sql": None,
                "error": None,
                "retry_feedback": None,
                "trace": ["plan_sql"],
            }
        except AppError as exc:
            return {
                "attempts": attempts,
                "proposal": None,
                "error": _error_info(exc),
                "retry_feedback": RETRY_FEEDBACK if exc.retryable else None,
                "trace": ["plan_sql"],
            }
        except Exception as exc:
            malformed = AppError(
                "PROVIDER_MALFORMED_OUTPUT",
                "The provider returned malformed structured output.",
                503,
                retryable=True,
            )
            malformed.__cause__ = exc
            return {
                "attempts": attempts,
                "proposal": None,
                "error": _error_info(malformed),
                "retry_feedback": RETRY_FEEDBACK,
                "trace": ["plan_sql"],
            }

    def _validate_sql(self, state: AgentState) -> AgentState:
        proposal = state["proposal"]
        if proposal is None:
            return {"error": _internal_error(), "trace": ["validate_sql"]}
        allowed_tables = frozenset(table.name for table in state["schema"].tables)
        try:
            validated = validate_sql(
                proposal.sql,
                allowed_tables,
                max_sql_length=self.executor.max_sql_length,
            )
            return {
                "validated_sql": validated.sql,
                "error": None,
                "trace": ["validate_sql"],
            }
        except AppError as exc:
            return {
                "error": _error_info(exc),
                "retry_feedback": RETRY_FEEDBACK if exc.retryable else None,
                "trace": ["validate_sql"],
            }

    def _execute_sql(self, state: AgentState) -> AgentState:
        sql = state.get("validated_sql")
        if not sql:
            return {"error": _internal_error(), "trace": ["execute_sql"]}
        try:
            result = self.executor.execute(state["dataset_id"], sql)
            return {"query_result": result, "error": None, "trace": ["execute_sql"]}
        except AppError as exc:
            return {
                "error": _error_info(exc),
                "retry_feedback": RETRY_FEEDBACK if exc.retryable else None,
                "trace": ["execute_sql"],
            }

    def _format_result(self, state: AgentState) -> AgentState:
        result = state["query_result"]
        proposal = state["proposal"]
        if proposal is None:
            return {"error": _internal_error(), "trace": ["format_result"]}
        is_empty = result.row_count_returned == 0
        warnings = (
            ["Result rows were truncated to the configured limit."] if result.truncated else []
        )
        response = AgentResponse(
            status="empty" if is_empty else "success",
            mode=self.mode,
            answer=(
                "No rows matched the query."
                if is_empty
                else f"The query returned {result.row_count_returned} row(s)."
            ),
            explanation=proposal.explanation,
            sql=result.sql,
            columns=result.columns,
            rows=result.rows,
            row_count_returned=result.row_count_returned,
            truncated=result.truncated,
            attempts=state.get("attempts", 0),
            elapsed_ms=result.elapsed_ms,
            warnings=warnings,
            error=None,
        )
        return {"formatted_response": response, "trace": ["format_result"]}

    def _finish(self, state: AgentState) -> AgentState:
        response = state.get("formatted_response")
        if response is None:
            error = state.get("error") or _internal_error()
            response = AgentResponse(
                status="error",
                mode=self.mode,
                answer="",
                explanation="",
                sql=None,
                columns=[],
                rows=[],
                row_count_returned=0,
                truncated=False,
                attempts=state.get("attempts", 0),
                elapsed_ms=0,
                warnings=[],
                error=error,
            )
        return {"final_response": response, "trace": ["finish"]}

    @staticmethod
    def _route_after_schema(state: AgentState) -> Literal["plan_sql", "finish"]:
        return "finish" if state.get("error") else "plan_sql"

    @staticmethod
    def _route_after_plan(state: AgentState) -> Literal["plan_sql", "validate_sql", "finish"]:
        return _retry_or_finish(state, "validate_sql")

    @staticmethod
    def _route_after_validation(
        state: AgentState,
    ) -> Literal["plan_sql", "execute_sql", "finish"]:
        return _retry_or_finish(state, "execute_sql")

    @staticmethod
    def _route_after_execution(
        state: AgentState,
    ) -> Literal["plan_sql", "format_result", "finish"]:
        return _retry_or_finish(state, "format_result")


def _retry_or_finish(state: AgentState, success_route: str):
    error = state.get("error")
    if error is None:
        return success_route
    if error.retryable and state.get("attempts", 0) < MAX_LLM_CALLS:
        return "plan_sql"
    return "finish"


def _error_info(exc: AppError) -> AgentErrorInfo:
    return AgentErrorInfo(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )


def _internal_error() -> AgentErrorInfo:
    return AgentErrorInfo(
        code="WORKFLOW_ERROR",
        message="The query workflow could not complete.",
        status_code=500,
    )
