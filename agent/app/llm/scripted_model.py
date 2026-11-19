"""A scripted stand-in for the model, for graph tests and replaying saved outputs.

Each turn is a ReasonOutput dict, a callable that builds one from the state, or an exception to
raise. Strings in a turn can name state values that only exist at run time:
  "@hyp:<cause_category>"   the first hypothesis with that cause
  "@latest_ev:<n>"          inside a list, the first n evidence IDs of the latest check
  "@event:<text>"           the event whose description contains <text>
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from app.errors import INTERNAL
from app.llm.base import ModelError, ModelReply, RenderedPrompt

Turn = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | Exception


def _resolve(value: Any, state: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _resolve(v, state) for k, v in value.items()}
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if isinstance(item, str) and item.startswith("@latest_ev:"):
                n = int(item.split(":", 1)[1])
                latest = next((c for c in state.get("checks", []) if c["check_id"] == state.get("latest_check_id")), {})
                out.extend(latest.get("result", {}).get("evidence_ids", [])[:n])
            else:
                out.append(_resolve(item, state))
        return out
    if isinstance(value, str) and value.startswith("@hyp:"):
        cause = value.split(":", 1)[1]
        match = next((h for h in state.get("hypotheses", []) if h["cause_category"] == cause), None)
        return match["hypothesis_id"] if match else value
    if isinstance(value, str) and value.startswith("@event:"):
        text = value.split(":", 1)[1]
        match = next((e for e in state.get("event_ledger", []) if text in e.get("description", "")), None)
        return match["evidence_id"] if match else value
    return value


class ScriptedReasonModel:
    name = "scripted"

    def __init__(self, turns: list[Turn]):
        self.turns = list(turns)
        self.calls = 0
        self.prompts: list[RenderedPrompt] = []

    async def reason(self, prompt: RenderedPrompt, state: dict[str, Any]) -> ModelReply:
        self.prompts.append(prompt)
        if self.calls >= len(self.turns):
            raise ModelError(INTERNAL, f"the script has only {len(self.turns)} turns")
        turn = self.turns[self.calls]
        self.calls += 1
        if isinstance(turn, Exception):
            raise turn
        if callable(turn):
            turn = turn(state)
        output = _resolve(copy.deepcopy(turn), state)
        return ModelReply(
            output=output,
            raw_text=json.dumps(output),
            model="scripted",
            stop_reason="end_turn",
            usage={"input_tokens": 0, "output_tokens": 0},
        )
