from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    build_context,
    plan_generate_code,
    local_execute,
    finalize_answer,
    best_guess_fallback,
    handle_error,
    finalize,
)
from graph.edges import after_build_context, after_plan, after_execute


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("build_context", build_context)
    g.add_node("plan_generate_code", plan_generate_code)
    g.add_node("local_execute", local_execute)
    g.add_node("finalize_answer", finalize_answer)
    g.add_node("best_guess_fallback", best_guess_fallback)
    g.add_node("handle_error", handle_error)
    g.add_node("finalize", finalize)

    g.set_entry_point("build_context")

    g.add_conditional_edges(
        "build_context",
        after_build_context,
        {"plan_generate_code": "plan_generate_code", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "plan_generate_code",
        after_plan,
        {"local_execute": "local_execute", "handle_error": "handle_error"},
    )
    g.add_conditional_edges(
        "local_execute",
        after_execute,
        {
            "finalize_answer": "finalize_answer",
            "plan_generate_code": "plan_generate_code",
            "best_guess_fallback": "best_guess_fallback",
            "handle_error": "handle_error",
        },
    )

    g.add_edge("finalize_answer", "finalize")
    g.add_edge("best_guess_fallback", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()
