"""THE MOST IMPORTANT TEST IN THIS BUILD.

Proves the LLM boundary (spec/architecture.md#llm-boundary-what-crosses-vs-what-stays-local):
a distinctive, unique raw cell value present in the uploaded dataset must NEVER
appear in any prompt sent to Gemini across a full, real, multi-step run_agent()
invocation — only schema/stats/code/question text may cross the boundary.

Runs against the real Gemini API using AGENT_GEMINI_API_KEY from `.env` and the
real (isolated) DB/session fixtures already wired by the sibling slices. Skips
(does not stub) if the key is genuinely absent.
"""
import pytest

UNIQUE_CELL_VALUE = "ZXQ-UNIQUE-CELL-42"


def _csv_with_unique_cell() -> bytes:
    # `note` is a HIGH-cardinality column (every row a distinct string, 30 > the
    # profiler's low-cardinality threshold of 20) so its distinct values are
    # NEVER included in schema_json.sample_values — per architecture.md, the
    # only values allowed to cross the LLM boundary from a categorical column
    # are the distinct values of a LOW-cardinality column. This keeps the test
    # a true negative-control: the unique cell must come from raw row data,
    # not from a legitimately-crossing aggregate/sample.
    rows = ["order_id,region,note,revenue"]
    rows.append(f"1,East,{UNIQUE_CELL_VALUE},100.0")
    for i in range(2, 31):
        rows.append(f"{i},West,distinct-note-{i},{50.0 + i}")
    return ("\n".join(rows) + "\n").encode("utf-8")


@pytest.fixture
def _gemini_key_or_skip():
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real Gemini boundary test")


def test_unique_raw_cell_value_never_crosses_llm_boundary(api_client, _isolated_db, _gemini_key_or_skip):
    from llm.providers.gemini import GeminiProvider
    from graph.runner import run_agent

    captured_prompts: list[str] = []
    original_call_model = GeminiProvider.call_model

    def _wrapped_call_model(self, prompt, *, system=None):
        captured_prompts.append(prompt)
        if system:
            captured_prompts.append(system)
        return original_call_model(self, prompt, system=system)

    import unittest.mock as mock

    with mock.patch.object(GeminiProvider, "call_model", _wrapped_call_model):
        files = {"file": ("orders.csv", _csv_with_unique_cell(), "text/csv")}
        upload_resp = api_client.post("/datasets", files=files)
        assert upload_resp.status_code == 200
        upload_body = upload_resp.json()["data"]
        dataset_id = upload_body["dataset_id"]
        session_id = upload_body["session_id"]

        # The upload/profile response itself must never leak the raw cell either.
        assert UNIQUE_CELL_VALUE not in api_client.get(f"/datasets/{dataset_id}").text

        result = run_agent(
            dataset_id=dataset_id,
            question="What is the total revenue across all orders?",
            session_id=session_id,
            prior_messages=[],
        )

    assert result["status"] in ("completed", "completed_with_fallback")
    # A real multi-call run happened (at least plan + finalize).
    assert len(captured_prompts) >= 2

    for prompt in captured_prompts:
        assert UNIQUE_CELL_VALUE not in prompt, (
            "Raw dataset cell value leaked across the LLM boundary into a Gemini prompt!"
        )

    # The final answer surfaced to the user must not contain it either.
    assert result["final_answer"] is not None
    assert UNIQUE_CELL_VALUE not in result["final_answer"]

    # And the persisted step history's generated code / result summaries
    # (which is exactly what's allowed to cross the boundary on refine) must
    # not contain it either — proves local_execute never smuggled it back in.
    import json as _json

    for step in result["step_history"]:
        assert UNIQUE_CELL_VALUE not in (step.get("code") or "")
        assert UNIQUE_CELL_VALUE not in _json.dumps(step.get("result_summary"), default=str)
