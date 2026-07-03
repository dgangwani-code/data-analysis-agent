"""Session/message chat API routes — see `spec/api.md`.

Only the endpoints documented in `spec/api.md` are implemented here:
  - GET  /sessions/{session_id}
  - GET  /sessions/{session_id}/messages
  - POST /sessions/{session_id}/messages

`spec/api.md` does not document a bare `POST /sessions` creation route —
per `spec/data.md`'s Data Lifecycle, a `ChatSession` is created by
`POST /datasets` (owned by the `file-parsing-profiling` slice) when no
`session_id` is supplied on upload. This router only operates on sessions
that already exist.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.session import get_session
from db.models import AnalysisRun, AnalysisStep, ChatMessage, ChatSession
from domain.chat import (
    AnalysisStepOut,
    AskRequest,
    AskResponse,
    ChatMessageOut,
    ChatMessagesResponse,
    ChatSessionOut,
)
from graph.runner import run_agent

router = APIRouter()

# Number of most-recent chat turns handed to the agent as conversation
# memory — mirrors `spec/agent.md`'s "Context window management" cap.
_CONTEXT_WINDOW = 20


def _get_session_or_404(db: Session, session_id: str) -> ChatSession:
    chat_session = db.get(ChatSession, session_id)
    if chat_session is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)
    return chat_session


@router.get("/sessions/{session_id}")
def get_session_metadata(session_id: str, db: Session = Depends(get_session)) -> dict:
    chat_session = _get_session_or_404(db, session_id)
    return ok(
        ChatSessionOut(
            session_id=chat_session.id,
            title=chat_session.title,
            active_dataset_id=chat_session.active_dataset_id,
        ).model_dump()
    )


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str, db: Session = Depends(get_session)) -> dict:
    _get_session_or_404(db, session_id)

    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    ).all()

    messages = [
        ChatMessageOut(
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            run_id=row.run_id,
        )
        for row in rows
    ]
    return ok(ChatMessagesResponse(session_id=session_id, messages=messages).model_dump())


@router.post("/sessions/{session_id}/messages")
def ask_question(
    session_id: str, req: AskRequest, db: Session = Depends(get_session)
) -> dict:
    chat_session = _get_session_or_404(db, session_id)

    content = req.content.strip()
    if not content:
        raise api_error("VALIDATION_ERROR", "content must not be empty", 400)

    if not chat_session.active_dataset_id:
        raise api_error(
            "NO_ACTIVE_DATASET", "Session has no active dataset yet", 400
        )

    in_progress = db.scalars(
        select(AnalysisRun).where(
            AnalysisRun.session_id == session_id, AnalysisRun.status == "pending"
        )
    ).first()
    if in_progress is not None:
        raise api_error(
            "RUN_IN_PROGRESS",
            "A run is already in progress for this session",
            409,
        )

    # Prior turns, oldest-first, capped to the last N — this is the
    # `context_messages` memory the graph reads via `build_context`.
    prior_rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(_CONTEXT_WINDOW)
    ).all()
    prior_messages = [
        {"role": row.role, "content": row.content} for row in reversed(prior_rows)
    ]

    # Persist the user's turn before invoking the graph.
    user_message = ChatMessage(session_id=session_id, role="user", content=content)
    db.add(user_message)
    db.flush()

    try:
        result = run_agent(
            dataset_id=chat_session.active_dataset_id,
            question=content,
            session_id=session_id,
            prior_messages=prior_messages,
        )
    except Exception as exc:  # Gemini/agent unavailable for the run's retry budget
        raise api_error(
            "AGENT_UNAVAILABLE",
            f"The analysis service is unavailable, try again ({exc})",
            502,
        ) from exc

    # `run_agent` may return either the full final AgentState (a dict with
    # a "run_id" key) or, per the skeleton runner pattern, just the run_id
    # string — the AnalysisRun/AnalysisStep rows are the source of truth
    # either way (persisted by the graph's `finalize` node).
    run_id = result.get("run_id") if isinstance(result, dict) else result

    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise api_error(
            "AGENT_UNAVAILABLE", "Analysis run was not persisted", 502
        )

    if run.status == "failed":
        raise api_error(
            "AGENT_UNAVAILABLE",
            run.error_message or "The analysis service is unavailable, try again",
            502,
        )

    step_rows = db.scalars(
        select(AnalysisStep)
        .where(AnalysisStep.run_id == run_id)
        .order_by(AnalysisStep.step_number.asc())
    ).all()
    steps = [
        AnalysisStepOut(
            step_number=step.step_number,
            generated_code=step.generated_code,
            status=step.status,
            result_summary=step.result_summary,
            error_message=step.error_message,
        )
        for step in step_rows
    ]

    # Ensure the assistant's turn is persisted and linked to this run —
    # idempotent so this works whether or not the graph's `finalize` node
    # already appended it.
    existing_assistant_message = db.scalars(
        select(ChatMessage).where(
            ChatMessage.run_id == run_id, ChatMessage.role == "assistant"
        )
    ).first()
    if existing_assistant_message is None and run.final_answer:
        db.add(
            ChatMessage(
                session_id=session_id,
                run_id=run_id,
                role="assistant",
                content=run.final_answer,
            )
        )

    chat_session.updated_at = datetime.now(timezone.utc)
    db.flush()

    return ok(
        AskResponse(
            run_id=run_id,
            session_id=session_id,
            status=run.status,
            answer=run.final_answer,
            final_code=run.final_code,
            is_fallback=run.is_fallback,
            steps=steps,
        ).model_dump()
    )
