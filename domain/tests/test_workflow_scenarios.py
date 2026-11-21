"""C-04: run workflow scenarios W-03, W-04 and W-05 from eval.workflow_scenarios.

Each test performs the scenario's steps, records what happened in the same order as the stored
`expected` list, and compares every value the row names. Changing a row in workflow_scenarios.py
changes what these tests demand. W-01 and W-02 need C-05 and B-04 and are not run here yet.
"""
import pytest
from sqlalchemy import func, select

from domain.app.db import SessionLocal
from domain.app.models import Dispatch, Proposal, WorkflowScenario
from domain.app.services import proposals as proposal_service
from domain.tests.conftest import auth
from domain.tests.test_proposals import ACTION, AGENT, ANALYST, claim_id, create, decide, user_only


@pytest.fixture
def case_a(client, clean_cases):
    """A fresh STORE-A case opened by the monitor (the same setup as test_proposals)."""
    r = client.post("/monitor/run", headers={**ANALYST, "Idempotency-Key": "t-c04"}, json={"as_of": "2026-11-15"})
    assert r.status_code == 200
    return client.get("/cases?store_id=STORE-A", headers=ANALYST).json()[0]["case_id"]


def expected(scenario_id: str) -> list[dict]:
    with SessionLocal() as s:
        row = s.get(WorkflowScenario, scenario_id)
    assert row is not None, f"{scenario_id} missing: run python -m domain.scripts.reset_and_seed"
    return row.expected


def check(scenario_id: str, observed: list[dict]):
    """Compare each stored expectation with what the test saw at the same step."""
    rows = expected(scenario_id)
    assert len(observed) == len(rows), f"{scenario_id}: {len(observed)} observations for {len(rows)} expectations"
    for want, got in zip(rows, observed):
        for key, value in want.items():
            if key == "then":
                continue
            assert key in got, f"{scenario_id} '{want['then']}': test did not record {key}"
            if key == "invalid_reasons":  # a set of reasons; order doesn't matter
                got[key], value = sorted(got[key]), sorted(value)
            assert got[key] == value, f"{scenario_id} '{want['then']}': {key} is {got[key]!r}, expected {value!r}"


def seen(r, **extra) -> dict:
    body = r.json() if r.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return {"status": r.status_code, "code": error["code"] if error else None, **extra}


def counts(case_id: str) -> dict:
    with SessionLocal() as s:
        pids = s.scalars(select(Proposal.proposal_id).where(Proposal.case_id == case_id)).all()
        sent = s.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.proposal_id.in_(pids))) if pids else 0
    return {"proposals": len(pids), "dispatches": sent}


def status_of(client, pid):
    return client.get(f"/proposals/{pid}", headers=ANALYST).json()["status"]


def test_scenarios_are_seeded():
    with SessionLocal() as s:
        ids = s.scalars(select(WorkflowScenario.scenario_id).order_by(WorkflowScenario.scenario_id)).all()
    assert ids == ["W-01", "W-02", "W-03", "W-04", "W-05"]


def test_w03_invalid_or_incomplete_input(client, case_a):
    # The bad proposals go first: once a proposal is pending, any new one gets 409 PROPOSAL_PENDING.
    unknown = create(client, case_a, content={**ACTION, "action_id": "call_the_ceo"})
    bad_evidence = create(client, case_a, evidence=[claim_id("STORE-C"), "EV-CLM-999999"])
    reasons = [i["reason"] for i in bad_evidence.json()["error"]["details"]["invalid"]]
    pid = create(client, case_a).json()["proposal_id"]  # the one valid proposal, used by the decision steps
    no_key = client.post(f"/proposals/{pid}/decision", headers=ANALYST, json={"version": 1, "decision": "approve"})
    no_field = client.post(f"/proposals/{pid}/decision", headers={**ANALYST, "Idempotency-Key": "w03"},
                           json={"version": 1})
    obs = [
        seen(no_key),
        seen(no_field),
        seen(unknown),
        seen(bad_evidence, invalid_reasons=reasons),
        seen(client.get("/cases/CASE-9999", headers=ANALYST)),
        {**counts(case_a), "proposal_status": status_of(client, pid)},
    ]
    check("W-03", obs)


def test_w04_unauthorized_or_cross_store_access(client, case_a):
    pid = create(client, case_a).json()["proposal_id"]
    other = auth(store_ids=["STORE-C"])
    viewer = auth(role="viewer", store_ids=["STORE-A"])
    obs = [
        seen(client.get(f"/cases/{case_a}", headers=other)),
        seen(client.get("/stores/STORE-A/overview", headers=other)),
        seen(decide(client, pid, 1, headers=other)),
    ]
    edit = client.post(f"/proposals/{pid}/versions", headers=viewer, json={"content": ACTION})
    approve = decide(client, pid, 1, headers=viewer)
    assert seen(edit) == seen(approve)  # both steps of the viewer row must give the same refusal
    obs.append(seen(approve))
    obs.append(seen(create(client, case_a, headers={**user_only(), **AGENT})))
    obs.append(seen(client.get(f"/cases/{case_a}")))
    obs.append({"dispatches": counts(case_a)["dispatches"], "proposal_status": status_of(client, pid)})
    check("W-04", obs)


def test_w05_dispatch_without_approval(client, case_a, monkeypatch):
    pid = create(client, case_a).json()["proposal_id"]
    obs = [{"dispatches": counts(case_a)["dispatches"]}]  # pending: nothing sent

    client.post(f"/proposals/{pid}/versions", headers=ANALYST, json={"content": {**ACTION, "title": "Edited"}})
    obs.append(seen(decide(client, pid, 1)))  # approve the old version 1

    obs.append(seen(client.post(f"/proposals/{pid}/dispatch", headers=ANALYST, json={})))

    def broken(*args):
        raise proposal_service.DispatchFailed("mock queue down")

    monkeypatch.setattr(proposal_service, "mock_send", broken)
    r = decide(client, pid, 2)
    monkeypatch.undo()
    audit = client.get(f"/cases/{case_a}/audit", headers=ANALYST).json()
    obs.append(seen(r, proposal_status=status_of(client, pid), audit_action=audit[-1]["action"]))

    assert decide(client, pid, 2, "reject").json()["status"] == "rejected"
    obs.append(seen(decide(client, pid, 2)))
    obs.append({"dispatches": counts(case_a)["dispatches"]})
    check("W-05", obs)
