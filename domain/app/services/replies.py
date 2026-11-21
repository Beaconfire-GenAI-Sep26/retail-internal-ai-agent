"""Merchant replies (C-05).

A reply answers one approved, dispatched merchant question and becomes evidence (EV-RPL-...).

- The merchant's answer comes in by itself: when a question is dispatched, the mock merchant answers
  from the seeded inbox (`mock_merchant_inbox`) in the same transaction. The analyst never types it.
- A store with no inbox answer never replies. The analyst then records `no_reply`
  (POST /proposals/{id}/merchant-reply), and the agent continues without an answer.
- One reply per question: a second one gets 409 REPLY_EXISTS. A repeat of the same request
  (same Idempotency-Key) returns the first result.
- Domain doesn't change the case status for a reply. The case stays `awaiting_merchant` until the
  agent resumes and reports `running` (contracts.md Status model).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.errors import ApiError
from domain.app.models import (
    REPLY_SEQ,
    Case,
    Dispatch,
    MerchantReply,
    MockMerchantInbox,
    Proposal,
    ProposalKind,
    ProposalStatus,
    ReplyOutcome,
)
from domain.app.schemas import MerchantReply as MerchantReplyOut
from domain.app.schemas import MerchantReplyCreate
from domain.app.security import CurrentUser
from domain.app.services.audit import write_audit

SVC_MOCK_MERCHANT = "svc_mock_merchant"


def reply_out(r: MerchantReply) -> MerchantReplyOut:
    return MerchantReplyOut(evidence_id=r.evidence_id, proposal_id=r.proposal_id, outcome=r.outcome.value,
                            text=r.text, recorded_by=r.recorded_by, recorded_at=r.recorded_at)


def case_replies(session: Session, case_id: str) -> list[MerchantReplyOut]:
    rows = session.scalars(
        select(MerchantReply).where(MerchantReply.case_id == case_id)
        .order_by(MerchantReply.recorded_at, MerchantReply.evidence_id)
    ).all()
    return [reply_out(r) for r in rows]


def _save(session: Session, p: Proposal, outcome: ReplyOutcome, text: str | None, recorded_by: str,
          now: datetime) -> MerchantReply:
    r = MerchantReply(
        evidence_id=f"EV-RPL-{session.scalar(REPLY_SEQ.next_value()):06d}",
        proposal_id=p.proposal_id, case_id=p.case_id, outcome=outcome,
        text=text.strip() if text else None, recorded_by=recorded_by, recorded_at=now,
    )
    session.add(r)
    return r


def mock_merchant_answers(session: Session, p: Proposal, case: Case, rid: str, now: datetime) -> MerchantReply | None:
    """Called when a question is dispatched. Writes the store's seeded answer, if it has one."""
    inbox = session.get(MockMerchantInbox, case.store_id)
    if inbox is None:
        return None  # this merchant never answers: the analyst records no_reply
    r = _save(session, p, ReplyOutcome.REPLIED, inbox.reply_text, SVC_MOCK_MERCHANT, now)
    write_audit(session, case_id=case.case_id, action="merchant_reply.recorded", request_id=rid,
                service=SVC_MOCK_MERCHANT, proposal_id=p.proposal_id,
                details={"evidence_id": r.evidence_id, "outcome": "replied"})
    return r


def record_reply(session: Session, user: CurrentUser, p: Proposal, body: MerchantReplyCreate,
                 rid: str) -> MerchantReplyOut:
    """Analyst records the reply, usually `no_reply`. `p` must be locked. The caller commits."""
    dispatched = session.scalar(select(Dispatch.dispatch_id).where(Dispatch.proposal_id == p.proposal_id))
    if p.kind != ProposalKind.MERCHANT_QUESTION or p.status != ProposalStatus.APPROVED or not dispatched:
        raise ApiError(409, "NOT_DISPATCHED",
                       f"{p.proposal_id} is not an approved, dispatched merchant question.",
                       {"kind": p.kind.value, "status": p.status.value})
    existing = session.scalar(select(MerchantReply).where(MerchantReply.proposal_id == p.proposal_id))
    if existing is not None:
        raise ApiError(409, "REPLY_EXISTS", f"{p.proposal_id} already has a reply, {existing.evidence_id}.",
                       {"evidence_id": existing.evidence_id})
    now = datetime.now(timezone.utc)
    r = _save(session, p, ReplyOutcome(body.outcome), body.text, user.user_id, now)
    case = session.get(Case, p.case_id)
    case.updated_at = now
    write_audit(session, case_id=p.case_id, action="merchant_reply.recorded", request_id=rid, user=user,
                proposal_id=p.proposal_id, details={"evidence_id": r.evidence_id, "outcome": body.outcome})
    session.flush()
    return reply_out(r)
