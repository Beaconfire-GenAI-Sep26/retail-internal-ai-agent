from domain.tests.conftest import auth

H = auth()


def run(client, key, as_of="2026-11-15", headers=H):
    return client.post("/monitor/run", headers={**headers, "Idempotency-Key": key}, json={"as_of": as_of})


def test_monitor_opens_cases_only_for_problem_stores(client, clean_cases):
    r = run(client, "run-1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["evaluated_store_ids"]) == 10
    assert body["opened_case_ids"] == ["CASE-0001", "CASE-0002"]
    reasons = {s["store_id"]: s["reason"] for s in body["skipped"]}
    assert reasons["STORE-I"] == "low_volume"
    assert reasons["STORE-J"] == "below_threshold"

    cases = client.get("/cases", headers=H).json()
    assert sorted(c["store_id"] for c in cases) == ["STORE-A", "STORE-B"]
    for c in cases:
        assert c["status"] == "open"
        assert c["trigger_rule"] == "over_goal"
        assert c["eligible_orders"] >= 100
        assert abs(c["mi_rate"] - c["attributable_claims"] / c["eligible_orders"]) < 0.0001


def test_rerun_does_not_duplicate(client, clean_cases):
    first = run(client, "run-1").json()
    # same key: the stored response comes back
    assert run(client, "run-1").json() == first
    # new key: stores with an open case are skipped
    second = run(client, "run-2").json()
    assert second["opened_case_ids"] == []
    reasons = {s["store_id"]: s["reason"] for s in second["skipped"]}
    assert reasons["STORE-A"] == reasons["STORE-B"] == "open_case_exists"
    assert len(client.get("/cases", headers=H).json()) == 2


def test_monitor_needs_idempotency_key(client, clean_cases):
    r = client.post("/monitor/run", headers=H, json={})
    assert r.status_code == 422


def test_monitor_as_of_outside_data_is_422(client, clean_cases):
    assert run(client, "run-x", as_of="2027-01-01").status_code == 422


def test_case_detail_and_scoping(client, clean_cases):
    run(client, "run-1")
    detail = client.get("/cases/CASE-0001", headers=H).json()
    assert detail["store"]["store_id"] == detail["store_id"]
    assert len(detail["daily_rates"]) == 42
    assert detail["proposals"] == [] and detail["investigation_ids"] == []

    other = auth(store_ids=["STORE-C"])
    assert client.get("/cases/CASE-0001", headers=other).status_code == 404
    assert client.get("/cases", headers=other).json() == []
    assert client.get("/cases/CASE-9999", headers=H).json()["error"]["code"] == "CASE_NOT_FOUND"


def test_case_list_filters(client, clean_cases):
    run(client, "run-1")
    assert len(client.get("/cases?status=open", headers=H).json()) == 2
    assert client.get("/cases?status=closed", headers=H).json() == []
    assert [c["store_id"] for c in client.get("/cases?store_id=STORE-B", headers=H).json()] == ["STORE-B"]
    assert client.get("/cases?status=nonsense", headers=H).status_code == 422
