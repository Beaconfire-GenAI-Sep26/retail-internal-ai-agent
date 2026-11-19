"""submit_recommendation: creates the intervention or handoff proposal through Domain."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from app.contracts.models import ActionContent, ProposalCreate
from app.domain.client import DomainError
from app.graph.context import AgentContext
from app.graph.finalize import action_content
from app.graph.nodes.common import domain_error
from app.graph.state import InvestigationState


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
        if exc.status != 409 or exc.code != "PROPOSAL_PENDING":
            return {"error": domain_error(exc, "submit_recommendation")}
        proposal_id = exc.details.get("proposal_id")
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
