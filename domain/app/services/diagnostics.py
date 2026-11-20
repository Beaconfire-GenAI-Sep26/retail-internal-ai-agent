"""Read-only diagnostic tools. Each returns a contracts.md `ToolResult`.

Rate rules (contracts.md "Rate rules"):
- Eligible orders are delivered orders. Store-attributable claims are store_fault + pending.
- A group with fewer than MIN_GROUP_ORDERS eligible orders gets value null (insufficient data).
- Claims with a null item_id fall into the group item_id=unknown.
- Claims with a null modifier_detail are not in any modifier group; a note says how many.

Evidence ID order (agent-graph.md): groups with enough orders first, then the group statistic
(highest first), then newest first, then evidence_id ascending. Lists stop at 200 IDs.
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.models import ErrorCategory, EventType, OperationalEvent, ReviewLabel
from domain.app.schemas import (
    CancellationBreakdownRequest,
    CancellationFilter,
    ClaimBreakdownRequest,
    ClaimScope,
    ComparePeriodsRequest,
    EvidenceSampleRequest,
    Metric,
    ToolResult,
    Window,
)
from domain.app.services.evidence import event_evidence, load_evidence
from domain.app.services.store_data import (
    ATTRIBUTABLE,
    CancellationRow,
    ClaimRow,
    OrderRow,
    StoreContext,
    load_window,
    utc_bounds,
)
from domain.app.settings import settings

MAX_IDS = 200
UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def ratio(num: int, den: int, min_den: int = 1) -> float | None:
    if den <= 0 or den < min_den:
        return None
    return round(num / den, 4)


def rate_metric(name: str, group: str | None, num: int, den: int) -> Metric:
    value = ratio(num, den, settings.min_group_orders)
    return Metric(name=name, group=group, value=value, numerator=num, denominator=den, unit="rate")


def share_metric(name: str, group: str | None, num: int, den: int) -> Metric:
    return Metric(name=name, group=group, value=ratio(num, den), numerator=num, denominator=den, unit="share")


def count_metric(name: str, group: str | None, n: int) -> Metric:
    return Metric(name=name, group=group, value=n, numerator=None, denominator=None, unit="count")


def newest_first(rows: Iterable, ts: Callable) -> list:
    """Newest first, then evidence_id ascending."""
    rows = sorted(rows, key=lambda r: r.evidence_id)
    return sorted(rows, key=ts, reverse=True)  # stable, so ties keep evidence_id order


def capped(ids: list[str], notes: list[str]) -> list[str]:
    if len(ids) > MAX_IDS:
        notes.append(f"evidence_ids lists the first {MAX_IDS} of {len(ids)} records.")
    return ids[:MAX_IDS]


def bucket(item_count: int) -> str:
    return "1-2" if item_count <= 2 else "3-4" if item_count <= 4 else "5+"


def excluded_note(claims: list[ClaimRow], labels: set[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for c in claims:
        if c.review_label not in labels:
            counts[c.review_label] += 1
    if not counts:
        return []
    parts = ", ".join(f"{label} {n}" for label, n in sorted(counts.items()))
    return [f"{sum(counts.values())} claims excluded by review_label: {parts}."]


def result(ctx: StoreContext, tool: str, start: date, end: date, eligible: int, **kw) -> ToolResult:
    return ToolResult(
        tool=tool,
        store_id=ctx.store.store_id,
        window=Window(start=start, end=end),
        eligible_orders=eligible,
        pending_claims=kw.get("pending_claims", 0),
        data_sufficient=kw.get("data_sufficient", eligible >= settings.min_group_orders),
        headline=kw["headline"],
        metrics=kw.get("metrics", []),
        evidence_ids=kw.get("evidence_ids", []),
        evidence=kw.get("evidence", []),
        notes=kw.get("notes", []),
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def check_claim_scope(ctx: StoreContext, scope: ClaimScope) -> None:
    ctx.check_items(scope.item_id)
    ctx.check_modifiers(scope.modifiers)


def labels_of(scope: ClaimScope) -> set[str]:
    return {r.value for r in scope.review_label} if scope.review_label else set(ATTRIBUTABLE)


def order_in_scope(o: OrderRow, scope: ClaimScope | CancellationFilter) -> bool:
    """Order-level part of a filter: the denominator side."""
    if scope.item_id and not o.item_ids.intersection(scope.item_id):
        return False
    if getattr(scope, "modifiers", None) and not o.modifiers.intersection(scope.modifiers):
        return False
    if scope.daypart and o.daypart not in {d.value for d in scope.daypart}:
        return False
    if scope.weekday and o.weekday not in scope.weekday:
        return False
    if getattr(scope, "item_count_min", None) and o.item_count < scope.item_count_min:
        return False
    if getattr(scope, "item_count_max", None) and o.item_count > scope.item_count_max:
        return False
    return True


def claim_in_scope(c: ClaimRow, scope: ClaimScope) -> bool:
    """Claim-level part of a filter: the numerator side."""
    if scope.item_id and c.item_id not in scope.item_id:
        return False
    if scope.modifiers and c.modifier_detail not in scope.modifiers:
        return False
    if scope.daypart and c.order.daypart not in {d.value for d in scope.daypart}:
        return False
    if scope.weekday and c.order.weekday not in scope.weekday:
        return False
    if scope.item_count_min and c.order.item_count < scope.item_count_min:
        return False
    if scope.item_count_max and c.order.item_count > scope.item_count_max:
        return False
    if scope.error_category and c.error_category not in {e.value for e in scope.error_category}:
        return False
    return c.review_label in labels_of(scope)


def cancellation_in_scope(x: CancellationRow, f: CancellationFilter) -> bool:
    if f.item_id and x.item_id not in f.item_id:
        return False
    if f.daypart and x.order.daypart not in {d.value for d in f.daypart}:
        return False
    if f.weekday and x.order.weekday not in f.weekday:
        return False
    if f.cancellation_category and x.cancellation_category not in {c.value for c in f.cancellation_category}:
        return False
    return True


# ---------------------------------------------------------------------------
# store_overview
# ---------------------------------------------------------------------------
def store_overview(session: Session, ctx: StoreContext, start: date, end: date) -> ToolResult:
    ctx.check_window(start, end)
    data = load_window(session, ctx, start, end)
    delivered = data.delivered
    attributable = [c for c in data.claims if c.attributable]
    metrics = [rate_metric("claim_rate", None, len(attributable), len(delivered))]
    for label in ReviewLabel:
        n = sum(1 for c in data.claims if c.review_label == label.value)
        metrics.append(count_metric("claim_count", f"review_label={label.value}", n))
    for cat in ErrorCategory:
        n = sum(1 for c in attributable if c.error_category == cat.value)
        metrics.append(count_metric("claim_count", f"error_category={cat.value}", n))
    orders_by_day: dict[date, int] = defaultdict(int)
    claims_by_day: dict[date, int] = defaultdict(int)
    for o in delivered:
        orders_by_day[o.local_date] += 1
    for c in attributable:
        claims_by_day[c.order.local_date] += 1
    day = start
    while day <= end:
        metrics.append(rate_metric("daily_claim_rate", f"day={day}", claims_by_day[day], orders_by_day[day]))
        day += timedelta(days=1)

    notes = excluded_note(data.claims, set(ATTRIBUTABLE))
    ids = [c.evidence_id for c in newest_first(data.claims, lambda c: c.reported_at)]
    rate = metrics[0].value
    return result(
        ctx,
        "store_overview",
        start,
        end,
        len(delivered),
        pending_claims=sum(1 for c in attributable if c.review_label == "pending"),
        headline=(
            f"M&I rate {pct(rate)} ({len(attributable)} attributable claims / {len(delivered)} "
            f"delivered orders) from {start} to {end}."
        ),
        metrics=metrics,
        evidence_ids=capped(ids, notes),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# claim_breakdown
# ---------------------------------------------------------------------------
def _claim_groups(c: ClaimRow, group_by: str) -> list[str]:
    if group_by == "item_id":
        return [c.item_id or UNKNOWN]
    if group_by == "modifier":
        return [c.modifier_detail] if c.modifier_detail else []
    if group_by == "daypart":
        return [c.order.daypart]
    if group_by == "weekday":
        return [str(c.order.weekday)]
    if group_by == "item_count":
        return [bucket(c.order.item_count)]
    if group_by == "error_category":
        return [c.error_category]
    if group_by == "review_label":
        return [c.review_label]
    return [str(c.order.local_date)]  # day


def _order_groups(o: OrderRow, group_by: str) -> list[str] | None:
    """Groups an order counts toward. None: the grouping has no order-level split
    (error_category, review_label), so every group uses all eligible orders."""
    if group_by == "item_id":
        return sorted(o.item_ids)
    if group_by == "modifier":
        return sorted(o.modifiers)
    if group_by == "daypart":
        return [o.daypart]
    if group_by == "weekday":
        return [str(o.weekday)]
    if group_by == "item_count":
        return [bucket(o.item_count)]
    if group_by == "day":
        return [str(o.local_date)]
    return None


def claim_breakdown(session: Session, ctx: StoreContext, req: ClaimBreakdownRequest) -> ToolResult:
    f, group_by = req.filter, req.group_by
    ctx.check_window(f.start, f.end)
    check_claim_scope(ctx, f)
    data = load_window(session, ctx, f.start, f.end)
    orders = [o for o in data.delivered if order_in_scope(o, f)]
    claims = [c for c in data.claims if c.order.delivered and order_in_scope(c.order, f) and claim_in_scope(c, f)]
    total_orders, total_claims = len(orders), len(claims)

    group_orders: dict[str, int] = defaultdict(int)
    group_claims: dict[str, list[ClaimRow]] = defaultdict(list)
    no_split = False
    for o in orders:
        groups = _order_groups(o, group_by)
        if groups is None:
            no_split = True
            break
        for g in groups:
            group_orders[g] += 1
    for c in claims:
        for g in _claim_groups(c, group_by):
            group_claims[g].append(c)

    names = set(group_claims) | (set() if no_split else set(group_orders))
    stats = {}
    for g in names:
        n_orders = total_orders if no_split or g == UNKNOWN else group_orders[g]
        claim_share = ratio(len(group_claims[g]), total_claims)
        order_share = None if no_split or g == UNKNOWN else ratio(group_orders[g], total_orders)
        lift = claim_share / order_share if claim_share is not None and order_share else None
        enough = n_orders >= settings.min_group_orders
        stats[g] = (n_orders, claim_share, order_share, lift, enough)

    def stat(g: str) -> float:
        _, claim_share, _, lift, _ = stats[g]
        value = lift if lift is not None else claim_share
        return value if value is not None else -1.0

    ordered = sorted(sorted(names), key=lambda g: (not stats[g][4], -stat(g)))
    metrics: list[Metric] = []
    for g in ordered:
        n_orders, _, _, _, _ = stats[g]
        label = f"{group_by}={g}"
        if g == UNKNOWN:
            # No order-side denominator for claims without an item_id.
            metrics.append(Metric(name="claim_rate", group=label, value=None,
                                  numerator=len(group_claims[g]), denominator=None, unit="rate"))
        else:
            metrics.append(rate_metric("claim_rate", label, len(group_claims[g]), n_orders))
        metrics.append(share_metric("claim_share", label, len(group_claims[g]), total_claims))
        if no_split or g == UNKNOWN:
            metrics.append(Metric(name="order_share", group=label, value=None,
                                  numerator=None, denominator=None, unit="share"))
        else:
            metrics.append(share_metric("order_share", label, group_orders[g], total_orders))

    in_groups = [c for g in names for c in group_claims[g]]
    rank = {g: (not stats[g][4], -stat(g)) for g in names}
    group_of = {c.evidence_id: g for g in names for c in group_claims[g]}
    by_time = newest_first(in_groups, lambda c: c.reported_at)
    ordered_claims = sorted(by_time, key=lambda c: rank[group_of[c.evidence_id]])  # stable sort keeps time order

    notes = excluded_note([c for c in data.claims if order_in_scope(c.order, f)], labels_of(f))
    if group_by == "modifier":
        missing = total_claims - len(in_groups)
        if missing:
            notes.append(f"{missing} claims have no modifier_detail and are not in any modifier group.")
    if group_by == "item_id" and group_claims.get(UNKNOWN):
        notes.append(
            f"{len(group_claims[UNKNOWN])} claims have no item_id and are grouped as item_id=unknown "
            "(no order denominator)."
        )
    if no_split:
        notes.append(f"Grouping by {group_by} splits claims only; every claim_rate uses all eligible orders.")

    top = next((g for g in ordered if stats[g][4] and stats[g][3] is not None), None)
    if top is None:
        headline = f"No {group_by} group has at least {settings.min_group_orders} orders and a lift to compare."
        if no_split and ordered:
            top = ordered[0]
            headline = (
                f"{group_by}={top} has the most claims: {len(group_claims[top])} of {total_claims} "
                f"({pct(stats[top][1])})."
            )
    else:
        n_orders, claim_share, order_share, lift, _ = stats[top]
        headline = (
            f"{group_by}={top} has the highest lift ({lift:.1f}x): claim rate "
            f"{pct(ratio(len(group_claims[top]), n_orders))} ({len(group_claims[top])}/{n_orders}) vs "
            f"{pct(ratio(total_claims, total_orders))} overall; {pct(claim_share)} of claims on "
            f"{pct(order_share)} of orders."
        )

    return result(
        ctx,
        "claim_breakdown",
        f.start,
        f.end,
        total_orders,
        pending_claims=sum(1 for c in claims if c.review_label == "pending"),
        headline=headline,
        metrics=metrics,
        evidence_ids=capped([c.evidence_id for c in ordered_claims], notes),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------
def compare_periods(session: Session, ctx: StoreContext, req: ComparePeriodsRequest) -> ToolResult:
    before_start = req.split_date - timedelta(days=req.days_before)
    after_end = req.split_date + timedelta(days=req.days_after - 1)
    ctx.check_window(before_start, after_end)
    check_claim_scope(ctx, req.target)
    if req.control:
        check_claim_scope(ctx, req.control)
    data = load_window(session, ctx, before_start, after_end)

    def after(d: date) -> bool:
        return d >= req.split_date

    target_orders = [o for o in data.delivered if order_in_scope(o, req.target)]
    target_claims = [c for c in data.claims if order_in_scope(c.order, req.target) and claim_in_scope(c, req.target)]
    if req.control is None:
        target_ids = {o.order_id for o in target_orders}
        default_labels = labels_of(req.target)
        control_orders = [o for o in data.delivered if o.order_id not in target_ids]
        control_claims = [c for c in data.claims if c.order.order_id not in target_ids and c.review_label in default_labels]
    else:
        control_orders = [o for o in data.delivered if order_in_scope(o, req.control)]
        control_claims = [c for c in data.claims if order_in_scope(c.order, req.control) and claim_in_scope(c, req.control)]

    def period(orders, claims, is_after):
        o = sum(1 for x in orders if after(x.local_date) == is_after)
        cl = [c for c in claims if after(c.order.local_date) == is_after]
        return o, cl

    t_before_o, t_before_c = period(target_orders, target_claims, False)
    t_after_o, t_after_c = period(target_orders, target_claims, True)
    c_before_o, c_before_c = period(control_orders, control_claims, False)
    c_after_o, c_after_c = period(control_orders, control_claims, True)
    metrics = [
        rate_metric("rate_before", "target", len(t_before_c), t_before_o),
        rate_metric("rate_after", "target", len(t_after_c), t_after_o),
        rate_metric("rate_before", "control", len(c_before_c), c_before_o),
        rate_metric("rate_after", "control", len(c_after_c), c_after_o),
    ]
    # Fixed order: target after, target before, control (newest first inside each).
    ordered = (
        newest_first(t_after_c, lambda c: c.reported_at)
        + newest_first(t_before_c, lambda c: c.reported_at)
        + newest_first(c_after_c + c_before_c, lambda c: c.reported_at)
    )
    notes: list[str] = []
    if req.control is None:
        notes.append("control is every delivered order of the store outside the target.")
    if t_before_o == 0:
        notes.append(f"The target has no orders before {req.split_date}, so rate_before for the target is null.")
    elif t_before_o < settings.min_group_orders:
        notes.append(
            f"The target has only {t_before_o} orders before {req.split_date} "
            f"(fewer than {settings.min_group_orders}), so rate_before for the target is null."
        )
    tb, ta, cb, ca = (m.value for m in metrics)
    headline = (
        f"Target rate {pct(tb)} ({len(t_before_c)}/{t_before_o}) before {req.split_date} and "
        f"{pct(ta)} ({len(t_after_c)}/{t_after_o}) after; control {pct(cb)} before and {pct(ca)} after."
    )
    counted = t_before_c + t_after_c + c_before_c + c_after_c
    return result(
        ctx,
        "compare_periods",
        before_start,
        after_end,
        len(data.delivered),
        pending_claims=sum(1 for c in counted if c.review_label == "pending"),
        # Enough data = target after + both control periods have MIN_GROUP_ORDERS orders.
        # The target's before period may be empty (e.g. a modifier added on split_date).
        data_sufficient=all(m.value is not None for m in metrics[1:]),
        headline=headline,
        metrics=metrics,
        evidence_ids=capped([c.evidence_id for c in ordered], notes),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# sample_evidence
# ---------------------------------------------------------------------------
def sample_evidence(session: Session, ctx: StoreContext, req: EvidenceSampleRequest) -> ToolResult:
    f = req.filter
    ctx.check_window(f.start, f.end)
    ctx.check_items(f.item_id)
    data = load_window(session, ctx, f.start, f.end)
    if req.evidence_type == "claim":
        ctx.check_modifiers(f.modifiers)
        rows = [c for c in data.claims if order_in_scope(c.order, f) and claim_in_scope(c, f)]
        rows = newest_first(rows, lambda c: c.reported_at)
        pending = sum(1 for c in rows if c.review_label == "pending")
    else:
        rows = [x for x in data.cancellations if cancellation_in_scope(x, f)]
        rows = newest_first(rows, lambda x: x.canceled_at)
        pending = 0
    picked = [r.evidence_id for r in rows[: req.limit]]
    found = load_evidence(session, picked)
    kind = "claims" if req.evidence_type == "claim" else "cancellations"
    return result(
        ctx,
        "sample_evidence",
        f.start,
        f.end,
        len(data.delivered),
        pending_claims=sum(1 for r in rows[: req.limit] if getattr(r, "review_label", "") == "pending"),
        headline=f"{len(picked)} of {len(rows)} matching {kind}, newest first.",
        evidence_ids=picked,
        evidence=[found[i] for i in picked],
        notes=[f"{pending} of the matching claims are pending review."] if pending else [],
    )


# ---------------------------------------------------------------------------
# cancellation_breakdown
# ---------------------------------------------------------------------------
def cancellation_breakdown(session: Session, ctx: StoreContext, req: CancellationBreakdownRequest) -> ToolResult:
    f, group_by = req.filter, req.group_by
    ctx.check_window(f.start, f.end)
    ctx.check_items(f.item_id)
    data = load_window(session, ctx, f.start, f.end)
    placed = [o for o in data.orders if order_in_scope(o, f)]
    cxl = [x for x in data.cancellations if order_in_scope(x.order, f) and cancellation_in_scope(x, f)]

    def x_group(x: CancellationRow) -> str:
        if group_by == "cancellation_category":
            return x.cancellation_category
        if group_by == "item_id":
            return x.item_id or UNKNOWN
        if group_by == "daypart":
            return x.order.daypart
        if group_by == "weekday":
            return str(x.order.weekday)
        return str(x.order.local_date)

    group_placed: dict[str, int] = defaultdict(int)
    for o in placed:
        if group_by == "item_id":
            for i in o.item_ids:
                group_placed[i] += 1
        elif group_by == "daypart":
            group_placed[o.daypart] += 1
        elif group_by == "weekday":
            group_placed[str(o.weekday)] += 1
        elif group_by == "day":
            group_placed[str(o.local_date)] += 1
    group_cxl: dict[str, list[CancellationRow]] = defaultdict(list)
    for x in cxl:
        group_cxl[x_group(x)].append(x)

    all_orders = group_by == "cancellation_category"
    names = set(group_cxl) | (set() if all_orders or group_by == "item_id" else set(group_placed))

    def den(g: str) -> int:
        return len(placed) if all_orders or g == UNKNOWN else group_placed[g]

    def rank(g: str):
        value = ratio(len(group_cxl[g]), den(g))
        return (den(g) < settings.min_group_orders, -(value if value is not None else -1.0))

    ordered = sorted(sorted(names), key=rank)
    metrics: list[Metric] = []
    for g in ordered:
        label = f"{group_by}={g}"
        metrics.append(rate_metric("cancellation_rate", label, len(group_cxl[g]), den(g)))
        metrics.append(count_metric("cancellation_count", label, len(group_cxl[g])))
    group_rank = {g: rank(g) for g in names}
    rows = newest_first(cxl, lambda x: x.canceled_at)
    rows = sorted(rows, key=lambda x: group_rank[x_group(x)])
    notes = [f"cancellation_rate is cancellations / placed orders ({len(placed)}), delivered and canceled."]
    if all_orders:
        notes.append("Every cancellation_category rate uses all placed orders.")
    if group_by == "item_id" and group_cxl.get(UNKNOWN):
        notes.append(f"{len(group_cxl[UNKNOWN])} cancellations have no item_id (item_id=unknown).")
    top = ordered[0] if ordered else None
    headline = (
        f"{len(cxl)} cancellations out of {len(placed)} placed orders ({pct(ratio(len(cxl), len(placed)))})"
        + (f"; top {group_by}={top} with {len(group_cxl[top])}." if top and group_cxl[top] else ".")
    )
    return result(
        ctx,
        "cancellation_breakdown",
        f.start,
        f.end,
        sum(1 for o in placed if o.delivered),
        # Enough data = the whole filter has MIN_GROUP_ORDERS placed orders; small groups just get null.
        data_sufficient=len(placed) >= settings.min_group_orders,
        headline=headline,
        metrics=metrics,
        evidence_ids=capped([x.evidence_id for x in rows], notes),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# fraud_signals
# ---------------------------------------------------------------------------
def fraud_signals(session: Session, ctx: StoreContext, start: date, end: date) -> ToolResult:
    """Flags customer_refs with at least FRAUD_MIN_PENDING_CLAIMS pending claims at this store.

    Pending claims count toward the M&I rate, so a cluster of them can inflate it before
    review catches up. Claims already labeled fraud are excluded from rates anyway.
    """
    ctx.check_window(start, end)
    data = load_window(session, ctx, start, end)
    by_ref: dict[str, list[ClaimRow]] = defaultdict(list)
    for c in data.claims:
        if c.review_label == "pending":
            by_ref[c.order.customer_ref].append(c)
    threshold = settings.fraud_min_pending_claims
    flagged = {ref: claims for ref, claims in by_ref.items() if len(claims) >= threshold}
    ordered_refs = sorted(sorted(flagged), key=lambda r: -len(flagged[r]))
    metrics = [count_metric("claim_count", f"customer_ref={r}", len(flagged[r])) for r in ordered_refs]
    ids = [c.evidence_id for r in ordered_refs for c in newest_first(flagged[r], lambda c: c.reported_at)]
    pending = sum(len(v) for v in by_ref.values())
    fraud_labeled = sum(1 for c in data.claims if c.review_label == "fraud")
    notes = [f"A customer_ref is flagged at {threshold} or more pending claims in the window."]
    if fraud_labeled:
        notes.append(f"{fraud_labeled} claims already labeled fraud are excluded from every rate.")
    headline = (
        f"{len(flagged)} customer_refs have {threshold}+ pending claims ({len(ids)} claims)."
        if flagged
        else f"No customer_ref has {threshold} or more pending claims; {pending} claims are pending in total."
    )
    notes_ids = capped(ids, notes)
    return result(
        ctx,
        "fraud_signals",
        start,
        end,
        len(data.delivered),
        pending_claims=pending,
        headline=headline,
        metrics=metrics,
        evidence_ids=notes_ids,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# event_log
# ---------------------------------------------------------------------------
def event_log(
    session: Session, ctx: StoreContext, start: date, end: date, event_types: list[EventType] | None
) -> ToolResult:
    """Operational events that overlap the window, oldest first. No metrics."""
    ctx.check_window(start, end)
    lo, hi = utc_bounds(ctx.tz, start, end)
    q = select(OperationalEvent).where(
        OperationalEvent.store_id == ctx.store.store_id,
        OperationalEvent.started_at < hi,
        (OperationalEvent.ended_at.is_(None)) | (OperationalEvent.ended_at >= lo),
    )
    if event_types:
        q = q.where(OperationalEvent.event_type.in_(event_types))
    events = session.scalars(q.order_by(OperationalEvent.started_at, OperationalEvent.evidence_id)).all()
    events = events[:MAX_IDS]
    data = load_window(session, ctx, start, end)
    headline = (
        f"{len(events)} operational events from {start} to {end}: "
        + "; ".join(f"{e.started_at.astimezone(ctx.tz).date()} {e.event_type.value}" for e in events[:5])
        + ("; ..." if len(events) > 5 else ".")
        if events
        else f"No operational events from {start} to {end}."
    )
    return result(
        ctx,
        "event_log",
        start,
        end,
        len(data.delivered),
        headline=headline,
        evidence_ids=[e.evidence_id for e in events],
        evidence=[event_evidence(e) for e in events],
        notes=["Events with no ended_at are still in effect."],
    )
