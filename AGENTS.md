# SQLInsights repository instructions for Codex

## Your mission
Build **SQLInsights**, a small, local-first natural-language-to-SQL analytics portfolio app. Read `SQLINSIGHTS_BUILD_PLAN.md` fully before writing application code. That plan is the source of truth for requirements, architecture, phase gates, security controls, demo behavior, and definition of done.

## Priority order
1. Correctness and truthful observed results.
2. Read-only SQL safety, dataset isolation, privacy, and bounded execution.
3. Complete end-to-end minimal demo.
4. Tests, reproducibility, and documentation.
5. Optional polish only after all P0 requirements pass.

## Rules
- Implement only the **current requested milestone**. Do not start later phases automatically.
- Inspect the repository before changing anything. Preserve existing work; do not delete unrelated files.
- Follow the planned public API contract. Keep UI, API, graph, SQL validation, and executor separate.
- Treat every LLM-generated SQL statement and CSV value as untrusted. Never execute raw model SQL without deterministic validation **and** a restricted SQLite connection.
- Build and test safe SQL execution before connecting an LLM.
- No arbitrary SQL writes, external databases, generated Python execution, shell execution, web browsing agents, multi-user SaaS, or public deployment in the MVP.
- `AI_MODE=demo` must work without an API key, but should support **only explicit predefined example questions**. Label it honestly. Never pretend demo output comes from a live LLM.
- `AI_MODE=llm` must call a configured provider for real novel questions. If the provider is unavailable, report the error; do not silently fall back to demo mode.
- Never fabricate accuracy, screenshots, benchmarks, command output, tests, model usage, or completion claims.
- Do not commit, push, deploy, or use external credentials without explicit user direction.
- No secrets or private datasets in Git. Logs must not contain uploaded row data, SQL literals, user question text, or keys.
- Keep the app single-user and localhost-only. The demo is **not** secure for public multi-user deployment.
- Prefer Python 3.12, tested current library APIs, typed code, small modules, `uv.lock`, Ruff, and pytest. Consult official documentation if library APIs are uncertain.
- If a requirement is unsafe or infeasible, preserve the security boundary, document the precise blocker in `BUILD_STATUS.md`, and stop that phase rather than weakening safeguards.

## Verification and handoff on every phase
1. List changed files and material design choices.
2. Run the applicable plan tests, lint, smoke checks, and build checks.
3. Write **exact commands executed** and truthful pass/fail/untested statuses to `BUILD_STATUS.md`.
4. Fix reproducible failures before declaring that phase complete.
5. State the remaining risks and next *proposed* phase; stop for user direction.

## Initial action
Read the plan and ask to implement phases 0–1 only when the user supplies the first-phase prompt. Do not build everything at once unless the user expressly changes this scope.
