"""Run a planned recheck (C-05): did the approved action fix the targeted problem?

C-03 scheduled the recheck when the action was approved and saved `before`: the target's rate over the
last `recheck_after_days` days of the case window. Running it (POST /rechecks/{id}/run, the manual demo
trigger) adds:

- `after`: the same target over a window of the same length AFTER the last day of data. These days come
  from the seeded future snapshot (`future_*` tables), which nothing else reads. The first recheck of a
  case uses the first days after the data; a second recheck (after a reopen) uses the days after that.
- `control`: the store's orders OUTSIDE the target in the after window, the unaffected comparison.
  The control's before rate goes into the audit row. No control when the target is the whole store.
- `data_sufficient`: both windows have at least MIN_GROUP_ORDERS target orders.

Outcome (contracts.md Status model):

    data not sufficient                                  insufficient_data -> case paused
    after <= before * (1 - RECHECK_MIN_DROP), and the     improved          -> case closed
      target fell by more than the control did
    otherwise, case not reopened yet                     not_improved      -> case reopened (reopen_count 1)
    otherwise                                            not_improved      -> case analyst_review

A recheck runs once: running it again gets 409 RECHECK_ALREADY_RUN. A repeat of the same request (same
Idempotency-Key) returns the first result.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.errors import ApiError
from domain.app.models import (
    Case,
    CaseStatus,
    FutureClaim,
    FutureOrder,
    FutureOrderItem,
    Recheck,
    RecheckStatus,
    Store,
)
from domain.app.schemas import ClaimScope, RateWindow, Target
from domain.app.schemas import Recheck as RecheckOut
from domain.app.security import CurrentUser
from domain.app.services.audit import write_audit
from domain.app.services.diagnostics import claim_in_scope, order_in_scope
from domain.app.services.proposals import recheck_out
from domain.app.services.store_data import (
    ClaimRow,
    OrderRow,
    StoreContext,
    WindowData,
    load_context,
    load_window,
    utc_bounds,
)
from domain.app.settings import settings


def _scope(target: Target) -> ClaimScope:
    return ClaimScope(item_id=target.item_id or None, modifiers=target.modifiers or None,
                      daypart=target.daypart or None, item_count_min=target.item_count_min)


def _whole_store(target: Target) -> bool:
    return not (target.item_id or target.modifiers or target.daypart or target.item_count_min)


def _rate(start: date, end: date, orders: int, claims: int) -> RateWindow:
    rate = round(claims / orders, 4) if orders >= settings.min_group_orders else None
    return RateWindow(start=start, end=end, claims=claims, eligible_orders=orders, rate=rate)


def target_and_control(data: WindowData, target: Target) -> tuple[RateWindow, RateWindow | None]:
    """Rate of the target's orders, and of every other order in the same window (None for the whole store)."""
    scope = _scope(target)
    delivered = data.delivered
    inside = sum(1 for o in delivered if order_in_scope(o, scope))
    inside_claims = sum(1 for c in data.claims if claim_in_scope(c, scope))
    t = _rate(data.start, data.end, inside, inside_claims)
    if _whole_store(target):
        return t, None
    outside = len(delivered) - inside
    outside_claims = sum(1 for c in data.claims if c.attributable and not order_in_scope(c.order, scope))
    return t, _rate(data.start, data.end, outside, outside_claims)


def load_future_window(session: Session, ctx: StoreContext, start: date, end: date) -> WindowData:
    """The future snapshot for one store, shaped like load_window's result so the same filters apply."""
    store_id = ctx.store.store_id
    lo, hi = utc_bounds(ctx.tz, start, end)
    in_window = (FutureOrder.store_id == store_id, FutureOrder.placed_at >= lo, FutureOrder.placed_at < hi)
    lines: dict[str, list] = {}
    for order_id, item_id, modifiers in session.execute(
        select(FutureOrderItem.order_id, FutureOrderItem.item_id, FutureOrderItem.modifiers)
        .join(FutureOrder, FutureOrder.order_id == FutureOrderItem.order_id).where(*in_window)
    ):
        lines.setdefault(order_id, []).append((item_id, modifiers or []))
    orders = {}
    for o in session.scalars(select(FutureOrder).where(*in_window)):
        local = o.placed_at.astimezone(ctx.tz)
        mine = lines.get(o.order_id, [])
        orders[o.order_id] = OrderRow(
            order_id=o.order_id, local_date=local.date(), weekday=local.weekday(), daypart=o.daypart.value,
            item_count=o.item_count, delivered=True, customer_ref="",
            item_ids=frozenset(i for i, _ in mine), modifiers=frozenset(m for _, mods in mine for m in mods),
        )
    claims = [
        ClaimRow(evidence_id=c.claim_id, order=orders[c.order_id], item_id=c.item_id, item_name="",
                 error_category=c.error_category.value, modifier_detail=c.modifier_detail, customer_comments=None,
                 error_charge=0, reported_at=None, review_label=c.review_label.value, reviewed_at=None)
        for c in session.scalars(
            select(FutureClaim).join(FutureOrder, FutureOrder.order_id == FutureClaim.order_id).where(*in_window)
        )
    ]
    return WindowData(start, end, list(orders.values()), claims, [])


