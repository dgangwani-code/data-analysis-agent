"""Entry point for a single question-answering loop invocation.

Creates the AnalysisRun row up front (status="pending"), invokes the compiled
graph, and returns the run's result for the API layer to surface. The graph's
own `finalize`/`handle_error` nodes are responsible for the terminal DB writes
(AnalysisRun status/answer/code, AnalysisStep rows, the assistant ChatMessage).
"""
from __future__ import annotations

from typing import Any

from db.models import AnalysisRun
from db.session import create_db_session
from graph.agent import agentic_ai
from graph.state import AgentState

DEFAULT_MAX_STEPS = 6


def run_agent(
    dataset_id: str,
    question: str,
    session_id: str | None = None,
    prior_messages: list[dict] | None = None,
) -> dict[str, Any]:
    """Runs one bounded analysis loop for `question` against `dataset_id`.

    Returns a dict: {run_id, status, final_answer, final_code, step_history,
    is_fallback, error}.
    """
    with create_db_session() as session:
        run = AnalysisRun(
            session_id=session_id,
            dataset_id=dataset_id,
            question=question,
            status="pending",
            step_count=0,
            is_fallback=False,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    initial: AgentState = {
        "run_id": run_id,
        "session_id": session_id or "",
        "dataset_id": dataset_id,
        "question": question,
        "context_messages": prior_messages or [],
        "step_count": 0,
        "max_steps": DEFAULT_MAX_STEPS,
        "step_history": [],
        "current_code": None,
        "current_result_summary": None,
        "current_error": None,
        "final_answer": None,
        "final_code": None,
        "is_fallback": False,
        "error": None,
        "status": None,
    }

    final_state = agentic_ai.invoke(initial, config={"recursion_limit": 50})

    return {
        "run_id": run_id,
        "status": final_state.get("status"),
        "final_answer": final_state.get("final_answer"),
        "final_code": final_state.get("final_code"),
        "step_history": final_state.get("step_history", []),
        "is_fallback": final_state.get("is_fallback", False),
        "error": final_state.get("error"),
    }
