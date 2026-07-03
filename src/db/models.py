from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    """One uploaded file (Phase 1: exactly one file per dataset)."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("chat_sessions.id"), nullable=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="profiling")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class DatasetProfile(Base):
    """Auto-computed schema + summary-statistics profile for a Dataset."""

    __tablename__ = "dataset_profiles"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    schema_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    stats_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    profiled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class ChatSession(Base):
    """One ongoing conversation/analysis project."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_dataset_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey(
            "datasets.id", use_alter=True, name="fk_chat_sessions_active_dataset_id"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ChatMessage(Base):
    """One turn in a session — either the user's question or the assistant's answer."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chat_sessions.id"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("analysis_runs.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class AnalysisRun(Base):
    """One question-answering loop invocation (one LangGraph run)."""

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chat_sessions.id"), nullable=False
    )
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class AnalysisStep(Base):
    """One iteration of the code-gen/execute loop within an AnalysisRun."""

    __tablename__ = "analysis_steps"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("analysis_runs.id"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_code: Mapped[str] = mapped_column(Text, nullable=False)
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
