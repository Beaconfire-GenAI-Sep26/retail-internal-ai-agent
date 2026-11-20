from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.errors import ApiError, request_id
from domain.app.models import IdempotencyRecord
from domain.app.schemas import DecisionRequest, Proposal, ProposalEdit
from domain.app.security import CurrentUser, current_user, require_analyst
from domain.app.services import proposals

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/{proposal_id}", response_model=Proposal)
def get_proposal(proposal_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    """The proposal with its current version and, once approved, its dispatch."""
    p, _ = proposals.visible_proposal(session, user, proposal_id)
    return proposals.proposal_out(session, p)


@router.post("/{proposal_id}/versions", response_model=Proposal, status_code=201)
def edit_proposal(
    proposal_id: str,
    body: ProposalEdit,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_analyst),
    session: Session = Depends(get_session),
):
    """Analyst edit of a pending proposal. Adds the next version; the old one is kept.

    Content identical to the current version adds no version (200 instead of 201).
    """
    out, created = proposals.edit_proposal(session, user, proposal_id, body, request_id(request))
    session.commit()
    if not created:
        response.status_code = 200
    return out


@router.post("/{proposal_id}/decision", response_model=Proposal)
def decide(
    proposal_id: str,
    body: DecisionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(require_analyst),
    session: Session = Depends(get_session),
):
    """Approve or reject the named version. Analyst only, for a store in the token.

    Approve: mock dispatch + audit + case status + planned recheck (intervention/handoff), all
    in one transaction. Reject: audit + case status, never a dispatch.
    Requires an Idempotency-Key header (a UUID per click). A repeat returns the first result.
    """
    if not idempotency_key or len(idempotency_key) > 64:
        raise ApiError(422, "VALIDATION_ERROR", "An Idempotency-Key header of 1 to 64 characters is required.")
    rid = request_id(request)
    route = f"POST /proposals/{proposal_id}/decision"
    p, case = proposals.visible_proposal(session, user, proposal_id, lock=True)  # waits for a parallel decision
    stored = session.get(IdempotencyRecord, {"key": idempotency_key, "route": route})
    if stored is not None:
        session.rollback()
        return Proposal.model_validate(stored.response)

    case_id, version = case.case_id, body.version
    try:
        out = proposals.decide(session, user, p, case, body, rid)
    except proposals.DispatchFailed as exc:
        session.rollback()  # nothing from the decision is kept; the proposal stays pending
        proposals.record_dispatch_failure(session, user, case_id, proposal_id, version, rid, str(exc))
        session.commit()
        raise ApiError(502, "DISPATCH_FAILED", "The mock dispatch failed. The proposal is still pending.")
    session.add(IdempotencyRecord(key=idempotency_key, route=route, status_code=200,
                                  response=out.model_dump(mode="json"), created_at=datetime.now(timezone.utc)))
    session.commit()
    return out
