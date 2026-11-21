"""Graph wiring. Routers are pure functions of state; each one checks `error` first."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.app.graph import nodes
from agent.app.graph.context import AgentContext
from agent.app.graph.state import InvestigationState


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
    if action.get("type") == "ask_merchant":
        return "draft_question"
    return "reason"


def route_after_draft(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    return "wait_question_decision" if state.get("question_open") else "reason"  # not open: Domain can't take one


def route_after_question_decision(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    outcome = state.get("question_outcome")
    if outcome == "approved":
        return "wait_merchant_reply"
    return "reason" if outcome == "rejected" else "wait_question_decision"  # still pending: pause again


def route_after_merchant_reply(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "fail"
    return "reason" if state.get("question_outcome") in ("replied", "no_reply") else "wait_merchant_reply"


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
    graph.add_node("draft_question", nodes.draft_question)
    graph.add_node("wait_question_decision", nodes.wait_question_decision)
    graph.add_node("wait_merchant_reply", nodes.wait_merchant_reply)
    graph.add_node("finalize", nodes.finalize)
    graph.add_node("submit_recommendation", nodes.submit_recommendation)
    graph.add_node("report_status", nodes.report_status)
    graph.add_node("fail", nodes.fail)

    graph.add_edge(START, "load_case")
    graph.add_conditional_edges("load_case", route_after_load, ["reason", "fail"])
    graph.add_conditional_edges("reason", route_after_reason, ["guard", "fail"])
    graph.add_conditional_edges(
        "guard", route_after_guard, ["run_check", "conclude_gate", "draft_question", "reason", "finalize", "fail"]
    )
    graph.add_conditional_edges("draft_question", route_after_draft, ["wait_question_decision", "reason", "fail"])
    graph.add_conditional_edges("wait_question_decision", route_after_question_decision,
                                ["wait_question_decision", "wait_merchant_reply", "reason", "fail"])
    graph.add_conditional_edges("wait_merchant_reply", route_after_merchant_reply,
                                ["wait_merchant_reply", "reason", "fail"])
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
