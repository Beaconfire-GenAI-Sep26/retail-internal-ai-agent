"""The agent against the real Domain Service: tool contracts, determinism, evidence checks, graph and API.

While Domain has no catalog or proposals route, the runs use the bundled catalog and finish without saving a
proposal. Once those routes exist, each run saves a real pending proposal, and the tests reject it afterwards
(as the frontend would) so the next run on the same case can save its own. The API only starts a run on a case
nobody has decided, so the API test first returns STORE-A's case to `open`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from shared.security import JWTSettings

from agent.app.domain.catalog import load_bundled_catalog
from agent.app.domain.client import DomainError, HttpDomainClient, _parse_error
from agent.app.graph.build import build_graph, run_config
from agent.app.graph.context import AgentContext
from agent.app.graph.nodes.submit import NO_PROPOSALS_ROUTE_GAP
from agent.app.graph.state import initial_state
from agent.app.ids import CounterIdFactory
from agent.app.llm.scripted_model import ScriptedReasonModel
from agent.app.main import create_app
from agent.app.tools.registry import call_tool
from agent.tests.conftest import make_settings
from agent.tests.live.conftest import (
    JWT_ISSUER,
    JWT_SECRET,
    SERVICE_TOKEN,
    LiveDomain,
    auth,
    mint,
    pending_proposals,
    release_proposals,
    reopen_case,
)
from agent.tests.scripts import FULL, store_a_turns, store_b_turns

pytestmark = pytest.mark.live_domain

TOOL_CALLS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "STORE-A": [
        ("store_overview", {"start": FULL[0], "end": FULL[1]}),
        ("event_log", {"start": FULL[0], "end": FULL[1], "event_type": []}),
        ("claim_breakdown", {"filter": {"start": FULL[0], "end": FULL[1]}, "group_by": "modifier"}),
        ("compare_periods", {"split_date": "2026-10-30", "days_before": 14, "days_after": 17,
                             "target": {"modifiers": ["Extra sauce"]}, "control": None}),
        ("sample_evidence", {"evidence_type": "claim", "limit": 3,
                             "filter": {"start": "2026-10-30", "end": FULL[1], "modifiers": ["Extra sauce"]}}),
        ("cancellation_breakdown", {"filter": {"start": FULL[0], "end": FULL[1]}, "group_by": "day"}),
        ("fraud_signals", {"start": FULL[0], "end": FULL[1]}),
    ],
    "STORE-B": [
        ("claim_breakdown", {"filter": {"start": "2026-11-03", "end": FULL[1]}, "group_by": "item_count"}),
        ("compare_periods", {"split_date": "2026-11-10", "days_before": 7, "days_after": 6,
                             "target": {"daypart": ["dinner"], "item_count_min": 5}, "control": None}),
        ("sample_evidence", {"evidence_type": "cancellation", "limit": 5,
                             "filter": {"start": FULL[0], "end": FULL[1], "cancellation_category": ["too_busy"]}}),
        ("cancellation_breakdown", {"filter": {"start": FULL[0], "end": FULL[1], "daypart": ["dinner"]},
                                    "group_by": "weekday"}),
    ],
}


def jwt_settings() -> JWTSettings:
    return JWTSettings(JWT_SECRET, JWT_ISSUER)


@pytest.fixture
async def ports(live: LiveDomain):
    """A port per store, bound to that store's case the way an investigation's client is."""
    client = HttpDomainClient(live.url, SERVICE_TOKEN, max_retries=0, jwt_settings=jwt_settings())

    def bind(store: str):
        return client.bind(token=mint(), request_id="live-test", investigation_id="INV-LIVE", store_id=store,
                           case_id=live.cases[store])

    yield bind
    await client.aclose()


def live_settings(live: LiveDomain):
    return make_settings(agent_domain_mode="http", domain_service_url=live.url, jwt_secret=JWT_SECRET,
                         jwt_issuer=JWT_ISSUER, internal_service_token=SERVICE_TOKEN)


def check_proposal(live: LiveDomain, final: dict[str, Any]) -> None:
    """Either Domain saved this run's proposal, or the result says it couldn't."""
    result = final["result"]
    saved = result["proposal_id"] is not None
    assert saved != (NO_PROPOSALS_ROUTE_GAP in result["evidence_gaps"])
    if saved:
        mine = [p for p in pending_proposals(live, final["case_id"]) if p["proposal_id"] == result["proposal_id"]]
        assert mine and mine[0].get("investigation_id") == final["investigation_id"]


# --- Tools: accepted, parsed and deterministic ----------------------------------------------------


@pytest.mark.parametrize(("store", "tool", "request_body"),
                         [(s, t, r) for s, calls in TOOL_CALLS.items() for t, r in calls])
async def test_each_tool_returns_the_same_result_twice(ports, store, tool, request_body):
    port = ports(store)
    first = await call_tool(port, store, tool, request_body)
    second = await call_tool(port, store, tool, request_body)
    assert first.tool == tool and first.store_id == store
    assert first.model_dump() == second.model_dump()


async def test_the_seed_has_both_cases_and_flags_one_store_a_customer(live, ports):
    assert set(live.cases) == {"STORE-A", "STORE-B"}
    fraud = await ports("STORE-A").fraud_signals("STORE-A", *FULL)
    assert any(m.name == "claim_count" and (m.group or "").startswith("customer_ref=") for m in fraud.metrics)


# --- What the fallbacks and the evidence checks rely on ---------------------------------------------


async def test_a_route_without_a_handler_returns_the_envelope_route_missing_expects(live):
    # /catalog/actions is in Domain's access policy but has no handler until C-03. A route outside the policy
    # gets 403 instead, so it can't stand in for a missing route.
    async with httpx.AsyncClient(base_url=live.url, timeout=10) as http:
        response = await http.get("/catalog/actions", headers=auth(mint()))
    if response.status_code == 200:
        pytest.skip("Domain has /catalog/actions now (C-03)")
    code, message, details = _parse_error(response)
    assert DomainError(response.status_code, code, message, details).route_missing


async def test_resolve_checks_more_than_200_ids_and_flags_other_stores(ports):
    port = ports("STORE-A")
    overview = await port.store_overview("STORE-A", *FULL)
    cancellations = await port.cancellation_breakdown(
        "STORE-A", {"filter": {"start": FULL[0], "end": FULL[1]}, "group_by": "day"})
    other = await ports("STORE-B").claim_breakdown("STORE-B", {"filter": {"start": "2026-11-03", "end": FULL[1]},
                                                               "group_by": "item_count"})
    store_a = list(dict.fromkeys([*overview.evidence_ids, *cancellations.evidence_ids]))
    fakes = [f"EV-CLM-9{n:05d}" for n in range(max(1, 205 - len(store_a)))]
    result = await port.resolve_evidence("STORE-A", [*store_a, other.evidence_ids[0], *fakes])
    assert set(result.valid) == set(store_a)
    reasons = {item["evidence_id"]: item["reason"] for item in result.invalid}
    assert reasons.pop(other.evidence_ids[0]) == "other_store"
    assert set(reasons) == set(fakes) and set(reasons.values()) == {"not_found"}


async def test_bundled_catalog_ids_exist_in_domains_catalog(ports):
    try:
        entries = await ports("STORE-A").get_catalog()
    except DomainError as exc:
        if exc.route_missing:
            pytest.skip("Domain has no /catalog/actions yet (C-03)")
        raise
    assert {e.action_id for e in load_bundled_catalog()} <= {e.action_id for e in entries}


# --- The graph over HTTP with the scripted turns ------------------------------------------------------


async def run_live(live: LiveDomain, store: str, turns: list[Any]) -> dict[str, Any]:
    settings = live_settings(live)
    investigation_id = f"INV-LIVE-{uuid.uuid4().hex[:8].upper()}"
    client = HttpDomainClient(live.url, SERVICE_TOKEN, jwt_settings=jwt_settings())
    try:
        domain = client.bind(token=mint(), request_id=f"live-{store}", investigation_id=investigation_id,
                             store_id=store, case_id=live.cases[store])
        ctx = AgentContext(domain=domain, model=ScriptedReasonModel(turns), ids=CounterIdFactory(), settings=settings,
                           user_id="USR-901", request_id=f"live-{store}", deadline=time.monotonic() + 600)
        state = initial_state(investigation_id=investigation_id, case_id=live.cases[store], store_id=store,
                              started_by="USR-901", started_at="2026-11-19T00:00:00Z", reopen_of=None, run_config={})
        return await build_graph().ainvoke(state, run_config(investigation_id, settings.recursion_limit),
                                           context=ctx, durability="sync")
    finally:
        await client.aclose()


def sequence(state: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(c["tool"], c["request"].get("group_by")) for c in state["checks"] if c["source"] == "reason"]


def cited(result: dict[str, Any]) -> list[str]:
    ids = [*result["supporting_evidence_ids"], *result["contradicting_evidence_ids"]]
    for entry in result["ruled_out"]:
        ids += entry["evidence_ids"]
    return list(dict.fromkeys(ids))


async def test_store_a_and_store_b_reach_their_causes_by_different_checks(live, ports):
    a = await run_live(live, "STORE-A", store_a_turns())
    b = await run_live(live, "STORE-B", store_b_turns())
    try:
        assert a["status"] == b["status"] == "completed", (a.get("error"), b.get("error"))
        assert a["result"]["cause_category"] == "pos_modifier_mapping"
        assert b["result"]["cause_category"] == "packing"
        assert sequence(a) != sequence(b)
        assert not [c for c in a["checks"] + b["checks"] if c.get("domain_rejected")]
        for store, final in (("STORE-A", a), ("STORE-B", b)):
            ids = cited(final["result"])
            assert ids and set((await ports(store).resolve_evidence(store, ids)).valid) == set(ids)
            check_proposal(live, final)
    finally:
        for final in (a, b):
            release_proposals(live, final["case_id"], {final["investigation_id"]})


# --- The API with the real Domain behind it ------------------------------------------------------------


def wait_for(client: TestClient, investigation_id: str, token: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    view: dict[str, Any] = {}
    while time.monotonic() < deadline:
        view = client.get(f"/investigations/{investigation_id}", headers=auth(token)).json()
        if view["status"] in ("completed", "unsure", "failed"):
            return view
        time.sleep(0.1)
    raise AssertionError(f"investigation {investigation_id} stayed {view.get('status')}")


def test_the_api_runs_a_case_with_the_users_permissions(live):
    reopen_case(live, "STORE-A")  # the graph test above leaves the case decided
    app = create_app(live_settings(live), domain_client=HttpDomainClient(live.url, SERVICE_TOKEN,
                                                                         jwt_settings=jwt_settings()),
                     model=ScriptedReasonModel(store_a_turns()), ids=CounterIdFactory(), configure_logs=False)
    case_id = live.cases["STORE-A"]
    analyst = mint(stores=("STORE-A", "STORE-B"))
    with TestClient(app) as client:
        started = client.post("/investigations", json={"case_id": case_id}, headers=auth(analyst))
        assert started.status_code == 202, started.text
        investigation_id = started.json()["investigation_id"]
        try:
            done = wait_for(client, investigation_id, analyst)
            assert done["status"] == "completed", done.get("error")
            assert done["result"]["cause_category"] == "pos_modifier_mapping"
            check_proposal(live, {"result": done["result"], "case_id": case_id, "investigation_id": investigation_id})
        finally:
            release_proposals(live, case_id, {investigation_id})
        viewer = mint(role="viewer", stores=("STORE-A",))
        assert client.post("/investigations", json={"case_id": case_id}, headers=auth(viewer)).status_code == 403
        outsider = mint(stores=("STORE-B",))  # Domain hides the case from a user without STORE-A
        refused = client.post("/investigations", json={"case_id": case_id}, headers=auth(outsider))
        assert refused.status_code == 404 and refused.json()["error"]["code"] == "CASE_NOT_FOUND"
