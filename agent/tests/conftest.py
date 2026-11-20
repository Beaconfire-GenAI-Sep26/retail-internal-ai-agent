from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

import pytest

from agent.app.config import Settings
from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.graph.build import build_graph, run_config
from agent.app.graph.context import AgentContext
from agent.app.graph.state import initial_state
from agent.app.ids import CounterIdFactory
from agent.app.llm.base import ModelError
from agent.app.llm.scripted_model import ScriptedReasonModel

FIXTURES = Path(__file__).parent / "fixtures" / "domain"
TEST_SECRET = "test-secret-0123456789-0123456789-abcd"


def make_settings(**overrides: Any) -> Settings:
    values = {
        "jwt_secret": TEST_SECRET,
        "jwt_issuer": "mi-auth",
        "agent_domain_mode": "fixtures",
        "agent_fixtures_dir": FIXTURES,
        "internal_service_token": "svc-test",
        "anthropic_api_key": "",
        "agent_max_steps": 12,
        "agent_run_timeout_seconds": 600,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def domain() -> FixtureDomainClient:
    return FixtureDomainClient(FIXTURES)


async def run_investigation(store_id: str, model: Any, *, settings: Settings, domain: FixtureDomainClient | None = None,
                            deadline_seconds: float = 600) -> tuple[dict[str, Any], FixtureDomainClient]:
    domain = domain or FixtureDomainClient(FIXTURES)
    case = domain.case_for_store(store_id)
    graph = build_graph()
    investigation_id = f"INV-TEST-{store_id}"
    ctx = AgentContext(domain=domain, model=model, ids=CounterIdFactory(), settings=settings, user_id="USR-001",
                       request_id="req-test", deadline=time.monotonic() + deadline_seconds)
    state = initial_state(investigation_id=investigation_id, case_id=case.case_id, store_id=store_id,
                          started_by="USR-001", started_at="2026-11-18T15:00:00Z", reopen_of=None, run_config={})
    final = await graph.ainvoke(state, run_config(investigation_id, settings.recursion_limit), context=ctx,
                                durability="sync")
    return final, domain


async def capture_state(store_id: str, turns: list[Any], *, settings: Settings | None = None,
                        domain: FixtureDomainClient | None = None) -> dict[str, Any]:
    """The state the model sees on the turn after `turns` have run."""
    captured: dict[str, Any] = {}

    def grab(state: dict[str, Any]) -> dict[str, Any]:
        captured.update(copy.deepcopy(state))
        raise ModelError("INTERNAL", "captured")

    await run_investigation(store_id, ScriptedReasonModel([*turns, grab]), settings=settings or make_settings(),
                            domain=domain)
    return captured
