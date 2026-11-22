"""C-05: merchant replies (mock merchant + no_reply) and running rechecks on the future snapshot."""
import uuid

import pytest

from domain.tests.conftest import auth
from domain.tests.test_proposals import claim_id

STORES = [f"STORE-{c}" for c in "ABCDEFGHIJKLM"]
ANALYST = auth(store_ids=STORES)  # the conftest default only covers A-J
QUESTION = {"question_text": "How are large dinner orders bagged?", "why_asked": "Missing items rose on dinner orders."}


def action(action_id, owner_team, days=14, **target):
    return {"action_id": action_id, "owner_team": owner_team, "title": "Fix it", "instructions": "Do the fix.",
            "rationale": "The rise matches this target.", "recheck_after_days": days,
            "target": {"item_id": [], "modifiers": [], "daypart": [], "item_count_min": None, **target}}


A_FIX = action("fix_modifier_mapping", "pos_team", modifiers=["Extra sauce"])
B_FIX = action("add_large_order_bag_check", "merchant", daypart=["dinner"], item_count_min=5)
L_FIX = action("review_dasher_handoff", "dasher_ops")
M_FIX = action("send_to_fraud_review", "fraud_review", days=7)


def open_cases(client) -> dict[str, str]:
    """Open the seeded cases (A, B, K, L, M) and return {store_id: case_id}."""
    r = client.post("/monitor/run", headers={**ANALYST, "Idempotency-Key": "t-c05"}, json={"as_of": "2026-11-15"})
    assert r.status_code == 200
    return {c["store_id"]: c["case_id"] for c in client.get("/cases", headers=ANALYST).json()}


@pytest.fixture
def cases(client, clean_cases):
    return open_cases(client)


def k_fix(client):
    item = next(m["item_id"] for m in client.get("/stores/STORE-K/menu", headers=ANALYST).json()
                if m["name"] == "Carne Asada Tacos (3)")
    return action("update_item_availability", "merchant", item_id=[item])


def propose(client, case_id, store_id, content, kind=None):
    kind = kind or ("merchant_question" if "question_text" in content
                    else "intervention" if content["owner_team"] == "merchant" else "handoff")
    headers = {**ANALYST, "X-Investigation-ID": "INV-C05", "X-Store-ID": store_id}
    r = client.post(f"/internal/cases/{case_id}/proposals", headers=headers,
                    json={"investigation_id": "INV-C05", "kind": kind, "content": content,
                          "evidence_ids": [] if kind == "merchant_question" else [claim_id(store_id)]})
    assert r.status_code == 201, r.text
    return r.json()["proposal_id"]


def approve(client, pid):
    r = client.post(f"/proposals/{pid}/decision", headers={**ANALYST, "Idempotency-Key": str(uuid.uuid4())},
                    json={"version": 1, "decision": "approve", "note": None})
    assert r.status_code == 200, r.text
    return r.json()


def reply(client, pid, outcome="no_reply", text=None, key=None, headers=None):
    return client.post(f"/proposals/{pid}/merchant-reply",
                       headers={**(headers or ANALYST), "Idempotency-Key": key or str(uuid.uuid4())},
                       json={"outcome": outcome, "text": text})


def replies(client, case_id):
    return client.get(f"/cases/{case_id}/merchant-replies", headers=ANALYST).json()


def scheduled(client, case_id):
    return next(r for r in client.get(f"/cases/{case_id}/rechecks", headers=ANALYST).json() if r["status"] == "scheduled")


def run(client, recheck_id, key=None, headers=None):
    return client.post(f"/rechecks/{recheck_id}/run",
                       headers={**(headers or ANALYST), "Idempotency-Key": key or str(uuid.uuid4())})


def case_view(client, case_id):
    return client.get(f"/cases/{case_id}", headers=ANALYST).json()


def act_and_recheck(client, cases, store_id, content):
    """Approve an action on the store's case and run its recheck. Returns the recheck."""
    approve(client, propose(client, cases[store_id], store_id, content))
    r = run(client, scheduled(client, cases[store_id])["recheck_id"])
    assert r.status_code == 200, r.text
    return r.json()


def audit_actions(client, case_id):
    return [a["action"] for a in client.get(f"/cases/{case_id}/audit", headers=ANALYST).json()]


# ---------------------------------------------------------------------------
# Merchant replies
# ---------------------------------------------------------------------------
def test_dispatched_question_gets_the_mock_merchant_answer(client, cases):
    case_b = cases["STORE-B"]
    pid = propose(client, case_b, "STORE-B", QUESTION)
    assert replies(client, case_b) == []  # nothing before approval
    approve(client, pid)
    assert case_view(client, case_b)["status"] == "awaiting_merchant"  # the agent's resume moves it on

    [r] = replies(client, case_b)
    assert r["proposal_id"] == pid and r["outcome"] == "replied" and r["recorded_by"] == "svc_mock_merchant"
    assert r["evidence_id"].startswith("EV-RPL-") and "two bags" in r["text"]
    ev = client.get(f"/evidence/{r['evidence_id']}", headers=ANALYST).json()
    assert ev["type"] == "merchant_reply" and ev["store_id"] == "STORE-B"
    resolved = client.post("/evidence/resolve", headers=ANALYST,
                           json={"store_id": "STORE-B", "evidence_ids": [r["evidence_id"]]}).json()
    assert resolved["valid"] == [r["evidence_id"]]  # the agent can cite it
    assert audit_actions(client, case_b)[-1] == "merchant_reply.recorded"

    again = reply(client, pid)
    assert again.status_code == 409 and again.json()["error"]["code"] == "REPLY_EXISTS"


