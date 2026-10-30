from __future__ import annotations

import json

from backend.app.agent.models import AgentSchema

SYSTEM_PROMPT = """You generate one SQLite analytical SELECT query for SQLInsights.
Use only the supplied dataset schema. Never use writes, DDL, PRAGMA, ATTACH, SQLite internal
tables, file functions, extensions, table-valued functions, compound queries, or recursive CTEs.
Use only these functions when needed: COUNT, SUM, AVG, MIN, MAX, ROUND, LOWER, UPPER, COALESCE,
DATE, DATETIME, STRFTIME, ABS, LENGTH, SUBSTR, TRIM, IFNULL, NULLIF, REPLACE, JULIANDAY,
UNIXEPOCH, and PRINTF. Produce SQLite syntax. If the question is ambiguous, unrelated, requests a
write, or cannot be answered from the schema, set disposition to unsupported, sql to an empty
string, and briefly explain why. Do not claim the query was executed and do not invent results."""


def build_provider_input(
    question: str,
    schema: AgentSchema,
    retry_feedback: str | None,
) -> list[dict[str, str]]:
    schema_payload = {
        "tables": [
            {
                "name": table.name,
                "columns": [column.model_dump() for column in table.columns],
            }
            for table in schema.tables
        ]
    }
    user_payload = {
        "question": question,
        "schema": schema_payload,
        "retry_feedback": retry_feedback,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))},
    ]
