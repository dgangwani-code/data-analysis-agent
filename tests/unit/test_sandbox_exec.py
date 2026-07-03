"""sandbox_exec.run — real pandas DataFrame, restricted exec.

Covers: happy-path aggregation, blocked forbidden imports/builtins, timeout
enforcement, and capped/aggregated result summaries (never a raw row dump).
"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from tools import sandbox_exec


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["east", "west", "east", "west", "north"],
            "revenue": [100, 200, 150, 300, 50],
        }
    )


def test_happy_path_scalar_aggregate(df):
    code = "result = df['revenue'].sum()"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "success"
    assert out["error"] is None
    assert out["result_summary"]["type"] == "scalar"
    assert out["result_summary"]["data"] == 800


def test_happy_path_groupby_small_table(df):
    code = "result = df.groupby('region')['revenue'].sum().reset_index()"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "success"
    assert out["result_summary"]["type"] == "table"
    assert out["result_summary"]["aggregated"] is False
    assert out["result_summary"]["row_count"] == 3


def test_blocks_import_os(df):
    code = "import os\nresult = os.getcwd()"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "error"
    assert "not allowed" in out["error"]


def test_blocks_import_socket_and_subprocess(df):
    for bad in ("import socket\nresult = 1", "import subprocess\nresult = 1"):
        out = sandbox_exec.run(bad, df)
        assert out["status"] == "error"
        assert "not allowed" in out["error"]


def test_blocks_dunder_attribute_access(df):
    code = "result = df.__class__.__mro__"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "error"


def test_blocks_open_and_exec_builtins(df):
    for bad in ("result = open('/etc/passwd').read()", "exec('result = 1')"):
        out = sandbox_exec.run(bad, df)
        assert out["status"] == "error"


def test_blocks_dunder_import(df):
    code = "result = __import__('os').getcwd()"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "error"


def test_syntax_error_returns_structured_error(df):
    out = sandbox_exec.run("result = df[", df)
    assert out["status"] == "error"
    assert out["result_summary"] is None
    assert "Syntax error" in out["error"]


def test_missing_result_variable_is_an_error(df):
    out = sandbox_exec.run("x = df['revenue'].sum()", df)
    assert out["status"] == "error"
    assert "result" in out["error"]


def test_runtime_error_is_captured_not_raised(df):
    out = sandbox_exec.run("result = df['nonexistent_column'].sum()", df)
    assert out["status"] == "error"
    assert out["error"]


def test_timeout_is_enforced(df):
    code = "i = 0\nwhile True:\n    i += 1"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "error"
    assert "timeout" in out["error"].lower()


def test_large_result_is_aggregated_not_dumped_raw():
    big_df = pd.DataFrame({"x": range(5000), "y": range(5000)})
    code = "result = df[df['x'] >= 0]"  # returns all 5000 rows unfiltered
    out = sandbox_exec.run(code, big_df)
    assert out["status"] == "success"
    summary = out["result_summary"]
    assert summary["type"] == "table_summary"
    assert summary["aggregated"] is True
    assert summary["row_count"] == 5000
    # never a raw row dump — no "data" key with 5000 records
    assert "data" not in summary
    assert "describe" in summary


def test_dict_result_small_is_not_aggregated(df):
    code = "result = df.groupby('region')['revenue'].sum().to_dict()"
    out = sandbox_exec.run(code, df)
    assert out["status"] == "success"
    summary = out["result_summary"]
    assert summary["type"] == "dict"
    assert summary["aggregated"] is False
    assert summary["data"] == {"east": 250, "north": 50, "west": 500}


def test_large_dict_result_is_capped_not_dumped_raw():
    big_df = pd.DataFrame({"id": range(5000), "revenue": range(5000)})
    # simulate LLM-generated code smuggling row-level data via .to_dict()
    code = "result = df.set_index('id')['revenue'].to_dict()"
    out = sandbox_exec.run(code, big_df)
    assert out["status"] == "success"
    summary = out["result_summary"]
    assert summary["type"] == "dict_summary"
    assert summary["aggregated"] is True
    assert summary["count"] == 5000
    # never a raw dump of all 5000 keys
    assert len(summary["data"]) <= sandbox_exec.MAX_RESULT_ROWS
    assert "note" in summary


def test_dict_with_oversized_nested_value_is_aggregated():
    # top-level dict is small, but one value is a huge nested list — must
    # still be capped, not passed through raw.
    code = "result = {'label': 'summary', 'values': list(range(5000))}"
    out = sandbox_exec.run(code, pd.DataFrame({"a": [1, 2, 3]}))
    assert out["status"] == "success"
    summary = out["result_summary"]
    assert summary["type"] == "dict_summary"
    assert summary["aggregated"] is True
    nested = summary["data"]["values"]
    assert nested["aggregated"] is True
    assert nested["count"] == 5000
    # never a raw dump of the 5000-element list
    assert isinstance(nested, dict)


def test_run_works_from_a_background_thread(df):
    # Regression test: sandbox_exec is invoked from FastAPI/uvicorn request
    # handler threads, never the main thread. A signal.alarm()-based timeout
    # raises ValueError("signal only works in main thread of the main
    # interpreter") off the main thread; the timeout mechanism must be
    # thread-safe (see _run_with_timeout).
    code = "result = df['revenue'].sum()"
    with ThreadPoolExecutor(max_workers=1) as executor:
        out = executor.submit(sandbox_exec.run, code, df).result(timeout=30)
    assert out["status"] == "success"
    assert out["result_summary"]["data"] == 800


def test_never_raises_on_arbitrary_bad_code():
    df = pd.DataFrame({"a": [1, 2, 3]})
    # this should never raise out of run(), regardless of how malformed
    out = sandbox_exec.run("this is not python at all !!!", df)
    assert isinstance(out, dict)
    assert out["status"] == "error"
