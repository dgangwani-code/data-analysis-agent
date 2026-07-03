"""Graph compiles and is wired without hitting any network or requiring env vars."""


def test_graph_compiles():
    from graph.agent import agentic_ai

    assert agentic_ai is not None


def test_graph_has_expected_nodes():
    from graph.agent import agentic_ai

    node_names = set(agentic_ai.get_graph().nodes.keys())
    expected = {
        "build_context",
        "plan_generate_code",
        "local_execute",
        "finalize_answer",
        "best_guess_fallback",
        "handle_error",
        "finalize",
    }
    assert expected.issubset(node_names)


def test_state_shape_importable():
    from graph.state import AgentState

    # TypedDict — just confirm the annotations exist for the fields the graph relies on
    fields = AgentState.__annotations__
    for key in (
        "run_id",
        "session_id",
        "dataset_id",
        "question",
        "step_count",
        "max_steps",
        "step_history",
        "current_code",
        "current_result_summary",
        "current_error",
        "final_answer",
        "final_code",
        "is_fallback",
        "error",
        "status",
    ):
        assert key in fields
