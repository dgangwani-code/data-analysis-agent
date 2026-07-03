"""Nodes for the bounded code-gen/execute/inspect/refine loop.

Only `plan_generate_code`, `finalize_answer`, and `best_guess_fallback` call the
LLM, and each is passed exclusively `schema_summary`/`profile_stats`/`question`/
`context_messages`/`step_history` — text and JSON-safe aggregates only. No node
in this file ever passes a DataFrame or a raw row to `LLMClient`. `local_execute`
is the only node that touches the real DataFrame, and it never forwards
anything but a capped/aggregated `result_summary` back into state (see
spec/architecture.md#llm-boundary-what-crosses-vs-what-stays-local).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from db.models import AnalysisRun, AnalysisStep, ChatMessage, Dataset, DatasetProfile
from db.session import create_db_session
from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger
from tools import file_parser, sandbox_exec

logger = get_logger("graph")

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

MAX_CONTEXT_MESSAGES = 20


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _call_with_retry(fn, retries: int = 1) -> str:
    """One immediate retry on transient error, then re-raise (per spec/agent.md)."""
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, retried once
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def _extract_code(text: str) -> str | None:
    match = _CODE_BLOCK_RE.search(text or "")
    if not match:
        return None
    code = match.group(1).strip()
    return code or None


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _build_plan_prompt(state: AgentState) -> str:
    lines = [f"Question: {state.get('question', '')}", "", "Dataset schema and stats:", state.get("schema_summary", "")]

    profile_stats = state.get("profile_stats")
    if profile_stats:
        lines += ["", f"Structured stats (JSON): {_safe_json(profile_stats)}"]

    context_messages = state.get("context_messages") or []
    if context_messages:
        lines += ["", "Conversation so far:"]
        for m in context_messages:
            lines.append(f"  {m.get('role')}: {m.get('content')}")

    step_history = state.get("step_history") or []
    if step_history:
        lines += ["", "Prior attempts this run:"]
        for i, step in enumerate(step_history, start=1):
            lines.append(f"  Step {i} code:\n{step.get('code')}")
            if step.get("error"):
                lines.append(f"  Step {i} error: {step['error']}")
            else:
                lines.append(f"  Step {i} result_summary: {_safe_json(step.get('result_summary'))}")
        lines += ["", "The previous attempt(s) did not fully succeed. Write corrected code."]

    lines += [
        "",
        "Write pandas code (assume a DataFrame variable `df` is already loaded) "
        "that computes the answer and assigns it to a variable named `result`. "
        "`result` should be a scalar, small dict, small list, or a small "
        "(<=20 row) DataFrame/Series — never the full raw dataset.",
    ]
    return "\n".join(lines)


def _build_finalize_prompt(state: AgentState, *, fallback: bool) -> str:
    lines = [f"Question: {state.get('question', '')}", "", "Dataset schema:", state.get("schema_summary", "")]

    if fallback:
        lines += ["", "FALLBACK MODE — no attempt fully succeeded.", "", "All attempts made this run:"]
        for i, step in enumerate(state.get("step_history") or [], start=1):
            lines.append(f"  Step {i} code:\n{step.get('code')}")
            lines.append(
                f"  Step {i} status={step.get('status')} error={step.get('error')} "
                f"result_summary={_safe_json(step.get('result_summary'))}"
            )
        lines += [
            "",
            "Synthesize the best possible answer from whatever partial information "
            "is available above. Explicitly flag this as an uncertain best guess.",
        ]
    else:
        lines += [
            "",
            f"Final result summary (aggregated, JSON): {_safe_json(state.get('current_result_summary'))}",
            "",
            f"Code that produced it:\n{state.get('current_code')}",
            "",
            "Write a plain-language answer to the question with key numbers inline. "
            "Flag any assumption you had to make about ambiguous column names or interpretation.",
        ]
    return "\n".join(lines)


def _load_dataframe(dataset_id: str):
    with create_db_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            raise ValueError(f"Dataset {dataset_id} not found")
        storage_path = dataset.storage_path
        filename = dataset.filename

    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found on disk: {storage_path}")

    content = path.read_bytes()
    df, _file_type = file_parser.parse_file(content, filename)
    return df


def build_context(state: AgentState) -> AgentState:
    """Loads the pre-computed profile + recent chat history; resets loop counters.

    No LLM call. This is the node that establishes exactly what the LLM
    boundary will and will not see for the rest of the run.
    """
    dataset_id = state.get("dataset_id")
    session_id = state.get("session_id")
    try:
        with create_db_session() as session:
            profile = (
                session.query(DatasetProfile)
                .filter(DatasetProfile.dataset_id == dataset_id)
                .order_by(DatasetProfile.profiled_at.desc())
                .first()
            )
            if profile is None:
                return {**state, "error": f"No profile found for dataset {dataset_id!r}"}

            schema_summary = profile.schema_summary_text
            profile_stats = profile.stats_summary

            context_messages: list[dict] = []
            if session_id:
                rows = (
                    session.query(ChatMessage)
                    .filter(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(MAX_CONTEXT_MESSAGES)
                    .all()
                )
                context_messages = [{"role": r.role, "content": r.content} for r in reversed(rows)]

        return {
            **state,
            "schema_summary": schema_summary,
            "profile_stats": profile_stats,
            "context_messages": state.get("context_messages") or context_messages,
            "step_count": 0,
            "step_history": [],
            "max_steps": state.get("max_steps") or 6,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("build_context_failed", dataset_id=dataset_id, error=str(exc))
        return {**state, "error": f"build_context failed: {exc}"}


def plan_generate_code(state: AgentState) -> AgentState:
    """LLM node: writes the next pandas code attempt. Sees schema/stats/question/
    conversation/prior-step summaries only — never the DataFrame."""
    step_count = state.get("step_count", 0) + 1
    start = time.perf_counter()
    try:
        system_prompt = _load_prompt("plan_code.md")
        user_prompt = _build_plan_prompt(state)
        response = _call_with_retry(lambda: LLMClient().call_model(user_prompt, system=system_prompt))
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        code = _extract_code(response)
        if code is None:
            logger.warning("plan_generate_code_unparsable", step=step_count, latency_ms=latency_ms)
            return {
                **state,
                "step_count": step_count,
                "error": "plan_generate_code: model response did not contain a parsable code block",
            }
        logger.info(
            "plan_generate_code_ok",
            step=step_count,
            model=getattr(LLMClient, "model", None),
            prompt_char_count=len(user_prompt),
            latency_ms=latency_ms,
        )
        return {**state, "step_count": step_count, "current_code": code}
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.error("plan_generate_code_failed", step=step_count, latency_ms=latency_ms, error=str(exc))
        return {**state, "step_count": step_count, "error": f"plan_generate_code failed: {exc}"}


def local_execute(state: AgentState) -> AgentState:
    """The only node that touches the real DataFrame. Runs generated code in a
    restricted, network-disabled sandbox and reduces the result to a capped,
    JSON-safe summary before it ever re-enters state."""
    dataset_id = state.get("dataset_id")
    code = state.get("current_code") or ""
    step_number = state.get("step_count", 0)
    start = time.perf_counter()

    try:
        df = _load_dataframe(dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("local_execute_dataset_load_failed", dataset_id=dataset_id, error=str(exc))
        return {**state, "error": f"local_execute: failed to load dataset: {exc}"}

    result = sandbox_exec.run(code, df)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "sandbox_exec_run",
        step=step_number,
        status=result["status"],
        latency_ms=latency_ms,
        error=result.get("error"),
    )

    step_entry = {
        "code": code,
        "result_summary": result.get("result_summary"),
        "error": result.get("error"),
        "status": result["status"],
    }
    step_history = [*(state.get("step_history") or []), step_entry]

    return {
        **state,
        "step_history": step_history,
        "current_result_summary": result.get("result_summary"),
        "current_error": result.get("error"),
    }


def finalize_answer(state: AgentState) -> AgentState:
    """LLM node: turns the summarized result into a plain-language answer.
    Reached only when local_execute succeeded."""
    start = time.perf_counter()
    try:
        system_prompt = _load_prompt("finalize_answer.md")
        user_prompt = _build_finalize_prompt(state, fallback=False)
        answer = _call_with_retry(lambda: LLMClient().call_model(user_prompt, system=system_prompt))
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info("finalize_answer_ok", latency_ms=latency_ms, prompt_char_count=len(user_prompt))
        return {
            **state,
            "final_answer": answer,
            "final_code": state.get("current_code"),
            "status": "completed",
            "is_fallback": False,
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.error("finalize_answer_failed", latency_ms=latency_ms, error=str(exc))
        return {**state, "error": f"finalize_answer failed: {exc}"}


def best_guess_fallback(state: AgentState) -> AgentState:
    """LLM node: reached only when step_count >= max_steps without success.
    Synthesizes the best available answer and explicitly flags it as a guess."""
    start = time.perf_counter()
    try:
        system_prompt = _load_prompt("finalize_answer.md")
        user_prompt = _build_finalize_prompt(state, fallback=True)
        answer = _call_with_retry(lambda: LLMClient().call_model(user_prompt, system=system_prompt))
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info("best_guess_fallback_ok", latency_ms=latency_ms, prompt_char_count=len(user_prompt))
        step_history = state.get("step_history") or []
        last_code = step_history[-1]["code"] if step_history else None
        return {
            **state,
            "final_answer": answer,
            "final_code": last_code,
            "status": "completed_with_fallback",
            "is_fallback": True,
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.error("best_guess_fallback_failed", latency_ms=latency_ms, error=str(exc))
        return {**state, "error": f"best_guess_fallback failed: {exc}"}


def handle_error(state: AgentState) -> AgentState:
    """Terminal error state. Never reached for a recoverable code-execution
    error — only for fatal failures (missing dataset, DB failure, exhausted
    LLM retries)."""
    run_id = state.get("run_id")
    error = state.get("error")
    try:
        with create_db_session() as session:
            run = session.get(AnalysisRun, run_id) if run_id else None
            if run is not None:
                from datetime import datetime, timezone

                run.status = "failed"
                run.error_message = error
                run.completed_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        logger.error("handle_error_persist_failed", run_id=run_id, error=str(exc))

    logger.error("agent_run_failed", run_id=run_id, error=error)
    return {**state, "status": "failed"}


def finalize(state: AgentState) -> AgentState:
    """Terminal persistence node: writes AnalysisRun + one AnalysisStep per
    step_history entry + the assistant ChatMessage, in exact 1:1 correspondence
    with the in-memory step_history. A DB hiccup here never blocks the
    in-memory answer from being returned to the caller."""
    run_id = state.get("run_id")
    try:
        with create_db_session() as session:
            from datetime import datetime, timezone

            run = session.get(AnalysisRun, run_id) if run_id else None
            step_history = state.get("step_history") or []
            if run is not None:
                run.status = state.get("status", "completed")
                run.final_answer = state.get("final_answer")
                run.final_code = state.get("final_code")
                run.step_count = len(step_history)
                run.is_fallback = bool(state.get("is_fallback", False))
                run.completed_at = datetime.now(timezone.utc)

            for i, step in enumerate(step_history, start=1):
                session.add(
                    AnalysisStep(
                        run_id=run_id,
                        step_number=i,
                        generated_code=step.get("code") or "",
                        result_summary=step.get("result_summary"),
                        status=step.get("status") or "error",
                        error_message=step.get("error"),
                    )
                )

            session_id = state.get("session_id")
            final_answer = state.get("final_answer")
            if session_id and final_answer:
                session.add(
                    ChatMessage(
                        session_id=session_id,
                        run_id=run_id,
                        role="assistant",
                        content=final_answer,
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.error("finalize_persist_failed", run_id=run_id, error=str(exc))

    return state