def test_no_reply_is_recorded_once_and_replays_return_the_first_result(client, cases):
    case_k = cases["STORE-K"]
    pid = propose(client, case_k, "STORE-K", QUESTION)
    early = reply(client, pid)
    assert early.status_code == 409 and early.json()["error"]["code"] == "NOT_DISPATCHED"
    approve(client, pid)
    assert replies(client, case_k) == []  # STORE-K's merchant never answers

    viewer = reply(client, pid, headers=auth(role="viewer", store_ids=["STORE-K"]))
    assert viewer.status_code == 403
    bad = reply(client, pid, outcome="no_reply", text="but some text")
    assert bad.status_code == 422
    missing_text = reply(client, pid, outcome="replied", text="  ")
    assert missing_text.status_code == 422

    first = reply(client, pid, key="click-1")
    assert first.status_code == 201 and first.json()["outcome"] == "no_reply" and first.json()["text"] is None
    assert reply(client, pid, key="click-1").json() == first.json()  # replay: same result, nothing new
    assert len(replies(client, case_k)) == 1
    assert reply(client, pid, key="click-2").json()["error"]["code"] == "REPLY_EXISTS"


def test_only_merchant_questions_take_replies(client, cases):
    pid = propose(client, cases["STORE-A"], "STORE-A", A_FIX)
    approve(client, pid)
    r = reply(client, pid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_DISPATCHED"


# ---------------------------------------------------------------------------
# Rechecks
# ---------------------------------------------------------------------------
def test_improved_recheck_closes_the_case_and_runs_once(client, cases):
    case_a = cases["STORE-A"]
    approve(client, propose(client, case_a, "STORE-A", A_FIX))
    rk = scheduled(client, case_a)
    r = run(client, rk["recheck_id"], key="run-1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "improved" and out["data_sufficient"] is True and out["ran_at"]
    # Same-length windows: before = the last 14 days of data, after = the first 14 days after it
    assert (out["before"]["start"], out["before"]["end"]) == ("2026-11-02", "2026-11-15")
    assert (out["after"]["start"], out["after"]["end"]) == ("2026-11-16", "2026-11-29")
    assert out["after"]["rate"] < out["before"]["rate"] / 2
    assert out["control"]["eligible_orders"] > 0  # orders without Extra sauce, the unaffected comparison
    case = case_view(client, case_a)
    assert case["status"] == "closed" and case["reopen_count"] == 0
    assert audit_actions(client, case_a)[-1] == "recheck.improved"

    assert run(client, rk["recheck_id"], key="run-1").json() == out  # replay
    again = run(client, rk["recheck_id"], key="run-2")
    assert again.status_code == 409 and again.json()["error"]["code"] == "RECHECK_ALREADY_RUN"


def test_failed_recheck_reopens_once_then_the_next_one_can_improve(client, cases):
    first = act_and_recheck(client, cases, "STORE-B", B_FIX)
    assert first["status"] == "not_improved" and first["data_sufficient"] is True
    case = case_view(client, cases["STORE-B"])
    assert case["status"] == "reopened" and case["reopen_count"] == 1

    second = act_and_recheck(client, cases, "STORE-B", B_FIX)  # the next investigation's action
    assert second["after"]["start"] == "2026-11-30"  # the weeks after the first recheck's window
    assert second["status"] == "improved"
    assert case_view(client, cases["STORE-B"])["status"] == "closed"


def test_too_few_orders_pauses_and_whole_store_targets_have_no_control(client, cases):
    k = act_and_recheck(client, cases, "STORE-K", k_fix(client))
    assert k["status"] == "insufficient_data" and k["data_sufficient"] is False and k["after"]["rate"] is None
    assert case_view(client, cases["STORE-K"])["status"] == "paused"

    m = act_and_recheck(client, cases, "STORE-M", M_FIX)  # 7-day recheck on the whole store
    assert m["status"] == "improved" and m["control"] is None
    assert (m["after"]["start"], m["after"]["end"]) == ("2026-11-16", "2026-11-22")


def test_recheck_access(client, cases):
    approve(client, propose(client, cases["STORE-A"], "STORE-A", A_FIX))
    rk = scheduled(client, cases["STORE-A"])["recheck_id"]
    viewer = run(client, rk, headers=auth(role="viewer", store_ids=["STORE-A"]))
    assert viewer.status_code == 403 and viewer.json()["error"]["code"] == "FORBIDDEN"
    other = run(client, rk, headers=auth(store_ids=["STORE-C"]))
    assert other.status_code == 403 and other.json()["error"]["code"] == "STORE_NOT_PERMITTED"
    no_key = client.post(f"/rechecks/{rk}/run", headers=ANALYST)
    assert no_key.status_code == 422
    assert scheduled(client, cases["STORE-A"])["recheck_id"] == rk  # still scheduled


def test_agent_tools_never_see_the_future(client, cases):
    """The future snapshot is for rechecks only: the store's data still ends on Nov 15."""
    r = client.post("/stores/STORE-A/diagnostics/claim-breakdown", headers=ANALYST,
                    json={"filter": {"start": "2026-11-10", "end": "2026-11-20"}, "group_by": "daypart"})
    assert r.status_code == 422 and r.json()["error"]["details"]["data_end"] == "2026-11-15"
