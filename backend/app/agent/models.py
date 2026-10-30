from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SchemaColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str


class SchemaTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    row_count: int
    columns: list[SchemaColumn]


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    name: str
    tables: list[SchemaTable]


class SQLProposal(BaseModel):
    """Structured provider output; every field is required for API schema compatibility."""

    model_config = ConfigDict(extra="forbid")

    disposition: Literal["query", "unsupported"]
    sql: str
    explanation: str = Field(max_length=1_000)

    @model_validator(mode="after")
    def validate_disposition(self) -> SQLProposal:
        if self.disposition == "query" and not self.sql.strip():
            raise ValueError("query proposals require SQL")
        if self.disposition == "unsupported" and self.sql.strip():
            raise ValueError("unsupported proposals must not contain SQL")
        return self


class AgentErrorInfo(BaseModel):
    code: str
    message: str
    status_code: int
    retryable: bool = False


class AgentResponse(BaseModel):
    status: Literal["success", "empty", "error"]
    mode: Literal["demo", "llm"]
    answer: str
    explanation: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count_returned: int
    truncated: bool
    attempts: int
    elapsed_ms: int
    warnings: list[str]
    error: AgentErrorInfo | None = None
