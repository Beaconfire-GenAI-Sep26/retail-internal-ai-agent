"""The Agent Service API through TestClient, in fixtures and memory mode."""

import asyncio
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agent.app.domain.client import DomainError
from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.ids import CounterIdFactory
from agent.app.llm.base import ModelError, ModelReply
from agent.app.llm.scripted_model import ScriptedReasonModel
from agent.app.main import create_app
from agent.tests.conftest import FIXTURES, TEST_SECRET, make_settings
from agent.tests.scripts import store_a_turns, store_b_question_turns


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


def make_client(model=None, domain=None, settings=None):
    app = create_app(settings or make_settings(), domain_client=domain or FixtureDomainClient(FIXTURES),
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


def test_a_pending_proposal_must_be_decided_before_a_new_run():
    domain = FixtureDomainClient(FIXTURES)
    analyst = token()
    with make_client(domain=domain) as client:
        first = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        assert wait_for(client, first["investigation_id"], analyst)["pending_proposal_id"] == "PROP-0001"
        again = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst))
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "PROPOSAL_PENDING"
        assert again.json()["error"]["details"]["proposal_id"] == "PROP-0001"
        assert len(client.get("/investigations", params={"case_id": "CASE-0001"}, headers=auth(analyst)).json()) == 1
    assert [u["status"] for u in domain.status_updates] == ["running", "completed"]  # nothing reported for the refusal


@pytest.mark.parametrize(("case_status", "starts"), [
    ("action_dispatched", False), ("analyst_review", False), ("closed", False),
    ("investigating", True),  # no run here: the agent lost it in a restart
])
def test_a_fresh_run_needs_a_case_nobody_has_decided(case_status, starts):
    domain = FixtureDomainClient(FIXTURES)
    domain.stores["STORE-A"].case.status = case_status
    with make_client(model=BlockingModel(), domain=domain) as client:
        resp = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(token()))
        if starts:
            assert resp.status_code == 202, resp.text
        else:
            assert resp.status_code == 409
            assert resp.json()["error"]["code"] == "CASE_NOT_STARTABLE"
            assert resp.json()["error"]["details"]["case_status"] == case_status


def test_a_run_stopped_by_a_shutdown_reports_agent_restarted():
    domain = FixtureDomainClient(FIXTURES)
    with make_client(model=BlockingModel(), domain=domain) as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(token())).json()
    # Leaving the block shuts the app down, which stops the run.
    assert domain.status_updates[-1] == {"case_id": "CASE-0001", "investigation_id": inv["investigation_id"],
                                         "status": "failed", "error_code": "AGENT_RESTARTED"}


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


# --- Status reports to Domain --------------------------------------------------------------------


def status_calls(domain):
    return [c for c in domain.calls if c["method"] == "report_investigation_status"]


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_a_missing_status_route_is_not_retried_on_every_poll():
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(404, "NOT_FOUND", "Not Found")})
    analyst = token()
    with make_client(domain=domain) as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, inv["investigation_id"], analyst)
        for _ in range(3):
            client.get(f"/investigations/{inv['investigation_id']}", headers=auth(analyst))
        assert client.app.state.store.get(inv["investigation_id"]).domain_sync_pending is False
    assert len(status_calls(domain)) == 2  # "running" at start and "completed" at the end, nothing more


def test_a_failed_status_report_is_retried_in_the_background_with_a_throttle(monkeypatch):
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    analyst = token()
    with make_client(domain=domain) as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        inv_id = inv["investigation_id"]
        view = wait_for(client, inv_id, analyst)  # its last read sees the finished row and schedules a flush
        assert view["status"] == "completed"
        runner = client.app.state.runner
        wait_until(lambda: not runner.flush_tasks)
        tried = len(status_calls(domain))
        assert tried == 3  # "running" at start, "completed" at the end, and the first background retry
        for _ in range(5):  # inside the throttle window: no new attempt
            client.get(f"/investigations/{inv_id}", headers=auth(analyst))
        wait_until(lambda: not runner.flush_tasks)
        assert len(status_calls(domain)) == tried
        assert client.app.state.store.get(inv_id).domain_sync_pending is True

        del domain.faults["report_investigation_status"]  # Domain is back
        monkeypatch.setattr("agent.app.runner.FLUSH_INTERVAL_SECONDS", 0)
        client.get(f"/investigations/{inv_id}", headers=auth(analyst))
        wait_until(lambda: client.app.state.store.get(inv_id).domain_sync_pending is False)
    assert domain.status_updates[-1]["status"] == "completed"


