# Agent

---

## Agent Architecture Pattern

| Pattern | Use when |
|---------|----------|
| **Single-agent loop** | One LLM drives a deterministic tool-call loop. No branches, no handoffs. |
| **Graph (LangGraph)** | Multi-step pipeline with conditional edges, checkpointing, or parallel nodes. |
| **Multi-agent** | Specialised sub-agents with distinct roles; orchestrator routes between them. |
| **Supervisor** | One supervisor LLM dispatches to worker agents based on task type. |
| **Human-in-the-loop** | Execution pauses at defined checkpoints for user review or approval. |

**Chosen: Graph (LangGraph)**, composing two `harness/patterns/agentic-ai.md` patterns beyond the base ReAct loop: **#22 LLM-Generated Code Execution** (the LLM writes pandas code; the system executes it against the real local data) and **#12 Exception Handling and Recovery** (a bounded refine loop on execution failure, with a flagged best-guess fallback when the step budget is exhausted). This is chosen because the task is inherently "arbitrary, open-ended questions about structured data" — the anti-pattern (a hardcoded op-list) fails on any question outside a fixed menu, so the agent must always generate and run real code. A conditional-edge graph is required (not a plain loop) because the routing after each execution genuinely branches three ways: success → finalize, recoverable error → refine, step-budget exhausted → fallback.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `plan_generate_code` | Gemini | `gemini-3.1-pro` | Code generation needs strong reasoning about schema + prior errors; this is the quality-critical node. |
| `finalize_answer` | Gemini | `gemini-3.1-pro` | Final answer quality matters — it's what the user reads and acts on. |
| `best_guess_fallback` | Gemini | `gemini-3.1-pro` | Same model; a smaller/faster model isn't warranted since this path is rare and still needs to reason over the full step history. |

Model is read from `AGENT_LLM_MODEL` (falls back to the provider default `gemini-3.1-pro`) via the existing `LLMClient`/`GeminiProvider` — no new env vars.

**Fallback behaviour:** any Gemini call failure (timeout, rate-limit, API error) is caught in the calling node, sets `state["error"]`, and routes to `handle_error` — the API surfaces "the analysis service is unavailable, try again" rather than a stack trace. No silent retry-forever; a single node-level retry (one immediate retry on a transient 5xx/timeout) is attempted before treating it as a hard error.

