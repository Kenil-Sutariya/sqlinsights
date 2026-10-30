from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.errors import AppError
from backend.app.services.dataset_store import DatasetStore
from backend.app.services.sql_policy import ALLOWED_FUNCTIONS, ValidatedQuery, validate_sql

# SQLite implements operators such as LIKE through runtime functions even though SQLGlot does not
# represent them as function-call AST nodes.
SQLITE_RUNTIME_FUNCTIONS = ALLOWED_FUNCTIONS | {"glob", "like"}


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count_returned: int
    truncated: bool
    elapsed_ms: int


@dataclass
class _ExecutionGuards:
    timed_out: bool = False
    access_denied: bool = False


class QueryExecutor:
    def __init__(
        self,
        store: DatasetStore,
        *,
        max_result_rows: int = 200,
        timeout_seconds: float = 5.0,
        max_sql_length: int = 20_000,
    ) -> None:
        if max_result_rows < 1:
            raise ValueError("max_result_rows must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.store = store
        self.max_result_rows = max_result_rows
        self.timeout_seconds = timeout_seconds
        self.max_sql_length = max_sql_length

    def execute(self, dataset_id: str, sql: str) -> QueryResult:
        db_path, allowed_tables = self.store.query_target(dataset_id)
        validated = validate_sql(
            sql,
            allowed_tables,
            max_sql_length=self.max_sql_length,
        )
        return self._execute_validated(db_path, allowed_tables, validated)

    def _execute_validated(
        self,
        db_path: Path,
        allowed_tables: frozenset[str],
        validated: ValidatedQuery,
    ) -> QueryResult:
        started = time.monotonic()
        with _restricted_connection(
            db_path,
            allowed_tables,
            timeout_seconds=self.timeout_seconds,
        ) as (connection, guards):
            try:
                cursor = connection.execute(validated.sql)
                columns = [description[0] for description in cursor.description or []]
                fetched = cursor.fetchmany(self.max_result_rows + 1)
            except sqlite3.Error as exc:
                if guards.timed_out:
                    raise AppError(
                        "QUERY_TIMEOUT", "The query exceeded its execution deadline.", 504
                    ) from exc
                if guards.access_denied:
                    raise AppError(
                        "SQL_ACCESS_DENIED", "SQLite denied the query operation.", 422
                    ) from exc
                raise AppError(
                    "QUERY_EXECUTION_ERROR",
                    "The query could not be executed.",
                    422,
                    retryable=True,
                ) from exc

        truncated = len(fetched) > self.max_result_rows
        rows = [list(row) for row in fetched[: self.max_result_rows]]
        elapsed_ms = max(0, round((time.monotonic() - started) * 1_000))
        return QueryResult(
            sql=validated.sql,
            columns=columns,
            rows=rows,
            row_count_returned=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
        )


@contextmanager
def _restricted_connection(
    db_path: Path,
    allowed_tables: frozenset[str] | set[str],
    *,
    timeout_seconds: float,
) -> Iterator[tuple[sqlite3.Connection, _ExecutionGuards]]:
    """Open one fresh read-only SQLite connection with deny-by-default authorization."""
    resolved_path = db_path.resolve(strict=True)
    uri = f"{resolved_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=0.25)
    guards = _ExecutionGuards()
    deadline = time.monotonic() + timeout_seconds
    allowed = {name.lower() for name in allowed_tables}

    try:
        connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only=ON")

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database: str | None,
            _source: str | None,
        ) -> int:
            if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                table_name = (arg1 or "").lower()
                # SQLite reports database=None for COUNT(*) because no concrete column is read.
                if database in {"main", None} and table_name in allowed:
                    return sqlite3.SQLITE_OK
            elif action == sqlite3.SQLITE_FUNCTION:
                function_name = (arg2 or arg1 or "").lower()
                if function_name in SQLITE_RUNTIME_FUNCTIONS:
                    return sqlite3.SQLITE_OK
            guards.access_denied = True
            return sqlite3.SQLITE_DENY

        def check_deadline() -> int:
            if time.monotonic() >= deadline:
                guards.timed_out = True
                return 1
            return 0

        connection.set_authorizer(authorize)
        connection.set_progress_handler(check_deadline, 1_000)
        yield connection, guards
    finally:
        connection.set_progress_handler(None, 0)
        connection.set_authorizer(None)
        connection.close()
