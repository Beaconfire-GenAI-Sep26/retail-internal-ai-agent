from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.errors import ApiError, request_id
from domain.app.models import IdempotencyRecord
from domain.app.schemas import Recheck
from domain.app.security import CurrentUser, require_analyst
from domain.app.services import rechecks

router = APIRouter(prefix="/rechecks", tags=["rechecks"])


@router.post("/{recheck_id}/run", response_model=Recheck)
def run_recheck(
    recheck_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(require_analyst),
    session: Session = Depends(get_session),
):
    """Run a planned recheck now (C-05, the manual demo trigger). Analyst only.

    Compares the target's rate before the action with the same-length window after the data ends
    (seeded future snapshot), plus the store's other orders as a control. Then: improved -> case closed;
    insufficient_data -> paused; not_improved -> reopened the first time, analyst_review the second.
    A recheck runs once (409 RECHECK_ALREADY_RUN). Requires an Idempotency-Key header; a repeat
    returns the first result.
    """
    if not idempotency_key or len(idempotency_key) > 64:
        raise ApiError(422, "VALIDATION_ERROR", "An Idempotency-Key header of 1 to 64 characters is required.")
    route = f"POST /rechecks/{recheck_id}/run"
    r, case = rechecks.visible_recheck(session, user, recheck_id, lock=True)
    stored = session.get(IdempotencyRecord, {"key": idempotency_key, "route": route})
    if stored is not None:
        session.rollback()
        return Recheck.model_validate(stored.response)
    out = rechecks.run_recheck(session, user, r, case, request_id(request))
    session.add(IdempotencyRecord(key=idempotency_key, route=route, status_code=200,
                                  response=out.model_dump(mode="json"), created_at=datetime.now(timezone.utc)))
    session.commit()
    return out
