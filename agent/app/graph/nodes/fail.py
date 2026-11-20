"""fail: records an operational failure as status failed, with a structured log line."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.runtime import Runtime

from agent.app.errors import INTERNAL
from agent.app.graph.context import AgentContext
from agent.app.graph.state import InvestigationState
from agent.app.logs import log_event

logger = logging.getLogger("agent.fail")


async def fail(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    error = state.get("error") or {"code": INTERNAL, "message": "The investigation stopped without an error record."}
    log_event(
        logger,
        logging.ERROR,
        "investigation failed",
        code=error["code"],
        error_message=error["message"],
        investigation_id=state.get("investigation_id"),
        case_id=state.get("case_id"),
        step_count=state.get("step_count", 0),
        reason_calls=state.get("reason_calls", 0),
    )
    return {"status": "failed", "error": error}
