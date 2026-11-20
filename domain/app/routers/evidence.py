from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.errors import ApiError
from domain.app.schemas import Evidence, EvidenceResolveRequest, EvidenceResolveResponse, InvalidEvidence
from domain.app.security import CurrentUser, check_store, current_user
from domain.app.services.evidence import load_evidence

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{evidence_id}", response_model=Evidence)
def get_evidence(evidence_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    found = load_evidence(session, [evidence_id]).get(evidence_id)
    if found is None or not user.can_see(found.store_id):
        raise ApiError(404, "NOT_FOUND", f"Evidence {evidence_id} was not found.")
    return found


@router.post("/resolve", response_model=EvidenceResolveResponse)
def resolve(
    body: EvidenceResolveRequest, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)
):
    """Checks that cited evidence IDs exist and belong to the store (used before saving a proposal)."""
    check_store(user, body.store_id)
    found = load_evidence(session, body.evidence_ids)
    valid, invalid = [], []
    for eid in dict.fromkeys(body.evidence_ids):  # keep order, drop repeats
        ev = found.get(eid)
        if ev is None:
            invalid.append(InvalidEvidence(evidence_id=eid, reason="not_found"))
        elif ev.store_id != body.store_id:
            invalid.append(InvalidEvidence(evidence_id=eid, reason="other_store"))
        else:
            valid.append(eid)
    return EvidenceResolveResponse(valid=valid, invalid=invalid)
