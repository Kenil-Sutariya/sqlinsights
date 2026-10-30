from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend.app.errors import AppError
from backend.app.services.dataset_store import DEMO_ID, DatasetStore
from backend.app.services.query_executor import QueryExecutor, _restricted_connection
from backend.app.services.sql_policy import ValidatedQuery


@pytest.fixture
def seeded_store(tmp_path: Path) -> DatasetStore:
    project_root = Path(__file__).resolve().parents[1]
    store = DatasetStore(tmp_path / "data", 5)
    store.seed_demo(project_root / "sample_data")
    return store


def test_joins_aggregates_filters_grouping_sorting_and_cte(seeded_store: DatasetStore) -> None:
    executor = QueryExecutor(seeded_store)
    result = executor.execute(
        DEMO_ID,
        """
        WITH revenue AS (
          SELECT product_id, SUM(quantity * unit_price) AS total
          FROM orders
          WHERE order_date >= '2026-09-01'
          GROUP BY product_id
        )
        SELECT p.product_name, ROUND(r.total, 2) AS revenue
        FROM revenue AS r
        JOIN products AS p ON p.product_id = r.product_id
        ORDER BY revenue DESC
        LIMIT 3
        """,
    )
    assert result.columns == ["product_name", "revenue"]
    assert result.rows == [["USB-C Hub", 359.1], ["Wireless Mouse", 252.0], ["Desk Lamp", 220.5]]
    assert result.row_count_returned == len(result.rows) == 3
    assert result.truncated is False
    assert result.sql.startswith("WITH")


def test_safe_subquery_executes(seeded_store: DatasetStore) -> None:
    result = QueryExecutor(seeded_store).execute(
        DEMO_ID,
        "SELECT COUNT(*) AS count FROM (SELECT * FROM orders WHERE quantity >= 5)",
    )
    assert result.rows == [[6]]


def test_row_cap_and_truncation_are_truthful(seeded_store: DatasetStore) -> None:
    result = QueryExecutor(seeded_store, max_result_rows=3).execute(
        DEMO_ID, "SELECT order_id FROM orders ORDER BY order_id"
    )
    assert result.rows == [["O0001"], ["O0002"], ["O0003"]]
    assert result.row_count_returned == 3
    assert result.truncated is True


def test_policy_blocks_cross_dataset_table(seeded_store: DatasetStore) -> None:
    other = seeded_store.create_dataset("Other")
    seeded_store.upload_table(other["id"], "private.csv", b"secret\nvalue\n")
    executor = QueryExecutor(seeded_store)
    with pytest.raises(AppError) as caught:
        executor.execute(DEMO_ID, "SELECT * FROM private")
    assert caught.value.code == "SQL_POLICY_DENIED"


def test_forged_validated_write_is_denied_and_database_unchanged(
    seeded_store: DatasetStore,
) -> None:
    db_path, allowed_tables = seeded_store.query_target(DEMO_ID)
    before_checksum = hashlib.sha256(db_path.read_bytes()).hexdigest()
    executor = QueryExecutor(seeded_store)

    forged = ValidatedQuery(
        sql="UPDATE orders SET quantity = 0",
        referenced_tables=frozenset({"orders"}),
    )
    with pytest.raises(AppError) as caught:
        executor._execute_validated(db_path, allowed_tables, forged)
    assert caught.value.code == "SQL_ACCESS_DENIED"

    after_checksum = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after_checksum == before_checksum
    assert executor.execute(DEMO_ID, "SELECT SUM(quantity) FROM orders").rows == [[66]]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE forbidden (value TEXT)",
        "DELETE FROM orders",
        "PRAGMA database_list",
        "ATTACH DATABASE '/tmp/elsewhere.db' AS other",
    ],
)
def test_restricted_connection_denies_direct_bypass(
    seeded_store: DatasetStore,
    sql: str,
) -> None:
    db_path, allowed_tables = seeded_store.query_target(DEMO_ID)
    with _restricted_connection(db_path, allowed_tables, timeout_seconds=1) as (
        connection,
        guards,
    ):
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(sql)
        assert guards.access_denied is True


def test_expensive_cross_join_is_interrupted(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data", 5)
    dataset = store.create_dataset("Large")
    rows = "\n".join(str(value) for value in range(2_000))
    store.upload_table(dataset["id"], "numbers.csv", f"value\n{rows}\n".encode())
    executor = QueryExecutor(store, timeout_seconds=0.001)

    with pytest.raises(AppError) as caught:
        executor.execute(
            dataset["id"],
            "SELECT COUNT(*) FROM numbers a CROSS JOIN numbers b CROSS JOIN numbers c",
        )
    assert caught.value.code == "QUERY_TIMEOUT"
    assert caught.value.status_code == 504


def test_execution_errors_do_not_reuse_previous_results(seeded_store: DatasetStore) -> None:
    executor = QueryExecutor(seeded_store)
    successful = executor.execute(DEMO_ID, "SELECT COUNT(*) FROM orders")
    assert successful.rows == [[18]]
    with pytest.raises(AppError) as caught:
        executor.execute(DEMO_ID, "SELECT missing_column FROM orders")
    assert caught.value.code == "QUERY_EXECUTION_ERROR"
