"""POST /datasets and GET /datasets/{id} — upload/fetch a dataset + its profile.

Phase 1: synchronous parse + profile (no async job queue, no LLM call ever —
profiling is 100% local per architecture.md's LLM boundary).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.session import get_session
from db.models import Dataset, DatasetProfile, ChatSession
from domain.dataset import ColumnProfile, DatasetProfileOut, DatasetSummary
from tools.file_parser import FileParseError, UnsupportedFileTypeError, parse_file
from tools.profiler import profile_dataframe

router = APIRouter()

UPLOAD_ROOT = Path("data/uploads")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — configured upload size limit


def _profile_out(profile: DatasetProfile) -> DatasetProfileOut:
    return DatasetProfileOut(
        schema_=[ColumnProfile(**col) for col in profile.schema_json],
        stats_summary=profile.stats_summary,
    )


def _summary(dataset: Dataset, profile: DatasetProfile | None) -> dict:
    return DatasetSummary(
        dataset_id=dataset.id,
        session_id=dataset.session_id,
        filename=dataset.filename,
        status=dataset.status,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        profile=_profile_out(profile) if profile else None,
        error_message=dataset.error_message,
    ).model_dump()


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> dict:
    content = await file.read()

    if len(content) > MAX_UPLOAD_BYTES:
        raise api_error(
            "FILE_TOO_LARGE",
            f"File exceeds the {MAX_UPLOAD_BYTES} byte upload size limit",
            413,
        )

    if session_id is not None:
        existing_session = session.get(ChatSession, session_id)
        if existing_session is None:
            raise api_error("SESSION_NOT_FOUND", f"Session {session_id} not found", 404)
    else:
        existing_session = ChatSession()
        session.add(existing_session)
        session.flush()
        session_id = existing_session.id

    try:
        df, file_type = parse_file(content, file.filename or "")
    except (UnsupportedFileTypeError, FileParseError) as exc:
        raise api_error("INVALID_FILE", str(exc), 400) from exc

    dataset = Dataset(
        session_id=session_id,
        filename=file.filename or "unnamed",
        file_type=file_type,
        storage_path="",
        row_count=0,
        column_count=0,
        status="profiling",
    )
    session.add(dataset)
    session.flush()

    dataset_dir = UPLOAD_ROOT / dataset.id
    dataset_dir.mkdir(parents=True, exist_ok=True)
    storage_path = dataset_dir / dataset.filename
    try:
        storage_path.write_bytes(content)

        profile_data = profile_dataframe(df)

        dataset.storage_path = str(storage_path)
        dataset.row_count = profile_data["row_count"]
        dataset.column_count = profile_data["column_count"]
        dataset.status = "ready"

        profile = DatasetProfile(
            dataset_id=dataset.id,
            schema_json=profile_data["schema_json"],
            stats_summary=profile_data["stats_summary"],
            schema_summary_text=profile_data["schema_summary_text"],
        )
        session.add(profile)
        session.flush()

        existing_session.active_dataset_id = dataset.id
        session.add(existing_session)
        session.flush()
    except Exception as exc:  # unexpected parsing/profiling failure after row was created
        dataset.status = "failed"
        dataset.error_message = str(exc)
        session.flush()
        raise api_error("PROFILING_FAILED", f"Failed to profile dataset: {exc}", 500) from exc

    return ok(_summary(dataset, profile))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)

    profile = (
        session.query(DatasetProfile)
        .filter(DatasetProfile.dataset_id == dataset.id)
        .first()
    )
    return ok(_summary(dataset, profile))
