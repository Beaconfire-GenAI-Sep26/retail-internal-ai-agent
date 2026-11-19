"""Load one store's rows for a date window into plain Python objects.

Every diagnostic and the monitor read the data through here, so the same rules apply everywhere:

- Dates are the store's local dates (stores.timezone). An order belongs to the day it was placed.
- A claim or cancellation belongs to the window of its order, so a claim is never counted
  against a day whose orders do not include it (numerator and denominator always match).
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import (
    Cancellation,
    MenuItem,
    MIClaim,
    Order,
    OrderItem,
    OrderStatus,
    Store,
)
from app.security import CurrentUser, check_store

ATTRIBUTABLE = ("store_fault", "pending")
INVESTIGATION_DAYS = 42


@dataclass
class StoreContext:
    """A store the user may see, with its data range and menu (for validating filters)."""

    store: Store
    tz: ZoneInfo
    first_date: date | None  # first local date with orders
    last_date: date | None  # last local date with orders
    item_names: dict[str, str]  # item_id -> name
    modifiers: set[str]  # every modifier on the store's menu

    def default_window(self) -> tuple[date, date]:
        end = self.require_data()[1]
        return max(self.first_date, end - timedelta(days=INVESTIGATION_DAYS - 1)), end

    def require_data(self) -> tuple[date, date]:
        if self.first_date is None:
            raise ApiError(422, "VALIDATION_ERROR", f"Store {self.store.store_id} has no order data.")
        return self.first_date, self.last_date

    def check_window(self, start: date, end: date) -> None:
        first, last = self.require_data()
        if start > end:
            raise ApiError(422, "VALIDATION_ERROR", "start must be on or before end.")
        if start < first or end > last:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                f"Dates must be within the store's data, {first} to {last}.",
                {"data_start": str(first), "data_end": str(last)},
            )

    def check_items(self, item_ids: list[str] | None) -> None:
        unknown = sorted(set(item_ids or []) - set(self.item_names))
        if unknown:
            raise ApiError(
                422, "VALIDATION_ERROR", "Unknown item_id for this store.", {"unknown_item_ids": unknown}
            )

    def check_modifiers(self, modifiers: list[str] | None) -> None:
        unknown = sorted(set(modifiers or []) - self.modifiers)
        if unknown:
            raise ApiError(
                422, "VALIDATION_ERROR", "Unknown modifier for this store.", {"unknown_modifiers": unknown}
            )


def store_context(session: Session, user: CurrentUser, store_id: str) -> StoreContext:
    check_store(user, store_id)  # 403 STORE_NOT_PERMITTED
    store = session.get(Store, store_id)
    if store is None:
        raise ApiError(404, "NOT_FOUND", f"Store {store_id} was not found.")
    return load_context(session, store)


def load_context(session: Session, store: Store) -> StoreContext:
    tz = ZoneInfo(store.timezone)
    first, last = session.execute(
        select(func.min(Order.placed_at), func.max(Order.placed_at)).where(Order.store_id == store.store_id)
    ).one()
    items = session.scalars(select(MenuItem).where(MenuItem.store_id == store.store_id)).all()
    return StoreContext(
        store=store,
        tz=tz,
        first_date=first.astimezone(tz).date() if first else None,
        last_date=last.astimezone(tz).date() if last else None,
        item_names={i.item_id: i.name for i in items},
        modifiers={m for i in items for m in (i.available_modifiers or [])},
    )


def utc_bounds(tz: ZoneInfo, start: date, end: date) -> tuple[datetime, datetime]:
    """UTC instants for local midnight of `start` and local midnight after `end` (exclusive)."""
    return (
        datetime.combine(start, time.min, tz),
        datetime.combine(end + timedelta(days=1), time.min, tz),
    )


@dataclass
class OrderRow:
    order_id: str
    local_date: date
    weekday: int  # 0 = Monday
    daypart: str
    item_count: int
    delivered: bool
    customer_ref: str
    item_ids: frozenset[str]
    modifiers: frozenset[str]


@dataclass
class ClaimRow:
    evidence_id: str
    order: OrderRow
    item_id: str | None
    item_name: str
    error_category: str
    modifier_detail: str | None
    customer_comments: str | None
    error_charge: Decimal
    reported_at: datetime
    review_label: str
    reviewed_at: datetime | None

    @property
    def attributable(self) -> bool:
        return self.review_label in ATTRIBUTABLE


@dataclass
class CancellationRow:
    evidence_id: str
    order: OrderRow
    item_id: str | None
    cancellation_category: str
    canceled_at: datetime


@dataclass
class WindowData:
    start: date
    end: date
    orders: list[OrderRow]  # delivered and canceled
    claims: list[ClaimRow]  # every review_label
    cancellations: list[CancellationRow]

    @property
    def delivered(self) -> list[OrderRow]:
        return [o for o in self.orders if o.delivered]


def load_window(session: Session, ctx: StoreContext, start: date, end: date) -> WindowData:
    store_id = ctx.store.store_id
    lo, hi = utc_bounds(ctx.tz, start, end)
    in_window = (Order.store_id == store_id, Order.placed_at >= lo, Order.placed_at < hi)

    items: dict[str, list[tuple[str, list]]] = {}
    for order_id, item_id, modifiers in session.execute(
        select(OrderItem.order_id, OrderItem.item_id, OrderItem.modifiers)
        .join(Order, Order.order_id == OrderItem.order_id)
        .where(*in_window)
    ):
        items.setdefault(order_id, []).append((item_id, modifiers or []))

    orders: dict[str, OrderRow] = {}
    for o in session.scalars(select(Order).where(*in_window).order_by(Order.placed_at, Order.order_id)):
        local = o.placed_at.astimezone(ctx.tz)
        lines = items.get(o.order_id, [])
        orders[o.order_id] = OrderRow(
            order_id=o.order_id,
            local_date=local.date(),
            weekday=local.weekday(),
            daypart=o.daypart.value,
            item_count=o.item_count,
            delivered=o.status == OrderStatus.DELIVERED,
            customer_ref=o.customer_ref,
            item_ids=frozenset(i for i, _ in lines),
            modifiers=frozenset(m for _, mods in lines for m in mods),
        )

    claims = [
        ClaimRow(
            evidence_id=c.evidence_id,
            order=orders[c.order_id],
            item_id=c.item_id,
            item_name=c.item_name,
            error_category=c.error_category.value,
            modifier_detail=c.modifier_detail,
            customer_comments=c.customer_comments,
            error_charge=c.error_charge,
            reported_at=c.reported_at,
            review_label=c.review_label.value,
            reviewed_at=c.reviewed_at,
        )
        for c in session.scalars(
            select(MIClaim).join(Order, Order.order_id == MIClaim.order_id).where(*in_window)
        )
        if orders[c.order_id].delivered  # a canceled order can't have an M&I claim
    ]
    cancellations = [
        CancellationRow(
            evidence_id=x.evidence_id,
            order=orders[x.order_id],
            item_id=x.item_id,
            cancellation_category=x.cancellation_category.value,
            canceled_at=x.canceled_at,
        )
        for x in session.scalars(
            select(Cancellation).join(Order, Order.order_id == Cancellation.order_id).where(*in_window)
        )
    ]
    return WindowData(start, end, list(orders.values()), claims, cancellations)
