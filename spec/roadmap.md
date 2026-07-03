# Roadmap

---

## What This Agent Does

A personal data-analysis assistant for one user's CSV/Excel exports and PDFs (including scanned/OCR'd ones). The user uploads files across a multi-day analysis project, the agent auto-profiles each dataset the moment it lands, and the user asks questions in an ongoing chat. Each question runs an iterative agent loop — the agent writes analysis code, runs it locally against the real data, inspects the result, and refines up to a bounded number of steps — then returns a plain-language answer with key numbers, the code that produced it (collapsible), and (from Phase 2) charts and exports. Conversation history and uploaded datasets persist so the user can pick a project back up days later.

## Who Uses It

One person, a few times a day, running multi-day data-analysis projects (e.g. reconciling exports, comparing periods, cleaning a dataset before reporting on it). They are comfortable reading a plain-language answer and a snippet of generated pandas code, but do not want to write the code themselves.

## Core Problem Being Solved

Today this person opens a notebook or spreadsheet, writes throwaway pandas/Excel formulas by hand, and re-derives context every session because nothing is remembered. This agent replaces that manual loop: upload once, ask in plain English, get an answer backed by real code run against the real data, with the reasoning and history kept so the next question in the same investigation doesn't start from zero.

## Success Criteria

- [ ] A user can upload one CSV or Excel file and see it auto-profiled (columns, types, ranges, row count) before asking anything.
- [ ] A user can ask a free-text question about the uploaded dataset and receive a plain-language answer containing correct key numbers, backed by real generated code executed against the full dataset (not a sample).
- [ ] The generated code and the full reasoning chain (what was tried, including any refinement steps) are visible to the user, collapsed by default.
- [ ] No raw data row ever appears in an outbound LLM request — verified by an automated test inspecting the actual request payload sent to Gemini.
- [ ] A second question in the same chat session correctly uses context from the first question and answer (session memory).
- [ ] When the agent cannot resolve a question within the step budget, it returns its best guess, flags the assumption, and shows what it tried — never a silent failure or a stack trace.

## What This Agent Does NOT Do (Out of Scope)

