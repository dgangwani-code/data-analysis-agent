"""Conditional routing functions for the bounded code-gen/execute/refine loop.

See spec/agent.md#graph--flow-topology for the full routing table.
"""
from graph.state import AgentState


def after_build_context(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "plan_generate_code"


def after_plan(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "local_execute"


def after_execute(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    if state.get("current_error") is None:
        return "finalize_answer"
    step_count = state.get("step_count", 0)
    max_steps = state.get("max_steps", 6)
    if step_count < max_steps:
        return "plan_generate_code"
    return "best_guess_fallback"
