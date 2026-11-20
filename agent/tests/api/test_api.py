"""The Agent Service API through TestClient, in fixtures and memory mode."""

import asyncio
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.ids import CounterIdFactory
from agent.app.llm.base import ModelReply
from agent.app.llm.scripted_model import ScriptedReasonModel
from agent.app.main import create_app
from agent.tests.conftest import FIXTURES, TEST_SECRET, make_settings
from agent.tests.scripts import store_a_turns


def token(role="loe_analyst", stores=("STORE-A", "STORE-B"), ttl=3600, sub="USR-001", secret=TEST_SECRET):
    now = int(time.time())
    claims = {"sub": sub, "name": "Ana Analyst", "role": role, "store_ids": list(stores), "iss": "mi-auth",
              "iat": now, "exp": now + ttl}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(t):
    return {"Authorization": f"Bearer {t}"}


class BlockingModel:
    """Holds the first turn open so an investigation stays running."""

    name = "blocking"

    def __init__(self):
        self.release = asyncio.Event()

    async def reason(self, prompt, state):
        await self.release.wait()
        return ModelReply(output=None, raw_text="", model="blocking", stop_reason="end_turn")


def make_client(model=None, domain=None):
    app = create_app(make_settings(), domain_client=domain or FixtureDomainClient(FIXTURES),
                     model=model or ScriptedReasonModel(store_a_turns()), ids=CounterIdFactory(), configure_logs=False)
    return TestClient(app)


def wait_for(client, investigation_id, t, statuses=("completed", "unsure", "failed"), timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = client.get(f"/investigations/{investigation_id}", headers=auth(t)).json()
        if view["status"] in statuses:
            return view
        time.sleep(0.05)
    raise AssertionError(f"investigation {investigation_id} stayed {view['status']}")


def test_health_needs_no_token():
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok", "service": "agent"}


def test_post_starts_a_run_that_finishes():
    analyst = token()
    with make_client() as client:
        resp = client.post("/investigations", json={"case_id": "CASE-0001", "reopen_of": None}, headers=auth(analyst))
        assert resp.status_code == 202, resp.text
        view = resp.json()
        assert view["status"] == "running" and view["max_steps"] == 12 and view["started_by"] == "USR-001"
        assert resp.headers["X-Request-ID"]
        done = wait_for(client, view["investigation_id"], analyst)
        assert done["status"] == "completed"
        assert done["result"]["cause_category"] == "pos_modifier_mapping"
        assert done["pending_proposal_id"] == "PROP-0001"
        assert done["checks"][0]["tool"] == "store_overview"
        assert [h["status"] for h in done["hypotheses"]] == ["supported", "ruled_out", "ruled_out"]
        listed = client.get("/investigations", params={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        assert [v["investigation_id"] for v in listed] == [view["investigation_id"]]


def test_status_is_reported_to_domain_at_start_and_end():
    domain = FixtureDomainClient(FIXTURES)
    analyst = token()
    with make_client(domain=domain) as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, inv["investigation_id"], analyst)
    assert [u["status"] for u in domain.status_updates] == ["running", "completed"]


def test_the_jwt_never_reaches_the_checkpoint():
    analyst = token()
    with make_client() as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, inv["investigation_id"], analyst)
        graph = client.app.state.graph
        config = {"configurable": {"thread_id": inv["investigation_id"]}}

        async def dump():
            items = []
            async for snapshot in graph.aget_state_history(config):
                items.append(json.dumps(snapshot.values, default=str) + json.dumps(snapshot.metadata, default=str))
            return items

        history = client.portal.call(dump)
        assert history and not any(analyst in item for item in history)


@pytest.mark.parametrize(
    "headers, status, code",
    [
        ({}, 401, "UNAUTHENTICATED"),
        ({"Authorization": "Bearer not-a-jwt"}, 401, "UNAUTHENTICATED"),
        (auth(token(secret="another-secret-0123456789-0123456789")), 401, "UNAUTHENTICATED"),
        (auth(token(ttl=-10)), 401, "UNAUTHENTICATED"),
        (auth(token(ttl=60)), 401, "UNAUTHENTICATED"),
        (auth(token(role="viewer")), 403, "FORBIDDEN"),
    ],
)
def test_post_rejects_bad_callers(headers, status, code):
    with make_client() as client:
        resp = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=headers)
        assert resp.status_code == status
        body = resp.json()["error"]
        assert body["code"] == code and body["request_id"]


def test_unknown_or_unpermitted_cases_are_not_found():
    with make_client() as client:
        resp = client.post("/investigations", json={"case_id": "CASE-9999"}, headers=auth(token()))
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "CASE_NOT_FOUND"
        resp = client.post("/investigations", json={"case_id": "CASE-0003"}, headers=auth(token()))
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_a_second_run_on_an_active_case_conflicts():
    model = BlockingModel()
    analyst = token()
    with make_client(model=model) as client:
        first = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst))
        assert first.status_code == 202
        second = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst))
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "INVESTIGATION_ACTIVE"
        assert second.json()["error"]["details"]["investigation_id"] == first.json()["investigation_id"]


def test_reopen_needs_a_reopened_case():
    with make_client() as client:
        resp = client.post("/investigations", json={"case_id": "CASE-0001", "reopen_of": "INV-T0001"},
                           headers=auth(token()))
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "REOPEN_NOT_ALLOWED"


def test_invalid_bodies_use_the_error_envelope():
    with make_client() as client:
        resp = client.post("/investigations", json={"case": "CASE-0001"}, headers=auth(token()))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_reads_hide_other_stores_and_allow_viewers():
    analyst = token()
    with make_client() as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, inv["investigation_id"], analyst)
        viewer = token(role="viewer", stores=("STORE-A",))
        assert client.get(f"/investigations/{inv['investigation_id']}", headers=auth(viewer)).status_code == 200
        outsider = token(stores=("STORE-B",))
        resp = client.get(f"/investigations/{inv['investigation_id']}", headers=auth(outsider))
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "NOT_FOUND"
        assert client.get("/investigations", headers=auth(outsider)).json() == []


def test_request_id_is_echoed():
    with make_client() as client:
        resp = client.get("/health", headers={"X-Request-ID": "abc123"})
        assert resp.headers["X-Request-ID"] == "abc123"
