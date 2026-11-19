"""reason: the only node that calls the model."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from app.graph.context import AgentContext
from app.graph.nodes.common import timeout_error
from app.graph.state import InvestigationState
from app.llm.base import ModelError
from app.prompts.render import render_prompt


def _add_usage(total: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    out = dict(total)
    for key, value in new.items():
        out[key] = out.get(key, 0) + value
    return out


async def reason(state: InvestigationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.expired():
        return {"error": timeout_error()}
    turn = state.get("reason_calls", 0) + 1
    prompt = render_prompt(state, ctx.settings)
    try:
        reply = await ctx.model.reason(prompt, dict(state))
    except ModelError as exc:
        return {"error": {"code": exc.code, "message": exc.message}, "reason_calls": turn}
    output = reply.output if reply.output is not None else {"__unparsed__": reply.raw_text[:4000]}
    return {
        "reason_output": output,
        "reason_calls": turn,
        "usage": _add_usage(state.get("usage", {}), reply.usage),
        "model_calls": [{
            "turn": turn,
            "model": reply.model,
            "stop_reason": reply.stop_reason,
            "usage": reply.usage,
            "latency_ms": reply.latency_ms,
            "request_id": reply.request_id,
            "output": output,
        }],
    }
