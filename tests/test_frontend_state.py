from __future__ import annotations

from frontend.state import clear_query_state, initialize_state, sync_active_dataset


def test_dataset_change_clears_stale_query_and_chart_state() -> None:
    state = {
        "active_dataset_id": "dataset-a",
        "last_result": {"rows": [[1]]},
        "last_error": {"code": "OLD"},
        "last_question": "Old question",
        "query_input": "Old question",
        "chart_type": "Bar",
        "chart_x": "name",
        "chart_y": "value",
    }
    assert sync_active_dataset(state, "dataset-b") is True
    assert state["active_dataset_id"] == "dataset-b"
    assert state["last_result"] is None
    assert state["last_error"] is None
    assert state["last_question"] == ""
    assert state["query_input"] == ""
    assert "chart_type" not in state


def test_same_dataset_preserves_result_and_initialization_is_idempotent() -> None:
    state: dict = {"active_dataset_id": "dataset-a", "last_result": {"rows": [[1]]}}
    initialize_state(state)
    initialize_state(state)
    assert sync_active_dataset(state, "dataset-a") is False
    assert state["last_result"] == {"rows": [[1]]}


def test_clearing_query_can_preserve_input() -> None:
    state = {"query_input": "Reusable question", "last_result": {"rows": []}}
    clear_query_state(state)
    assert state["query_input"] == "Reusable question"
    assert state["last_result"] is None
