"""C-03: proposals, versions, decisions, mock dispatch, rechecks and audit."""
import uuid

import pytest
from sqlalchemy import func, select

from domain.app.db import SessionLocal
from domain.app.models import Dispatch, MIClaim
from domain.app.services import proposals as proposal_service
from domain.tests.conftest import auth

ANALYST = auth()  # conftest's auth() also carries the service token
# What the agent adds on its two internal writes (access.py): investigation and store context
AGENT = {"X-Investigation-ID": "INV-TEST1", "X-Store-ID": "STORE-A"}


def user_only(**kw):
    """A user's JWT without the service token: what a browser sends."""
    headers = auth(**kw)
    headers.pop("X-Service-Token")
    return headers
ACTION = {
    "action_id": "fix_modifier_mapping",
    "owner_team": "pos_team",
    "title": "Fix the Extra sauce modifier mapping",
    "instructions": "Check that Extra sauce maps to the right kitchen ticket line.",
    "rationale": "The rise starts Oct 30 and is limited to orders with Extra sauce.",
    "target": {"item_id": [], "modifiers": ["Extra sauce"], "daypart": [], "item_count_min": None},
    "recheck_after_days": 14,
}
QUESTION = {"question_text": "Did you change Extra sauce in the POS around Oct 30?", "why_asked": "Claims rose then."}


def claim_id(store: str) -> str:
    with SessionLocal() as s:
        return s.scalar(select(MIClaim.evidence_id).where(MIClaim.store_id == store).order_by(MIClaim.evidence_id))


def dispatch_count(proposal_id: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.proposal_id == proposal_id))


@pytest.fixture
def case_a(client, clean_cases):
    r = client.post("/monitor/run", headers={**ANALYST, "Idempotency-Key": "t-c03"}, json={"as_of": "2026-11-15"})
    assert r.status_code == 200
    cases = client.get("/cases?store_id=STORE-A", headers=ANALYST).json()
    return cases[0]["case_id"]


def create(client, case_id, kind="handoff", content=ACTION, evidence=None, headers=None):
    body = {"investigation_id": "INV-TEST1", "kind": kind, "content": content,
            "evidence_ids": evidence if evidence is not None else [claim_id("STORE-A")]}
    return client.post(f"/internal/cases/{case_id}/proposals", headers=headers or {**ANALYST, **AGENT}, json=body)


def decide(client, pid, version, decision="approve", key=None, headers=None):
    return client.post(f"/proposals/{pid}/decision",
                       headers={**(headers or ANALYST), "Idempotency-Key": key or str(uuid.uuid4())},
                       json={"version": version, "decision": decision, "note": None})


def case_status(client, case_id):
    return client.get(f"/cases/{case_id}", headers=ANALYST).json()["status"]


