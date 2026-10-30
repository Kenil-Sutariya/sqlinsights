from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

ChartType = Literal["Bar", "Line", "Scatter", "Pie"]
SUPPORTED_CHART_TYPES: tuple[ChartType, ...] = ("Bar", "Line", "Scatter", "Pie")
DATE_NAME_HINTS = ("date", "day", "month", "quarter", "week", "year", "time")


@dataclass(frozen=True)
class ChartOptions:
    available: tuple[ChartType, ...]
    default: ChartType | None
    reason: str | None = None


def result_frame(columns: list[str], rows: list[list[object]]) -> pd.DataFrame:
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("Result rows do not match the returned columns.")
    return pd.DataFrame(rows, columns=columns)


def chart_options(frame: pd.DataFrame) -> ChartOptions:
    if frame.empty:
        return ChartOptions((), None, "Empty results cannot be charted.")

    numeric = numeric_columns(frame)
    categories = category_columns(frame)
    dates = date_columns(frame)
    available: list[ChartType] = []

    if categories and numeric and 1 < len(frame) <= 100:
        available.append("Bar")
    if dates and numeric and len(frame) > 1:
        available.append("Line")
    if len(numeric) >= 2 and len(frame) > 1:
        available.append("Scatter")
    if categories and numeric and 1 < len(frame) <= 20 and pie_value_columns(frame):
        available.append("Pie")

    if not available:
        return ChartOptions(
            (),
            None,
            "The returned columns do not form a meaningful supported chart.",
        )
    default: ChartType = "Line" if "Line" in available else available[0]
    return ChartOptions(tuple(available), default)


def chart_axes(frame: pd.DataFrame, chart_type: ChartType) -> tuple[list[str], list[str]]:
    numeric = numeric_columns(frame)
    categories = category_columns(frame)
    if chart_type == "Line":
        return date_columns(frame), numeric
    if chart_type == "Scatter":
        return numeric, numeric
    if chart_type == "Pie":
        return categories, pie_value_columns(frame)
    if chart_type == "Bar":
        return categories, numeric
    raise ValueError("Unsupported chart type.")


def build_chart(frame: pd.DataFrame, chart_type: str, x: str, y: str) -> Figure:
    options = chart_options(frame)
    if chart_type not in options.available:
        raise ValueError("This chart type is not supported for the current result.")
    x_options, y_options = chart_axes(frame, chart_type)  # type: ignore[arg-type]
    if x not in x_options or y not in y_options:
        raise ValueError("The selected chart columns are not compatible with this chart type.")
    if chart_type == "Scatter" and x == y:
        raise ValueError("Scatter plots require two different numeric columns.")

    labels = {column: _humanize(column) for column in frame.columns}
    title = f"{labels[y]} by {labels[x]}"
    if chart_type == "Bar":
        figure = px.bar(frame, x=x, y=y, labels=labels, title=title)
    elif chart_type == "Line":
        plot_frame = frame.copy()
        plot_frame[x] = pd.to_datetime(plot_frame[x], errors="coerce")
        figure = px.line(plot_frame, x=x, y=y, markers=True, labels=labels, title=title)
    elif chart_type == "Scatter":
        figure = px.scatter(frame, x=x, y=y, labels=labels, title=title)
    else:
        figure = px.pie(frame, names=x, values=y, labels=labels, title=title)
    figure.update_layout(margin={"l": 16, "r": 16, "t": 56, "b": 16})
    return figure


def numeric_columns(frame: pd.DataFrame) -> list[str]:
    return [
        str(column)
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
    ]


def date_columns(frame: pd.DataFrame) -> list[str]:
    matches: list[str] = []
    for column in category_columns(frame):
        if not any(hint in column.casefold() for hint in DATE_NAME_HINTS):
            continue
        values = frame[column].dropna()
        if not values.empty and pd.to_datetime(values, errors="coerce").notna().all():
            matches.append(column)
    return matches


def category_columns(frame: pd.DataFrame) -> list[str]:
    numeric = set(numeric_columns(frame))
    return [str(column) for column in frame.columns if str(column) not in numeric]


def pie_value_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in numeric_columns(frame)
        if frame[column].dropna().ge(0).all() and frame[column].fillna(0).sum() > 0
    ]


def _humanize(column: object) -> str:
    return str(column).replace("_", " ").strip().title()
