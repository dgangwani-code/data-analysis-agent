"""Pure function: DataFrame -> profile (schema_json, stats_summary, schema_summary_text).

No LLM call anywhere in this file. schema_summary_text is the literal text that
later crosses the LLM boundary (see architecture.md#llm-boundary), so it must be
complete and information-dense but MUST NEVER contain a raw row value — only
column names, dtypes, aggregate stats, and capped distinct-value samples for
low-cardinality columns.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# Columns with <= this many distinct values are considered "low cardinality"
# and get a capped sample of their distinct values in schema_json.
LOW_CARDINALITY_THRESHOLD = 20
SAMPLE_VALUES_CAP = 10


def _python_scalar(value: Any) -> Any:
    """Convert a numpy/pandas scalar to a plain JSON-serializable Python value."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _dtype_label(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    return "string"


def _column_schema(series: pd.Series) -> dict[str, Any]:
    dtype = _dtype_label(series)
    non_null = series.dropna()
    entry: dict[str, Any] = {
        "name": series.name,
        "dtype": dtype,
        "null_count": int(series.isna().sum()),
        "distinct_count": int(non_null.nunique()),
    }

    if dtype in ("integer", "float", "datetime") and not non_null.empty:
        entry["min"] = _python_scalar(non_null.min())
        entry["max"] = _python_scalar(non_null.max())
    else:
        entry["min"] = None
        entry["max"] = None

    distinct_count = entry["distinct_count"]
    if 0 < distinct_count <= LOW_CARDINALITY_THRESHOLD:
        distinct_values = sorted(
            (_python_scalar(v) for v in non_null.unique()),
            key=lambda v: (v is None, str(v)),
        )
        entry["sample_values"] = distinct_values[:SAMPLE_VALUES_CAP]

    return entry


def _stats_summary(df: pd.DataFrame) -> dict[str, Any]:
    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty:
        return {}
    described = numeric_df.describe(percentiles=[0.25, 0.5, 0.75]).to_dict()
    summary: dict[str, Any] = {}
    for column, stats in described.items():
        summary[column] = {
            "count": _python_scalar(stats.get("count")),
            "mean": _python_scalar(stats.get("mean")),
            "std": _python_scalar(stats.get("std")),
            "min": _python_scalar(stats.get("min")),
            "p25": _python_scalar(stats.get("25%")),
            "p50": _python_scalar(stats.get("50%")),
            "p75": _python_scalar(stats.get("75%")),
            "max": _python_scalar(stats.get("max")),
        }
    return summary


def _render_schema_summary_text(
    schema_json: list[dict[str, Any]], stats_summary: dict[str, Any], row_count: int, column_count: int
) -> str:
    lines = [f"Dataset: {row_count} rows, {column_count} columns.", "", "Columns:"]
    for col in schema_json:
        parts = [f"  - {col['name']} ({col['dtype']})", f"null_count={col['null_count']}", f"distinct_count={col['distinct_count']}"]
        if col.get("min") is not None or col.get("max") is not None:
            parts.append(f"range=[{col['min']}, {col['max']}]")
        if "sample_values" in col:
            parts.append(f"sample_values(distinct, capped at {SAMPLE_VALUES_CAP})={col['sample_values']}")
        lines.append(", ".join(parts))

    if stats_summary:
        lines.append("")
        lines.append("Summary statistics (aggregate, describe()-style):")
        for column, stats in stats_summary.items():
            stat_str = ", ".join(f"{k}={v}" for k, v in stats.items())
            lines.append(f"  - {column}: {stat_str}")

    return "\n".join(lines)


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Compute the profile for a DataFrame.

    Returns a dict with keys: schema_json (list), stats_summary (dict),
    schema_summary_text (str), row_count (int), column_count (int).
    Contains only aggregates and capped distinct-value samples — never a raw
    row value.
    """
    row_count = int(df.shape[0])
    column_count = int(df.shape[1])

    schema_json = [_column_schema(df[col]) for col in df.columns]
    stats_summary = _stats_summary(df)
    schema_summary_text = _render_schema_summary_text(schema_json, stats_summary, row_count, column_count)

    return {
        "schema_json": schema_json,
        "stats_summary": stats_summary,
        "schema_summary_text": schema_summary_text,
        "row_count": row_count,
        "column_count": column_count,
    }
