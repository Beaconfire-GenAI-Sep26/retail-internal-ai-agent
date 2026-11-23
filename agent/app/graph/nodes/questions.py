"""The merchant question loop: draft the question, wait for the analyst, wait for the merchant.

LangGraph re-runs a node from the top when it resumes, so nothing with a side effect comes before
interrupt(). wait_question_decision pauses first. wait_merchant_reply reads the replies first, because
Domain's simulated merchant can answer as soon as the question goes out, and pauses only while there's
none. On resume both re-read Domain and never trust the resume value. A resume that finds nothing new
changes nothing: the node returns no update and its router sends it back to pause again.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agent.app.contracts.models import InvestigationStatusUpdate, MerchantQuestionContent, ProposalCreate
from agent.app.domain.client import DomainError
from agent.app.graph.context import AgentContext
from agent.app.graph.nodes.common import domain_error, timeout_error
from agent.app.graph.policy import scrub
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.questions")
QUESTION_EVIDENCE_LIMIT = 20
NOTE_LIMIT = 500
REPLY_LIMIT = 1500


async def _report(ctx: AgentContext, state: InvestigationState, status: str) -> None:
    """Best effort. Domain moves the case on the proposal itself, and the run's final report supersedes this one."""
    try:
        await ctx.domain.report_investigation_status(state["case_id"], InvestigationStatusUpdate(
            investigation_id=state["investigation_id"], status=status, error_code=None))
    except DomainError as exc:
        if not exc.route_missing:
            log_event(logger, logging.WARNING, "status report failed", status=status, code=exc.code)


def _updated(state: InvestigationState, **changes: Any) -> list[dict[str, Any]]:
    """The question records, with the latest one changed."""
    questions = [dict(q) for q in state.get("questions", [])]
    questions[-1].update(changes)
    return questions


def _record(action: dict[str, Any], proposal_id: str | None, outcome: str) -> dict[str, Any]:
    return {"proposal_id": proposal_id, "question_text": action["question_text"], "approved_text": None,
            "why_asked": action["why_asked"], "separates": list(action["separates"]), "outcome": outcome,
            "decision_note": None, "reply_evidence_id": None, "reply_text": None}


def _unavailable(state: InvestigationState, ctx: AgentContext, action: dict[str, Any], route: str) -> dict[str, Any]:
    """Domain can't take questions, so none are asked in this run. reason hears why and goes on."""
    log_event(logger, logging.INFO, "Domain has no route for merchant questions; none will be asked", path=route)
    return {"questions": [*state.get("questions", []), _record(action, None, "unavailable")],
            "questions_asked": ctx.settings.agent_max_questions, "question_outcome": "unavailable"}


