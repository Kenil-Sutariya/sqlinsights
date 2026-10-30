from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from backend.app.errors import AppError

DEFAULT_MAX_SQL_LENGTH = 20_000

# These are deliberately limited to deterministic analytical functions needed by the MVP.
ALLOWED_FUNCTIONS = frozenset(
    {
        "abs",
        "avg",
        "coalesce",
        "count",
        "date",
        "datetime",
        "ifnull",
        "julianday",
        "length",
        "lower",
        "ltrim",
        "max",
        "min",
        "nullif",
        "printf",
        "replace",
        "round",
        "rtrim",
        "strftime",
        "substr",
        "substring",
        "sum",
        "trim",
        "unixepoch",
        "upper",
    }
)

INTERNAL_TABLE_PREFIX = "sqlite_"
COMPOUND_QUERY_TYPES = (exp.Union, exp.Intersect, exp.Except)


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    referenced_tables: frozenset[str]


def validate_sql(
    sql: str,
    allowed_tables: set[str] | frozenset[str],
    *,
    max_sql_length: int = DEFAULT_MAX_SQL_LENGTH,
) -> ValidatedQuery:
    """Parse and allowlist one read-only SQLite SELECT statement."""
    if not sql or not sql.strip():
        _deny("A query is required.")
    if len(sql) > max_sql_length:
        _deny("The proposed query is too long.")

    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except (ParseError, ValueError, RecursionError) as exc:
        raise AppError(
            "SQL_POLICY_DENIED",
            "The proposed query is not valid SQLite SQL.",
            422,
            retryable=True,
        ) from exc

    parsed = [statement for statement in statements if statement is not None]
    if len(parsed) != 1:
        _deny("Exactly one SQL statement is required.")
    expression = parsed[0]
    if sum(1 for _node in expression.walk()) > 2_000:
        _deny("The proposed query is too complex.")
    if not isinstance(expression, exp.Select):
        _deny("Only SELECT queries are allowed.")
    if any(isinstance(node, COMPOUND_QUERY_TYPES) for node in expression.walk()):
        _deny("Compound queries are not supported.")
    if expression.find(exp.Into):
        _deny("SELECT INTO is not allowed.")

    allowed = {name.lower() for name in allowed_tables}
    cte_aliases = _validate_ctes(expression, allowed)
    referenced_tables: set[str] = set()

    for table in expression.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            _deny("Table-valued functions are not allowed.")
        if table.args.get("db") is not None or table.args.get("catalog") is not None:
            _deny("Cross-database references are not allowed.")
        table_name = table.name.lower()
        if table_name.startswith(INTERNAL_TABLE_PREFIX):
            _deny("SQLite internal tables are not allowed.")
        if table_name in cte_aliases:
            continue
        if table_name not in allowed:
            _deny("The query references a table outside the selected dataset.")
        referenced_tables.add(table_name)

    for function in expression.find_all(exp.Func):
        # sqlglot models boolean AND/OR connectors as Func subclasses even though
        # they are SQL operators rather than callable functions.
        if isinstance(function, exp.Connector):
            continue
        function_name = _function_name(function)
        if function_name not in ALLOWED_FUNCTIONS:
            _deny("The query uses a function that is not allowed.")

    try:
        canonical_sql = expression.sql(dialect="sqlite", pretty=False)
    except (ValueError, TypeError) as exc:
        raise AppError(
            "SQL_POLICY_DENIED", "The proposed query cannot be normalized safely.", 422
        ) from exc
    if not canonical_sql:
        _deny("The proposed query cannot be normalized safely.")
    return ValidatedQuery(sql=canonical_sql, referenced_tables=frozenset(referenced_tables))


def _validate_ctes(expression: exp.Select, allowed_tables: set[str]) -> set[str]:
    with_clause = expression.args.get("with_")
    if with_clause is None:
        return set()
    if with_clause.args.get("recursive"):
        _deny("Recursive CTEs are not supported.")

    aliases: set[str] = set()
    for cte in expression.find_all(exp.CTE):
        alias = cte.alias_or_name.lower()
        if not alias or alias in aliases or alias in allowed_tables:
            _deny("CTE aliases must be unique and cannot shadow dataset tables.")
        if not isinstance(cte.this, exp.Select):
            _deny("Only read-only SELECT CTEs are supported.")
        aliases.add(alias)
    return aliases


def _function_name(function: exp.Func) -> str:
    if isinstance(function, exp.Anonymous):
        return function.name.lower()
    return function.sql_name().lower()


def _deny(message: str) -> None:
    raise AppError("SQL_POLICY_DENIED", message, 422)
