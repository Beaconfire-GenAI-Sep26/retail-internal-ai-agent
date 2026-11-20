"""load_case: the case, the window's overview, the menu, fraud signals and the catalog.

None of its calls count as steps. The overview becomes the first finding.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from langgraph.runtime import Runtime

from agent.app.contracts.models import DailyRate
from agent.app.domain.catalog import load_bundled_catalog
from agent.app.domain.client import DomainError
from agent.app.graph.context import AgentContext
from agent.app.graph.nodes.common import domain_error, make_record, scrub_result, timeout_error, window_end_date
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.load_case")

WINDOW_DAYS = 42


def clip_window(end: date, daily_rates: list[DailyRate]) -> tuple[date, date]:
    """The 42 days ending on `end`, kept inside the store's data.

    Domain's case detail already clips its daily rates to the data range, and its tools reject dates
    outside it, so the window never starts before the first daily rate or ends after the last one.
    """
    days = sorted(date.fromisoformat(r.date[:10]) for r in daily_rates if r.date)
    if days:
        end = min(end, days[-1])
    start = end - timedelta(days=WINDOW_DAYS - 1)
    if days:
        start = max(start, days[0])
    return start, end


async def load_case(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    store_id = state["store_id"]
    try:
        case = await ctx.domain.get_case(state["case_id"])
        tz = case.store.timezone
        start, end = clip_window(window_end_date(case.window_end, tz), case.daily_rates)
        overview = await ctx.domain.store_overview(store_id, start.isoformat(), end.isoformat())
        window = {"start": overview.window.start, "end": overview.window.end}
        menu = await ctx.domain.get_menu(store_id)
        fraud = await ctx.domain.fraud_signals(store_id, window["start"], window["end"])
    except DomainError as exc:
        return {"error": domain_error(exc, "load_case")}
    try:
        catalog = await ctx.domain.get_catalog()
        catalog_source = "domain"
    except DomainError as exc:
        if not exc.route_missing:
            return {"error": domain_error(exc, "load_case")}
        log_event(logger, logging.INFO, "Domain has no catalog route; using the bundled catalog", path=exc.path)
        catalog = load_bundled_catalog()
        catalog_source = "bundled"

    overview_result = scrub_result(overview.model_dump(mode="json"))
    fraud_result = scrub_result(fraud.model_dump(mode="json"))
    overview_id, fraud_id = ctx.ids.new("CHK"), ctx.ids.new("CHK")
    records = [
        make_record(overview_id, source="load_case", kind="explore", tool="store_overview",
                    request={"start": start.isoformat(), "end": end.isoformat()}, result=overview_result,
                    purpose="Store overview for the whole window, loaded at the start."),
        make_record(fraud_id, source="load_case", kind="explore", tool="fraud_signals",
                    request={"start": window["start"], "end": window["end"]}, result=fraud_result,
                    purpose="Fraud signals for the whole window, loaded at the start."),
    ]
    counts = {m.group: m.value for m in overview.metrics if m.name == "claim_count" and m.group}
    excluded = {
        "fraud": int(counts.get("review_label=fraud") or 0),
        "not_store_fault": int(counts.get("review_label=not_store_fault") or 0),
    }
    suspect = any(
        m.name == "claim_count" and (m.group or "").startswith("customer_ref=") and (m.value or 0) > 0
        for m in fraud.metrics
    )
    modifiers: list[str] = []
    for item in menu:
        for mod in item.available_modifiers:
            if mod not in modifiers:
                modifiers.append(mod)
    case_facts = case.model_dump(mode="json", exclude={"daily_rates", "proposals", "rechecks"})
    return {
        "run_config": {**(state.get("run_config") or {}), "catalog_source": catalog_source},
        "case": case_facts,
        "timezone": tz,
        "window": window,
        "data_start": window["start"],
        "menu": [m.model_dump(mode="json") for m in menu],
        "known_items": [m.item_id for m in menu],
        "known_modifiers": modifiers,
        "catalog": [e.model_dump(mode="json") for e in catalog],
        "excluded": excluded,
        "suspect_cluster": suspect,
        "checks": records,
        "retrieved_evidence_ids": [*overview.evidence_ids, *fraud.evidence_ids],
        "latest_check_id": overview_id,
        "status": "running",
    }
