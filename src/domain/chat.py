"""Pydantic domain models for the chat session/message API surface.

Shapes here mirror `spec/api.md`'s documented `data` payloads for:
  - GET  /sessions/{session_id}
  - GET  /sessions/{session_id}/messages
  - POST /sessions/{session_id}/messages
"""
from datetime import datetime

from pydantic import BaseModel, Field


class ChatSessionOut(BaseModel):
    """`GET /sessions/{session_id}` response shape."""

    session_id: str
    title: str | None = None
    active_dataset_id: str | None = None


class ChatMessageOut(BaseModel):
    """One entry in `GET /sessions/{session_id}/messages`'s `messages` list."""

    role: str
    content: str
    created_at: datetime
    run_id: str | None = None


class ChatMessagesResponse(BaseModel):
    """`GET /sessions/{session_id}/messages` response shape."""

    session_id: str
    messages: list[ChatMessageOut]


class AskRequest(BaseModel):
    """`POST /sessions/{session_id}/messages` request body."""

    content: str = Field(..., min_length=1)


class AnalysisStepOut(BaseModel):
    """One entry in an `AskResponse.steps` list — mirrors `AnalysisStep`."""

    step_number: int
    generated_code: str
    status: str
    result_summary: dict | None = None
    error_message: str | None = None


class AskResponse(BaseModel):
    """`POST /sessions/{session_id}/messages` response shape."""

    run_id: str
    session_id: str
    status: str
    answer: str | None = None
    final_code: str | None = None
    is_fallback: bool = False
    steps: list[AnalysisStepOut] = Field(default_factory=list)
