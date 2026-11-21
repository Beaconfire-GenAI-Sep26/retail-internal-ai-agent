"""Proposals, decisions, mock dispatch and planned rechecks (C-03).

Rules (contracts.md "Decision rules" and "Idempotency"):
- The agent creates a proposal through an internal route. It starts `pending` at version 1.
  A case has at most one pending proposal.
- An analyst may edit a pending proposal. Each real change adds a version; old versions are kept.
- A decision names the version it was made on. An old version gets 409 STALE_VERSION, so nobody
  approves text they have not seen. A decided proposal can't be edited or decided again
  (409 ALREADY_DECIDED), except that repeating the same decision returns the first result.
- Approval writes the decision, the mock dispatch, the case status, the audit rows and (for an
  intervention or handoff) the planned recheck in one transaction. Rejection never dispatches.
- If the mock send fails, nothing is saved except a `dispatch.failed` audit row, and the proposal
  stays pending (502 DISPATCH_FAILED).
- C-05: a dispatched question gets the store's mock merchant answer in the same transaction
  (services/replies.py). Rechecks are run by services/rechecks.py.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.catalog import BY_ID
from domain.app.errors import ApiError
from domain.app.models import (
    DISPATCH_SEQ,
    PROPOSAL_SEQ,
    RECHECK_SEQ,
    Case,
    CaseStatus,
    Dispatch,
    Proposal,
    ProposalKind,
    ProposalStatus,
    ProposalVersion,
    Recheck,
    RecheckStatus,
    Store,
)
from domain.app.schemas import (
    ActionContent,
    ClaimScope,
    DecisionRequest,
    InvestigationStatusUpdate,
    MerchantQuestionContent,
    ProposalCreate,
    ProposalEdit,
    RateWindow,
    Target,
)
from domain.app.schemas import Dispatch as DispatchOut
from domain.app.schemas import Proposal as ProposalOut
from domain.app.schemas import Recheck as RecheckOut
from domain.app.security import CurrentUser, check_store
from domain.app.services.audit import SVC_AGENT, write_audit
from domain.app.services.diagnostics import claim_in_scope, order_in_scope
from domain.app.services.evidence import load_evidence
from domain.app.services.replies import mock_merchant_answers
from domain.app.services.store_data import StoreContext, load_context, load_window
from domain.app.settings import settings


class DispatchFailed(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Lookups. A case or proposal in a store outside the token's grants is a 404,
# so IDs from other stores can't be probed (contracts.md Errors).
# ---------------------------------------------------------------------------
def visible_case(session: Session, user: CurrentUser, case_id: str, lock: bool = False,
                 internal: bool = False) -> Case:
    """Public reads hide other stores' cases (404). Internal routes, like every route that touches
    a store, answer 403 STORE_NOT_PERMITTED when the case's store isn't in the token (contracts.md)."""
    q = select(Case).where(Case.case_id == case_id)
    case = session.scalar(q.with_for_update() if lock else q)
    if case is not None and internal:
        check_store(user, case.store_id)
    if case is None or not user.can_see(case.store_id):
        raise ApiError(404, "CASE_NOT_FOUND", f"Case {case_id} was not found.")
    return case


def visible_proposal(session: Session, user: CurrentUser, proposal_id: str, lock: bool = False) -> tuple[Proposal, Case]:
    q = select(Proposal).where(Proposal.proposal_id == proposal_id)
    p = session.scalar(q.with_for_update() if lock else q)
    case = session.get(Case, p.case_id) if p else None
    if p is None or not user.can_see(case.store_id):
        raise ApiError(404, "NOT_FOUND", f"Proposal {proposal_id} was not found.")
    return p, case


def _content_model(kind: ProposalKind):
    return MerchantQuestionContent if kind == ProposalKind.MERCHANT_QUESTION else ActionContent


def proposal_out(session: Session, p: Proposal) -> ProposalOut:
    v = session.get(ProposalVersion, {"proposal_id": p.proposal_id, "version": p.current_version})
    d = session.scalar(select(Dispatch).where(Dispatch.proposal_id == p.proposal_id))
    return ProposalOut(
        proposal_id=p.proposal_id,
        case_id=p.case_id,
        investigation_id=p.investigation_id,
        kind=p.kind,
        version=p.current_version,
        status=p.status,
        content=_content_model(p.kind).model_validate(v.content),
        evidence_ids=list(p.evidence_ids),
        created_at=p.created_at,
        decided_by=p.decided_by,
        decided_at=p.decided_at,
        decision_note=p.decision_note,
        dispatch=DispatchOut(
            dispatch_id=d.dispatch_id, status=d.status, channel=d.channel, owner_team=d.owner_team,
            dispatched_at=d.dispatched_at,
        ) if d else None,
    )


def case_proposals(session: Session, case_id: str) -> list[ProposalOut]:
    rows = session.scalars(
        select(Proposal).where(Proposal.case_id == case_id).order_by(Proposal.created_at.desc(), Proposal.proposal_id.desc())
    ).all()
    return [proposal_out(session, p) for p in rows]


def recheck_out(r: Recheck) -> RecheckOut:
    return RecheckOut(
        recheck_id=r.recheck_id, case_id=r.case_id, proposal_id=r.proposal_id, scheduled_for=r.scheduled_for,
        status=r.status, target=Target.model_validate(r.target), before=RateWindow.model_validate(r.before),
        after=RateWindow.model_validate(r.after) if r.after else None,
        control=RateWindow.model_validate(r.control) if r.control else None,
        data_sufficient=r.data_sufficient, ran_at=r.ran_at,
    )


def case_rechecks(session: Session, case_id: str) -> list[RecheckOut]:
    rows = session.scalars(
        select(Recheck).where(Recheck.case_id == case_id).order_by(Recheck.scheduled_for, Recheck.recheck_id)
    ).all()
    return [recheck_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Validation shared by create and edit
# ---------------------------------------------------------------------------
def check_content(ctx: StoreContext, kind: ProposalKind, content) -> str:
    """Checks the content fits the kind and the catalog. Returns the owner team."""
    if kind == ProposalKind.MERCHANT_QUESTION:
        if not isinstance(content, MerchantQuestionContent):
            raise ApiError(422, "VALIDATION_ERROR", "A merchant_question needs question_text and why_asked.")
        return "merchant"
    if not isinstance(content, ActionContent):
        raise ApiError(422, "VALIDATION_ERROR", f"A {kind.value} needs action content (action_id, target, ...).")
    entry = BY_ID.get(content.action_id)
    if entry is None:
        raise ApiError(422, "UNKNOWN_ACTION", f"{content.action_id} is not in the action catalog.",
                       {"catalog": sorted(BY_ID)})
    if entry.kind != kind.value:
        raise ApiError(422, "VALIDATION_ERROR", f"{content.action_id} is a {entry.kind}, not a {kind.value}.")
    if entry.owner_team != content.owner_team:
        raise ApiError(422, "VALIDATION_ERROR",
                       f"{content.action_id} belongs to {entry.owner_team}, not {content.owner_team}.")
    ctx.check_items(content.target.item_id or None)
    ctx.check_modifiers(content.target.modifiers or None)
    return content.owner_team


def _set_status(case: Case, status: CaseStatus, now: datetime) -> None:
    case.status = status
    case.updated_at = now


# ---------------------------------------------------------------------------
# Internal routes (agent only)
# ---------------------------------------------------------------------------
def create_proposal(session: Session, user: CurrentUser, case_id: str, body: ProposalCreate, rid: str) -> ProposalOut:
    case = visible_case(session, user, case_id, lock=True, internal=True)  # row lock: one pending proposal per case
    pending = session.scalar(
        select(Proposal.proposal_id).where(Proposal.case_id == case_id, Proposal.status == ProposalStatus.PENDING)
    )
    if pending:
        raise ApiError(409, "PROPOSAL_PENDING", f"Case {case_id} already has a pending proposal, {pending}.",
                       {"proposal_id": pending})
    ctx = load_context(session, session.get(Store, case.store_id))
    check_content(ctx, body.kind, body.content)

    found = load_evidence(session, body.evidence_ids)
    invalid = [
        {"evidence_id": eid, "reason": "not_found" if eid not in found else "other_store"}
        for eid in dict.fromkeys(body.evidence_ids)
        if eid not in found or found[eid].store_id != case.store_id
    ]
    if invalid:
        raise ApiError(422, "INVALID_EVIDENCE", "Some cited evidence IDs can't be used for this case.",
                       {"invalid": invalid})

    now = _now()
    p = Proposal(
        proposal_id=f"PROP-{session.scalar(PROPOSAL_SEQ.next_value()):04d}",
        case_id=case_id,
        investigation_id=body.investigation_id,
        kind=body.kind,
        status=ProposalStatus.PENDING,
        current_version=1,
        evidence_ids=list(dict.fromkeys(body.evidence_ids)),
        created_at=now,
    )
    session.add(p)
    session.add(ProposalVersion(proposal_id=p.proposal_id, version=1, content=body.content.model_dump(mode="json"),
                                created_by=SVC_AGENT, created_at=now))
    _set_status(case, CaseStatus.AWAITING_DECISION, now)
    write_audit(session, case_id=case_id, action="proposal.created", request_id=rid, service=SVC_AGENT, user=user,
                proposal_id=p.proposal_id, version=1,
                details={"kind": body.kind.value, "investigation_id": body.investigation_id})
    session.flush()
    return proposal_out(session, p)


def update_investigation(session: Session, user: CurrentUser, case_id: str, body: InvestigationStatusUpdate,
                         rid: str) -> Case:
    """Map the agent's investigation_status to case_status (contracts.md Status model)."""
    case = visible_case(session, user, case_id, lock=True, internal=True)
    now = _now()
    if body.investigation_id not in case.investigation_ids:
        case.investigation_ids = [*case.investigation_ids, body.investigation_id]  # new list, so it is saved
    status = body.status
    if status == "running":
        case.active_investigation_id = body.investigation_id
        case.last_error = None
        _set_status(case, CaseStatus.INVESTIGATING, now)
    elif status in ("awaiting_approval", "awaiting_merchant"):
        # Paused, still active. The case status follows the proposal (awaiting_decision / awaiting_merchant).
        case.active_investigation_id = body.investigation_id
        case.updated_at = now
    else:
        case.active_investigation_id = None
        if status == "completed":
            has_pending = session.scalar(
                select(Proposal.proposal_id).where(Proposal.case_id == case_id, Proposal.status == ProposalStatus.PENDING)
            )
            if has_pending:
                _set_status(case, CaseStatus.AWAITING_DECISION, now)
            else:
                case.updated_at = now
        elif status == "unsure":
            _set_status(case, CaseStatus.ANALYST_REVIEW, now)
        elif status == "failed":
            case.last_error = body.error_code or "failed"
            _set_status(case, CaseStatus.OPEN, now)
    write_audit(session, case_id=case_id, action=f"investigation.{status}", request_id=rid, service=SVC_AGENT,
                user=user, details={"investigation_id": body.investigation_id, "error_code": body.error_code})
    session.flush()
    return case


