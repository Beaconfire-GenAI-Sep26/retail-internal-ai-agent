"""Store reads and the read-only diagnostic tools. None of these routes change data."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.app.deps import get_session
from domain.app.models import EventType, MenuItem
from domain.app.schemas import (
    CancellationBreakdownRequest,
    ClaimBreakdownRequest,
    ComparePeriodsRequest,
    EvidenceSampleRequest,
    MenuItemOut,
    StoreSummary,
    ToolResult,
)
from domain.app.security import CurrentUser, current_user
from domain.app.services import diagnostics
from domain.app.services.cases import store_summary
from domain.app.services.store_data import StoreContext, store_context

router = APIRouter(prefix="/stores/{store_id}", tags=["stores"])


def window(ctx: StoreContext, start: date | None, end: date | None) -> tuple[date, date]:
    """Default: the 42 days ending on the store's last day of data."""
    default_start, default_end = ctx.default_window()
    return start or default_start, end or default_end


@router.get("", response_model=StoreSummary)
def get_store(store_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    return store_summary(store_context(session, user, store_id).store)


@router.get("/menu", response_model=list[MenuItemOut])
def get_menu(store_id: str, user: CurrentUser = Depends(current_user), session: Session = Depends(get_session)):
    """The store's menu items with their modifiers. Read once by load_case; not a model tool."""
    store_context(session, user, store_id)
    items = session.scalars(select(MenuItem).where(MenuItem.store_id == store_id).order_by(MenuItem.item_id))
    return [
        MenuItemOut(
            item_id=i.item_id,
            store_id=i.store_id,
            name=i.name,
            category=i.category,
            price=float(i.price),
            available_modifiers=i.available_modifiers or [],
        )
        for i in items
    ]


@router.get("/overview", response_model=ToolResult)
def overview(
    store_id: str,
    start: date | None = None,
    end: date | None = None,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """store_overview: M&I rate, claim counts by review_label and error_category, daily rates."""
    ctx = store_context(session, user, store_id)
    return diagnostics.store_overview(session, ctx, *window(ctx, start, end))


@router.get("/diagnostics/events", response_model=ToolResult)
def events(
    store_id: str,
    start: date | None = None,
    end: date | None = None,
    event_type: list[EventType] | None = Query(default=None),
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """event_log: operational events overlapping the window, oldest first."""
    ctx = store_context(session, user, store_id)
    return diagnostics.event_log(session, ctx, *window(ctx, start, end), event_type)


@router.post("/diagnostics/claim-breakdown", response_model=ToolResult)
def claim_breakdown(
    store_id: str,
    body: ClaimBreakdownRequest,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """claim_breakdown: claim_rate, claim_share and order_share per group, highest lift first."""
    return diagnostics.claim_breakdown(session, store_context(session, user, store_id), body)


@router.post("/diagnostics/compare-periods", response_model=ToolResult)
def compare_periods(
    store_id: str,
    body: ComparePeriodsRequest,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """compare_periods: rate_before and rate_after for the target and the control."""
    return diagnostics.compare_periods(session, store_context(session, user, store_id), body)


@router.post("/diagnostics/evidence-sample", response_model=ToolResult)
def evidence_sample(
    store_id: str,
    body: EvidenceSampleRequest,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """sample_evidence: up to `limit` matching claims or cancellations, newest first."""
    return diagnostics.sample_evidence(session, store_context(session, user, store_id), body)


@router.post("/diagnostics/cancellation-breakdown", response_model=ToolResult)
def cancellation_breakdown(
    store_id: str,
    body: CancellationBreakdownRequest,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """cancellation_breakdown: cancellation_rate and cancellation_count per group."""
    return diagnostics.cancellation_breakdown(session, store_context(session, user, store_id), body)


@router.get("/diagnostics/fraud-signals", response_model=ToolResult)
def fraud_signals(
    store_id: str,
    start: date | None = None,
    end: date | None = None,
    user: CurrentUser = Depends(current_user),
    session: Session = Depends(get_session),
):
    """fraud_signals: customer_refs with FRAUD_MIN_PENDING_CLAIMS or more pending claims."""
    ctx = store_context(session, user, store_id)
    return diagnostics.fraud_signals(session, ctx, *window(ctx, start, end))
