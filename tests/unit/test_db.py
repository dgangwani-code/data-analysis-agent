"""DB layer tests — real PostgreSQL driver (production driver), no SQLite substitution.

Connects directly to AGENT_DATABASE_URL from .env, per harness rules that forbid
substituting SQLite for a PostgreSQL production DB. Each test runs inside a
transaction that is rolled back, so it never leaves rows behind in the real DB.
"""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models import (
    AnalysisRun,
    AnalysisStep,
    Base,
    ChatMessage,
    ChatSession,
    Dataset,
    DatasetProfile,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    """Override conftest's SQLite-backed autouse fixture for this module.

    These models use PostgreSQL-only column types (JSONB) and are tested
    against the real production PostgreSQL driver via the `pg_session`
    fixture below — never against SQLite.
    """
    yield None


@pytest.fixture
def pg_session():
    """Real PostgreSQL session, wrapped in a transaction that's rolled back after each test."""
    engine = create_engine(get_settings().database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_all_tables_exist_in_db():
    """Confirms the migration actually created every table for every entity in data.md."""
    engine = create_engine(get_settings().database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    expected = {
        "datasets",
        "dataset_profiles",
        "chat_sessions",
        "chat_messages",
        "analysis_runs",
        "analysis_steps",
    }
    assert expected.issubset(table_names)


def test_model_metadata_matches_declared_tables():
    """Every model class is registered on Base.metadata with the expected table name."""
    table_names = set(Base.metadata.tables.keys())
    assert table_names == {
        "datasets",
        "dataset_profiles",
        "chat_sessions",
        "chat_messages",
        "analysis_runs",
        "analysis_steps",
    }


def test_dataset_roundtrip(pg_session):
    dataset = Dataset(
        filename="sales.csv",
        file_type="csv",
        storage_path="data/uploads/x/sales.csv",
        row_count=100,
        column_count=5,
        status="ready",
    )
    pg_session.add(dataset)
    pg_session.flush()

    fetched = pg_session.get(Dataset, dataset.id)
    assert fetched is not None
    assert fetched.filename == "sales.csv"
    assert fetched.file_type == "csv"
    assert fetched.status == "ready"
    assert fetched.row_count == 100
    assert fetched.session_id is None
    assert fetched.error_message is None


def test_dataset_status_failed_requires_no_error_message_field_but_can_set_one(pg_session):
    """Edge case: a failed dataset can carry an error_message; row/column counts still required."""
    dataset = Dataset(
        filename="broken.xlsx",
        file_type="xlsx",
        storage_path="data/uploads/y/broken.xlsx",
        row_count=0,
        column_count=0,
        status="failed",
        error_message="could not parse sheet",
    )
    pg_session.add(dataset)
    pg_session.flush()

    fetched = pg_session.get(Dataset, dataset.id)
    assert fetched.status == "failed"
    assert fetched.error_message == "could not parse sheet"


def test_dataset_profile_fk_and_jsonb_fields(pg_session):
    dataset = Dataset(
        filename="a.csv",
        file_type="csv",
        storage_path="p",
        row_count=10,
        column_count=2,
        status="ready",
    )
    pg_session.add(dataset)
    pg_session.flush()

    profile = DatasetProfile(
        dataset_id=dataset.id,
        schema_json=[{"name": "col_a", "dtype": "int64", "null_count": 0, "distinct_count": 10}],
        stats_summary={"col_a": {"mean": 5.0, "std": 2.0}},
        schema_summary_text="col_a: int64, no nulls",
    )
    pg_session.add(profile)
    pg_session.flush()

    fetched = pg_session.get(DatasetProfile, profile.id)
    assert fetched.dataset_id == dataset.id
    assert fetched.schema_json[0]["name"] == "col_a"
    assert fetched.stats_summary["col_a"]["mean"] == 5.0


def test_chat_session_and_dataset_mutual_fk(pg_session):
    """Verifies the deliberately deferred (use_alter) circular FK between
    ChatSession.active_dataset_id and Dataset.session_id both resolve correctly."""
    session_row = ChatSession()
    pg_session.add(session_row)
    pg_session.flush()

    dataset = Dataset(
        session_id=session_row.id,
        filename="b.csv",
        file_type="csv",
        storage_path="p2",
        row_count=1,
        column_count=1,
        status="ready",
    )
    pg_session.add(dataset)
    pg_session.flush()

    session_row.active_dataset_id = dataset.id
    pg_session.flush()

    fetched_session = pg_session.get(ChatSession, session_row.id)
    fetched_dataset = pg_session.get(Dataset, dataset.id)
    assert fetched_session.active_dataset_id == dataset.id
    assert fetched_dataset.session_id == session_row.id


def test_chat_message_requires_session_and_supports_optional_run(pg_session):
    session_row = ChatSession()
    pg_session.add(session_row)
    pg_session.flush()

    message = ChatMessage(session_id=session_row.id, role="user", content="what's the total?")
    pg_session.add(message)
    pg_session.flush()

    fetched = pg_session.get(ChatMessage, message.id)
    assert fetched.role == "user"
    assert fetched.run_id is None


def test_analysis_run_and_steps_full_chain(pg_session):
    """Multi-row happy path: a session, dataset, run, and its ordered steps."""
    session_row = ChatSession()
    pg_session.add(session_row)
    pg_session.flush()

    dataset = Dataset(
        session_id=session_row.id,
        filename="c.csv",
        file_type="csv",
        storage_path="p3",
        row_count=50,
        column_count=3,
        status="ready",
    )
    pg_session.add(dataset)
    pg_session.flush()

    run = AnalysisRun(
        session_id=session_row.id,
        dataset_id=dataset.id,
        question="what is the average of col_a?",
        status="pending",
        step_count=0,
        is_fallback=False,
    )
    pg_session.add(run)
    pg_session.flush()

    for i in range(1, 3):
        step = AnalysisStep(
            run_id=run.id,
            step_number=i,
            generated_code=f"df['col_a'].mean()  # step {i}",
            result_summary={"mean": 5.0},
            status="success",
        )
        pg_session.add(step)
    run.step_count = 2
    run.status = "completed"
    run.final_answer = "The average is 5.0"
    run.final_code = "df['col_a'].mean()"
    pg_session.flush()

    fetched_run = pg_session.get(AnalysisRun, run.id)
    assert fetched_run.status == "completed"
    assert fetched_run.step_count == 2
    assert fetched_run.final_answer == "The average is 5.0"

    steps = (
        pg_session.query(AnalysisStep)
        .filter(AnalysisStep.run_id == run.id)
        .order_by(AnalysisStep.step_number)
        .all()
    )
    assert [s.step_number for s in steps] == [1, 2]
    assert all(s.status == "success" for s in steps)


def test_analysis_run_error_path(pg_session):
    """Error-path: a failed run with no final_answer/final_code but an error_message set."""
    session_row = ChatSession()
    pg_session.add(session_row)
    pg_session.flush()

    dataset = Dataset(
        session_id=session_row.id,
        filename="d.csv",
        file_type="csv",
        storage_path="p4",
        row_count=1,
        column_count=1,
        status="ready",
    )
    pg_session.add(dataset)
    pg_session.flush()

    run = AnalysisRun(
        session_id=session_row.id,
        dataset_id=dataset.id,
        question="does not compute",
        status="failed",
        step_count=6,
        is_fallback=True,
        error_message="step budget exhausted without a resolvable answer",
    )
    pg_session.add(run)
    pg_session.flush()

    fetched = pg_session.get(AnalysisRun, run.id)
    assert fetched.status == "failed"
    assert fetched.is_fallback is True
    assert fetched.final_answer is None
    assert fetched.error_message == "step budget exhausted without a resolvable answer"
