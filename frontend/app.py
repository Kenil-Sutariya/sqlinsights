from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.api_client import APIClient, APIClientError  # noqa: E402
from frontend.charts import build_chart, chart_axes, chart_options, result_frame  # noqa: E402
from frontend.state import (  # noqa: E402
    clear_chart_state,
    clear_query_state,
    initialize_state,
    sync_active_dataset,
)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_TIMEOUT_SECONDS = 20.0
DEMO_QUESTIONS = (
    ("Order count", "How many orders are there?", ":material/receipt_long:"),
    ("Total revenue", "What is the total revenue?", ":material/payments:"),
    (
        "Top 5 products by revenue",
        "What are the top 5 products by revenue?",
        ":material/leaderboard:",
    ),
    (
        "Revenue by category",
        "How does revenue compare by category?",
        ":material/category:",
    ),
)


@st.cache_data(ttl=10, max_entries=4, show_spinner=False)
def load_health(base_url: str) -> dict[str, str]:
    return APIClient(base_url, timeout_seconds=API_TIMEOUT_SECONDS).health()


@st.cache_data(ttl=30, max_entries=12, show_spinner=False)
def load_datasets(base_url: str, workspace_version: int) -> list[dict[str, Any]]:
    del workspace_version
    return [
        dataset.model_dump()
        for dataset in APIClient(base_url, timeout_seconds=API_TIMEOUT_SECONDS).list_datasets()
    ]


@st.cache_data(ttl=30, max_entries=24, show_spinner=False)
def load_schema(base_url: str, dataset_id: str, workspace_version: int) -> dict[str, Any]:
    del workspace_version
    return APIClient(base_url, timeout_seconds=API_TIMEOUT_SECONDS).schema(dataset_id).model_dump()


def remember_flash(message: str) -> None:
    st.session_state["flash_message"] = message


def render_api_error(error: APIClientError, *, context: str) -> None:
    titles = {
        "BACKEND_UNAVAILABLE": "Backend unavailable",
        "REQUEST_TIMEOUT": "Request timed out",
        "PROVIDER_NOT_CONFIGURED": "AI provider not configured",
        "PROVIDER_AUTH_FAILED": "AI provider credentials rejected",
        "PROVIDER_TIMEOUT": "AI provider timed out",
        "PROVIDER_UNAVAILABLE": "AI provider unavailable",
        "SQL_POLICY_DENIED": "Query rejected by the SQL safety policy",
        "SQL_ACCESS_DENIED": "Query blocked by SQLite",
        "QUERY_TIMEOUT": "Query execution timed out",
        "QUERY_EXECUTION_ERROR": "Query execution failed",
        "DEMO_QUESTION_UNSUPPORTED": "Question unavailable in demo mode",
        "DEMO_DATASET_UNSUPPORTED": "Dataset unavailable in demo mode",
        "EMPTY_DATASET": "Dataset has no tables",
        "DATASET_NOT_FOUND": "Dataset not found",
    }
    st.error(
        f"{context}: {error.message}",
        title=titles.get(error.code, "Request failed"),
        icon=":material/error:",
    )


st.set_page_config(page_title="SQLInsights", page_icon=":material/query_stats:", layout="wide")
initialize_state(st.session_state)
client = APIClient(API_BASE_URL, timeout_seconds=API_TIMEOUT_SECONDS)

st.title("SQLInsights")
st.caption("Ask questions of local CSV data through a validated, read-only SQL workflow.")

try:
    health = load_health(API_BASE_URL)
    datasets = load_datasets(API_BASE_URL, st.session_state["workspace_version"])
except APIClientError as exc:
    render_api_error(exc, context="Could not load SQLInsights")
    st.info(
        "Start the API with `.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 "
        "--port 8000`, then refresh this page.",
        title="Local startup",
        icon=":material/terminal:",
    )
    st.stop()

mode = health.get("mode", "unknown")
with st.container(horizontal=True, vertical_alignment="center"):
    st.badge(f"{mode} mode", color="blue" if mode == "demo" else "green")
    st.caption("Local API connected · SQL executes only on the backend")

flash_message = st.session_state.pop("flash_message", None)
if flash_message:
    st.success(flash_message, icon=":material/check_circle:")

