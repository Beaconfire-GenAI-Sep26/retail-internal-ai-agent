"""Graph wiring. Routers are pure functions of state; each one checks `error` first."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.context import AgentContext
from app.graph.state import InvestigationState


def route_after_load(state: dict[str, Any]) -> str:
    return "fail" if state.get("error") else "reason"


def route_after_reason(state: dict[str, Any]) -> str:
    return "fail" if state.get("error") else "guard"


def route_after_guard(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    if state.get("end_reason"):
        return "finalize"
    if state.get("guard_feedback"):
        return "reason"
    action = state.get("next_action") or {}
    if action.get("type") == "check":
        return "run_check"
    if action.get("type") == "conclude":
        return "conclude_gate"
    return "reason"  # ask_merchant goes to draft_question in M3; G16 rejects it until then


def route_after_run_check(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    return "finalize" if state.get("end_reason") else "reason"


def route_after_gate(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    return "finalize" if state.get("end_reason") else "reason"


def route_after_finalize(state: dict[str, Any]) -> str:
    result = state.get("result") or {}
    return "submit_recommendation" if result.get("outcome") == "diagnosis" else "report_status"


def route_after_submit(state: dict[str, Any]) -> str:
    return "fail" if state.get("error") else "report_status"


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(InvestigationState, context_schema=AgentContext)
    graph.add_node("load_case", nodes.load_case)
    graph.add_node("reason", nodes.reason)
    graph.add_node("guard", nodes.guard)
    graph.add_node("run_check", nodes.run_check)
    graph.add_node("conclude_gate", nodes.conclude_gate)
    graph.add_node("finalize", nodes.finalize)
    graph.add_node("submit_recommendation", nodes.submit_recommendation)
    graph.add_node("report_status", nodes.report_status)
    graph.add_node("fail", nodes.fail)

    graph.add_edge(START, "load_case")
    graph.add_conditional_edges("load_case", route_after_load, ["reason", "fail"])
    graph.add_conditional_edges("reason", route_after_reason, ["guard", "fail"])
    graph.add_conditional_edges(
        "guard", route_after_guard, ["run_check", "conclude_gate", "reason", "finalize", "fail"]
    )
    graph.add_conditional_edges("run_check", route_after_run_check, ["reason", "finalize", "fail"])
    graph.add_conditional_edges("conclude_gate", route_after_gate, ["reason", "finalize", "fail"])
    graph.add_conditional_edges("finalize", route_after_finalize, ["submit_recommendation", "report_status"])
    graph.add_conditional_edges("submit_recommendation", route_after_submit, ["report_status", "fail"])
    graph.add_edge("fail", "report_status")
    graph.add_edge("report_status", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


def run_config(investigation_id: str, recursion_limit: int) -> dict[str, Any]:
    """The LangGraph config. Only the thread ID goes in configurable; the JWT never does."""
    return {"configurable": {"thread_id": investigation_id}, "recursion_limit": recursion_limit}