# ---------------------------------------------------------------------------
# Analyst routes
# ---------------------------------------------------------------------------
def edit_proposal(session: Session, user: CurrentUser, proposal_id: str, body: ProposalEdit,
                  rid: str) -> tuple[ProposalOut, bool]:
    """Adds a version. Returns (proposal, created). Identical content adds nothing."""
    p, case = visible_proposal(session, user, proposal_id, lock=True)
    if p.status != ProposalStatus.PENDING:
        raise ApiError(409, "ALREADY_DECIDED", f"Proposal {proposal_id} was already {p.status.value}.",
                       {"status": p.status.value})
    ctx = load_context(session, session.get(Store, case.store_id))
    check_content(ctx, p.kind, body.content)
    new = body.content.model_dump(mode="json")
    current = session.get(ProposalVersion, {"proposal_id": proposal_id, "version": p.current_version})
    if current.content == new:
        return proposal_out(session, p), False
    now = _now()
    p.current_version += 1
    session.add(ProposalVersion(proposal_id=proposal_id, version=p.current_version, content=new,
                                created_by=user.user_id, created_at=now))
    case.updated_at = now
    write_audit(session, case_id=p.case_id, action="proposal.edited", request_id=rid, user=user,
                proposal_id=proposal_id, version=p.current_version)
    session.flush()
    return proposal_out(session, p), True


