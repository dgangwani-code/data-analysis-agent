# Architecture

---

## System Overview

A single-user web app: a Next.js frontend talks to a FastAPI backend over REST. The user uploads a data file; the backend parses it locally with pandas and computes a profile (schema + summary statistics) with no LLM involvement. The user then asks questions in a chat thread; each question runs a bounded LangGraph loop that alternates between an LLM node (Gemini — plans and writes pandas code) and a local node (executes that code against the real dataframe in a network-disabled sandbox, then summarizes the result). Only the summarized result, the code, and the question ever go back to the LLM — the raw dataframe never leaves the local process. Results, generated code, and chat history persist in PostgreSQL so the user can resume a multi-day analysis project.

## Component Map

```
Next.js UI (upload zone, profile panel, chat thread)
    ↓ REST (fetch, JSON + multipart)
FastAPI (src/api/*)  ──────────────────────────────┐
    ↓                                               │
Local tools (src/tools/*)                           │
  - file_parser: CSV/Excel → pandas DataFrame        │
  - profiler: DataFrame → schema + stats (no LLM)     │
  - sandbox_exec: restricted, network-disabled exec    │
    ↓                                               │
LangGraph agent (src/graph/*)                       │
  - plan_generate_code (LLM: Gemini)  ←──────────────┤
  - local_execute (local sandbox, real dataframe)     │
  - finalize_answer / best_guess_fallback (LLM)       │
    ↓                                               │
PostgreSQL (src/db/*)  ←── Dataset, DatasetProfile, ChatSession,
                            ChatMessage, AnalysisRun, AnalysisStep
    ↓
Local filesystem (data/uploads/<dataset_id>/…) ←── the actual uploaded file bytes;
                                                     never stored in the DB, never sent to the LLM
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **UI (Next.js)** | Upload interaction, profile display, chat thread, collapsible code, loading/error states, Phase-1 stub surfaces. |
| **API (FastAPI)** | HTTP boundary: validates requests, calls tools/graph runner, returns the `ok()`/`api_error()` envelope. |
| **Tools (`src/tools/`)** | Pure local functions: parse a file, compute a profile, execute generated code in a sandbox. Never call the LLM. |
| **Agent graph (`src/graph/`)** | The bounded code-gen/execute/inspect/refine loop. Owns the LLM boundary (see below). |
| **LLM client (`src/llm/`)** | Thin wrapper around the active provider (Gemini). Only ever receives schema/stats/code/question text — never a dataframe. |
| **Data (`src/db/`, filesystem)** | PostgreSQL for structured metadata/history; local filesystem for the actual file bytes. |

## Data Flow

1. Trigger: user uploads a file via the UI (`POST /datasets`).
2. `file_parser` loads it into a pandas DataFrame; the raw file is saved to local disk (`data/uploads/<dataset_id>/…`); `profiler` computes schema + summary statistics (column names/types/null-counts/ranges/sample values) purely locally — no LLM call. The `Dataset` and `DatasetProfile` rows are persisted; the response returns the profile immediately.
3. User asks a question (`POST /sessions/{id}/messages`). The graph runner loads the profile (schema + stats) and recent chat history, then invokes the LangGraph loop.
4. The loop alternates: `plan_generate_code` (Gemini, sees only schema/stats/question/prior-step summaries) → `local_execute` (loads the real DataFrame from disk, runs the generated code in a restricted, network-disabled exec, produces a small aggregated result or an error) → `inspect_result` (pure Python routing: success → finalize, error and under the step cap → refine, step cap reached → best-guess fallback).
5. Output: `finalize_answer` (or `best_guess_fallback`) produces a plain-language answer with key numbers, drawn only from the summarized result; the API returns the answer, the final generated code, and the step history (for the collapsible "what it tried" view). `AnalysisRun`/`AnalysisStep`/`ChatMessage` rows persist the full record for later resumption.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Google Gemini API | Plans/generates analysis code, and drafts the final plain-language answer | Node-level try/except sets `state["error"]`; graph routes to `handle_error`; API returns a clear "the analysis service is unavailable, try again" message — never a raw stack trace |
| PostgreSQL | Persists datasets, profiles, chat sessions/messages, analysis runs/steps | FastAPI returns `503`-style `api_error()`; app does not crash; retried on next request |
| Local filesystem (`data/uploads/`) | Stores the actual uploaded file bytes | If the file is missing/unreadable at execution time, `local_execute` returns a fatal error routed to `handle_error` with a clear message |

## LLM Boundary — What Crosses vs. What Stays Local

This is the single most important architectural constraint in this system. It is enforced at every node in the agent graph (full node-by-node detail in [`agent.md`](agent.md)) and provably tested (`tests/integration/test_llm_boundary.py`, Phase 1 gate).

**Crosses the LLM boundary (sent to Gemini):**
- The dataset **schema**: column names, inferred types, null counts, min/max/range for numeric columns, distinct-value counts and (for low-cardinality columns only) the distinct values themselves — never a sample of actual rows.
- **Summary statistics**: `describe()`-style aggregates, counts, group-by aggregates capped at a small row count (≤ 20 result rows), i.e. results that are already aggregated/derived, never a row-level dump of the source data.
- The **user's question** and the **conversation history** (prior questions/answers in the session — text only).
- The **generated code** itself (python/pandas source text) and, on retries, the **prior step's error message or result summary** — never the data the code touched.

**Stays 100% local (never sent to Gemini):**
- The raw uploaded file and the in-memory/on-disk DataFrame it parses to.
- Any row-level data — individual cell values, individual records, or any result set that is not already aggregated down to a small summary.
- Actual code **execution** — `local_execute` runs the LLM-generated code against the real DataFrame in-process, in a restricted, network-disabled sandbox. The LLM only ever sees the *code it wrote* and the *summarized result* of running it, never the data itself.

**Enforcement mechanism:** the `plan_generate_code`, `finalize_answer`, and `best_guess_fallback` nodes are the only nodes that call `LLMClient`. Each of those nodes is passed a `PromptContext` object built exclusively from `schema_summary` (str), `profile_stats` (dict of aggregates), `question`/`messages` (str/list of str), and `step_history` (list of `{code: str, result_summary: dict, error: str | None}`) — there is no code path by which a DataFrame or a raw row reaches `LLMClient.call_model()`. `tests/integration/test_llm_boundary.py` wraps the real Gemini client call and asserts a known unique fixture cell value never appears in any outbound prompt across a full multi-step run.

## Stack

- **Language:** Python 3.12 (backend), TypeScript (frontend) — matches the existing `pyproject.toml` (`requires-python = ">=3.11"`) and `frontend/package.json`.
  > **Assumed:** target Python 3.12 specifically (pyproject's floor of `>=3.11` is kept as-is; no change needed).
- **Agent framework:** LangGraph (already a dependency) — the bounded code-gen/execute/inspect/refine loop described in [`agent.md`](agent.md).
- **LLM provider + model:** Google Gemini, model `gemini-3.1-pro` (the existing `GeminiProvider.DEFAULT_MODEL`), selected via `AGENT_LLM_PROVIDER=gemini` (or auto-detected because `AGENT_GEMINI_API_KEY` is set). The existing `AnthropicProvider` code path stays intact and unused as an alternate provider the settings already support.
  > **Assumed:** `AGENT_GEMINI_API_KEY` is present in `.env`; `AGENT_ANTHROPIC_API_KEY` is left blank so auto-detection selects Gemini. If both were ever set, `AGENT_LLM_PROVIDER=gemini` should be set explicitly in `.env` to avoid ambiguity.
- **Backend:** FastAPI (already scaffolded), served on port 8001 per `harness/patterns/tech-stack.md`.
- **Database + ORM:** PostgreSQL + SQLAlchemy 2.0 (declarative `Mapped` style, matching the existing `src/db/models.py`), migrated with Alembic.
  > **Assumed:** the production `AGENT_DATABASE_URL` is a real PostgreSQL URL (`postgresql://…`). The `.env` checked into this working tree currently has `AGENT_DATABASE_URL=sqlite:///./data/agent.db` as a boilerplate placeholder — this must be updated to a real PostgreSQL URL and `psycopg2-binary` added to `pyproject.toml`'s `[project.dependencies]` before the Phase 1 gate can run, per the DB Driver Rule in `harness/patterns/tech-stack.md`. This is flagged back to the user/orchestrator as a required manual step, not silently assumed away.
