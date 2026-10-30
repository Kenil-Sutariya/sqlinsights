# SQLInsights portfolio notes

## Concise project summary

SQLInsights is a local-first analytics assistant that converts natural-language questions into
reviewable SQLite queries through a bounded LangGraph workflow. Deterministic policy code validates
every generated query, and a separate read-only SQLite executor returns actual rows for a FastAPI
and Streamlit dashboard with Plotly visualizations.

The MVP is intentionally single-user and localhost-only. Demo mode uses eight predefined questions;
real LLM mode requires user-supplied OpenAI credentials and was not live-tested in Phase 5.

## Technology stack

- Python 3.12, FastAPI, Pydantic, LangGraph, OpenAI Python SDK
- SQLite, SQLGlot, read-only URI connections, authorizer, progress handler
- Streamlit and Plotly
- pytest, Ruff, uv, Docker Compose, GitHub Actions

## Main engineering contributions

- Built bounded CSV ingestion with encoding, shape, identifier, size, row, column, and cell limits.
- Isolated every dataset in an app-owned SQLite database with safe deletion/path checks.
- Separated model SQL proposal from SQLGlot policy and a deny-by-default SQLite executor.
- Implemented typed graph states and one safe regeneration attempt without an open-ended agent loop.
- Added deterministic result formatting and chart selection using only executed rows.
- Created an offline 25-question evaluation with known results and independent reference checks.
- Added API, agent, adversarial SQL, ingestion, UI state, chart, and Streamlit tests.

## Verified results

Measured locally on 2026-10-30:

- 106 offline tests passed; 27 focused security tests passed; Ruff format and lint passed.
- Deterministic fixture-provider workflow: 25/25 cases passed, 21/21 result comparisons correct,
  2/2 fixed unsafe proposals rejected; median 3 ms, p95 4 ms.
- Predefined demo registry: 8/8 exact questions passed; median 4 ms, p95 6 ms.
- Live localhost API/UI question flow returned the expected five products and rendered a chart.
- Real-provider evaluation: not run; these numbers are not LLM accuracy.
- Docker Compose: API and UI images built, both containers became healthy, application smoke tests
  passed, and teardown preserved application data.

## CV bullets

- Built SQLInsights, a local natural-language analytics application using LangGraph, FastAPI,
  SQLite, Streamlit, and Plotly to turn questions into reviewable SQL and actual visualized results.
- Implemented layered read-only SQL execution with SQLGlot AST validation, SQLite authorizer rules,
  query deadlines, bounded results, and a reproducible 25-case synthetic-data evaluation.

Do not add a model-accuracy percentage or deployment claim unless a named provider/model is actually
evaluated and the corresponding deployment is verified.

## 60-second interview explanation

“SQLInsights lets a user load small CSV datasets and ask analytical questions in English. A typed
LangGraph workflow retrieves only the active dataset schema and asks either a configured model or
an honest predefined demo registry for a structured SQL proposal. The important design choice is
that the model never owns execution: SQLGlot enforces a strict SELECT-only allowlist, and a separate
SQLite connection opens the app-owned database read-only with query-only mode, an authorizer,
deadline, and result cap. FastAPI exposes typed endpoints, while Streamlit shows the SQL, actual
rows, and deterministic Plotly charts. I evaluated the plumbing offline with 25 synthetic questions
and known row-level expectations, plus 106 tests. I label that as deterministic workflow testing,
not model accuracy; the live provider remains unverified without credentials.”

## Likely interview questions

### 1. Why is prompt instruction not enough to prevent destructive SQL?

Model output is untrusted. The app requires a single allowlisted SELECT AST, restricts tables and
functions, then independently uses SQLite read-only mode and a deny-by-default authorizer. A model
claiming that a query is safe grants no authority.

### 2. What does LangGraph add here?

It makes schema discovery, generation, validation, execution, retry routing, and final formatting
explicit and testable. The workflow has a recursion limit and at most two generation attempts, so it
is graph-orchestrated rather than an uncontrolled autonomous loop.

### 3. How did you evaluate SQL correctness?

The JSONL fixture stores 25 synthetic questions, expected columns/rows or error codes, needed
tables, and categories. Expected results are rechecked with hand-authored reference SQL, while a
deterministic provider exercises the complete graph/policy/executor path. Comparison is on executed
results, not SQL string similarity.

### 4. What is the most important limitation?

Real LLM quality is unknown because no configured provider was tested. Demo/mock scores validate
workflow determinism and security cases only. The app is also unauthenticated and must stay local.

### 5. How are expensive but read-only queries controlled?

The executor applies a monotonic deadline through SQLite's progress handler, a short lock timeout,
SQL-length/complexity limits, a fresh connection per query, and a 200-row fetch cap with a truthful
truncation flag. LIMIT alone is not treated as an execution-cost control.
