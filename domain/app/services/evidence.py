"""Evidence records (contracts.md `Evidence`): one claim, cancellation or operational event."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cancellation, MIClaim, OperationalEvent, Order
from app.schemas import Evidence


def _money(value) -> float:
    return float(value)


def claim_evidence(c: MIClaim, order: Order) -> Evidence:
    modifier = f" ({c.modifier_detail})" if c.modifier_detail else ""
    return Evidence(
        evidence_id=c.evidence_id,
        type="claim",
        store_id=c.store_id,
        occurred_at=c.reported_at,
        summary=(
            f"{c.error_category.value} on {c.item_name}{modifier}, ${c.error_charge}, "
            f"{c.review_label.value}, order {c.order_id}"
        ),
        attributes={
            "order_id": c.order_id,
            "item_id": c.item_id,
            "item_name": c.item_name,
            "error_category": c.error_category.value,
            "modifier_detail": c.modifier_detail,
            "customer_comments": c.customer_comments,  # untrusted customer text
            "error_charge": _money(c.error_charge),
            "reported_at": c.reported_at,
            "review_label": c.review_label.value,
            "reviewed_at": c.reviewed_at,
            "daypart": order.daypart.value,
            "item_count": order.item_count,
            "customer_ref": order.customer_ref,
        },
    )


def cancellation_evidence(x: Cancellation, order: Order) -> Evidence:
    item = f", item {x.item_id}" if x.item_id else ""
    return Evidence(
        evidence_id=x.evidence_id,
        type="cancellation",
        store_id=x.store_id,
        occurred_at=x.canceled_at,
        summary=f"{x.cancellation_category.value} cancellation{item}, order {x.order_id}",
        attributes={
            "order_id": x.order_id,
            "item_id": x.item_id,
            "cancellation_category": x.cancellation_category.value,
            "canceled_at": x.canceled_at,
            "daypart": order.daypart.value,
        },
    )


def event_evidence(e: OperationalEvent) -> Evidence:
    return Evidence(
        evidence_id=e.evidence_id,
        type="operational_event",
        store_id=e.store_id,
        occurred_at=e.started_at,
        summary=f"{e.event_type.value}: {e.description}",
        attributes={
            "event_type": e.event_type.value,
            "started_at": e.started_at,
            "ended_at": e.ended_at,
            "description": e.description,
        },
    )


def load_evidence(session: Session, evidence_ids: list[str]) -> dict[str, Evidence]:
    """Look up evidence by ID, in any store. Unknown IDs are left out of the result."""
    by_prefix: dict[str, list[str]] = {}
    for eid in set(evidence_ids):
        by_prefix.setdefault(eid[:7], []).append(eid)
    found: dict[str, Evidence] = {}
    if ids := by_prefix.get("EV-CLM-"):
        for c, o in session.execute(
            select(MIClaim, Order).join(Order, Order.order_id == MIClaim.order_id).where(MIClaim.evidence_id.in_(ids))
        ):
            found[c.evidence_id] = claim_evidence(c, o)
    if ids := by_prefix.get("EV-CXL-"):
        for x, o in session.execute(
            select(Cancellation, Order)
            .join(Order, Order.order_id == Cancellation.order_id)
            .where(Cancellation.evidence_id.in_(ids))
        ):
            found[x.evidence_id] = cancellation_evidence(x, o)
    if ids := by_prefix.get("EV-EVT-"):
        for e in session.scalars(select(OperationalEvent).where(OperationalEvent.evidence_id.in_(ids))):
            found[e.evidence_id] = event_evidence(e)
    # EV-RPL- (merchant replies) arrive with C-04.
    return found