**Prompt strategy:** system/user split via `LLMClient.call_model(prompt, system=...)`. `plan_generate_code` uses `src/prompts/plan_code.md` as the system prompt and requests a structured response (a fenced ```python code block plus a one-line rationale, parsed by the node — not full JSON mode, since Gemini code-fence extraction is simpler and more robust for multi-line code than escaping code inside JSON). `finalize_answer`/`best_guess_fallback` use `src/prompts/finalize_answer.md` and request plain markdown prose with numbers inline.

---

## Tools & Tool Calling

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `file_parser.parse` | Loads a CSV/Excel file into a pandas DataFrame | file path, declared type | `pandas.DataFrame` | Reads local disk only |
| `profiler.profile` | Computes schema + summary statistics from a DataFrame — no LLM call | `pandas.DataFrame` | `dict` (schema + stats, JSON-safe) | None (pure function) |
| `sandbox_exec.run` | Executes LLM-generated code against a real DataFrame in a restricted, network-disabled environment with a wall-clock timeout | `code: str`, `dataframe: pandas.DataFrame` | `{status, result_summary: dict, error: str \| None}` | In-process `exec()` with a restricted globals dict (allowlisted imports: `pandas`, `numpy`, `math`, `statistics`, `datetime`, `re`; AST-checked to reject `import os`, `socket`, `subprocess`, `__import__`, dunder attribute access, and any network call); 15-second timeout per call |

This is **not** LLM tool-calling in the function-calling-API sense — `plan_generate_code` is a plain text-generation call that *returns* code as text; `local_execute` then runs that code via `sandbox_exec.run`. The LLM never directly invokes a tool with live data in scope.

**Tool selection strategy:** N/A — there is exactly one execution path (generate code → run it locally); no tool routing decision.

**Tool failure handling:** `sandbox_exec.run` catches every exception (syntax error, runtime error, timeout) and returns `{status: "error", error: <message text only>}` — it never raises out of the node. The graph's conditional edge decides whether to refine or fall back based on this status.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                          # set at initialisation, persisted as AnalysisRun.id
    session_id: str                      # chat session this run belongs to
    dataset_id: str                      # dataset this run analyzes

    # Input
    question: str                        # the user's current question
    context_messages: list[dict]         # prior {role, content} turns in this session — text only

    # Pipeline data (populated progressively by nodes)
    schema_summary: str                  # human-readable schema description (build_context)
    profile_stats: dict                  # structured schema+stats dict (build_context)
    step_count: int                      # number of plan/execute cycles attempted so far
    max_steps: int                       # bound on step_count, set to 6 at initialisation
    step_history: list[dict]             # [{code, result_summary, error, status}, ...] — no raw data, ever
    current_code: str | None             # code generated on the current step
    current_result_summary: dict | None  # summarized result of the current step's execution
    current_error: str | None            # error text from the current step's execution, if any

    # Output
    final_answer: str | None             # plain-language answer (finalize_answer / best_guess_fallback)
    final_code: str | None               # the code that produced (or last attempted to produce) the answer
    is_fallback: bool                    # True if the best-guess fallback path was taken

    # Control
    error: str | None                    # set by any node on fatal failure (routes to handle_error)
    status: str | None                   # "completed" | "completed_with_fallback" | "failed"
```

---

## Nodes / Steps

### `build_context`

**Reads from state:** `dataset_id`, `session_id`, `question`

**Writes to state:** `schema_summary`, `profile_stats`, `context_messages`, `step_count=0`, `step_history=[]`, `max_steps=6`

**LLM call:** no

**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL | Load `DatasetProfile` by `dataset_id`; load last N `ChatMessage` rows for `session_id` | fatal — sets `state["error"]`, routes to `handle_error` (e.g. dataset was deleted) |

**Behaviour:** Loads the already-computed profile (no re-parsing, no LLM call) and recent chat history, and resets the per-run loop counters. This is the node that establishes exactly what the LLM boundary will and will not see for the rest of the run.

### `plan_generate_code`

**Reads from state:** `question`, `schema_summary`, `profile_stats`, `context_messages`, `step_history`, `step_count`

**Writes to state:** `current_code`, `step_count += 1`

**LLM call:** yes — Gemini `gemini-3.1-pro`, system prompt `src/prompts/plan_code.md`, output parsed from a fenced code block.

**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini API | Generate pandas code for the current step | one immediate retry on transient error, then fatal — sets `state["error"]`, routes to `handle_error` |

**Behaviour:** Composes a prompt from the question, schema/stats, prior step summaries/errors (text only), and conversation history, and asks the model to write the next piece of pandas code to try. On the first call this is "answer the question"; on a refine call, the prompt explicitly includes the previous error so the model can correct course.

### `local_execute`

**Reads from state:** `current_code`, `dataset_id`

**Writes to state:** `current_result_summary`, `current_error`, appends `{code, result_summary, error, status}` to `step_history`

**LLM call:** no

**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Load the dataset's DataFrame from `data/uploads/<dataset_id>/…` | fatal if the file is missing/unreadable — sets `state["error"]`, routes to `handle_error` |
| Local sandbox (`sandbox_exec.run`) | Execute `current_code` against the real DataFrame, no network, 15s timeout | non-fatal — captured as `current_error`, routes back into the refine loop via the conditional edge |

**Behaviour:** The only node that touches the real data. Runs the generated code in-process with a restricted globals dict, then reduces the result to a JSON-safe summary (scalars, or an aggregated table capped at 20 rows) before it ever re-enters state that a later LLM node will read. If the result is larger than the cap, it is summarized further (e.g. `describe()` of the result) rather than truncated silently — the summary always states that it was aggregated.

### `handle_error`

**Reads from state:** `error`, `run_id`

**Writes to state:** `status = "failed"`

**LLM call:** no

**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL | Update `AnalysisRun.status = "failed"`, `error_message` | logged, run still terminates |

**Behaviour:** Terminates the graph on any fatal error (missing dataset, DB failure, exhausted-retry LLM failure). Never reached for a recoverable code-execution error — those route through the refine loop instead.

### `finalize_answer`

**Reads from state:** `question`, `schema_summary`, `current_result_summary`, `current_code`, `step_history`

**Writes to state:** `final_answer`, `final_code = current_code`, `status = "completed"`, `is_fallback = False`

**LLM call:** yes — Gemini `gemini-3.1-pro`, system prompt `src/prompts/finalize_answer.md`.

**External calls:** none beyond the LLM call above.

**Behaviour:** Reached only when `local_execute` succeeded. Turns the summarized result into a plain-language answer with key numbers pulled from `current_result_summary`, and flags any assumption the model had to make (e.g. how it interpreted an ambiguous column name).

### `best_guess_fallback`

**Reads from state:** `question`, `schema_summary`, `step_history` (the full attempt history)

**Writes to state:** `final_answer` (explicitly flagged as a best guess), `final_code = step_history[-1]["code"]`, `status = "completed_with_fallback"`, `is_fallback = True`

**LLM call:** yes — Gemini `gemini-3.1-pro`, same prompt file as `finalize_answer` with a fallback-mode instruction appended.

**External calls:** none beyond the LLM call above.

**Behaviour:** Reached only when `step_count >= max_steps` without a successful execution. Synthesizes the best available answer from whatever partial/erroring attempts exist in `step_history`, explicitly tells the user it's an uncertain best guess, and summarizes what was tried and why it didn't fully resolve (surfaced in the UI's "what it tried" disclosure).

### `finalize`

**Reads from state:** `run_id`, `final_answer`, `final_code`, `status`, `step_history`

**Writes to state:** none (terminal persistence node)

**LLM call:** no

**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL | Persist `AnalysisRun` (final status/answer/code) and one `AnalysisStep` row per `step_history` entry; append the assistant's `ChatMessage` | fatal — sets `state["error"]` and logs; the in-memory answer is still returned to the API caller even if persistence fails, so the user isn't blocked by a DB hiccup, but the run is flagged for retry-on-read |

**Behaviour:** The single place a run and all of its steps are written to the database, keeping the graph's in-memory step history and the persisted `AnalysisStep` rows in exact 1:1 correspondence.

---

## Graph / Flow Topology

```
START
  │
  ▼
build_context ──(error)──► handle_error ──► END
  │
  ▼
plan_generate_code ──(error)──► handle_error ──► END
  │
  ▼
local_execute
  │
  ├──(success)────────────────────────► finalize_answer ──► finalize ──► END
  ├──(error, step_count < max_steps)──► plan_generate_code   (refine loop)
  └──(error, step_count >= max_steps)─► best_guess_fallback ──► finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `build_context` | `state.get("error")` is not None | `handle_error` |
| `build_context` | else | `plan_generate_code` |
| `plan_generate_code` | `state.get("error")` is not None | `handle_error` |
| `plan_generate_code` | else | `local_execute` |
| `local_execute` | `current_error is None` (execution succeeded) | `finalize_answer` |
| `local_execute` | `current_error is not None` and `step_count < max_steps` | `plan_generate_code` |
| `local_execute` | `current_error is not None` and `step_count >= max_steps` | `best_guess_fallback` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state (`AgentState`) | `step_history`, current code/result/error — all in-progress refine-loop data |
| **Across runs (within a session)** | PostgreSQL `ChatMessage` | Every user question and assistant answer, in order, keyed by `session_id` — loaded into `context_messages` by `build_context` on every new question, giving genuine multi-turn memory within the session |
| **Across sessions (Phase 2)** | PostgreSQL `ChatSession` list + browsing UI | Past sessions become resumable across days; Phase 1 persists the data but does not yet expose a history-browsing UI (labelled stub) |

**Context window management:** `context_messages` is capped at the last 20 turns per session for Phase 1 (a personal, few-times-a-day tool won't realistically exceed this in one sitting); `step_history` entries are already reduced to summaries (never raw data), so the loop's own context stays small by construction rather than needing separate truncation logic.

---

## Human-in-the-Loop Checkpoints

None. Per intake, the agent asks a clarifying question up front only when genuinely uncertain (handled inside `plan_generate_code`'s prompt — the model may return a "clarifying question" response instead of code on the *first* step of a run, which the API surfaces as the answer and ends the run without executing anything); otherwise it proceeds autonomously through the bounded loop and flags assumptions in the final answer rather than pausing for approval.

---

## Error Handling & Recovery

**Node-level:** Every node catches its own exceptions. `plan_generate_code` and `finalize_answer`/`best_guess_fallback` catch Gemini API errors (one immediate retry, then fatal). `local_execute` catches every possible exception from the generated code (syntax errors, runtime errors, timeouts) and never lets one propagate — it always returns a structured `{status, error}` instead.

**Graph-level (`handle_error` node):**
- Reads: `state.error`, `state.run_id`
- Updates DB: `AnalysisRun.status → "failed"`, `error_message`, timestamps
- Logs the error with `run_id` context via `structlog`
- Terminates the graph

**Resume / retry strategy:** A failed run is not auto-resumed; the user simply asks the question again (a new `run_id`), and the fresh `build_context` call re-establishes state. This is a deliberate simplification for a synchronous, few-times-a-day personal tool — no checkpoint store is needed.

**Partial failure:** Recoverable failures (a code-execution error) never abort the run — they route into the refine loop and, if the budget is exhausted, into the flagged best-guess fallback. Only truly fatal failures (missing dataset, DB down, exhausted LLM retries) abort via `handle_error`.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One trace per `run_id`, one span per node | LangSmith (`LANGCHAIN_TRACING_V2=true`) when configured; structured stdout log always |
| **LLM calls** | Node name, model, prompt char count, latency, outcome (never the raw prompt/response body for code nodes) | `structlog` → stdout |
| **Tool calls** | `sandbox_exec.run`: step number, status, latency, error (if any) | `structlog` → stdout |
| **Run outcome** | Final status, step count, `is_fallback`, total duration | DB (`AnalysisRun`) + structured log |

---

## Concurrency Model

- **Run isolation:** one analysis run at a time per session — `POST /sessions/{id}/messages` returns `409` if a run for that session is already in progress. This matches the single-user, synchronous-chat usage pattern; no queueing needed for Phase 1.
- **Parallel nodes within a run:** none — the refine loop is inherently sequential (each step's code generation depends on the previous step's result).
- **Checkpointing:** none for Phase 1 — runs are short-lived (bounded at 6 LLM round-trips) and synchronous; no human-in-the-loop pause requires resumability. Revisit with `PostgresSaver` only if a future phase adds long-running or pausable runs.

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    build_context, plan_generate_code, local_execute,
    finalize_answer, best_guess_fallback, handle_error, finalize,
)
from graph.edges import after_build_context, after_plan, after_execute


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("build_context", build_context)
    g.add_node("plan_generate_code", plan_generate_code)
    g.add_node("local_execute", local_execute)
    g.add_node("finalize_answer", finalize_answer)
    g.add_node("best_guess_fallback", best_guess_fallback)
    g.add_node("handle_error", handle_error)
    g.add_node("finalize", finalize)

    g.set_entry_point("build_context")

    g.add_conditional_edges(
        "build_context", after_build_context,
        {"plan_generate_code": "plan_generate_code", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "plan_generate_code", after_plan,
        {"local_execute": "local_execute", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "local_execute", after_execute,
        {
            "finalize_answer": "finalize_answer",
            "plan_generate_code": "plan_generate_code",
            "best_guess_fallback": "best_guess_fallback",
        },
    )

    g.add_edge("finalize_answer", "finalize")
    g.add_edge("best_guess_fallback", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()
```
