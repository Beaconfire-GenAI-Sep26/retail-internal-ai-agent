"""run_check: one read-only Domain call for the accepted plan."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from app.contracts.models import ToolResult, Window
from app.domain.client import DomainError
from app.graph.context import AgentContext
from app.graph.nodes.common import domain_error, ledger_entries, make_record, scrub_result, timeout_error
from app.graph.state import InvestigationState
from app.tools.registry import call_tool


def _rejected_result(tool: str, store_id: str, request: dict[str, Any], exc: DomainError) -> ToolResult:
    flt = request.get("filter", request)
    start = flt.get("start", request.get("split_date", ""))
    end = flt.get("end", request.get("split_date", ""))
    return ToolResult(
        tool=tool,
        store_id=store_id,
        window=Window(start=start, end=end),
        data_sufficient=False,
        headline=f"Domain rejected the request ({exc.code}).",
        notes=[exc.message],
    )


async def run_check(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    plan = state["next_action"]["plan"]
    store_id = state["store_id"]
    rejected = False
    try:
        result = await call_tool(ctx.domain, store_id, plan["tool"], plan["request"])
    except DomainError as exc:
        if not exc.rejected:
            return {"error": domain_error(exc, f"run_check {plan['tool']}")}
        result = _rejected_result(plan["tool"], store_id, plan["request"], exc)
        rejected = True
    result_dict = scrub_result(result.model_dump(mode="json"))
    check_id = ctx.ids.new("CHK")
    record = make_record(
        check_id,
        source="reason",
        kind=plan["kind"],
        tool=plan["tool"],
        request=plan["request"],
        result=result_dict,
        purpose=plan["purpose"],
        discriminates=plan["discriminates"],
        expectations=plan["expectations"],
        challenges=plan["challenges"],
        domain_rejected=rejected,
    )
    ids = [*result.evidence_ids, *(e.evidence_id for e in result.evidence)]
    update: dict[str, Any] = {
        "checks": [record],
        "step_count": state.get("step_count", 0) + 1,
        "explore_count": state.get("explore_count", 0) + (1 if plan["kind"] == "explore" else 0),
        "retrieved_evidence_ids": [] if rejected else ids,
        "event_ledger": ledger_entries(result_dict, state.get("timezone", "UTC")),
        "challenge_check_ids": [check_id] if plan["kind"] == "challenge" else [],
        "latest_check_id": check_id,
        "next_action": None,
    }
    if state.get("reason_calls", 0) >= ctx.settings.max_reason_calls:
        update["end_reason"] = "reason_cap"
    return update
