"""AgentState — the bounded code-gen/execute/inspect/refine loop's LangGraph state.

See spec/agent.md#agent-state. Every field here is either identity/control data
or text/JSON-safe summaries — never a raw DataFrame or row-level data (see
spec/architecture.md#llm-boundary-what-crosses-vs-what-stays-local).
"""
from typing import TypedDict


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
