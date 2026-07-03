"""Pure functions for parsing uploaded CSV/Excel files into pandas DataFrames.

No LLM call, no DB access, no network access — pure (bytes, filename) -> DataFrame.
"""
from __future__ import annotations

import io

import pandas as pd

SUPPORTED_FILE_TYPES = ("csv", "xlsx")


class UnsupportedFileTypeError(ValueError):
    """Raised when the uploaded filename has an extension we don't support."""


class FileParseError(ValueError):
    """Raised when pandas cannot parse the file content (empty/corrupt/malformed)."""


def detect_file_type(filename: str) -> str:
    """Return 'csv' or 'xlsx' based on the filename extension, or raise."""
    if not filename or "." not in filename:
        raise UnsupportedFileTypeError(f"Cannot determine file type from filename: {filename!r}")
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        return "csv"
    if ext in ("xlsx", "xls"):
        return "xlsx"
    raise UnsupportedFileTypeError(f"Unsupported file type: .{ext} (supported: {SUPPORTED_FILE_TYPES})")


def parse_file(content: bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """Parse raw file bytes into a DataFrame.

    Returns (dataframe, file_type). Raises UnsupportedFileTypeError for an
    unrecognized extension, FileParseError for empty/corrupt/malformed content
    that pandas cannot parse. Never raises an uncaught exception type.
    """
    file_type = detect_file_type(filename)

    if not content:
        raise FileParseError(f"Uploaded file {filename!r} is empty")

    buffer = io.BytesIO(content)
    try:
        if file_type == "csv":
            df = pd.read_csv(buffer)
        else:
            df = pd.read_excel(buffer, engine="openpyxl")
    except UnsupportedFileTypeError:
        raise
    except Exception as exc:  # pandas raises many different exception types
        raise FileParseError(f"Could not parse {filename!r} as {file_type}: {exc}") from exc

    if df.shape[1] == 0:
        raise FileParseError(f"{filename!r} has no columns")

    return df, file_type