def mock_send(p: Proposal, content: dict, owner_team: str) -> str:
    """Pretend to send. Returns the channel. Nothing leaves the system."""
    if settings.mock_dispatch_fail:
        raise DispatchFailed("MOCK_DISPATCH_FAIL is on.")
    return "mock_merchant" if owner_team == "merchant" else "mock_team_queue"


def decide(session: Session, user: CurrentUser, p: Proposal, case: Case, body: DecisionRequest,
           rid: str) -> ProposalOut:
    """`p` must be locked (visible_proposal with lock=True). The caller commits."""
    if p.status != ProposalStatus.PENDING:
        same = {"approve": ProposalStatus.APPROVED, "reject": ProposalStatus.REJECTED}[body.decision] == p.status
        if same and body.version == p.decided_version:
            return proposal_out(session, p)  # a repeat: the first result, nothing new
        raise ApiError(409, "ALREADY_DECIDED",
                       f"Proposal {p.proposal_id} was already {p.status.value} at version {p.decided_version}.",
                       {"status": p.status.value, "decided_version": p.decided_version})
    if body.version != p.current_version:
        raise ApiError(409, "STALE_VERSION",
                       f"Proposal {p.proposal_id} is at version {p.current_version}. "
                       "Review the latest version before deciding.",
                       {"current_version": p.current_version})

    now = _now()
    content = session.get(ProposalVersion, {"proposal_id": p.proposal_id, "version": p.current_version}).content
    is_question = p.kind == ProposalKind.MERCHANT_QUESTION
    p.decided_by, p.decided_at, p.decided_version, p.decision_note = user.user_id, now, body.version, body.note

    if body.decision == "reject":
        p.status = ProposalStatus.REJECTED
        write_audit(session, case_id=case.case_id, action="proposal.rejected", request_id=rid, user=user,
                    proposal_id=p.proposal_id, version=body.version, details={"note": body.note})
        # A rejected question lets the investigation go on; a rejected action goes to the analyst.
        _set_status(case, CaseStatus.INVESTIGATING if is_question else CaseStatus.ANALYST_REVIEW, now)
        session.flush()
        return proposal_out(session, p)

    owner_team = "merchant" if is_question else content["owner_team"]
    channel = mock_send(p, content, owner_team)  # raises DispatchFailed
    p.status = ProposalStatus.APPROVED
    write_audit(session, case_id=case.case_id, action="proposal.approved", request_id=rid, user=user,
                proposal_id=p.proposal_id, version=body.version, details={"note": body.note})
    dispatch = Dispatch(
        dispatch_id=f"DSP-{session.scalar(DISPATCH_SEQ.next_value()):06d}",
        proposal_id=p.proposal_id,
        version=body.version,
        status="dispatched",
        channel=channel,
        owner_team=owner_team,
        payload=content,
        dispatched_by=user.user_id,
        dispatched_at=now,
    )
    session.add(dispatch)
    write_audit(session, case_id=case.case_id, action="dispatch.sent", request_id=rid, user=user,
                proposal_id=p.proposal_id, version=body.version,
                details={"dispatch_id": dispatch.dispatch_id, "channel": channel, "owner_team": owner_team})
    if is_question:
        _set_status(case, CaseStatus.AWAITING_MERCHANT, now)
        mock_merchant_answers(session, p, case, rid, now)  # C-05: the merchant's answer comes in by itself
    else:
        _set_status(case, CaseStatus.ACTION_DISPATCHED, now)
        r = schedule_recheck(session, case, p, ActionContent.model_validate(content), now)
        write_audit(session, case_id=case.case_id, action="recheck.scheduled", request_id=rid, user=user,
                    proposal_id=p.proposal_id, version=body.version,
                    details={"recheck_id": r.recheck_id, "scheduled_for": r.scheduled_for.isoformat()})
    session.flush()
    return proposal_out(session, p)