- Does not send raw data rows, cell values, or full dataframes to the LLM under any circumstance — only schema, summary statistics, and code/text cross that boundary (see [`architecture.md`](architecture.md#llm-boundary-what-crosses-vs-what-stays-local)).
- Does not support multiple concurrent users, auth, or team sharing — single-user personal tool.
- Does not provide a fine-grained progress/step tracker during a query — a single spinner is the only in-flight feedback (per intake).
- Does not maintain a separate audit-log feature — session/history persistence is the only record of past activity.
- Phase 1 does not support: multiple simultaneous file uploads, folder-as-dataset, joins across files, PDF/OCR ingestion, interactive charts, cost-per-query display, cross-session history browsing, or on-demand export of cleaned files. These are explicitly deferred to Phase 2 (see below) and appear only as clearly-labelled, non-functional stubs in the Phase 1 UI.
- Never writes files or makes network calls from inside generated analysis code — the local execution sandbox blocks network access and restricts imports to a data-analysis allowlist.

## Key Constraints

- **Hard privacy rule (architecturally load-bearing):** LLM API calls are fine; raw data rows are never sent to the LLM. Only schema (column names/types/ranges), summary statistics, and generated code/text cross the LLM boundary. All computation (the generated pandas/analysis code) executes 100% locally in a sandboxed local runner with no network access. See [`architecture.md`](architecture.md#llm-boundary-what-crosses-vs-what-stays-local) and [`agent.md`](agent.md) for exactly which nodes see what.
- **Production-reliability bar** — answers are meant to be acted on; the quality bar is correctness against the full dataset, not a best-effort sample.
- **Bounded iteration** — each question runs a code-gen → execute → inspect → refine loop capped at a concrete step budget (`MAX_STEPS = 6`, see [`agent.md`](agent.md)); the agent falls back to a flagged best-guess answer rather than looping forever or failing silently.
- **Must scale to multiple joined files** without choking — Phase 1 is single-file only, but the architecture (dataset storage, profiling, and the execution sandbox) is designed so multi-file joins are a Phase 2 extension, not a redesign.
- **Stack** — Python + PostgreSQL backend, Gemini as the LLM provider, LangGraph for the iterative loop, Next.js web UI (see [`architecture.md`](architecture.md#stack) for the full, versioned stack).

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win.** It must work perfectly the first time the user tests it — zero rough edges on the tested path. Its backend is minimal but REAL on the one core path. Its frontend is visually complete: real UI for the one working path PLUS clearly-labelled NON-FUNCTIONAL stubs for everything coming later. Phase 2 wires those stubs into real functionality.

### Phase 1 — Upload, Auto-Profile, Ask, Answer

- **Goal:** the full primary journey works end-to-end for one file: upload a CSV or Excel file → see it auto-profiled immediately → ask one question in a chat thread → get back a plain-language answer with key numbers and the collapsible generated code, produced by a real bounded (≤6-step) local code-gen/execute/refine loop against Gemini, with the no-raw-data-to-LLM boundary provably enforced and conversation memory working within the session.
- **Independent slices (parallel build units):**
  - `db-schema` (backend) — SQLAlchemy models + Alembic migration for `Dataset`, `DatasetProfile`, `ChatSession`, `ChatMessage`, `AnalysisRun`, `AnalysisStep` (see [`data.md`](data.md)). Deps: none.
  - `file-parsing-profiling` (backend) — local file parsing (CSV/Excel via pandas) and profiling (schema + stats, no LLM call), plus the dataset upload/fetch API routes. Owns `src/tools/file_parser.py`, `src/tools/profiler.py`, `src/api/datasets.py`, `src/domain/dataset.py`. Deps: none (implements directly against `data.md`/`api.md`, not against another slice's live code).
  - `agent-graph-loop` (backend) — the LangGraph code-gen/execute/inspect/refine loop per [`agent.md`](agent.md): state, nodes, edges, graph assembly, the sandboxed local executor, and the two prompt templates. Owns `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py`, `src/tools/sandbox_exec.py`, `src/prompts/plan_code.md`, `src/prompts/finalize_answer.md`. Deps: none.
  - `chat-api` (backend) — session + message API routes that call the graph runner and persist `ChatMessage`/`AnalysisRun`/`AnalysisStep`. Owns `src/api/chat.py`, `src/domain/chat.py`. Deps: none.
  - `frontend-upload-profile` (frontend) — upload zone + dataset profile summary panel, plus the labelled stub shell (tabs/areas for charts, multi-file, export, history — visibly disabled). Owns `frontend/src/app/page.tsx` (layout shell), `frontend/src/components/UploadZone.tsx`, `frontend/src/components/ProfilePanel.tsx`, `frontend/src/components/StubPanels.tsx`. Deps: none.
  - `frontend-chat` (frontend) — chat thread, message composer, collapsible code block, loop spinner, error/empty states. Owns `frontend/src/components/ChatThread.tsx`, `frontend/src/components/CodeBlock.tsx`, `frontend/src/components/MessageBubble.tsx`, `tests/e2e/phase1.spec.ts`. Deps: none to author (built against `ui.md`); the Playwright suite requires the backend slices running to execute, which happens at gate time, not authoring time.
- **Key surfaces / files:** see each slice above. Backend slices never touch `frontend/`; frontend slices never touch `src/`.
- **Gate command:**
  ```
  uv run alembic upgrade head && \
  uv run pytest tests/ -q && \
  cd frontend && pnpm build && cd .. && \
  uv run python -m src &  \
  sleep 2 && cd frontend && npx playwright test tests/e2e/ --reporter=line
  ```
  Runs against the real Gemini API (`AGENT_GEMINI_API_KEY` from `.env`) and the real PostgreSQL database (`AGENT_DATABASE_URL` from `.env`) — never SQLite, never a stubbed provider. `tests/` includes `tests/integration/test_llm_boundary.py`, which asserts the literal outbound Gemini request payload never contains a raw data value from the fixture dataset, only schema/stats/code/question text, and `tests/integration/test_full_dataset_correctness.py`, which uses a ≥5,000-row fixture CSV and asserts the agent's final numeric answer matches an independently computed full-dataset ground truth (not a truncated-sample result).
- **How the user tests it (handoff seed):**
  1. `cd frontend && pnpm build && cd ..` then `uv run python -m src`, open `http://localhost:8001/app/`.
  2. Drag/drop or pick a CSV or Excel file into the upload zone. Within a few seconds, the profile panel populates with column names, types, ranges/sample stats, and row count — this is real, computed locally from the actual file.
  3. Type a question about the data into the chat box (e.g. "what's the average of column X grouped by column Y?") and send it. A spinner shows while the loop runs; the answer appears with key numbers in plain language, plus a "Show code" toggle revealing the actual generated pandas code that ran.
  4. Ask a follow-up question that references the first answer (e.g. "and what about just the top 10?") — the agent uses the conversation so far, proving session memory.
  5. **Labelled stubs (visible but non-functional, clearly marked "Coming in Phase 2"):** a disabled "Charts" tab, a disabled multi-file/folder upload toggle, a disabled "Export" button, a disabled "Session History" sidebar entry, and a cost-per-query pill showing "—". None of these should look broken — each carries a visible "Phase 2" label or tooltip.

### Phase 2 — Multi-File Analysis, Charts, History & Export

- **Goal:** every Phase 1 stub becomes real — the user can upload multiple files (or a whole folder) and ask cross-file questions, ingest PDFs (including scanned/OCR'd ones) as a data source, see chart output alongside numbers, see an estimated cost per query, browse and resume past chat sessions across days, and export the current/derived dataset on demand.
- **Independent slices (parallel build units):**
  - `multi-file-ingestion` (backend) — multi-file/folder upload, cross-file join/union logic, PDF/OCR parsing. Extends `src/tools/file_parser.py`, `src/api/datasets.py`; adds `src/tools/pdf_ocr.py`, `src/tools/joiner.py`. Deps: none.
  - `chart-and-cost` (backend) — extends the agent loop to produce chart-ready summary data and a per-query token/cost estimate. Extends `src/graph/nodes.py`; adds `src/tools/chart_data.py`, `src/tools/cost_estimator.py`. Deps: none.
  - `session-history-api` (backend) — cross-session persistence and history-browsing endpoints. Adds `src/api/sessions.py`; extends `src/domain/chat.py`. Deps: none.
  - `export-api` (backend) — on-demand export of the cleaned/derived dataset and results. Adds `src/api/export.py`, `src/tools/exporter.py`. Deps: none.
  - `frontend-multi-file-charts` (frontend) — multi-file/folder upload UI, chart rendering, cost-per-query display (wires the Phase 1 stubs). Owns `frontend/src/components/MultiFileUpload.tsx`, `frontend/src/components/ChartPanel.tsx`, `frontend/src/components/CostPill.tsx`. Deps: none.
  - `frontend-history-export` (frontend) — session history browser + export button (wires the Phase 1 stubs). Owns `frontend/src/components/SessionHistory.tsx`, `frontend/src/components/ExportButton.tsx`; extends `tests/e2e/phase1.spec.ts` → `tests/e2e/phase2.spec.ts`. Deps: none.
- **Key surfaces / files:** see each slice above.
- **Gate command:**
  ```
  uv run alembic upgrade head && \
  uv run pytest tests/ -q && \
  cd frontend && pnpm build && cd .. && \
  uv run python -m src & \
  sleep 2 && cd frontend && npx playwright test tests/e2e/ --reporter=line
  ```
  Same real-Gemini + real-PostgreSQL discipline as Phase 1. Adds `tests/integration/test_multi_file_join.py` (real multi-file question against a real Gemini call, asserting the joined-dataset numeric answer), `tests/integration/test_pdf_ocr_ingestion.py` (real scanned-PDF fixture), and `tests/integration/test_cross_session_history.py` (create session on day 1, resume and correctly reference it on a simulated day 2).
- **How the user tests it (handoff seed):**
  1. Same run command as Phase 1. Open `http://localhost:8001/app/`.
  2. Upload two related files (or a folder) at once; the profile panel now shows a combined/joined schema. Ask a question that spans both files (e.g. "which rows in file A have no match in file B?") and get a real answer.
  3. Upload a scanned PDF; it is OCR'd and profiled like any other dataset.
  4. Ask a question whose answer is naturally numeric-over-time or numeric-over-category; a real chart renders next to the numbers. A cost-per-query figure now shows a real estimated dollar amount instead of "—".
  5. Reload the app (simulating a new day); the session history sidebar lists past sessions — clicking one resumes the full chat thread and dataset context.
  6. Click "Export" on a result; a cleaned/derived file downloads.

