"""Case list and detail (contracts.md CaseSummary / CaseDetail)."""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.errors import ApiError
from domain.app.models import Case, CaseStatus, Store
from domain.app.schemas import CaseDetail, CaseSummary, DailyRate, StoreSummary
from domain.app.security import CurrentUser
from domain.app.services.store_data import INVESTIGATION_DAYS, load_context, load_window
from domain.app.services.proposals import case_proposals, case_rechecks
from domain.app.settings import settings


def store_summary(store: Store) -> StoreSummary:
    return StoreSummary(
        store_id=store.store_id, name=store.name, city=store.city, timezone=store.timezone, cuisine=store.cuisine
    )


def case_summary(case: Case, store: Store) -> CaseSummary:
    return CaseSummary(
        case_id=case.case_id,
        store_id=case.store_id,
        store_name=store.name,
        status=case.status,
        trigger_rule=case.trigger_rule,
        window_start=case.window_start,
        window_end=case.window_end,
        mi_rate=float(case.mi_rate),
        baseline_rate=float(case.baseline_rate) if case.baseline_rate is not None else None,
        eligible_orders=case.eligible_orders,
        attributable_claims=case.attributable_claims,
        goal_rate=float(case.goal_rate),
        opened_at=case.opened_at,
        updated_at=case.updated_at,
        active_investigation_id=case.active_investigation_id,
        reopen_count=case.reopen_count,  # C-05
        last_error=case.last_error,
    )


def list_cases(
    session: Session, user: CurrentUser, status: CaseStatus | None, store_id: str | None
) -> list[CaseSummary]:
    q = select(Case, Store).join(Store, Store.store_id == Case.store_id).where(Case.store_id.in_(user.store_ids))
    if status:
        q = q.where(Case.status == status)
    if store_id:
        q = q.where(Case.store_id == store_id)  # a store outside the grants simply returns nothing
    rows = session.execute(q.order_by(Case.opened_at.desc(), Case.case_id.desc()).limit(200)).all()
    return [case_summary(c, s) for c, s in rows]


def get_case(session: Session, user: CurrentUser, case_id: str) -> CaseDetail:
    case = session.get(Case, case_id)
    if case is None or not user.can_see(case.store_id):
        # 404 for other stores too, so case IDs can't be probed (contracts.md Errors).
        raise ApiError(404, "CASE_NOT_FOUND", f"Case {case_id} was not found.")
    store = session.get(Store, case.store_id)
    ctx = load_context(session, store)
    end = case.window_end.astimezone(ctx.tz).date()
    if ctx.last_date and end > ctx.last_date:
        end = ctx.last_date
    start = max(ctx.first_date, end - timedelta(days=INVESTIGATION_DAYS - 1)) if ctx.first_date else end
    daily: list[DailyRate] = []
    if ctx.first_date:
        data = load_window(session, ctx, start, end)
        orders, claims = defaultdict(int), defaultdict(int)
        for o in data.delivered:
            orders[o.local_date] += 1
        for c in data.claims:
            if c.attributable:
                claims[c.order.local_date] += 1
        day = start
        while day <= end:
            n = orders[day]
            rate = round(claims[day] / n, 4) if n >= settings.min_group_orders else None
            daily.append(DailyRate(date=day, rate=rate, claims=claims[day], eligible_orders=n))
            day += timedelta(days=1)
    return CaseDetail(
        **case_summary(case, store).model_dump(),
        store=store_summary(store),
        daily_rates=daily,
        investigation_ids=list(reversed(case.investigation_ids)),  # newest first
        proposals=case_proposals(session, case.case_id),
        rechecks=case_rechecks(session, case.case_id),
    )
