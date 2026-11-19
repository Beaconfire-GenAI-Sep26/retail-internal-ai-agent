"""The HTTP Domain client against the contract endpoints, with respx."""

import httpx
import pytest
import respx

from app.contracts.models import InvestigationStatusUpdate
from app.domain.client import DomainError, HttpDomainClient

BASE = "http://domain:8000"
TOOL_RESULT = {"tool": "claim_breakdown", "store_id": "STORE-A", "window": {"start": "2026-10-05", "end": "2026-11-15"},
               "eligible_orders": 2598, "pending_claims": 0, "data_sufficient": True, "headline": "h", "metrics": [],
               "evidence_ids": [], "evidence": [], "notes": []}


@pytest.fixture
def port():
    client = HttpDomainClient(BASE, "svc-token", max_retries=2, backoff_seconds=0)
    return client.bind(token="user-jwt", request_id="req-1", investigation_id="INV-1")


@respx.mock
async def test_diagnostics_forward_the_user_token_without_the_service_token(port):
    route = respx.post(f"{BASE}/stores/STORE-A/diagnostics/claim-breakdown").mock(
        return_value=httpx.Response(200, json=TOOL_RESULT))
    body = {"filter": {"start": "2026-10-05", "end": "2026-11-15"}, "group_by": "modifier"}
    result = await port.claim_breakdown("STORE-A", body)
    assert result.eligible_orders == 2598
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer user-jwt"
    assert sent.headers["X-Request-ID"] == "req-1"
    assert sent.headers["X-Investigation-ID"] == "INV-1"
    assert "X-Service-Token" not in sent.headers
    assert httpx.Response(200, content=sent.content).json() == body


@respx.mock
async def test_internal_routes_add_the_service_token(port):
    route = respx.put(f"{BASE}/internal/cases/CASE-0001/investigation").mock(return_value=httpx.Response(200, json={}))
    await port.report_investigation_status(
        "CASE-0001", InvestigationStatusUpdate(investigation_id="INV-1", status="completed", error_code=None))
    sent = route.calls.last.request
    assert sent.headers["X-Service-Token"] == "svc-token"
    assert sent.headers["Authorization"] == "Bearer user-jwt"


@respx.mock
async def test_event_types_are_repeated_query_params(port):
    route = respx.get(f"{BASE}/stores/STORE-A/diagnostics/events").mock(
        return_value=httpx.Response(200, json={**TOOL_RESULT, "tool": "event_log"}))
    await port.event_log("STORE-A", "2026-10-05", "2026-11-15", ["menu_change", "promotion"])
    query = route.calls.last.request.url.params
    assert query.get_list("event_type") == ["menu_change", "promotion"]
    assert query["start"] == "2026-10-05"


@respx.mock
async def test_validation_errors_keep_the_envelope_code(port):
    respx.post(f"{BASE}/stores/STORE-A/diagnostics/claim-breakdown").mock(return_value=httpx.Response(
        422, json={"error": {"code": "VALIDATION_ERROR", "message": "Unknown modifier: Truffle oil", "details": {}}}))
    with pytest.raises(DomainError) as info:
        await port.claim_breakdown("STORE-A", {"filter": {}, "group_by": "modifier"})
    assert info.value.rejected and info.value.code == "VALIDATION_ERROR"
    assert "Truffle oil" in info.value.message


@respx.mock
async def test_server_errors_are_retried_then_reported_unavailable(port):
    route = respx.get(f"{BASE}/catalog/actions").mock(return_value=httpx.Response(503))
    with pytest.raises(DomainError) as info:
        await port.get_catalog()
    assert info.value.unavailable and info.value.code == "UPSTREAM_UNAVAILABLE"
    assert route.call_count == 3


@respx.mock
async def test_a_retry_can_succeed(port):
    route = respx.get(f"{BASE}/catalog/actions").mock(side_effect=[httpx.ConnectError("down"),
                                                                   httpx.Response(200, json=[])])
    assert await port.get_catalog() == []
    assert route.call_count == 2


@respx.mock
async def test_conflict_details_reach_the_caller(port):
    respx.post(f"{BASE}/internal/cases/CASE-0001/proposals").mock(return_value=httpx.Response(
        409, json={"error": {"code": "PROPOSAL_PENDING", "message": "pending", "details": {"proposal_id": "PROP-0007"}}}))
    from app.contracts.models import ActionContent, ProposalCreate, Target

    body = ProposalCreate(investigation_id="INV-1", kind="handoff", evidence_ids=[],
                          content=ActionContent(action_id="a", owner_team="pos_team", title="t", instructions="i",
                                                rationale="r", recheck_after_days=14,
                                                target=Target(item_id=[], modifiers=[], daypart=[], item_count_min=None)))
    with pytest.raises(DomainError) as info:
        await port.create_proposal("CASE-0001", body)
    assert info.value.status == 409 and info.value.details["proposal_id"] == "PROP-0007"
