from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "active_dataset_id": None,
    "last_result": None,
    "last_error": None,
    "last_question": "",
    "query_input": "",
    "query_in_flight": False,
    "workspace_version": 0,
    "flash_message": None,
}

CHART_STATE_KEYS = ("chart_type", "chart_x", "chart_y")


def initialize_state(state: MutableMapping[str, Any]) -> None:
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, value)


def sync_active_dataset(state: MutableMapping[str, Any], dataset_id: str) -> bool:
    previous = state.get("active_dataset_id")
    state["active_dataset_id"] = dataset_id
    if previous is None or previous == dataset_id:
        return False
    clear_query_state(state, clear_input=True)
    return True


def clear_query_state(state: MutableMapping[str, Any], *, clear_input: bool = False) -> None:
    state["last_result"] = None
    state["last_error"] = None
    state["last_question"] = ""
    if clear_input:
        state["query_input"] = ""
    clear_chart_state(state)


def clear_chart_state(state: MutableMapping[str, Any]) -> None:
    for key in CHART_STATE_KEYS:
        state.pop(key, None)
