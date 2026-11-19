from sqlalchemy import select

from app.db import SessionLocal
from app.models import MIClaim
from tests.conftest import auth, make_token


def a_store_a_claim() -> str:
    with SessionLocal() as s:
        return s.scalar(select(MIClaim.evidence_id).where(MIClaim.store_id == "STORE-A").order_by(MIClaim.evidence_id))


def test_missing_token_is_401_with_envelope(client):
    r = client.get("/cases")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"]


def test_bad_signature_and_wrong_issuer_are_401(client):
    forged = make_token() + "x"
    assert client.get("/cases", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    other_iss = make_token(iss="someone-else")
    assert client.get("/cases", headers={"Authorization": f"Bearer {other_iss}"}).status_code == 401


def test_expired_token_is_401(client):
    old = make_token(exp=1)
    r = client.get("/cases", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401


def test_store_outside_grants_is_403(client):
    r = client.get("/stores/STORE-B/overview", headers=auth(store_ids=["STORE-A"]))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "STORE_NOT_PERMITTED"


def test_unknown_store_in_grants_is_404(client):
    r = client.get("/stores/STORE-Z", headers=auth(store_ids=["STORE-Z"]))
    assert r.status_code == 404


def test_viewer_cannot_run_monitor(client):
    r = client.post("/monitor/run", headers={**auth(role="viewer"), "Idempotency-Key": "k1"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_evidence_of_other_store_is_404(client):
    claim = a_store_a_claim()
    assert client.get(f"/evidence/{claim}", headers=auth(store_ids=["STORE-A"])).status_code == 200
    assert client.get(f"/evidence/{claim}", headers=auth(store_ids=["STORE-B"])).status_code == 404


def test_evidence_resolve(client):
    claim = a_store_a_claim()
    r = client.post(
        "/evidence/resolve",
        headers=auth(),
        json={"store_id": "STORE-B", "evidence_ids": [claim, "EV-CLM-999999"]},
    )
    assert r.status_code == 200
    assert r.json() == {
        "valid": [],
        "invalid": [
            {"evidence_id": claim, "reason": "other_store"},
            {"evidence_id": "EV-CLM-999999", "reason": "not_found"},
        ],
    }