with st.sidebar:
    st.header("Dataset workspace")
    st.caption("Create a dataset or use the reproducible Retail Demo.")

    with st.form("create_dataset", clear_on_submit=True, border=False):
        dataset_name = st.text_input(
            "New dataset name",
            max_chars=100,
            placeholder="Example: Q4 sales",
        )
        create_submitted = st.form_submit_button(
            "Create dataset",
            icon=":material/create_new_folder:",
            width="stretch",
        )
    if create_submitted:
        if not dataset_name.strip():
            st.warning("Enter a dataset name before creating it.")
        else:
            try:
                created = client.create_dataset(dataset_name.strip())
                st.session_state["workspace_version"] += 1
                st.session_state["dataset_selector"] = created.id
                remember_flash(f"Created dataset “{created.name}”.")
                st.rerun()
            except APIClientError as exc:
                render_api_error(exc, context="Could not create the dataset")

    if not datasets:
        st.warning("No datasets are available.")
        st.stop()

    labels = {item["id"]: f"{item['name']} · {item['table_count']} table(s)" for item in datasets}
    dataset_ids = list(labels)
    previous_id = st.session_state.get("active_dataset_id")
    default_index = dataset_ids.index(previous_id) if previous_id in dataset_ids else 0
    selected_id = st.selectbox(
        "Active dataset",
        dataset_ids,
        index=default_index,
        format_func=labels.get,
        key="dataset_selector",
    )
    sync_active_dataset(st.session_state, selected_id)

    st.divider()
    st.subheader("Upload CSV tables")
    st.caption("Files are validated and imported by the backend. Up to three tables per dataset.")
    upload_key = f"csv_upload_{st.session_state['workspace_version']}"
    uploaded_files = st.file_uploader(
        "CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key=upload_key,
    )
    upload_clicked = st.button(
        "Upload selected files",
        icon=":material/upload_file:",
        disabled=not uploaded_files,
        width="stretch",
    )
    if upload_clicked and uploaded_files:
        failures: list[str] = []
        progress = st.progress(0, text="Uploading files…")
        for index, uploaded_file in enumerate(uploaded_files, start=1):
            try:
                client.upload_table(selected_id, uploaded_file.name, uploaded_file.getvalue())
            except APIClientError as exc:
                failures.append(f"{uploaded_file.name}: {exc.message}")
            progress.progress(
                index / len(uploaded_files), text=f"Processed {index} of {len(uploaded_files)}"
            )
        progress.empty()
        st.session_state["workspace_version"] += 1
        clear_query_state(st.session_state)
        if failures:
            st.session_state["last_error"] = "\n".join(failures)
        else:
            remember_flash(f"Uploaded {len(uploaded_files)} table(s).")
        st.rerun()

try:
    schema = load_schema(
        API_BASE_URL,
        selected_id,
        st.session_state["workspace_version"],
    )
except APIClientError as exc:
    render_api_error(exc, context="Could not load the selected dataset")
    st.stop()

last_upload_error = st.session_state.get("last_error")
if isinstance(last_upload_error, str) and last_upload_error:
    st.error(last_upload_error, title="One or more uploads failed", icon=":material/upload_file:")
    st.session_state["last_error"] = None

st.header(schema["name"])
tables = schema["tables"]
total_rows = sum(table["row_count"] for table in tables)
with st.container(horizontal=True):
    st.metric("Tables", len(tables), border=True)
    st.metric("Rows", f"{total_rows:,}", border=True)
    st.metric(
        "Columns",
        sum(len(table["columns"]) for table in tables),
        border=True,
    )

with st.expander("Dataset schema", expanded=not tables):
    if not tables:
        st.info("Upload at least one CSV table before asking questions.")
    for table in tables:
        st.markdown(f"**{table['name']}** · {table['row_count']:,} rows")
        st.dataframe(
            [
                {
                    "Column": column["name"],
                    "Source header": column["source_name"],
                    "Type": column["type"],
                }
                for column in table["columns"]
            ],
            hide_index=True,
            alt=f"Columns in the {table['name']} table",
            key=f"schema_{selected_id}_{table['name']}",
        )

st.header("Ask your data")
if mode == "demo":
    st.caption(
        "Demo mode is deterministic and supports only the predefined Retail Demo questions below."
    )
else:
    st.caption("LLM mode sends your question and the selected schema to the configured provider.")

sample_question: str | None = None
if mode == "demo" and selected_id == "retail_demo":
    with st.container(horizontal=True):
        for label, question, icon in DEMO_QUESTIONS:
            if st.button(label, icon=icon, key=f"sample_{label}"):
                sample_question = question
    if sample_question is not None:
        st.session_state["query_input"] = sample_question

