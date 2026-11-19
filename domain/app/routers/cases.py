from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_session
from app.models import CaseStatus
from app.schemas import CaseDetail, CaseSummary
from app.security import CurrentUser, current_user
from app.services import cases

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
