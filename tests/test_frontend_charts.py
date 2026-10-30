from __future__ import annotations

import pandas as pd
import pytest

from frontend.charts import build_chart, chart_axes, chart_options, result_frame


def test_category_and_numeric_result_supports_bar_and_pie() -> None:
    frame = result_frame(["category", "revenue"], [["A", 10.0], ["B", 5.0]])
    options = chart_options(frame)
    assert options.available == ("Bar", "Pie")
    assert options.default == "Bar"
    assert chart_axes(frame, "Bar") == (["category"], ["revenue"])
    assert build_chart(frame, "Bar", "category", "revenue").data[0].type == "bar"
    assert build_chart(frame, "Pie", "category", "revenue").data[0].type == "pie"


def test_date_result_defaults_to_line_chart() -> None:
    frame = result_frame(
        ["order_month", "revenue"],
        [["2026-08-01", 10.0], ["2026-09-01", 12.0]],
    )
    options = chart_options(frame)
    assert "Line" in options.available
    assert options.default == "Line"
    assert build_chart(frame, "Line", "order_month", "revenue").data[0].mode == "lines+markers"


def test_two_numeric_columns_support_scatter() -> None:
    frame = pd.DataFrame({"quantity": [1, 2, 3], "revenue": [4.0, 7.0, 8.0]})
    assert chart_options(frame).available == ("Scatter",)
    assert build_chart(frame, "Scatter", "quantity", "revenue").data[0].type == "scatter"


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(),
        pd.DataFrame({"count": [18]}),
        pd.DataFrame({"name": ["only text", "still text"]}),
    ],
)
def test_empty_or_unvisualizable_results_fall_back_to_table(frame: pd.DataFrame) -> None:
    options = chart_options(frame)
    assert options.available == ()
    assert options.default is None
    assert options.reason


def test_unsupported_chart_or_malformed_rows_are_rejected() -> None:
    frame = pd.DataFrame({"category": ["A", "B"], "revenue": [1, 2]})
    with pytest.raises(ValueError, match="not supported"):
        build_chart(frame, "Scatter", "category", "revenue")
    with pytest.raises(ValueError, match="do not match"):
        result_frame(["a", "b"], [[1]])
