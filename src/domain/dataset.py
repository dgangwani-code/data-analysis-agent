from typing import Any

from pydantic import BaseModel


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    null_count: int
    distinct_count: int | None = None
    min: Any | None = None
    max: Any | None = None
    sample_values: list[Any] | None = None


class DatasetProfileOut(BaseModel):
    schema_: list[ColumnProfile]
    stats_summary: dict[str, Any]

    model_config = {"populate_by_name": True}

    def model_dump(self, **kwargs) -> dict:
        data = super().model_dump(**kwargs)
        # API contract uses the key "schema" (a Python builtin/reserved-ish name,
        # hence the field alias) — see spec/api.md POST /datasets response shape.
        data["schema"] = data.pop("schema_")
        return data


class DatasetSummary(BaseModel):
    dataset_id: str
    session_id: str | None
    filename: str
    status: str
    row_count: int
    column_count: int
    profile: DatasetProfileOut | None = None
    error_message: str | None = None

    def model_dump(self, **kwargs) -> dict:
        data = super().model_dump(**kwargs)
        if self.profile is not None:
            data["profile"] = self.profile.model_dump(**kwargs)
        return data
