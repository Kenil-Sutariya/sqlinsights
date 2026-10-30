# SQLInsights build status

**Checkpoint:** Phase 5 complete, including Docker runtime acceptance  
**Verified:** 2026-10-30 (Europe/Berlin)  
**Host:** macOS, CPython 3.12.13, SQLite 3.53.0, Streamlit 1.66.1,
Plotly 6.9.0, LangGraph 1.2.18, OpenAI Python 3.40.0, SQLGlot 28.10.1

## Phase audit

| Phase | Status | Verified evidence |
|---|---|---|
| 0 — bootstrap | Complete | Locked environment, health route, local startup, Ruff, and tests pass. |
| 1 — data and ingestion | Complete | Reproducible three-table seed, isolated CRUD, bounded CSV ingestion, schemas, previews, and API tests pass. |
| 2 — SQL policy/executor | Complete | AST policy, read-only URI, query-only mode, authorizer, deadline, result cap, isolation, checksum, and adversarial tests pass. |
| 3 — graph and modes | Complete | Typed StateGraph, active schema, structured proposals, identical security path, one safe retry, exact demo registry, and provider failures pass. |
| 4 — dashboard/charts | Complete | Dataset workspace, schema, question UI, actual SQL/rows, deterministic charts, safe errors/state, AppTest, and live browser smoke pass. |
| 5 — tests/evaluation/docs | Complete | 106 tests and Ruff pass; 25-case mock and 8-case demo evaluations pass; final public documentation is ready. |
| 5 — Docker runtime | Complete | Healthy engine; images build; API/UI containers become healthy; host health and application smoke tests pass; clean teardown preserves data. |

All Phase 5 acceptance criteria in section 13 of the build plan now pass. Real-provider evaluation
and remote GitHub Actions remain explicitly unverified; neither is represented as a pass and neither
is required for the deterministic no-key demo acceptance path.

## Phase 5 implementation

- Added `evaluation/questions.jsonl` with exactly 25 synthetic cases covering simple filters,
  aggregates, group/order, date filters/grouping, multiple conditions, two/three-table joins, empty
  results, ambiguity, invalid questions, `DELETE`, and `ATTACH`.
- Added a deterministic runner that seeds a temporary Retail Demo, verifies fixed expectations with
  hand-authored reference SQL, executes candidates through the actual LangGraph/policy/executor,
  compares columns and rows rather than SQL strings, records per-case SQL/results/errors/latency,
  and writes JSON reports. Mock/demo results are labelled not-real-LLM.
- Added evaluation tests for fixture structure/categories, 25-case expected-result comparison, and
  exact eight-question demo coverage.
- Added separate API/UI Dockerfiles, loopback-only Compose mappings, internal API routing, persistent
  local data mount, safe environment mapping, and both health checks.
- Updated CI to run locked sync, Ruff format/lint, all tests, and both deterministic evaluations.
- Fixed `.gitignore` so `.streamlit/config.toml` can be tracked while secrets, `.env`, virtualenvs,
  caches, local data, and SQLite files remain ignored. Added `.dockerignore`.
- Replaced the phase-specific README with final architecture, security, setup, environment, Docker,
  walkthrough, API, evaluation evidence, media-pending notice, and limitations.
- Added `DEMO.md` and `PORTFOLIO.md`. Local screenshots captured during verification are excluded
  from the publication candidate at the owner's request.
- Updated `START_HERE.md` so it no longer instructs readers to begin Phase 0.

## Automated verification — PASS

Commands run from the repository root:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Observed on 2026-10-30: **50 files already formatted**, `All checks passed!`, and
**106 passed in 3.27s**. No network or API key was required.

The full suite covers valid/multi-file/repeat ingestion; empty, malformed, wrong-delimiter,
invalid-encoding, BOM, duplicate/missing header, size/row/column/cell limits; type inference and
leading zeros; dataset isolation/deletion/path traversal; valid and unsafe SQL; direct-executor
bypass; checksum preservation; timeout/truncation; graph transitions/retry bounds; provider
configuration/failures/malformed output; correct/empty/failed queries; API status mapping; dataset
state changes; chart eligibility/creation; API client errors; and headless Streamlit behavior.

## Evaluation — PASS, deterministic only

```bash
.venv/bin/python evaluation/run_eval.py --mode mock \
  --output evaluation/results/mock_report.json
.venv/bin/python evaluation/run_eval.py --mode demo \
  --output evaluation/results/demo_report.json
```

Observed results:

