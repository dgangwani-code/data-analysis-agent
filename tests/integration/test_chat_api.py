"""Integration tests for /sessions/{id} chat endpoints.

Runs against the real production DB driver (via the shared `_isolated_db`
conftest fixture) and, for the full happy-path test, the real Gemini API
via `graph.runner.run_agent` (owned by the concurrently-built
`agent-graph-loop` slice). Dataset/DatasetProfile/ChatSession rows are
inserted directly for test setup rather than going through the datasets
upload API, per this slice's test brief.

NOTE: at authoring time `src/graph/runner.py` still ships the Phase-0
skeleton `run_agent(input_text)` signature (the `agent-graph-loop` slice
lands concurrently). These tests are written against the documented
`spec/agent.md` contract (`run_agent(dataset_id, question, session_id,
prior_messages)` returning/persisting the final `AgentState`) and are
expected to fail with a TypeError until that slice lands — see this
slice's handoff report.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db.models import ChatMessage, ChatSession, Dataset, DatasetProfile


def _fixture_csv_bytes() -> bytes:
    """Real CSV content matching the schema_json/stats_summary used below
    (region: string, revenue: float) so a real agent run can load and
    analyze it via local_execute."""
    return (
        "region,revenue\n"
        "East,100.5\n"
        "West,200.25\n"
        "East,50.0\n"
    ).encode("utf-8")


def _make_dataset_and_session(engine, tmp_path: Path) -> tuple[str, str]:
    """Insert a ready Dataset + DatasetProfile + ChatSession, return (session_id, dataset_id).

    Writes a real CSV file to `storage_path` (under `tmp_path`) so that the
    real agent loop's `local_execute` tool can actually load the dataset.
    """
    storage_path = tmp_path / "sales_q1.csv"
    storage_path.write_bytes(_fixture_csv_bytes())

    with Session(engine) as s:
        dataset = Dataset(
            filename="sales_q1.csv",
            file_type="csv",
            storage_path=str(storage_path),
            row_count=3,
            column_count=3,
            status="ready",
        )
        s.add(dataset)
        s.flush()

        profile = DatasetProfile(
            dataset_id=dataset.id,
            schema_json=[
                {"name": "region", "dtype": "string", "null_count": 0, "distinct_count": 2},
                {"name": "revenue", "dtype": "float", "null_count": 0, "min": 50.0, "max": 200.25},
            ],
            stats_summary={"revenue": {"mean": 116.9, "std": 61.2, "p50": 100.5}},
            schema_summary_text=(
                "Columns: region (string), revenue (float, mean=116.9)"
            ),
        )
        s.add(profile)

        chat_session = ChatSession(active_dataset_id=dataset.id)
        s.add(chat_session)
        s.commit()

        return chat_session.id, dataset.id


# ---------------------------------------------------------------------------
# Structural / error-path tests — no LLM call, exercise routing + envelope.
# ---------------------------------------------------------------------------


def test_get_session_not_found_error_path(api_client):
    r = api_client.get("/sessions/nonexistent-id")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_get_session_metadata(api_client, _isolated_db, tmp_path):
    session_id, dataset_id = _make_dataset_and_session(_isolated_db, tmp_path)
    r = api_client.get(f"/sessions/{session_id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["session_id"] == session_id
    assert data["active_dataset_id"] == dataset_id


def test_list_messages_empty_state(api_client, _isolated_db, tmp_path):
    session_id, _ = _make_dataset_and_session(_isolated_db, tmp_path)
    r = api_client.get(f"/sessions/{session_id}/messages")
    assert r.status_code == 200
    assert r.json()["data"]["messages"] == []


def test_list_messages_not_found_error_path(api_client):
    r = api_client.get("/sessions/nonexistent-id/messages")
    assert r.status_code == 404


def test_ask_question_session_not_found_error_path(api_client):
    r = api_client.post("/sessions/nonexistent-id/messages", json={"content": "hello?"})
    assert r.status_code == 404


def test_ask_question_no_active_dataset_error_path(api_client, _isolated_db):
    with Session(_isolated_db) as s:
        chat_session = ChatSession()
        s.add(chat_session)
        s.commit()
        session_id = chat_session.id

    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "hi"})
    assert r.status_code == 400


def test_ask_question_empty_content_edge_case(api_client, _isolated_db, tmp_path):
    session_id, _ = _make_dataset_and_session(_isolated_db, tmp_path)
    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "   "})
    assert r.status_code == 400


def test_ask_question_run_in_progress_returns_409(api_client, _isolated_db, tmp_path):
    from db.models import AnalysisRun

    session_id, dataset_id = _make_dataset_and_session(_isolated_db, tmp_path)
    with Session(_isolated_db) as s:
        run = AnalysisRun(
            session_id=session_id,
            dataset_id=dataset_id,
            question="already running",
            status="pending",
        )
        s.add(run)
        s.commit()

    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "hi again"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Session-memory plumbing test — spies on run_agent, no real LLM call needed.
# ---------------------------------------------------------------------------


def test_ask_question_passes_prior_messages_for_session_memory(
    api_client, _isolated_db, monkeypatch, tmp_path
):
    from db.models import AnalysisRun, AnalysisStep
    import api.chat as chat_module

    session_id, dataset_id = _make_dataset_and_session(_isolated_db, tmp_path)

    calls: list[dict] = []

    def _fake_run_agent(*, dataset_id, question, session_id, prior_messages):
        calls.append(
            {
                "dataset_id": dataset_id,
                "question": question,
                "session_id": session_id,
                "prior_messages": list(prior_messages),
            }
        )
        with Session(_isolated_db) as s:
            run = AnalysisRun(
                session_id=session_id,
                dataset_id=dataset_id,
                question=question,
                status="completed",
                final_answer=f"Answer to: {question}",
                final_code="df.head()",
                step_count=1,
            )
            s.add(run)
            s.flush()
            s.add(
                AnalysisStep(
                    run_id=run.id,
                    step_number=1,
                    generated_code="df.head()",
                    status="success",
                    result_summary={"rows": 3},
                )
            )
            s.commit()
            return {"run_id": run.id, "status": "completed"}

    monkeypatch.setattr(chat_module, "run_agent", _fake_run_agent)

    r1 = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "What is the average revenue?"},
    )
    assert r1.status_code == 200

    r2 = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "And what about just the top region?"},
    )
    assert r2.status_code == 200

    assert len(calls) == 2
    # First call had no prior turns yet.
    assert calls[0]["prior_messages"] == []
    # Second call's prior_messages include the first Q and A — proving
    # session memory is plumbed through to the graph.
    second_call_texts = [m["content"] for m in calls[1]["prior_messages"]]
    assert "What is the average revenue?" in second_call_texts
    assert any("Answer to: What is the average revenue?" in t for t in second_call_texts)

    # Follow-up response reflects it's a distinct answer from the same session.
    assert r2.json()["data"]["answer"] == "Answer to: And what about just the top region?"

    # Message history now has 4 turns (2 user + 2 assistant), in order.
    history = api_client.get(f"/sessions/{session_id}/messages").json()["data"]["messages"]
    assert len(history) == 4
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


def test_ask_question_agent_failure_returns_502(api_client, _isolated_db, monkeypatch, tmp_path):
    import api.chat as chat_module

    session_id, dataset_id = _make_dataset_and_session(_isolated_db, tmp_path)

    def _raise(**kwargs):
        raise RuntimeError("Gemini API unavailable")

    monkeypatch.setattr(chat_module, "run_agent", _raise)

    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "hi"})
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# Real Gemini happy-path test — exercises the actual graph runner end to end.
# ---------------------------------------------------------------------------


def test_ask_question_real_agent_happy_path(api_client, _isolated_db, _require_llm_key, tmp_path):
    session_id, dataset_id = _make_dataset_and_session(_isolated_db, tmp_path)

    r = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "What is the average revenue?"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["run_id"]
    assert data["session_id"] == session_id
    assert data["status"] in ("completed", "completed_with_fallback")
    assert data["answer"]
    assert data["final_code"]

    with Session(_isolated_db) as s:
        from db.models import AnalysisRun

        run = s.get(AnalysisRun, data["run_id"])
        assert run is not None
        assert run.status in ("completed", "completed_with_fallback")
        assert run.final_answer
