"""Pydantic shape tests for the chat domain models — no DB/network needed."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from domain.chat import (
    AnalysisStepOut,
    AskRequest,
    AskResponse,
    ChatMessageOut,
    ChatMessagesResponse,
    ChatSessionOut,
)


def test_chat_session_out_shape():
    out = ChatSessionOut(session_id="s1", title="sales_q1.csv analysis", active_dataset_id="d1")
    dumped = out.model_dump()
    assert dumped == {
        "session_id": "s1",
        "title": "sales_q1.csv analysis",
        "active_dataset_id": "d1",
    }


def test_chat_session_out_allows_null_title_and_dataset():
    out = ChatSessionOut(session_id="s1")
    assert out.title is None
    assert out.active_dataset_id is None


def test_chat_message_out_shape_and_optional_run_id():
    now = datetime.now(timezone.utc)
    user_msg = ChatMessageOut(role="user", content="What is the average?", created_at=now)
    assert user_msg.run_id is None

    assistant_msg = ChatMessageOut(
        role="assistant", content="The average is 42.", created_at=now, run_id="run-1"
    )
    assert assistant_msg.run_id == "run-1"


def test_chat_messages_response_shape():
    now = datetime.now(timezone.utc)
    resp = ChatMessagesResponse(
        session_id="s1",
        messages=[
            ChatMessageOut(role="user", content="hi", created_at=now),
            ChatMessageOut(role="assistant", content="hello", created_at=now, run_id="r1"),
        ],
    )
    dumped = resp.model_dump()
    assert dumped["session_id"] == "s1"
    assert len(dumped["messages"]) == 2
    assert dumped["messages"][0]["role"] == "user"
    assert dumped["messages"][1]["run_id"] == "r1"


def test_ask_request_requires_non_empty_content():
    req = AskRequest(content="What was the average revenue per region?")
    assert req.content

    with pytest.raises(ValidationError):
        AskRequest(content="")


def test_ask_request_missing_content_field_raises():
    with pytest.raises(ValidationError):
        AskRequest()  # type: ignore[call-arg]


def test_analysis_step_out_shape():
    step = AnalysisStepOut(
        step_number=1,
        generated_code="df.groupby('region')['revenue'].mean()",
        status="success",
        result_summary={"East": 4213.1, "West": 3891.4},
    )
    dumped = step.model_dump()
    assert dumped["step_number"] == 1
    assert dumped["status"] == "success"
    assert dumped["result_summary"] == {"East": 4213.1, "West": 3891.4}
    assert dumped["error_message"] is None


def test_ask_response_shape_matches_api_contract():
    resp = AskResponse(
        run_id="run-1",
        session_id="s1",
        status="completed",
        answer="Average revenue per region in March was...",
        final_code="df[df['order_date'].dt.month == 3].groupby('region')['revenue'].mean()",
        is_fallback=False,
        steps=[
            AnalysisStepOut(
                step_number=1,
                generated_code="...",
                status="success",
                result_summary={"East": 4213.1, "West": 3891.4},
            )
        ],
    )
    dumped = resp.model_dump()
    assert dumped["run_id"] == "run-1"
    assert dumped["session_id"] == "s1"
    assert dumped["status"] == "completed"
    assert dumped["is_fallback"] is False
    assert len(dumped["steps"]) == 1


def test_ask_response_defaults_steps_to_empty_list():
    resp = AskResponse(run_id="run-1", session_id="s1", status="completed")
    assert resp.steps == []
    assert resp.answer is None
    assert resp.is_fallback is False
