from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.agent.demo import DEMO_EXAMPLES, DemoSQLProvider  # noqa: E402
from backend.app.agent.graph import SQLAgent  # noqa: E402
from backend.app.agent.models import AgentSchema, SQLProposal  # noqa: E402
from backend.app.services.dataset_store import DEMO_ID, DatasetStore  # noqa: E402
from backend.app.services.query_executor import QueryExecutor  # noqa: E402

DEFAULT_CASES = Path(__file__).with_name("questions.jsonl")


class FixtureProvider:
    """Deterministic proposal provider for offline result evaluation; not an LLM."""

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        self.proposals = {
            case["question"]: SQLProposal.model_validate(case["proposal"]) for case in cases
        }

    def generate(
        self,
        question: str,
        _schema: AgentSchema,
        _retry_feedback: str | None = None,
    ) -> SQLProposal:
        return self.proposals[question]


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    payload = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(payload) < 25:
        raise ValueError("Evaluation fixture must contain at least 25 cases.")
    required = {
        "id",
        "category",
        "question",
        "needed_tables",
        "expected_behavior",
        "proposal",
        "reference_sql",
        "expected",
    }
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for case in payload:
        if not required <= case.keys():
            raise ValueError("Every evaluation case must contain the required fields.")
        if case["id"] in seen_ids or case["question"] in seen_questions:
            raise ValueError("Evaluation case IDs and questions must be unique.")
        SQLProposal.model_validate(case["proposal"])
        if not isinstance(case["needed_tables"], list):
            raise ValueError("needed_tables must be a list.")
        seen_ids.add(case["id"])
        seen_questions.add(case["question"])
    return payload


def evaluate(*, mode: str, cases_path: Path = DEFAULT_CASES) -> dict[str, Any]:
    all_cases = load_cases(cases_path)
    if mode == "demo":
        demo_questions = {example.question for example in DEMO_EXAMPLES}
        cases = [case for case in all_cases if case["question"] in demo_questions]
        provider = DemoSQLProvider()
        agent_mode = "demo"
        provider_label = "predefined demo registry (deterministic, not an LLM)"
    elif mode == "mock":
        cases = all_cases
        provider = FixtureProvider(cases)
        agent_mode = "llm"
        provider_label = "fixture provider (deterministic, not an LLM)"
    else:
        raise ValueError("mode must be 'mock' or 'demo'")

    with tempfile.TemporaryDirectory(prefix="sqlinsights-eval-") as temp_dir:
        store = DatasetStore(Path(temp_dir) / "data", 5)
        store.seed_demo(PROJECT_ROOT / "sample_data")
        executor = QueryExecutor(store)
        _verify_references(executor, cases)
        agent = SQLAgent(
            store=store,
            executor=executor,
            provider=provider,
            mode=agent_mode,
        )
        records = [_evaluate_case(agent, case) for case in cases]

    latencies = sorted(record["latency_ms"] for record in records)
    result_records = [
        record for record in records if record["expected_result"]["status"] in {"success", "empty"}
    ]
    unsafe_records = [record for record in records if record["category"] == "unsafe"]
    error_categories = Counter(
        record["error_category"] for record in records if record["error_category"] is not None
    )
    passed = sum(record["passed"] for record in records)
    correct_results = sum(record["passed"] for record in result_records)
    unsafe_passed = sum(record["passed"] for record in unsafe_records)
    return {
        "metadata": {
            "evaluated_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "provider": provider_label,
            "dataset": "Retail Demo synthetic fixture",
            "question_count": len(records),
            "result_comparison": "columns and executed rows; SQL string similarity is not scored",
            "reference_checks": "hard-coded expectations verified with hand-authored SQL",
            "is_real_llm_evaluation": False,
        },
        "metrics": {
            "task_success_rate": _rate(passed, len(records)),
            "correct_result_rate": _rate(correct_results, len(result_records)),
            "unsafe_query_rejection_rate": _rate(unsafe_passed, len(unsafe_records)),
            "passed_cases": passed,
            "result_cases": len(result_records),
            "unsafe_cases": len(unsafe_records),
            "median_latency_ms": statistics.median(latencies) if latencies else None,
            "p95_latency_ms": _nearest_rank(latencies, 0.95),
            "observed_error_categories": dict(sorted(error_categories.items())),
        },
        "cases": records,
    }


def _verify_references(executor: QueryExecutor, cases: list[dict[str, Any]]) -> None:
    """Fail closed if a fixture expectation no longer matches the synthetic database."""
    for case in cases:
        expected = case["expected"]
        reference_sql = case["reference_sql"]
        if expected["status"] not in {"success", "empty"}:
            if reference_sql is not None:
                raise ValueError(f"Error case {case['id']} must not contain reference SQL.")
            continue
        if not isinstance(reference_sql, str) or not reference_sql.strip():
            raise ValueError(f"Result case {case['id']} requires reference SQL.")
        result = executor.execute(DEMO_ID, reference_sql)
        observed_status = "empty" if not result.rows else "success"
        if (
            observed_status != expected["status"]
            or result.columns != expected["columns"]
            or not _rows_equal(result.rows, expected["rows"])
        ):
            raise ValueError(f"Reference result mismatch for {case['id']}.")


def _evaluate_case(agent: SQLAgent, case: dict[str, Any]) -> dict[str, Any]:
    response = agent.ask(DEMO_ID, case["question"])
    actual = {
        "status": response.status,
        "columns": response.columns,
        "rows": response.rows,
        "error_code": response.error.code if response.error else None,
    }
    expected = case["expected"]
    passed = response.status == expected["status"]
    if expected["status"] in {"success", "empty"}:
        passed = (
            passed
            and response.columns == expected["columns"]
            and _rows_equal(response.rows, expected["rows"])
        )
    else:
        passed = (
            passed and response.error is not None and response.error.code == expected["error_code"]
        )
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected_behavior": case["expected_behavior"],
        "generated_sql": response.sql or case["proposal"]["sql"] or None,
        "actual_execution_result": actual,
        "expected_result": expected,
        "passed": passed,
        "error_category": response.error.code if response.error else None,
        "latency_ms": response.elapsed_ms,
    }


def _rows_equal(actual: list[list[Any]], expected: list[list[Any]]) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected, strict=True):
        if len(actual_row) != len(expected_row):
            return False
        for actual_value, expected_value in zip(actual_row, expected_row, strict=True):
            if isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)):
                if not math.isclose(actual_value, expected_value, rel_tol=1e-9, abs_tol=1e-9):
                    return False
            elif actual_value != expected_value:
                return False
    return True


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate SQLInsights against deterministic synthetic-data expectations."
    )
    parser.add_argument("--mode", choices=("mock", "demo"), default="mock")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(mode=args.mode, cases_path=args.cases)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    summary = {"metadata": report["metadata"], "metrics": report["metrics"]}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if report["metrics"]["passed_cases"] != report["metadata"]["question_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