- **Frontend:** Next.js 15 + React 19, static-exported and served by FastAPI at `/app` (already scaffolded, unchanged).
- **Dependency management:** uv (Python, `pyproject.toml`) / pnpm (TypeScript, `frontend/package.json`).

| Key library | Version | Purpose |
|-------------|---------|---------|
| `pandas` | >=2.2 | Parse CSV/Excel, compute profiles, execute generated analysis code |
| `openpyxl` | >=3.1 | Excel (`.xlsx`) read support for pandas |
| `python-multipart` | >=0.0.9 | FastAPI multipart file-upload parsing |
| `psycopg2-binary` | >=2.9 | PostgreSQL driver — **must be added to `[project.dependencies]`**, never dev-only |
| `structlog` | >=24.1 (existing) | Structured request/response/LLM-call logging (Observability, below) |
| `langgraph` | >=0.1 (existing) | The iterative agent loop |
| `google-genai` | >=2.9.0 (existing) | Gemini API client |
| *(Phase 2)* `pdfplumber` + `pytesseract` | latest | PDF text extraction + OCR fallback for scanned PDFs |
| *(Phase 2)* `recharts` (frontend) | ^2 | Interactive chart rendering |

**Avoid:** a hardcoded op-list the LLM maps questions onto (anti-pattern per `harness/patterns/agentic-ai.md` #22) — the agent always generates real executable code, never picks from a fixed menu of operations. Avoid heavyweight sandboxing infrastructure (Docker-per-query, gVisor) for this single-user local tool — an in-process, AST-restricted, network-disabled `exec()` with a wall-clock timeout is sufficient and keeps latency low; revisit only if this ever becomes multi-tenant.

## Deployment Model

Long-running local/self-hosted service: `uv run python -m src` serves both the FastAPI API and the built Next.js static export on `http://localhost:8001`. Single process, single worker — this is a personal tool used a few times a day, not a scaled multi-tenant deployment.

## Observability

- **Structured logging (`src/observability/events.py`, `structlog`):** every LLM call logs `{node, model, prompt_char_count, latency_ms, outcome}` to stdout — never the prompt/response text verbatim for the code-execution nodes (to avoid leaking generated code containing user column names into logs beyond what's needed for debugging; the question/answer text is fine to log since it never contains raw data). Every `local_execute` call logs `{step, status, latency_ms, error?}`.
- **LangSmith tracing:** enabled via `LANGCHAIN_TRACING_V2=true` / `LANGCHAIN_API_KEY` env vars (optional — if unset, structured stdout logging is the source of truth; both are wired from Phase 1, never deferred).
