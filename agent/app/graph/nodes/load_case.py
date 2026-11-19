"""load_case: the case, the window's overview, the menu, fraud signals and the catalog.

None of its calls count as steps. The overview becomes the first finding.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langgraph.runtime import Runtime

from app.domain.client import DomainError
from app.graph.context import AgentContext
from app.graph.nodes.common import domain_error, make_record, scrub_result, timeout_error, window_end_date
from app.graph.state import InvestigationState

WINDOW_DAYS = 42


async def load_case(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    store_id = state["store_id"]
    try:
        case = await ctx.domain.get_case(state["case_id"])
        tz = case.store.timezone
        end = window_end_date(case.window_end, tz)
        start = end - timedelta(days=WINDOW_DAYS - 1)
        overview = await ctx.domain.store_overview(store_id, start.isoformat(), end.isoformat())
        window = {"start": overview.window.start, "end": overview.window.end}
        menu = await ctx.domain.get_menu(store_id)
        fraud = await ctx.domain.fraud_signals(store_id, window["start"], window["end"])
        catalog = await ctx.domain.get_catalog()
    except DomainError as exc:
        return {"error": domain_error(exc, "load_case")}

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
