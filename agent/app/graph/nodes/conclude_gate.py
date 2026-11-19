"""conclude_gate: checks an accepted conclusion against K1-K5."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime

from agent.app.graph.context import AgentContext
from agent.app.graph.gate import evaluate_gate
from agent.app.graph.nodes.common import timeout_error
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.gate")
GATE_CAP = 2


async def conclude_gate(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    result = evaluate_gate(dict(state), state["next_action"])
    if result["passed"]:
        return {"gate_result": result, "end_reason": "gate_passed", "gate_feedback": None}
    rejections = state.get("gate_rejections", 0) + 1
    log_event(logger, logging.INFO, "conclude gate unmet", rules=[c["rule"] for c in result["unmet"]],
              rejections=rejections)
    update: dict[str, Any] = {
        "gate_result": result,
        "gate_rejections": rejections,
        "gate_feedback": {"unmet": result["unmet"]},
    }
    if state.get("step_count", 0) >= ctx.settings.agent_max_steps:
        update["end_reason"] = "budget_spent"
    elif rejections >= GATE_CAP:
        update["end_reason"] = "gate_cap"
    elif state.get("reason_calls", 0) >= ctx.settings.max_reason_calls:
        update["end_reason"] = "reason_cap"
    return update
