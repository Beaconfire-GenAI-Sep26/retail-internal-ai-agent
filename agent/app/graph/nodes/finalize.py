"""finalize: builds the InvestigationResult. No model call."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime

from agent.app.domain.client import DomainError
from agent.app.graph.context import AgentContext
from agent.app.graph.finalize import build_result, decide
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.finalize")


async def finalize(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    decision = decide(dict(state))
    invalid: set[str] = set()
    unverified = False
    if decision["outcome"] == "diagnosis":
        leader = state["next_action"]["leading_hypothesis_id"]
        cited: list[str] = []
        for h in state.get("hypotheses", []):
            if h["hypothesis_id"] == leader:
                cited += h["supporting_evidence_ids"] + h["contradicting_evidence_ids"]
            elif h["status"] == "ruled_out":
                cited += h["contradicting_evidence_ids"]
        cited = list(dict.fromkeys(cited))
        retrieved = set(state.get("retrieved_evidence_ids", []))
        invalid = {e for e in cited if e not in retrieved}
        to_resolve = [e for e in cited if e in retrieved]
        if to_resolve:
            try:
                response = await ctx.domain.resolve_evidence(state["store_id"], to_resolve)
                invalid |= {i["evidence_id"] for i in response.invalid}
            except DomainError as exc:
                unverified = True
                log_event(logger, logging.WARNING, "evidence resolve failed", status=exc.status, code=exc.code)
    result = build_result(dict(state), max_steps=ctx.settings.agent_max_steps, invalid_ids=invalid)
    if unverified:
        result["evidence_gaps"].append("Citations could not be verified because Domain was unavailable.")
    status = "completed" if result["outcome"] == "diagnosis" else "unsure"
    log_event(logger, logging.INFO, "investigation finalized", outcome=result["outcome"],
              end_reason=decision["end_reason"], cause=result["cause_category"])
    return {"result": result, "status": status, "end_reason": decision["end_reason"]}