def test_a_new_investigation_drops_an_older_runs_unsent_status_report():
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    model = ScriptedReasonModel([*store_a_turns(), ModelError("INTERNAL", "second run stops here")])
    analyst = token()
    with make_client(model=model, domain=domain) as client:
        first = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, first["investigation_id"], analyst)
        store, runner = client.app.state.store, client.app.state.runner
        wait_until(lambda: not runner.flush_tasks)
        assert store.get(first["investigation_id"]).domain_sync_pending is True
        domain.proposals["PROP-0001"].status = "rejected"  # the analyst decides it before starting again
        second = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst))
        assert second.status_code == 202
        # The newer run owns the case status now, so the older report is never sent late.
        assert store.get(first["investigation_id"]).domain_sync_pending is False
        before = len(status_calls(domain))
        client.get(f"/investigations/{first['investigation_id']}", headers=auth(analyst))
        assert not runner.flush_tasks.get(first["investigation_id"])
        assert all(c["body"]["investigation_id"] != first["investigation_id"]
                   for c in status_calls(domain)[before:])


def test_a_viewer_read_never_schedules_a_status_write():
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    analyst, viewer = token(), token(role="viewer", stores=("STORE-A",))
    with make_client(domain=domain) as client:
        inv = client.post("/investigations", json={"case_id": "CASE-0001"}, headers=auth(analyst)).json()
        wait_for(client, inv["investigation_id"], viewer)
        for _ in range(3):
            client.get(f"/investigations/{inv['investigation_id']}", headers=auth(viewer))
        assert not client.app.state.runner.flush_tasks
        assert client.app.state.store.get(inv["investigation_id"]).domain_sync_pending is True
    assert len(status_calls(domain)) == 2  # the start and the end report only


def test_an_analysts_list_resends_a_failed_final_report():
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    analyst, viewer = token(), token(role="viewer", stores=("STORE-A",))
    case = {"case_id": "CASE-0001"}
    with make_client(domain=domain) as client:
        inv_id = client.post("/investigations", json=case, headers=auth(analyst)).json()["investigation_id"]
        wait_for(client, inv_id, viewer)  # a viewer's reads never resend, so the end report stays unsent
        store, runner = client.app.state.store, client.app.state.runner
        del domain.faults["report_investigation_status"]  # Domain is back
        sent = len(status_calls(domain))
        client.get("/investigations", params=case, headers=auth(viewer))
        assert not runner.flush_tasks and len(status_calls(domain)) == sent
        client.get("/investigations", params=case, headers=auth(analyst))  # the case page opens
        wait_until(lambda: store.get(inv_id).domain_sync_pending is False)
    assert domain.status_updates == [
        {"case_id": "CASE-0001", "investigation_id": inv_id, "status": "completed", "error_code": None}]