def record_dispatch_failure(session: Session, user: CurrentUser, case_id: str, proposal_id: str, version: int,
                            rid: str, reason: str) -> None:
    """Called after the decision was rolled back. The caller commits."""
    write_audit(session, case_id=case_id, action="dispatch.failed", request_id=rid, user=user,
                proposal_id=proposal_id, version=version, details={"reason": reason})


# ---------------------------------------------------------------------------
# Planned recheck. C-03 schedules it and records the "before" rate; C-05 runs it (services/rechecks.py).
# ---------------------------------------------------------------------------
def target_rate(session: Session, ctx: StoreContext, target: Target, start: date, end: date) -> RateWindow:
    """Attributable claims / delivered orders for the target's orders, store-local dates."""
    scope = ClaimScope(
        item_id=target.item_id or None,
        modifiers=target.modifiers or None,
        daypart=target.daypart or None,
        item_count_min=target.item_count_min,
    )
    data = load_window(session, ctx, start, end)
    orders = sum(1 for o in data.delivered if order_in_scope(o, scope))
    claims = sum(1 for c in data.claims if claim_in_scope(c, scope))
    rate = round(claims / orders, 4) if orders >= settings.min_group_orders else None
    return RateWindow(start=start, end=end, claims=claims, eligible_orders=orders, rate=rate)


def schedule_recheck(session: Session, case: Case, p: Proposal, content: ActionContent, now: datetime) -> Recheck:
    """`before` = the target's rate over the last `recheck_after_days` days of the case window
    (store-local), so the recheck can compare a window of the same length after the action."""
    ctx = load_context(session, session.get(Store, case.store_id))
    end = case.window_end.astimezone(ctx.tz).date()
    if ctx.last_date and end > ctx.last_date:
        end = ctx.last_date
    start = end - timedelta(days=content.recheck_after_days - 1)
    if ctx.first_date and start < ctx.first_date:
        start = ctx.first_date
    before = target_rate(session, ctx, content.target, start, end)
    r = Recheck(
        recheck_id=f"RCK-{session.scalar(RECHECK_SEQ.next_value()):04d}",
        case_id=case.case_id,
        proposal_id=p.proposal_id,
        scheduled_for=now + timedelta(days=content.recheck_after_days),
        status=RecheckStatus.SCHEDULED,
        target=content.target.model_dump(mode="json"),
        before=before.model_dump(mode="json"),
    )
    session.add(r)
    return r
