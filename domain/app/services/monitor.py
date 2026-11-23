"""Fixed-rule store monitor (C-02). Not an agent: the same data always gives the same cases.

For each store, with `as_of` as the last day:
- 7-day window: as_of-6 .. as_of. Baseline: the 28 days before the window.
- rate = store-attributable claims / delivered orders (contracts.md rate rules).
- Skip when the store already has a case that is not closed (one open case per store),
  when a closed case already covers part of this 7-day window (`already_reviewed`: the data is
  static, so rerunning the monitor after a case is closed would otherwise reopen the same spike),
  or when the window has fewer than MONITOR_MIN_ORDERS delivered orders.
- Open a case when
    over_goal:          rate > MONITOR_GOAL_RATE, or
    spike_vs_baseline:  rate >= MONITOR_SPIKE_RATIO x baseline AND rate - baseline >= MONITOR_MIN_RISE.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from domain.app.errors import ApiError
from domain.app.models import Case, CaseStatus, Store
from domain.app.schemas import MonitorRunResponse, SkippedStore
from domain.app.security import CurrentUser
from domain.app.services.audit import SVC_MONITOR, write_audit
from domain.app.services.store_data import load_context, load_window
from domain.app.settings import settings

WINDOW_DAYS = 7
BASELINE_DAYS = 28
MONITOR_LOCK_ID = 802402  # pg advisory lock: one monitor run at a time


@dataclass
class StoreCheck:
    store_id: str
    window_start: date
    window_end: date
    eligible: int
    claims: int
    rate: Decimal | None
    baseline_eligible: int
    baseline_rate: Decimal | None


def _rate(num: int, den: int) -> Decimal | None:
    if den == 0:
        return None
    return (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def check_store(session: Session, store: Store, as_of: date) -> StoreCheck | None:
    ctx = load_context(session, store)
    if ctx.first_date is None:
        return None
    w_start = as_of - timedelta(days=WINDOW_DAYS - 1)
    b_start = max(ctx.first_date, w_start - timedelta(days=BASELINE_DAYS))
    data = load_window(session, ctx, min(b_start, w_start), as_of)
    in_window = lambda d: d >= w_start  # noqa: E731
    eligible = sum(1 for o in data.delivered if in_window(o.local_date))
    claims = sum(1 for c in data.claims if c.attributable and in_window(c.order.local_date))
    b_eligible = sum(1 for o in data.delivered if not in_window(o.local_date))
    b_claims = sum(1 for c in data.claims if c.attributable and not in_window(c.order.local_date))
    baseline = _rate(b_claims, b_eligible) if b_eligible >= settings.min_group_orders else None
    return StoreCheck(store.store_id, w_start, as_of, eligible, claims, _rate(claims, eligible), b_eligible, baseline)


def trigger_rule(check: StoreCheck) -> str | None:
    if check.rate is None:
        return None
    if check.rate > settings.monitor_goal_rate:
        return "over_goal"
    if (
        check.baseline_rate is not None
        and check.rate >= settings.monitor_spike_ratio * check.baseline_rate
        and check.rate - check.baseline_rate >= settings.monitor_min_rise
    ):
        return "spike_vs_baseline"
    return None


def next_case_id(session: Session) -> str:
    last = session.scalar(select(func.max(Case.case_id)))
    n = int(last.split("-")[1]) + 1 if last else 1
    return f"CASE-{n:04d}"


def run_monitor(session: Session, user: CurrentUser, as_of: date | None, rid: str = "") -> MonitorRunResponse:
    """Evaluate the stores in the user's grants and open cases. The caller commits."""
    session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MONITOR_LOCK_ID})
    stores = session.scalars(
        select(Store).where(Store.store_id.in_(user.store_ids), Store.is_active.is_(True)).order_by(Store.store_id)
    ).all()
    if not stores:
        return MonitorRunResponse(run_id=_run_id(), as_of=as_of or date.today(), evaluated_store_ids=[],
                                  opened_case_ids=[], skipped=[])
    contexts = [load_context(session, s) for s in stores]
    firsts = [c.first_date for c in contexts if c.first_date]
    lasts = [c.last_date for c in contexts if c.last_date]
    if not lasts:
        raise ApiError(422, "VALIDATION_ERROR", "There is no order data to monitor.")
    as_of = as_of or max(lasts)
    if as_of < min(firsts) or as_of > max(lasts):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"as_of must be within the order data, {min(firsts)} to {max(lasts)}.",
            {"data_start": str(min(firsts)), "data_end": str(max(lasts))},
        )

    open_stores = set(session.scalars(select(Case.store_id).where(Case.status != CaseStatus.CLOSED)))
    # The latest window end of each store's closed cases: a new window that starts on or before it
    # would look at days an analyst already reviewed.
    reviewed_until = dict(session.execute(
        select(Case.store_id, func.max(Case.window_end)).where(Case.status == CaseStatus.CLOSED)
        .group_by(Case.store_id)
    ).all())
    evaluated, opened, skipped = [], [], []
    now = datetime.now(timezone.utc)
    for store, ctx in zip(stores, contexts):
        evaluated.append(store.store_id)
        if store.store_id in open_stores:
            skipped.append(SkippedStore(store_id=store.store_id, reason="open_case_exists"))
            continue
        window_start = datetime.combine(as_of - timedelta(days=WINDOW_DAYS - 1), time.min, ctx.tz)
        if store.store_id in reviewed_until and reviewed_until[store.store_id] >= window_start:
            skipped.append(SkippedStore(store_id=store.store_id, reason="already_reviewed"))
            continue
        check = check_store(session, store, as_of)
        if check is None or check.eligible < settings.monitor_min_orders:
            skipped.append(SkippedStore(store_id=store.store_id, reason="low_volume"))
            continue
        rule = trigger_rule(check)
        if rule is None:
            skipped.append(SkippedStore(store_id=store.store_id, reason="below_threshold"))
            continue
        case = Case(
            case_id=next_case_id(session),
            store_id=store.store_id,
            status=CaseStatus.OPEN,
            trigger_rule=rule,
            window_start=datetime.combine(check.window_start, time.min, ctx.tz),
            window_end=datetime.combine(check.window_end, time(23, 59, 59), ctx.tz),
            mi_rate=check.rate,
            baseline_rate=check.baseline_rate,
            eligible_orders=check.eligible,
            attributable_claims=check.claims,
            goal_rate=settings.monitor_goal_rate,
            opened_at=now,
            updated_at=now,
        )
        session.add(case)
        session.flush()  # so next_case_id sees it
        write_audit(session, case_id=case.case_id, action="case.opened", request_id=rid, service=SVC_MONITOR,
                    user=user, details={"trigger_rule": rule, "as_of": str(as_of)})
        opened.append(case.case_id)
    return MonitorRunResponse(
        run_id=_run_id(), as_of=as_of, evaluated_store_ids=evaluated, opened_case_ids=opened, skipped=skipped
    )


def _run_id() -> str:
    # Not in the contracts ID table yet; proposed format MON-<12 hex>.
    return f"MON-{uuid.uuid4().hex[:12].upper()}"
