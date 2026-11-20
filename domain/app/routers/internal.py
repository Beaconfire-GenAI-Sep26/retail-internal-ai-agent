"""Internal routes: the agent's only writes (contracts.md). Not exposed by the gateway.

The service token, analyst role, X-Investigation-ID / X-Store-ID headers and the case's store
are checked before the route runs, by domain/app/access.py (A-02).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.errors import request_id
from domain.app.models import Store
from domain.app.schemas import CaseSummary, InvestigationStatusUpdate, Proposal, ProposalCreate
from domain.app.security import CurrentUser, current_user
from domain.app.services import proposals
from domain.app.services.cases import case_summary

router = APIRouter(prefix="/internal", tags=["internal (agent only)"])


@router.post("/cases/{case_id}/proposals", response_model=Proposal, status_code=201)
def create_proposal(
    case_id: str,
    body: ProposalCreate,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Save a draft proposal: pending, version 1. One pending proposal per case."""
    out = proposals.create_proposal(session, user, case_id, body, request_id(request))
    session.commit()
    return out


@router.put("/cases/{case_id}/investigation", response_model=CaseSummary)
def update_investigation(
    case_id: str,
    body: InvestigationStatusUpdate,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Report the investigation status; Domain maps it to the case status."""
    case = proposals.update_investigation(session, user, case_id, body, request_id(request))
    session.commit()
    return case_summary(case, session.get(Store, case.store_id))
