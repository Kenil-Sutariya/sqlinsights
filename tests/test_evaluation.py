from __future__ import annotations

from evaluation.run_eval import evaluate, load_cases


def test_fixture_has_required_coverage() -> None:
    cases = load_cases()
    categories = {case["category"] for case in cases}
    assert len(cases) >= 25
    assert len({case["id"] for case in cases}) == len(cases)
    assert {
        "simple_filter",
        "aggregation",
        "group_by",
        "date_filter",
        "multiple_conditions",
    } <= categories
    assert any("join" in category for category in categories)
    assert {"ambiguous", "invalid_question", "unsafe"} <= categories


def test_mock_evaluation_matches_actual_database_results() -> None:
    report = evaluate(mode="mock")
    assert report["metadata"]["question_count"] == 25
    assert report["metadata"]["is_real_llm_evaluation"] is False
    assert report["metrics"]["passed_cases"] == 25
    assert report["metrics"]["task_success_rate"] == 1.0
    assert report["metrics"]["correct_result_rate"] == 1.0
    assert report["metrics"]["unsafe_query_rejection_rate"] == 1.0
    assert all(record["generated_sql"] or record["error_category"] for record in report["cases"])


def test_demo_evaluation_is_labeled_and_only_runs_declared_examples() -> None:
    report = evaluate(mode="demo")
    assert report["metadata"]["question_count"] == 8
    assert "not an LLM" in report["metadata"]["provider"]
    assert report["metrics"]["passed_cases"] == 8
