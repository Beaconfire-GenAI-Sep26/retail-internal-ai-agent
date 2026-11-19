"""guard: validates every ReasonOutput before anything runs or is saved."""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.runtime import Runtime

from app.graph.context import AgentContext
from app.graph.nodes.common import timeout_error
from app.graph.rules import evaluate_output
from app.graph.state import InvestigationState
from app.logs import log_event

logger = logging.getLogger("agent.guard")
GUARD_CAP = 2


async def guard(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    settings = ctx.settings
    raw = state.get("reason_output")
    decision = evaluate_output(
        dict(state),
        raw,
        max_steps=settings.agent_max_steps,
        max_questions=settings.agent_max_questions,
        ids=ctx.ids,
    )
    if not decision.accepted:
        rejections = state.get("consecutive_rejections", 0) + 1
        log_event(logger, logging.INFO, "guard rejected output", rules=decision.rule_ids, rejections=rejections)
        if decision.blocked_action:
            log_event(logger, logging.WARNING, "blocked_action", rules=decision.rule_ids)
        rejected = raw.get("next_action") if isinstance(raw, dict) else None
        update: dict[str, Any] = {
            "consecutive_rejections": rejections,
            "guard_feedback": {
                "rule_ids": decision.rule_ids,
                "violations": [v.as_dict() for v in decision.violations],
                "rejected_action": json.dumps(rejected, sort_keys=True)[:2000] if rejected else None,
            },
        }
        if rejections >= GUARD_CAP:
            update["end_reason"] = "guard_cap"
        elif state.get("reason_calls", 0) >= settings.max_reason_calls:
            update["end_reason"] = "reason_cap"
        return update

    update = {
        "hypotheses": decision.hypotheses,
        "consecutive_rejections": 0,
        "guard_feedback": None,
        "gate_feedback": None,
        "next_action": decision.action,
    }
    latest_id = state.get("latest_check_id")
    latest = next((c for c in state.get("checks", []) if c["check_id"] == latest_id), None)
    if latest and latest.get("needs_match"):
        update["checks"] = [{"check_id": latest_id, "matched": decision.matched, "needs_match": False}]
    if decision.budget_spent:
        update["end_reason"] = "budget_spent"
    elif decision.action and decision.action["type"] == "conclude":
        update["rise_started_at"] = decision.action["rise_started_at"]
    return update
