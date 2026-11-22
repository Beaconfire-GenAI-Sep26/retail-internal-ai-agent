from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.models import CaseStatus
from domain.app.schemas import AuditEntryOut, CaseDetail, CaseSummary, MerchantReply, Recheck
from domain.app.security import CurrentUser, current_user
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
