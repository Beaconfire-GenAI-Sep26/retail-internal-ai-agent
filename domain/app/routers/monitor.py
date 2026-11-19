from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_session
from app.errors import ApiError
from app.models import IdempotencyRecord
from app.schemas import MonitorRunRequest, MonitorRunResponse
from app.security import CurrentUser, require_analyst
from app.services.monitor import MONITOR_LOCK_ID, run_monitor

router = APIRouter(tags=["monitor"])
ROUTE = "POST /monitor/run"


@router.post("/monitor/run", response_model=MonitorRunResponse)
def monitor_run(
    body: MonitorRunRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(require_analyst),
    session: Session = Depends(get_session),
):
    """Manual demo trigger for the fixed-rule monitor. Analyst only.

    Requires an Idempotency-Key header (a UUID per click). A repeat with the same key returns
    the first result and opens nothing. A new key never opens a second case for a store that
    already has one that is not closed.
    """
    if not idempotency_key or len(idempotency_key) > 64:
        raise ApiError(422, "VALIDATION_ERROR", "An Idempotency-Key header of 1 to 64 characters is required.")
    session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MONITOR_LOCK_ID})
    stored = session.get(IdempotencyRecord, {"key": idempotency_key, "route": ROUTE})
    if stored is not None:
        session.rollback()
        return MonitorRunResponse.model_validate(stored.response)

    response = run_monitor(session, user, body.as_of if body else None)
    session.add(
        IdempotencyRecord(
            key=idempotency_key,
            route=ROUTE,
            status_code=200,
            response=response.model_dump(mode="json"),
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    return response
