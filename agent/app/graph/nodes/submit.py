"""submit_recommendation: creates the intervention or handoff proposal through Domain."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime

from agent.app.contracts.models import ActionContent, ProposalCreate
from agent.app.domain.client import DomainError
from agent.app.graph.context import AgentContext
from agent.app.graph.finalize import action_content
from agent.app.graph.nodes.common import domain_error
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.submit")

NO_PROPOSALS_ROUTE_GAP = "The recommendation was not saved as a proposal because Domain has no proposals route."


async def submit_recommendation(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    result = dict(state["result"])
    rec = result["recommendation"]
    body = ProposalCreate(
        investigation_id=state["investigation_id"],
        kind=rec["kind"],
        content=ActionContent.model_validate(action_content(result, dict(state))),
        evidence_ids=result["supporting_evidence_ids"],
    )
    try:
        proposal = await ctx.domain.create_proposal(state["case_id"], body)
        proposal_id = proposal.proposal_id
    except DomainError as exc:
        if exc.route_missing:
            # Domain hasn't shipped the proposals route yet: keep the diagnosis, say it wasn't saved.
            log_event(logger, logging.INFO, "Domain has no proposals route; the recommendation was not saved",
                      path=exc.path)
            result["proposal_id"] = None
            result["evidence_gaps"] = [*result.get("evidence_gaps", []), NO_PROPOSALS_ROUTE_GAP]
            return {"result": result}
        if exc.status != 409 or exc.code != "PROPOSAL_PENDING":
            return {"error": domain_error(exc, "submit_recommendation")}
        # Recover only a proposal this investigation created (a retried request); another one's pending
        # proposal on the same case is not this run's recommendation.
        details = exc.details or {}
        proposal_id = None
        if details.get("proposal_id") and details.get("investigation_id") == state["investigation_id"]:
            proposal_id = details["proposal_id"]
        if not proposal_id:
            try:
                case = await ctx.domain.get_case(state["case_id"])
            except DomainError as inner:
                return {"error": domain_error(inner, "submit_recommendation")}
            match = next(
                (p for p in case.proposals
                 if p.investigation_id == state["investigation_id"] and p.kind == rec["kind"] and p.status == "pending"),
                None,
            )
            if match is None:
                return {"error": domain_error(exc, "submit_recommendation")}
            proposal_id = match.proposal_id
    result["proposal_id"] = proposal_id
    return {"result": result}
