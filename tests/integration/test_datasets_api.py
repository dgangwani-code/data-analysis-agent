"""Integration tests for POST /datasets and GET /datasets/{id}.

Runs against the real production DB driver (PostgreSQL, via the shared
_isolated_db conftest fixture) and real pandas parsing/profiling — no LLM
call happens anywhere on this path (profiling is 100% local).
"""
import io

import pandas as pd
import pytest


def _csv_upload_bytes() -> bytes:
    return (
        "order_date,region,revenue\n"
        "2024-01-01,East,100.5\n"
        "2024-01-02,West,200.25\n"
        "2024-01-03,East,50.0\n"
    ).encode("utf-8")


def test_upload_dataset_happy_path(api_client):
    files = {"file": ("sales_q1.csv", _csv_upload_bytes(), "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200
    body = r.json()
    data = body["data"]
    assert data["status"] == "ready"
    assert data["row_count"] == 3
    assert data["column_count"] == 3
    assert data["filename"] == "sales_q1.csv"
    assert data["dataset_id"]
    assert data["session_id"]

    profile = data["profile"]
    names = {c["name"] for c in profile["schema"]}
    assert names == {"order_date", "region", "revenue"}
    assert "revenue" in profile["stats_summary"]


def test_upload_dataset_creates_db_state(api_client, _isolated_db):
    from sqlalchemy.orm import Session
    from db.models import Dataset, DatasetProfile

    files = {"file": ("sales.csv", _csv_upload_bytes(), "text/csv")}
    r = api_client.post("/datasets", files=files)
    dataset_id = r.json()["data"]["dataset_id"]

    with Session(_isolated_db) as s:
        dataset = s.get(Dataset, dataset_id)
        assert dataset is not None
        assert dataset.status == "ready"
        assert dataset.row_count == 3

        profile = (
            s.query(DatasetProfile)
            .filter(DatasetProfile.dataset_id == dataset_id)
            .first()
        )
        assert profile is not None
        assert profile.schema_summary_text
        assert isinstance(profile.schema_json, list)


def test_get_dataset_after_upload(api_client):
    files = {"file": ("sales.csv", _csv_upload_bytes(), "text/csv")}
    upload_resp = api_client.post("/datasets", files=files)
    dataset_id = upload_resp.json()["data"]["dataset_id"]

    r = api_client.get(f"/datasets/{dataset_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["dataset_id"] == dataset_id
    assert body["data"]["row_count"] == 3


def test_get_dataset_not_found_error_path(api_client):
    r = api_client.get("/datasets/nonexistent-id")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["code"] == "NOT_FOUND"


def test_upload_dataset_unsupported_file_type_error_path(api_client):
    files = {"file": ("notes.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "INVALID_FILE"


def test_upload_dataset_empty_file_edge_case(api_client):
    files = {"file": ("empty.csv", b"", "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400


def test_upload_dataset_malformed_content_error_path(api_client):
    files = {"file": ("bad.xlsx", b"not a real xlsx file at all", "application/octet-stream")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400


def test_upload_dataset_with_existing_session_id(api_client, _isolated_db):
    from sqlalchemy.orm import Session
    from db.models import ChatSession

    with Session(_isolated_db) as s:
        chat_session = ChatSession()
        s.add(chat_session)
        s.commit()
        session_id = chat_session.id

    files = {"file": ("sales.csv", _csv_upload_bytes(), "text/csv")}
    r = api_client.post("/datasets", files=files, data={"session_id": session_id})
    assert r.status_code == 200
    assert r.json()["data"]["session_id"] == session_id


def test_upload_dataset_no_raw_row_values_in_profile_response(api_client):
    # High-cardinality secret-looking column; response must never leak raw values.
    rows = "\n".join(f"secret-{i}" for i in range(50))
    content = f"secret_col\n{rows}\n".encode("utf-8")
    files = {"file": ("secrets.csv", content, "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200
    body_text = r.text
    for i in range(50):
        assert f"secret-{i}" not in body_text