with st.form("question_form", border=True):
    st.text_area(
        "Question",
        key="query_input",
        height=92,
        max_chars=2_000,
        placeholder="Which products generated the highest revenue?",
        disabled=not tables,
    )
    ask_submitted = st.form_submit_button(
        "Run question",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not tables or st.session_state["query_in_flight"],
        width="stretch",
    )

question_to_run = (
    sample_question
    if sample_question is not None
    else (st.session_state["query_input"] if ask_submitted else None)
)
if question_to_run is not None:
    cleaned_question = question_to_run.strip()
    if not cleaned_question:
        st.warning("Enter a question before running it.")
    elif not st.session_state["query_in_flight"]:
        st.session_state["query_in_flight"] = True
        clear_query_state(st.session_state)
        try:
            with st.spinner("Generating, validating, and running a read-only query…"):
                result = client.ask(selected_id, cleaned_question)
            st.session_state["last_result"] = result.model_dump()
            st.session_state["last_question"] = cleaned_question
            clear_chart_state(st.session_state)
        except APIClientError as exc:
            st.session_state["last_error"] = {
                "code": exc.code,
                "message": exc.message,
                "status_code": exc.status_code,
            }
        finally:
            st.session_state["query_in_flight"] = False

query_error = st.session_state.get("last_error")
if isinstance(query_error, dict):
    render_api_error(
        APIClientError(
            str(query_error.get("code", "API_ERROR")),
            str(query_error.get("message", "The question could not be completed.")),
            query_error.get("status_code"),
        ),
        context="The question could not be completed",
    )

result_payload = st.session_state.get("last_result")
if isinstance(result_payload, dict):
    st.divider()
    st.header("Query result")
    st.caption(f"Question: {st.session_state['last_question']}")
    with st.container(horizontal=True):
        st.metric("Status", str(result_payload["status"]).title(), border=True)
        st.metric("Rows returned", result_payload["row_count_returned"], border=True)
        st.metric("Execution", f"{result_payload['elapsed_ms']} ms", border=True)
        st.metric("Generation attempts", result_payload["attempts"], border=True)

    st.subheader("Generated SQL")
    st.code(result_payload["sql"], language="sql", wrap_lines=True)
    if result_payload["explanation"]:
        st.caption(result_payload["explanation"])
    for warning in result_payload["warnings"]:
        st.warning(warning)

    frame = result_frame(result_payload["columns"], result_payload["rows"])
    st.subheader("Rows")
    if frame.empty:
        st.info("The validated query ran successfully, but no rows matched.")
    else:
        st.dataframe(
            frame,
            hide_index=True,
            alt="Rows returned by the validated SQL query",
            key="query_results_table",
        )

    st.subheader("Visualization")
    options = chart_options(frame)
    if not options.available:
        st.info(options.reason or "This result is best explored as a table.")
    else:
        st.session_state.setdefault("chart_type", options.default)
        chart_type = st.segmented_control(
            "Chart type",
            options.available,
            key="chart_type",
        )
        if chart_type is not None:
            x_options, y_options = chart_axes(frame, chart_type)
            if st.session_state.get("chart_x") not in x_options:
                st.session_state["chart_x"] = x_options[0]
            valid_y = [column for column in y_options if column != st.session_state["chart_x"]]
            if not valid_y:
                st.info("Choose two different numeric columns for a scatter plot.")
            else:
                st.session_state.setdefault("chart_y", valid_y[0])
                controls = st.container(horizontal=True, vertical_alignment="bottom")
                with controls:
                    x_column = st.selectbox("Horizontal / category", x_options, key="chart_x")
                    selectable_y = [column for column in y_options if column != x_column]
                    if st.session_state.get("chart_y") not in selectable_y:
                        st.session_state["chart_y"] = selectable_y[0]
                    y_column = st.selectbox("Value", selectable_y, key="chart_y")
                try:
                    figure = build_chart(frame, chart_type, x_column, y_column)
                    result_key = hashlib.sha256(result_payload["sql"].encode()).hexdigest()[:12]
                    st.plotly_chart(
                        figure,
                        width="stretch",
                        key=f"result_chart_{result_key}",
                        config={"displaylogo": False, "scrollZoom": False},
                        alt=f"{chart_type} chart of {y_column} by {x_column}",
                    )
                except ValueError as exc:
                    st.info(str(exc), title="Visualization unavailable")

st.caption(
    "SQLInsights is a local, single-user demo. The backend validates every generated query and "
    "executes it through a restricted read-only SQLite connection."
)