def test_internal_route_needs_service_token_context_and_store_grant(client, case_a):
    for headers in ({**user_only(), **AGENT}, {**ANALYST, **AGENT, "X-Service-Token": "wrong"}):
        r = create(client, case_a, headers=headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "SERVICE_TOKEN_INVALID"
    no_context = create(client, case_a, headers=ANALYST)  # no X-Investigation-ID / X-Store-ID
    assert no_context.status_code == 403
    no_jwt = create(client, case_a, headers={"X-Service-Token": ANALYST["X-Service-Token"], **AGENT})
    assert no_jwt.status_code == 401
    other = create(client, case_a, headers={**auth(store_ids=["STORE-C"]), **AGENT, "X-Store-ID": "STORE-C"})
    assert other.status_code == 403 and other.json()["error"]["code"] == "STORE_NOT_PERMITTED"
    missing = create(client, "CASE-9999")
    assert missing.status_code == 404


def test_evidence_resolve_is_agent_only(client):
    body = {"store_id": "STORE-A", "evidence_ids": [claim_id("STORE-A")]}
    browser = client.post("/evidence/resolve", headers=user_only(), json=body)
    assert browser.status_code == 403 and browser.json()["error"]["code"] == "SERVICE_TOKEN_INVALID"
    agent = client.post("/evidence/resolve", headers=ANALYST, json=body)
    assert agent.status_code == 200 and agent.json()["valid"] == body["evidence_ids"]


def test_create_starts_pending_v1_and_one_pending_per_case(client, case_a):
    r = create(client, case_a)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "pending" and p["version"] == 1 and p["dispatch"] is None
    assert p["proposal_id"].startswith("PROP-")
    assert case_status(client, case_a) == "awaiting_decision"
    again = create(client, case_a)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PROPOSAL_PENDING"
    assert again.json()["error"]["details"]["proposal_id"] == p["proposal_id"]  # the agent can recover it
    audit = client.get(f"/cases/{case_a}/audit", headers=ANALYST).json()
    assert [a["action"] for a in audit] == ["case.opened", "proposal.created"]
    assert audit[1]["actor_id"] == "svc_agent" and audit[1]["actor_role"] == "service"


def test_create_rejects_unknown_action_bad_evidence_and_wrong_kind(client, case_a):
    r = create(client, case_a, content={**ACTION, "action_id": "call_the_ceo"})
    assert r.json()["error"]["code"] == "UNKNOWN_ACTION"
    r = create(client, case_a, evidence=[claim_id("STORE-C"), "EV-CLM-999999"])
    assert r.json()["error"]["code"] == "INVALID_EVIDENCE"
    reasons = {i["evidence_id"]: i["reason"] for i in r.json()["error"]["details"]["invalid"]}
    assert reasons["EV-CLM-999999"] == "not_found" and "other_store" in reasons.values()
    r = create(client, case_a, kind="merchant_question", content=ACTION)
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = create(client, case_a, kind="intervention", content=ACTION)  # catalog says handoff
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = create(client, case_a, content={**ACTION, "target": {**ACTION["target"], "modifiers": ["No such"]}})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_edit_makes_new_version_and_old_version_is_stale(client, case_a):
    pid = create(client, case_a).json()["proposal_id"]
    r = client.post(f"/proposals/{pid}/versions", headers=ANALYST,
                    json={"content": {**ACTION, "title": "Fix Extra sauce mapping on the POS"}})
    assert r.status_code == 201 and r.json()["version"] == 2
    same = client.post(f"/proposals/{pid}/versions", headers=ANALYST,
                       json={"content": {**ACTION, "title": "Fix Extra sauce mapping on the POS"}})
    assert same.status_code == 200 and same.json()["version"] == 2  # identical text adds no version
    stale = decide(client, pid, 1)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_VERSION"
    assert stale.json()["error"]["details"]["current_version"] == 2
    assert dispatch_count(pid) == 0


def test_approve_dispatches_once_schedules_recheck_and_audits(client, case_a):
    pid = create(client, case_a).json()["proposal_id"]
    r = decide(client, pid, 1, key="click-1")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "approved" and p["decided_by"] == "USR-001"
    assert p["dispatch"]["channel"] == "mock_team_queue" and p["dispatch"]["owner_team"] == "pos_team"
    assert case_status(client, case_a) == "action_dispatched"

    # Retries: same key, then a new key with the same decision. Still one dispatch.
    assert decide(client, pid, 1, key="click-1").json() == p
    assert decide(client, pid, 1, key="click-2").json()["dispatch"]["dispatch_id"] == p["dispatch"]["dispatch_id"]
    assert dispatch_count(pid) == 1
    # A different decision, or an edit, after the decision is refused.
    assert decide(client, pid, 1, "reject").json()["error"]["code"] == "ALREADY_DECIDED"
    r = client.post(f"/proposals/{pid}/versions", headers=ANALYST, json={"content": ACTION})
    assert r.json()["error"]["code"] == "ALREADY_DECIDED"

    rechecks = client.get(f"/cases/{case_a}/rechecks", headers=ANALYST).json()
    assert len(rechecks) == 1 and rechecks[0]["status"] == "scheduled"
    before = rechecks[0]["before"]
    assert before["end"] == "2026-11-15" and before["start"] == "2026-11-02"
    assert before["eligible_orders"] > 0 and before["claims"] > 0

    actions = [a["action"] for a in client.get(f"/cases/{case_a}/audit", headers=ANALYST).json()]
    assert actions == ["case.opened", "proposal.created", "proposal.approved", "dispatch.sent", "recheck.scheduled"]
    detail = client.get(f"/cases/{case_a}", headers=ANALYST).json()
    assert detail["proposals"][0]["proposal_id"] == pid and len(detail["rechecks"]) == 1


def test_reject_never_dispatches(client, case_a):
    pid = create(client, case_a).json()["proposal_id"]
    r = decide(client, pid, 1, "reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["dispatch"] is None
    assert dispatch_count(pid) == 0
    assert case_status(client, case_a) == "analyst_review"
    assert decide(client, pid, 1, "approve").json()["error"]["code"] == "ALREADY_DECIDED"
    assert client.get(f"/cases/{case_a}/rechecks", headers=ANALYST).json() == []


def test_merchant_question_approve_and_reject(client, case_a):
    q1 = create(client, case_a, kind="merchant_question", content=QUESTION, evidence=[]).json()["proposal_id"]
    r = decide(client, q1, 1, "reject")
    assert r.json()["status"] == "rejected"
    assert case_status(client, case_a) == "investigating"  # the investigation goes on
    q2 = create(client, case_a, kind="merchant_question", content=QUESTION, evidence=[]).json()["proposal_id"]
    r = decide(client, q2, 1)
    assert r.json()["dispatch"]["channel"] == "mock_merchant"
    assert case_status(client, case_a) == "awaiting_merchant"
    assert client.get(f"/cases/{case_a}/rechecks", headers=ANALYST).json() == []  # questions get no recheck


def test_only_an_analyst_for_that_store_can_decide(client, case_a):
    pid = create(client, case_a).json()["proposal_id"]
    viewer = decide(client, pid, 1, headers=auth(role="viewer"))
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "FORBIDDEN"
    other = decide(client, pid, 1, headers=auth(store_ids=["STORE-C"]))
    assert other.status_code == 403  # access.py: writes outside the grants are 403
    assert other.json()["error"]["code"] == "STORE_NOT_PERMITTED"
    hidden = client.get(f"/proposals/{pid}", headers=auth(store_ids=["STORE-C"]))
    assert hidden.status_code == 404  # reads hide other stores' proposals
    no_key = client.post(f"/proposals/{pid}/decision", headers=ANALYST, json={"version": 1, "decision": "approve"})
    assert no_key.status_code == 422
    assert client.get(f"/proposals/{pid}", headers=ANALYST).json()["status"] == "pending"


def test_dispatch_failure_keeps_proposal_pending(client, case_a, monkeypatch):
    pid = create(client, case_a).json()["proposal_id"]

    def broken(*args):
        raise proposal_service.DispatchFailed("mock queue down")

    monkeypatch.setattr(proposal_service, "mock_send", broken)
    r = decide(client, pid, 1, key="click-x")
    assert r.status_code == 502 and r.json()["error"]["code"] == "DISPATCH_FAILED"
    assert client.get(f"/proposals/{pid}", headers=ANALYST).json()["status"] == "pending"
    assert dispatch_count(pid) == 0
    actions = [a["action"] for a in client.get(f"/cases/{case_a}/audit", headers=ANALYST).json()]
    assert actions[-1] == "dispatch.failed"

    monkeypatch.undo()
    assert decide(client, pid, 1, key="click-x").json()["status"] == "approved"  # the retry works


def test_investigation_status_maps_to_case_status(client, case_a):
    url = f"/internal/cases/{case_a}/investigation"
    h = {**ANALYST, **AGENT}  # X-Investigation-ID is only context for access.py; the body names the run
    r = client.put(url, headers=h, json={"investigation_id": "INV-1", "status": "running", "error_code": None})
    assert r.json()["status"] == "investigating" and r.json()["active_investigation_id"] == "INV-1"
    r = client.put(url, headers=h, json={"investigation_id": "INV-1", "status": "failed", "error_code": "LLM_TIMEOUT"})
    assert r.json()["status"] == "open" and r.json()["last_error"] == "LLM_TIMEOUT"
    assert r.json()["active_investigation_id"] is None
    client.put(url, headers=h, json={"investigation_id": "INV-2", "status": "running", "error_code": None})
    r = client.put(url, headers=h, json={"investigation_id": "INV-2", "status": "unsure", "error_code": None})
    assert r.json()["status"] == "analyst_review"
    assert client.get(f"/cases/{case_a}", headers=ANALYST).json()["investigation_ids"] == ["INV-2", "INV-1"]


def test_catalog_lists_actions(client):
    r = client.get("/catalog/actions", headers=ANALYST)
    ids = {a["action_id"]: a for a in r.json()}
    assert ids["fix_modifier_mapping"]["owner_team"] == "pos_team"
    assert ids["add_large_order_bag_check"]["kind"] == "intervention"
    assert len(ids["analyst_review"]["applies_to"]) == 7  # the fallback for every cause
    assert {a["kind"] for a in r.json()} == {"intervention", "handoff"}
