"""Unit tests for src/tools/file_parser.py — pure functions, no DB/LLM required."""
import io

import pandas as pd
import pytest

from tools.file_parser import (
    FileParseError,
    UnsupportedFileTypeError,
    detect_file_type,
    parse_file,
)


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_detect_file_type_csv():
    assert detect_file_type("sales.csv") == "csv"


def test_detect_file_type_xlsx():
    assert detect_file_type("sales.xlsx") == "xlsx"


def test_detect_file_type_unsupported_extension_raises():
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type("sales.pdf")


def test_detect_file_type_no_extension_raises():
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type("sales")


def test_parse_file_happy_path_csv():
    content = _csv_bytes("region,revenue\nEast,100.5\nWest,200.25\n")
    df, file_type = parse_file(content, "sales.csv")
    assert file_type == "csv"
    assert list(df.columns) == ["region", "revenue"]
    assert df.shape == (2, 2)


def test_parse_file_happy_path_xlsx():
    source = pd.DataFrame({"region": ["East", "West"], "revenue": [100.5, 200.25]})
    content = _xlsx_bytes(source)
    df, file_type = parse_file(content, "sales.xlsx")
    assert file_type == "xlsx"
    assert list(df.columns) == ["region", "revenue"]
    assert df.shape == (2, 2)


def test_parse_file_empty_content_raises_edge_case():
    with pytest.raises(FileParseError):
        parse_file(b"", "sales.csv")


def test_parse_file_malformed_content_raises_error_path():
    # Random binary garbage with a .csv name — pandas cannot parse this into columns
    with pytest.raises(FileParseError):
        parse_file(b"\x00\x01\x02\x03not,a,real,csv\xffbroken", "sales.xlsx")


def test_parse_file_unsupported_extension_raises_before_parsing():
    with pytest.raises(UnsupportedFileTypeError):
        parse_file(_csv_bytes("a,b\n1,2\n"), "sales.pdf")