| Mode | Cases | Result correctness | Unsafe rejection | Median / p95 | Meaning |
|---|---:|---:|---:|---:|---|
| Mock fixture provider | 25/25 | 21/21 | 2/2 | 3 ms / 4 ms | Complete workflow with hand-authored proposals; not LLM accuracy |
| Demo registry | 8/8 | 8/8 | N/A | 4 ms / 6 ms | Exact predefined questions; not LLM accuracy |
| Real provider | Not run | Not evaluated | Not evaluated | N/A | `OPENAI_API_KEY` and `OPENAI_MODEL` were not configured |

Observed mock error categories were two `AMBIGUOUS_QUESTION` and two `SQL_POLICY_DENIED`. The
unsafe percentage applies only to the published two-case malicious evaluation subset. Latencies
are local end-to-end workflow measurements on synthetic data and exclude network model calls.

## Security review — PASS for specified offline controls

Focused adversarial command:

```bash
.venv/bin/pytest -q tests/test_sql_policy.py tests/test_query_executor.py \
  tests/test_agent.py -k 'malicious or write or unsafe or attach or restricted or checksum'
```

Observed: **27 passed, 31 deselected in 0.10s**.

- SQLGlot requires one SELECT AST, canonicalizes it, allowlists functions/tables, and rejects DDL,
  DML, PRAGMA, ATTACH, compound SQL, internal tables, cross-database references, and unknown calls.
- The executor revalidates and uses an app-controlled `mode=ro` URI, `query_only`, disabled extension
  loading, a deny-by-default authorizer, fresh connection, lock timeout, progress deadline, SQL
  length/complexity limit, and `MAX_RESULT_ROWS + 1` fetch for truthful truncation.
- Adversarial tests confirm attempted writes and forged-validator bypasses fail and the database
  checksum/row counts remain unchanged.
- CSV enforcement remains 5 MiB, three tables, 40 columns, 50,000 rows, and 20,000 characters/cell.
- Graph recursion and generation calls remain bounded; security/timeouts/auth failures do not retry.
- Source scan found no subprocess, `os.system`, `shell=True`, Python `eval`/`exec`, or agent tool path.
- No `.env` was present; no database file was found outside ignored `data/`; source has no logging of
  row contents, SQL literals, question text, or keys. Public errors remain typed and sanitized.
- API/UI commands and Compose host mappings bind only to `127.0.0.1`.

This is defense-in-depth evidence, not a claim of universal security. The app remains unauthenticated
and unsuitable for public multi-user exposure.

## Live local workflow — PASS

```bash
AI_MODE=demo DATA_DIR=/tmp/sqlinsights-phase5-demo-data \
  .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
API_BASE_URL=http://127.0.0.1:8000 \
  .venv/bin/streamlit run frontend/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
curl --silent --show-error --fail http://127.0.0.1:8000/health
curl --silent --show-error --fail http://127.0.0.1:8501/_stcore/health
curl --silent --show-error --fail --request POST \
  http://127.0.0.1:8000/api/v1/ask \
  --header 'Content-Type: application/json' \
  --data '{"dataset_id":"retail_demo","question":"What are the top 5 products by revenue?"}'
```

Observed health responses were API `{"status":"ok","mode":"demo"}` and UI `ok`. The ask call
returned HTTP 200, canonical join/aggregate SQL, five correct rows, one attempt, no truncation, and
11 ms observed API elapsed time. A browser run displayed the same rows and Plotly bar chart.

## Docker verification — PASS

The earlier Docker Desktop ENOSPC/ext4 failure was a host-runtime blocker, not an SQLInsights code
failure. After freeing disk space and restarting macOS, the complete runtime check passed on
2026-10-30 without resetting, pruning, deleting volumes, or modifying `Docker.raw`.

Commands and observed results:

```bash
df -h ~
docker version
docker info
docker ps -a
docker system df
docker compose config --quiet
docker compose build
docker compose up --detach --wait
docker compose ps
curl --fail --show-error http://127.0.0.1:8000/health
curl --fail --show-error http://127.0.0.1:8501/_stcore/health
docker compose down
docker compose ps --all
```

- Host data volume had **35 GiB available** (83% used).
- Docker Desktop 4.82.0, Engine 29.6.1, containerd 2.2.5, and the `desktop-linux`
  Linux/arm64 engine all responded successfully. No EOF, I/O, or filesystem errors appeared.
- Docker reported two unrelated stopped containers, seven images, four local volumes, and a healthy
  `overlayfs`/containerd snapshotter. No unrelated Docker object was changed.
- Compose validation exited 0. Source inspection confirmed two services, loopback-only host ports
  `127.0.0.1:8000` and `127.0.0.1:8501`, UI-to-API routing through `http://api:8000`, backend-only
  provider configuration, and persistent `./data:/app/data` storage. Resolved secret values were not
  printed.
- Both locked images installed 74 runtime packages, exported, unpacked, and finished successfully.
- `docker compose up --detach --wait` exited 0. `docker compose ps` reported both `api` and `ui` as
  healthy with only the expected loopback port mappings.
