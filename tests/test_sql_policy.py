from __future__ import annotations

import pytest

from backend.app.errors import AppError
from backend.app.services.sql_policy import validate_sql

TABLES = frozenset({"orders", "products", "customers"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT order_id, quantity FROM orders WHERE quantity >= 2 ORDER BY quantity DESC LIMIT 5",
        (
            "SELECT p.category, SUM(o.quantity * o.unit_price) AS revenue "
            "FROM orders AS o JOIN products AS p ON p.product_id = o.product_id "
            "GROUP BY p.category ORDER BY revenue DESC"
        ),
        "SELECT * FROM (SELECT order_id FROM orders WHERE order_date >= '2026-09-01')",
        (
            "WITH monthly AS (SELECT product_id, SUM(quantity) AS units FROM orders "
            "GROUP BY product_id) SELECT product_id, units FROM monthly ORDER BY units DESC"
        ),
        "SELECT COUNT(*), ROUND(AVG(unit_price), 2), MAX(quantity) FROM orders",
        "SELECT DATE(order_date), LOWER(order_id), COALESCE(product_id, '') FROM orders",
        "SELECT order_id FROM orders WHERE order_id LIKE 'O00%'",
    ],
)
def test_approved_selects_are_canonicalized(sql: str) -> None:
    validated = validate_sql(sql, TABLES)
    assert validated.sql.startswith(("SELECT", "WITH"))
    assert validated.referenced_tables <= TABLES


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "SELECT * FROM orders; DELETE FROM orders",
        "PRAGMA database_list",
        "ATTACH DATABASE '/tmp/other.db' AS other",
        "DETACH DATABASE other",
        "UPDATE orders SET quantity = 0",
        "INSERT INTO orders (order_id) VALUES ('x')",
        "DELETE FROM orders",
        "CREATE TABLE stolen (value TEXT)",
        "EXPLAIN SELECT * FROM orders",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('x')",
        "SELECT readfile('/etc/passwd')",
        "SELECT mystery_function(quantity) FROM orders",
        "SELECT * FROM other.orders",
        "SELECT * FROM missing_table",
        "SELECT * FROM json_each('[1,2]')",
        "SELECT * FROM orders UNION SELECT * FROM products",
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT * FROM n",
        "WITH orders AS (SELECT 1) SELECT * FROM orders",
        "",
        "SELECT (",
    ],
)
def test_unsafe_or_unsupported_sql_is_denied(sql: str) -> None:
    with pytest.raises(AppError) as caught:
        validate_sql(sql, TABLES)
    assert caught.value.code == "SQL_POLICY_DENIED"
    assert caught.value.status_code == 422


def test_safe_subquery_is_explicitly_supported() -> None:
    validated = validate_sql("SELECT * FROM (SELECT * FROM orders) WHERE 1 = 1", TABLES)
    assert validated.referenced_tables == {"orders"}


def test_boolean_connectors_are_allowed() -> None:
    validated = validate_sql(
        "SELECT order_id FROM orders WHERE quantity > 1 AND unit_price > 0",
        TABLES,
    )

    assert " AND " in validated.sql


def test_sql_length_is_bounded_before_parse() -> None:
    with pytest.raises(AppError) as caught:
        validate_sql("SELECT '" + ("x" * 100) + "'", TABLES, max_sql_length=20)
    assert caught.value.code == "SQL_POLICY_DENIED"
