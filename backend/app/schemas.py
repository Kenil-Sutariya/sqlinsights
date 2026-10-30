from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str
    mode: str


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DatasetSummary(BaseModel):
    id: str
    name: str
    table_count: int
    created_at: str
    protected: bool = False


class ColumnInfo(BaseModel):
    name: str
    source_name: str
    type: str


class TableInfo(BaseModel):
    name: str
    source_filename: str
    row_count: int
    columns: list[ColumnInfo]


class DatasetSchema(BaseModel):
    id: str
    name: str
    tables: list[TableInfo]


class PreviewResponse(BaseModel):
    table: str
    columns: list[str]
    rows: list[list[Any]]
    limit: int


class DeleteResponse(BaseModel):
    status: str
    dataset_id: str


class AskRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2_000)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question cannot be blank")
        return cleaned


class AskResponse(BaseModel):
    status: Literal["success", "empty"]
    mode: Literal["demo", "llm"]
    answer: str
    explanation: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count_returned: int
    truncated: bool
    attempts: int
    elapsed_ms: int
    warnings: list[str]