- API health returned `{"status":"ok","mode":"demo"}`; Streamlit health returned `ok`; the UI
  root returned HTTP 200.
- The Retail Demo API listed one protected dataset with three tables. Schema discovery reported
  6 customers, 6 products, and 18 orders. The predefined top-five-products question returned five
  actual rows, including `USB-C Hub` with revenue `438.9`, using the canonical validated join and
  aggregate SQL.
- `Delete all rows from orders.` returned HTTP 400 with `DEMO_QUESTION_UNSUPPORTED`; a subsequent
  approved count query still returned 18 orders. The focused policy/executor/agent regression suite
  also passed 27 tests, confirming the deterministic SQL security path remains active.
- Plain `docker compose down` cleanly removed only the SQLInsights containers and network. No
  `--volumes`, prune, reset, or deletion command was used; the bind-mounted application data remains.
  The final `docker compose ps --all` table was empty.

Containerized application smoke commands:

```bash
curl --fail --show-error --silent http://127.0.0.1:8000/api/v1/datasets
curl --fail --show-error --silent \
  http://127.0.0.1:8000/api/v1/datasets/retail_demo/schema
curl --fail --show-error --silent --request POST \
  http://127.0.0.1:8000/api/v1/ask \
  --header 'Content-Type: application/json' \
  --data '{"dataset_id":"retail_demo","question":"What are the top 5 products by revenue?"}'
curl --show-error --silent --request POST http://127.0.0.1:8000/api/v1/ask \
  --header 'Content-Type: application/json' \
  --data '{"dataset_id":"retail_demo","question":"Delete all rows from orders."}' \
  --write-out '\nHTTP_STATUS=%{http_code}\n'
curl --fail --show-error --silent --request POST \
  http://127.0.0.1:8000/api/v1/ask \
  --header 'Content-Type: application/json' \
  --data '{"dataset_id":"retail_demo","question":"How many orders are there?"}'
curl --fail --show-error --head http://127.0.0.1:8501/
```

Final post-Docker quality checks:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/pytest -q tests/test_sql_policy.py tests/test_query_executor.py \
  tests/test_agent.py -k 'malicious or write or unsafe or attach or restricted or checksum'
```

Observed: **50 files already formatted**, `All checks passed!`, **106 passed in 3.27s**, and
**27 passed, 31 deselected in 0.10s** for the focused adversarial regression.

## GitHub readiness

| Item | Status |
|---|---|
| Professional README | Ready; screenshots and video intentionally pending owner upload |
| MIT license, env template, lockfile | Ready |
| CI workflow for format/lint/tests/evaluations | Present; local equivalents pass |
| Ignore rules for secrets, data, DBs, caches, venv | Ready |
| Synthetic evaluation fixture/reports | Ready |
| Demo and interview material | Ready |
| Docker runtime proof | Ready; build, two healthy services, smoke tests, and teardown passed locally |
| Real-provider proof | Not run; explicitly disclosed |
| Remote CI status/badge | Not available |
| Git status/diff audit | Local `main` repository initialized; publication candidate review in progress |

No commit, push, deployment, credential use, authentication, payment, or cloud feature was added.

## Phase 5 files created or modified

- Created: `evaluation/__init__.py`, `evaluation/questions.jsonl`, `evaluation/run_eval.py`,
  `evaluation/results/mock_report.json`, `evaluation/results/demo_report.json`,
  `tests/test_evaluation.py`, `Dockerfile.api`, `Dockerfile.ui`, `docker-compose.yml`,
  `.dockerignore`, `DEMO.md`, and `PORTFOLIO.md`. Local `docs/screenshots/*.png` files are not part
  of the publication candidate.
- Modified: `.gitignore`, `.github/workflows/ci.yml`, `README.md`, `START_HERE.md`, and this file.
- Existing Phase 0–4 application code and security boundaries were preserved.

## Remaining work and final status

1. Commit and push only after the owner's explicit approval, then verify GitHub Actions, rendered
   documentation, excluded files, and GitHub commit attribution. Remote CI is not yet verified.
2. Optionally run and separately report a named real provider/model evaluation with user-supplied
   credentials. This is not required for the no-key demo but is required before claiming model
   quality or verified real-mode behavior in a portfolio.
3. Continue to present the MVP as localhost-only, single-user, unauthenticated software. Do not
   expose it publicly without a separate security and deployment design.

**Final Phase 5 status: COMPLETE.** Code, offline tests, deterministic evaluation, security review,
local workflow, portfolio documentation, Docker image builds, two-service healthy
startup, application smoke tests, and safe teardown all pass. The source tree is ready to place on
GitHub. Remote GitHub Actions and real-provider model quality remain unverified and must continue to
be disclosed until they are actually run.