def _after_start(session: Session, ctx: StoreContext, case_id: str) -> date:
    """The day after the data ends, or after the last window an earlier recheck of this case used."""
    start = ctx.last_date + timedelta(days=1)
    for after in session.scalars(
        select(Recheck.after).where(Recheck.case_id == case_id, Recheck.status != RecheckStatus.SCHEDULED)
    ):
        if after:
            start = max(start, date.fromisoformat(after["end"]) + timedelta(days=1))
    return start


def _drop(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return (before - after) / before if before > 0 else 0.0


def judge(before: RateWindow, after: RateWindow, control_before: RateWindow | None,
          control_after: RateWindow | None) -> RecheckStatus:
    if before.rate is None or after.rate is None:
        return RecheckStatus.INSUFFICIENT_DATA
    target_drop = _drop(before.rate, after.rate)
    enough = before.rate > 0 and target_drop >= float(settings.recheck_min_drop)
    control_drop = _drop(control_before.rate, control_after.rate) if control_before and control_after else None
    if enough and (control_drop is None or target_drop > control_drop):
        return RecheckStatus.IMPROVED
    return RecheckStatus.NOT_IMPROVED


def visible_recheck(session: Session, user: CurrentUser, recheck_id: str, lock: bool = False) -> tuple[Recheck, Case]:
    q = select(Recheck).where(Recheck.recheck_id == recheck_id)
    r = session.scalar(q.with_for_update() if lock else q)
    case = session.get(Case, r.case_id, with_for_update=lock) if r else None
    if r is None or not user.can_see(case.store_id):
        raise ApiError(404, "NOT_FOUND", f"Recheck {recheck_id} was not found.")
    return r, case


def run_recheck(session: Session, user: CurrentUser, r: Recheck, case: Case, rid: str) -> RecheckOut:
    """`r` and `case` must be locked (visible_recheck with lock=True). The caller commits."""
    if r.status != RecheckStatus.SCHEDULED:
        raise ApiError(409, "RECHECK_ALREADY_RUN", f"Recheck {r.recheck_id} already ran: {r.status.value}.",
                       {"status": r.status.value})
    ctx = load_context(session, session.get(Store, case.store_id))
    target = Target.model_validate(r.target)
    before = RateWindow.model_validate(r.before)
    days = (before.end - before.start).days + 1

    start = _after_start(session, ctx, case.case_id)
    after, control_after = target_and_control(load_future_window(session, ctx, start, start + timedelta(days=days - 1)), target)
    _, control_before = target_and_control(load_window(session, ctx, before.start, before.end), target)
    status = judge(before, after, control_before, control_after)

    now = datetime.now(timezone.utc)
    r.status, r.ran_at = status, now
    r.after = after.model_dump(mode="json")
    r.control = control_after.model_dump(mode="json") if control_after else None
    r.data_sufficient = status != RecheckStatus.INSUFFICIENT_DATA

    if status == RecheckStatus.IMPROVED:
        case.status = CaseStatus.CLOSED
    elif status == RecheckStatus.INSUFFICIENT_DATA:
        case.status = CaseStatus.PAUSED
    elif case.reopen_count == 0:
        case.status, case.reopen_count = CaseStatus.REOPENED, 1  # one more investigation is allowed
    else:
        case.status = CaseStatus.ANALYST_REVIEW  # second failure: no third investigation
    case.updated_at = now

    write_audit(session, case_id=case.case_id, action=f"recheck.{status.value}", request_id=rid, user=user,
                proposal_id=r.proposal_id, details={
                    "recheck_id": r.recheck_id, "case_status": case.status.value,
                    "before": r.before, "after": r.after, "control": r.control,
                    "control_before": control_before.model_dump(mode="json") if control_before else None,
                })
    session.flush()
    return recheck_out(r)
