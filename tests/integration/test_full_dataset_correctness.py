"""Full-dataset correctness: a >=5,000-row fixture with a known ground-truth
aggregate, run through the real run_agent() loop end-to-end, must produce the
TRUE full-dataset value — not a truncated-sample value. This is the guard
against the anti-pattern where an LLM "eyeballs" a sample instead of the
generated code actually running against every row.

Runs against the real Gemini API using AGENT_GEMINI_API_KEY from `.env`.
"""
import io
import re

import pandas as pd
import pytest


ROW_COUNT = 5000


def _fixture_dataframe() -> pd.DataFrame:
    # Deterministic — same every test run — so the ground-truth aggregate is stable.
    amounts = [round(10.0 + (i % 997) * 0.37, 2) for i in range(ROW_COUNT)]
    regions = ["East", "West", "North", "South"]
    return pd.DataFrame(
        {
            "order_id": range(1, ROW_COUNT + 1),
            "region": [regions[i % 4] for i in range(ROW_COUNT)],
            "amount": amounts,
        }
    )


def _fixture_csv_bytes() -> bytes:
    buf = io.StringIO()
    _fixture_dataframe().to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _numbers_in_text(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"-?\d[\d,]*\.?\d*", text.replace(",", ""))]


@pytest.fixture
def _gemini_key_or_skip():
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real Gemini correctness test")


def test_full_dataset_sum_is_correct_not_truncated(api_client, _isolated_db, _gemini_key_or_skip):
    from graph.runner import run_agent

    true_sum = round(_fixture_dataframe()["amount"].sum(), 2)

    files = {"file": ("big_orders.csv", _fixture_csv_bytes(), "text/csv")}
    upload_resp = api_client.post("/datasets", files=files)
    assert upload_resp.status_code == 200
    upload_body = upload_resp.json()["data"]
    assert upload_body["row_count"] == ROW_COUNT
    dataset_id = upload_body["dataset_id"]
    session_id = upload_body["session_id"]

    result = run_agent(
        dataset_id=dataset_id,
        question="What is the sum of the amount column across the entire dataset?",
        session_id=session_id,
        prior_messages=[],
    )

    assert result["status"] in ("completed", "completed_with_fallback")
    assert result["final_answer"]

    # The successfully-executed step's result_summary is the ground-truth
    # local computation the answer was derived from — it must reflect the
    # full dataset, not a truncated sample.
    successful_steps = [s for s in result["step_history"] if s["status"] == "success"]
    assert successful_steps, f"No step succeeded; step_history={result['step_history']}"
    last_success = successful_steps[-1]
    summary = last_success["result_summary"]
    reported_value = summary["data"] if summary.get("type") == "scalar" else summary
    assert reported_value is not None
    assert abs(float(reported_value) - true_sum) < max(1.0, abs(true_sum) * 0.01), (
        f"Executed result {reported_value} does not match true full-dataset sum {true_sum} "
        f"(within 1% tolerance) — looks like a truncated/sampled computation."
    )

    # The plain-language final answer must also surface a number close to the
    # true value, not a sample-derived guess.
    candidate_numbers = _numbers_in_text(result["final_answer"])
    assert any(
        abs(n - true_sum) < max(5.0, abs(true_sum) * 0.02) for n in candidate_numbers
    ), (
        f"No number in the final answer is close to the true sum {true_sum}. "
        f"Answer was: {result['final_answer']!r}"
    )