@pytest.mark.parametrize("read", ["by_id", "list"])
def test_no_read_resends_the_report_of_a_running_investigation(read):
    domain = FixtureDomainClient(FIXTURES, faults={
        "report_investigation_status": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    analyst = token()
    with make_client(model=BlockingModel(), domain=domain) as client:
        inv_id = client.post("/investigations", json={"case_id": "CASE-0001"},
                             headers=auth(analyst)).json()["investigation_id"]
        assert client.app.state.store.get(inv_id).domain_sync_pending is True  # the "running" report failed
        sent = len(status_calls(domain))
        if read == "by_id":
            client.get(f"/investigations/{inv_id}", headers=auth(analyst))
        else:
            client.get("/investigations", params={"case_id": "CASE-0001"}, headers=auth(analyst))
        # Only the run's own final report may follow a failed "running" one, so nothing is resent.
        assert not client.app.state.runner.flush_tasks and len(status_calls(domain)) == sent


# --- B-04: resume ---------------------------------------------------------------------------------


QUESTIONS_ON = make_settings(agent_max_questions=2)


class GatedModel(ScriptedReasonModel):
    """Holds turn `hold` open until `release` is set, so a resumed segment stays running."""

    def __init__(self, turns, hold):
        super().__init__(turns)
        self.hold = hold
        self.release = asyncio.Event()

    async def reason(self, prompt, state):
        if self.calls == self.hold:
            await self.release.wait()
        return await super().reason(prompt, state)


def reports(domain):
    return [u["status"] for u in domain.status_updates]


def test_a_question_pauses_the_run_and_resume_continues_it_only_when_domain_has_news():
    domain = FixtureDomainClient(FIXTURES)
    analyst = token()
    with make_client(model=ScriptedReasonModel(store_b_question_turns()), domain=domain,
                     settings=QUESTIONS_ON) as client:
        inv_id = client.post("/investigations", json={"case_id": "CASE-0002"},
                             headers=auth(analyst)).json()["investigation_id"]
        paused = wait_for(client, inv_id, analyst, statuses=("awaiting_approval",))
        pid = paused["pending_proposal_id"]
        assert domain.proposals[pid].kind == "merchant_question"

        def resume(t=analyst):
            return client.post(f"/investigations/{inv_id}/resume", headers={**auth(t), "Idempotency-Key": "k-1"})

        assert resume().json()["status"] == "awaiting_approval"  # nothing decided yet: nothing starts
        assert resume(token(role="viewer")).status_code == 403
        assert resume(token(stores=("STORE-A",))).json()["error"]["code"] == "STORE_NOT_PERMITTED"
        assert resume(token(ttl=60)).status_code == 401  # the resumed segment could outlive the token
        started = client.post("/investigations", json={"case_id": "CASE-0002"}, headers=auth(analyst))
        assert started.json()["error"]["code"] == "INVESTIGATION_ACTIVE"

        domain.decide(pid, "approve")
        assert resume().status_code == 202
        waiting = wait_for(client, inv_id, analyst, statuses=("awaiting_merchant",))
        assert waiting["pending_proposal_id"] == pid
        assert resume().json()["status"] == "awaiting_merchant"  # a repeat: still no reply, nothing starts
        assert reports(domain) == ["running", "awaiting_approval", "awaiting_merchant"]

        domain.record_reply(pid, "replied", "Large orders go out in two bags; the second is sometimes left behind.")
        assert resume().status_code == 202
        done = wait_for(client, inv_id, analyst)
        assert done["status"] == "completed" and done["pending_proposal_id"] == done["result"]["proposal_id"] != pid
        finished = resume()
        assert finished.status_code == 409 and finished.json()["error"]["code"] == "INVESTIGATION_FINISHED"
    assert reports(domain) == ["running", "awaiting_approval", "awaiting_merchant", "running", "completed"]


def test_a_resume_while_a_segment_runs_starts_nothing():
    domain = FixtureDomainClient(FIXTURES)
    analyst = token()
    turns = store_b_question_turns()
    model = GatedModel(turns, hold=len(turns) - 1)  # the turn after the reply
    with make_client(model=model, domain=domain, settings=QUESTIONS_ON) as client:
        inv_id = client.post("/investigations", json={"case_id": "CASE-0002"},
                             headers=auth(analyst)).json()["investigation_id"]
        pid = wait_for(client, inv_id, analyst, statuses=("awaiting_approval",))["pending_proposal_id"]
        domain.decide(pid, "approve")
        client.post(f"/investigations/{inv_id}/resume", headers=auth(analyst))
        wait_for(client, inv_id, analyst, statuses=("awaiting_merchant",))
        domain.record_reply(pid, "no_reply")
        first = client.post(f"/investigations/{inv_id}/resume", headers=auth(analyst))
        second = client.post(f"/investigations/{inv_id}/resume", headers=auth(analyst))
        assert first.json()["status"] == second.json()["status"] == "running"
        assert len(client.app.state.runner.tasks) == 1
        client.portal.call(model.release.set)
        assert wait_for(client, inv_id, analyst)["status"] == "completed"
    assert reports(domain).count("running") == 2  # the start, and one resume after the reply
