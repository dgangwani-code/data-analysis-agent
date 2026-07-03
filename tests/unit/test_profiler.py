"""Unit tests for src/tools/profiler.py — pure functions, no DB/LLM required.

Critically asserts that schema_summary_text / schema_json never leak a raw
row-level value for high-cardinality columns (only aggregates, and for
low-cardinality columns only a capped sample of DISTINCT values).
"""
import json

import pandas as pd
import pytest

from tools.profiler import LOW_CARDINALITY_THRESHOLD, SAMPLE_VALUES_CAP, profile_dataframe


@pytest.fixture
def small_df():
    return pd.DataFrame(
        {
            "order_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "region": ["East", "West", "East"],
            "revenue": [100.5, 200.25, 50.0],
        }
    )


@pytest.fixture
def high_cardinality_df():
    # A column with 200 unique, secret-looking string values — none of these
    # literal values should ever appear in schema_summary_text.
    return pd.DataFrame(
        {
            "customer_id": [f"CUST-SECRET-{i:04d}" for i in range(200)],
            "amount": [float(i) for i in range(200)],
        }
    )


def test_profile_dataframe_happy_path_shape(small_df):
    profile = profile_dataframe(small_df)
    assert profile["row_count"] == 3
    assert profile["column_count"] == 3
    assert len(profile["schema_json"]) == 3
    names = {c["name"] for c in profile["schema_json"]}
    assert names == {"order_date", "region", "revenue"}


def test_profile_dataframe_schema_json_shape(small_df):
    profile = profile_dataframe(small_df)
    revenue_col = next(c for c in profile["schema_json"] if c["name"] == "revenue")
    assert revenue_col["dtype"] == "float"
    assert revenue_col["null_count"] == 0
    assert revenue_col["distinct_count"] == 3
    assert revenue_col["min"] == 50.0
    assert revenue_col["max"] == 200.25

    region_col = next(c for c in profile["schema_json"] if c["name"] == "region")
    assert region_col["dtype"] == "string"
    assert "sample_values" in region_col
    assert set(region_col["sample_values"]) == {"East", "West"}


def test_profile_dataframe_stats_summary_is_aggregate_only(small_df):
    profile = profile_dataframe(small_df)
    assert "revenue" in profile["stats_summary"]
    stats = profile["stats_summary"]["revenue"]
    for key in ("count", "mean", "std", "min", "p25", "p50", "p75", "max"):
        assert key in stats


def test_profile_dataframe_high_cardinality_no_sample_values(high_cardinality_df):
    profile = profile_dataframe(high_cardinality_df)
    customer_col = next(c for c in profile["schema_json"] if c["name"] == "customer_id")
    assert customer_col["distinct_count"] == 200
    assert customer_col["distinct_count"] > LOW_CARDINALITY_THRESHOLD
    assert "sample_values" not in customer_col


def test_profile_dataframe_no_raw_row_values_in_summary_text(high_cardinality_df):
    profile = profile_dataframe(high_cardinality_df)
    text = profile["schema_summary_text"]
    # None of the 200 individual secret-looking customer IDs may appear —
    # only aggregate stats for the numeric column and column-level metadata.
    for i in range(200):
        assert f"CUST-SECRET-{i:04d}" not in text


def test_profile_dataframe_low_cardinality_sample_capped_at_10():
    df = pd.DataFrame({"category": [f"cat-{i}" for i in range(15)] * 1})  # 15 distinct values, <= threshold
    profile = profile_dataframe(df)
    col = profile["schema_json"][0]
    assert col["distinct_count"] == 15
    assert "sample_values" in col
    assert len(col["sample_values"]) <= SAMPLE_VALUES_CAP


def test_profile_dataframe_empty_dataframe_edge_case():
    df = pd.DataFrame({"a": pd.array([], dtype="float64")})
    profile = profile_dataframe(df)
    assert profile["row_count"] == 0
    assert profile["column_count"] == 1
    col = profile["schema_json"][0]
    assert col["null_count"] == 0
    assert col["distinct_count"] == 0
    assert "sample_values" not in col


def test_profile_dataframe_all_null_column_edge_case():
    df = pd.DataFrame({"a": [None, None, None], "b": [1, 2, 3]})
    profile = profile_dataframe(df)
    a_col = next(c for c in profile["schema_json"] if c["name"] == "a")
    assert a_col["null_count"] == 3
    assert a_col["min"] is None
    assert a_col["max"] is None


def test_profile_dataframe_summary_text_is_json_serializable(small_df):
    profile = profile_dataframe(small_df)
    # schema_json and stats_summary must be JSON-serializable (JSONB columns)
    json.dumps(profile["schema_json"])
    json.dumps(profile["stats_summary"])
    assert isinstance(profile["schema_summary_text"], str)
    assert len(profile["schema_summary_text"]) > 0
