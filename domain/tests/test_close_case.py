"""POST /cases/{id}/close: the analyst marks a case in analyst_review as resolved."""
import uuid

import pytest

from domain.tests.conftest import auth
from domain.tests.test_replies_rechecks import ANALYST, L_FIX, act_and_recheck, audit_actions, case_view, open_cases


@pytest.fixture
def cases(client, clean_cases):
    return open_cases(client)


def close(client, case_id, key=None, headers=None):
    return client.post(f"/cases/{case_id}/close",
                       headers={**(headers or ANALYST), "Idempotency-Key": key or str(uuid.uuid4())})


def to_analyst_review(client, cases):
    """STORE-L: two failed rechecks hand the case to an analyst (W-02)."""
    act_and_recheck(client, cases, "STORE-L", L_FIX)
    act_and_recheck(client, cases, "STORE-L", L_FIX)
    case_id = cases["STORE-L"]
    assert case_view(client, case_id)["status"] == "analyst_review"
    return case_id


def test_close_moves_analyst_review_to_closed_once(client, cases):
    case_id = to_analyst_review(client, cases)
    r = close(client, case_id, key="close-1")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed" and r.json()["case_id"] == case_id
    assert case_view(client, case_id)["status"] == "closed"
    assert audit_actions(client, case_id)[-1] == "case.closed"

    assert close(client, case_id, key="close-1").json() == r.json()  # replay: same result, nothing new
    assert audit_actions(client, case_id).count("case.closed") == 1
    again = close(client, case_id, key="close-2")
    assert again.status_code == 409 and again.json()["error"]["code"] == "CASE_NOT_CLOSABLE"


def test_only_analyst_review_can_be_closed(client, cases):
    r = close(client, cases["STORE-A"])  # open
    assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_NOT_CLOSABLE"
    assert r.json()["error"]["details"]["status"] == "open"
    assert case_view(client, cases["STORE-A"])["status"] == "open"


def test_close_access(client, cases):
    case_id = to_analyst_review(client, cases)
    viewer = close(client, case_id, headers=auth(role="viewer", store_ids=["STORE-L"]))
    assert viewer.status_code == 403
    other = close(client, case_id, headers=auth(store_ids=["STORE-A"]))
    assert other.status_code in (403, 404)
    no_key = client.post(f"/cases/{case_id}/close", headers=ANALYST)
    assert no_key.status_code == 422
    assert case_view(client, case_id)["status"] == "analyst_review"  # nothing changed
