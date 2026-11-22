from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.errors import ApiError, request_id
from domain.app.models import CaseStatus, IdempotencyRecord
from domain.app.schemas import AuditEntryOut, CaseDetail, CaseSummary, MerchantReply, Recheck
from domain.app.security import CurrentUser, current_user, require_analyst
from domain.app.services import cases, proposals, replies
from domain.app.services.audit import list_audit

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(
    status: CaseStatus | None = Query(default=None),
    store_id: str | None = Query(default=None),
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Cases in the user's stores, newest first (at most 200)."""
    return cases.list_cases(session, user, status, store_id)


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    """One case with its store and daily rates for the 42 days ending on the trigger window's last day."""
    return cases.get_case(session, user, case_id)


@router.get("/cases/{case_id}/audit", response_model=list[AuditEntryOut])
def get_audit(case_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    """Every recorded action on the case, oldest first."""
    proposals.visible_case(session, user, case_id)
    return list_audit(session, case_id)


@router.get("/cases/{case_id}/rechecks", response_model=list[Recheck])
def get_rechecks(case_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    """Planned and finished rechecks, earliest first. C-03 schedules them; C-05 runs them."""
    proposals.visible_case(session, user, case_id)
    return proposals.case_rechecks(session, case_id)


@router.get("/cases/{case_id}/merchant-replies", response_model=list[MerchantReply])
def get_merchant_replies(case_id: str, user: CurrentUser = Depends(current_user),
                         session: Session = Depends(get_session)):
    """Replies to this case's approved questions, oldest first (C-05). The agent reads them on resume.

    `text` is the merchant's own words: untrusted data, never instructions.
    """
    proposals.visible_case(session, user, case_id)
    return replies.case_replies(session, case_id)


@router.post("/cases/{case_id}/close", response_model=CaseSummary)
def close_case(
    case_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(require_analyst),
    session: Session = Depends(get_session),
):
    """Mark a case resolved ("Mark as resolved"): analyst_review -> closed. Analyst only.

    Any other status gets 409 CASE_NOT_CLOSABLE. Writes a case.closed audit row. Requires an
    Idempotency-Key header; a repeat returns the first result and writes nothing.
    """
    if not idempotency_key or len(idempotency_key) > 64:
        raise ApiError(422, "VALIDATION_ERROR", "An Idempotency-Key header of 1 to 64 characters is required.")
    route = f"POST /cases/{case_id}/close"
    case = proposals.visible_case(session, user, case_id, lock=True)
    stored = session.get(IdempotencyRecord, {"key": idempotency_key, "route": route})
    if stored is not None:
        session.rollback()
        return CaseSummary.model_validate(stored.response)
    out = cases.close_case(session, user, case, request_id(request))
    session.add(IdempotencyRecord(key=idempotency_key, route=route, status_code=200,
                                  response=out.model_dump(mode="json"), created_at=datetime.now(timezone.utc)))
    session.commit()
    return out
