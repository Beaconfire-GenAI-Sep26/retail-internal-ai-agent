"""The interface the `reason` node calls, and what a call returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RenderedPrompt:
    """One reason turn: S1 (system, cached), U1 (user, cached), U2 (user), C (system control)."""

    system: str
    case_facts: str
    turn_state: str
    control: str

    def to_messages(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        system = [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}]
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.case_facts, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": self.turn_state},
                ],
            },
            {"role": "system", "content": self.control},
        ]
        return system, messages


@dataclass
class ModelReply:
    output: dict[str, Any] | None  # parsed JSON; None when the text wasn't valid JSON
    raw_text: str
    model: str
    stop_reason: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    request_id: str | None = None


class ModelError(Exception):
    """A model call that can't produce a usable turn. `code` is an investigation error code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ReasonModel(Protocol):
    name: str

    async def reason(self, prompt: RenderedPrompt, state: dict[str, Any]) -> ModelReply: ...
