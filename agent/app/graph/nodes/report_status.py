"""report_status: tells Domain how the investigation ended. Idempotent; a failure is flushed later."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime

from agent.app.contracts.models import InvestigationStatusUpdate
from agent.app.domain.client import DomainError
from agent.app.graph.context import AgentContext
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.status")


async def report_status(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    status = state.get("status", "failed")
    error = state.get("error") or {}
    body = InvestigationStatusUpdate(
        investigation_id=state["investigation_id"],
        status=status,
        error_code=error.get("code") if status == "failed" else None,
    )
    try:
        await ctx.domain.report_investigation_status(state["case_id"], body)
    except DomainError as exc:
        if exc.route_missing:
            # Domain hasn't shipped the status route yet; retrying can't help, so nothing is pending.
            log_event(logger, logging.INFO, "Domain has no status route; status not reported", status=status)
            return {"domain_sync_pending": False}
        log_event(logger, logging.WARNING, "status report failed", status=status, code=exc.code)
        return {"domain_sync_pending": True}
    return {"domain_sync_pending": False}