async def draft_question(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    action = state["next_action"]
    # load_case already checked that Domain has the merchant-replies route. Reply IDs stay out of the
    # evidence, which shows the analyst the platform data behind the causes the question separates.
    hypotheses = {h["hypothesis_id"]: h for h in state.get("hypotheses", [])}
    evidence = list(dict.fromkeys(
        e for hid in action["separates"] for e in hypotheses.get(hid, {}).get("supporting_evidence_ids", [])
        if not e.startswith("EV-RPL-")
    ))[:QUESTION_EVIDENCE_LIMIT]
    body = ProposalCreate(
        investigation_id=state["investigation_id"],
        kind="merchant_question",
        content=MerchantQuestionContent(question_text=action["question_text"], why_asked=action["why_asked"]),
        evidence_ids=evidence,
    )
    try:
        proposal_id = (await ctx.domain.create_proposal(state["case_id"], body)).proposal_id
    except DomainError as exc:
        if exc.route_missing:
            return _unavailable(state, ctx, action, exc.path or "proposals")
        if exc.status != 409 or exc.code != "PROPOSAL_PENDING":
            return {"error": domain_error(exc, "draft_question")}
        # A retried request: adopt the question this investigation already created, never another one.
        try:
            case = await ctx.domain.get_case(state["case_id"])
        except DomainError as inner:
            return {"error": domain_error(inner, "draft_question")}
        mine = next((p for p in case.proposals if p.investigation_id == state["investigation_id"]
                     and p.kind == "merchant_question" and p.status == "pending"), None)
        if mine is None:
            return {"error": domain_error(exc, "draft_question")}
        proposal_id = mine.proposal_id

    await _report(ctx, state, "awaiting_approval")
    log_event(logger, logging.INFO, "merchant question drafted", proposal_id=proposal_id)
    return {
        "status": "awaiting_approval",
        "question_open": True,
        "question_proposal_id": proposal_id,
        "question_outcome": None,
        "questions_asked": state.get("questions_asked", 0) + 1,
        "questions": [*state.get("questions", []), _record(action, proposal_id, "pending")],
    }


async def wait_question_decision(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    interrupt({"waiting_for": "question_decision", "proposal_id": state["question_proposal_id"]})
    ctx = runtime.context
    try:
        proposal = await ctx.domain.get_proposal(state["question_proposal_id"])
    except DomainError as exc:
        if exc.unavailable or exc.route_missing:
            log_event(logger, logging.WARNING, "question decision unreadable; still paused", code=exc.code)
            return {}
        return {"error": domain_error(exc, "wait_question_decision")}
    if proposal.status == "approved":
        # Domain sent the current version, which the analyst may have edited.
        if not proposal.dispatch or proposal.dispatch.get("status") != "dispatched":
            return {}  # approval alone is not proof that the reviewed version was sent
        asked = scrub(str(proposal.content.get("question_text") or state["questions"][-1]["question_text"]))
        await _report(ctx, state, "awaiting_merchant")
        log_event(logger, logging.INFO, "merchant question approved", proposal_id=proposal.proposal_id)
        return {"status": "awaiting_merchant", "question_outcome": "approved",
                "questions": _updated(state, outcome="approved", approved_text=asked)}
    if proposal.status == "rejected":
        note = (scrub(proposal.decision_note) or "")[:NOTE_LIMIT] or None
        await _report(ctx, state, "running")
        log_event(logger, logging.INFO, "merchant question rejected", proposal_id=proposal.proposal_id)
        return {"status": "running", "question_open": False, "question_outcome": "rejected",
                "questions": _updated(state, outcome="rejected", decision_note=note)}
    return {}


async def wait_merchant_reply(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    try:  # a read only, so it's safe to repeat when a resume re-runs the node
        replies = await ctx.domain.list_merchant_replies(state["case_id"])
    except DomainError as exc:
        if not (exc.unavailable or exc.route_missing):
            return {"error": domain_error(exc, "wait_merchant_reply")}
        log_event(logger, logging.WARNING, "merchant replies unreadable; still paused", code=exc.code)
        replies = []
    reply = next((r for r in replies if r.proposal_id == state["question_proposal_id"]), None)
    if reply is None:
        interrupt({"waiting_for": "merchant_reply", "proposal_id": state["question_proposal_id"]})
        return {}  # resumed, but the read above found nothing: back round to read again and pause
    outcome = "replied" if reply.outcome == "replied" else "no_reply"
    text = None
    if outcome == "replied":
        text = (scrub(reply.text) or "")[:REPLY_LIMIT] or None  # untrusted: rendered inside <data> only
    await _report(ctx, state, "running")
    log_event(logger, logging.INFO, "merchant reply read", proposal_id=reply.proposal_id, outcome=outcome,
              evidence_id=reply.evidence_id)
    update = {"status": "running", "question_open": False, "question_outcome": outcome,
              "retrieved_evidence_ids": [reply.evidence_id],
              "questions": _updated(state, outcome=outcome, reply_evidence_id=reply.evidence_id, reply_text=text)}
    if text:  # the result lists what the merchant said as unverified, for the analyst to weigh
        update["reply_claims"] = [*state.get("reply_claims", []), f"{reply.evidence_id}: {text[:300]}"]
    return update
