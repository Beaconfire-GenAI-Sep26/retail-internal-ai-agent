"""LangGraph runtime context. It holds the JWT-bound Domain client and is never checkpointed."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import Settings
from app.domain.client import DomainPort
from app.ids import IdFactory
from app.llm.base import ReasonModel


@dataclass
class AgentContext:
    domain: DomainPort  # bound to the forwarded JWT, request ID and investigation ID
    model: ReasonModel
    ids: IdFactory
    settings: Settings
    user_id: str
    request_id: str
    deadline: float = field(default_factory=lambda: time.monotonic() + 3600)

    def expired(self) -> bool:
        return time.monotonic() > self.deadline
