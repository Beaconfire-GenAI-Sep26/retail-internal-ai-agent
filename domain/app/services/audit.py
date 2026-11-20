"""Append-only audit log (C-03). Every write to a case adds one row here, in the same transaction."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.models import AUDIT_SEQ, AuditEntry
from domain.app.schemas import AuditEntryOut
from domain.app.security import CurrentUser

SVC_AGENT = "svc_agent"
SVC_MONITOR = "svc_monitor"


def write_audit(
    session: Session,
    *,
    case_id: str,
    action: str,
    request_id: str,
    user: CurrentUser | None = None,
    service: str | None = None,
    proposal_id: str | None = None,
    version: int | None = None,
    details: dict | None = None,
) -> AuditEntry:
    """Record one action. Pass `user` for an analyst action, or `service` for svc_agent / svc_monitor.

    For a service action on behalf of a user, the user goes into details.on_behalf_of.
    """
    details = dict(details or {})
    if service:
        actor_id, actor_role = service, "service"
        if user:
            details["on_behalf_of"] = user.user_id
    else:
        actor_id, actor_role = user.user_id, user.role
    entry = AuditEntry(
        audit_id=f"AUD-{session.scalar(AUDIT_SEQ.next_value()):06d}",
        case_id=case_id,
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        proposal_id=proposal_id,
        version=version,
        request_id=request_id,
        at=datetime.now(timezone.utc),
        details=details,
    )
    session.add(entry)
    return entry


def list_audit(session: Session, case_id: str) -> list[AuditEntryOut]:
    rows = session.scalars(
        select(AuditEntry).where(AuditEntry.case_id == case_id).order_by(AuditEntry.at, AuditEntry.audit_id)
    ).all()
    return [
        AuditEntryOut(
            audit_id=r.audit_id, case_id=r.case_id, actor_id=r.actor_id, actor_role=r.actor_role, action=r.action,
            proposal_id=r.proposal_id, version=r.version, request_id=r.request_id, at=r.at,
        )
        for r in rows
    ]
