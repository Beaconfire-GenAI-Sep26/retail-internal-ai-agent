from domain.tests.conftest import auth

H = auth()
FULL = {"start": "2026-10-05", "end": "2026-11-15"}


def post(client, store, tool, body):
    return client.post(f"/stores/{store}/diagnostics/{tool}", headers=H, json=body)


def test_overview_rate_uses_eligible_orders_and_attributable_claims(client):
    r = client.get("/stores/STORE-A/overview", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == FULL
    rate = body["metrics"][0]
    assert rate["name"] == "claim_rate" and rate["group"] is None
    assert rate["denominator"] == body["eligible_orders"]
    labels = {m["group"]: m["value"] for m in body["metrics"] if m["group"] and m["group"].startswith("review_label=")}
    assert len(labels) == 4
    # numerator = store_fault + pending only; fraud and not_store_fault are excluded
    assert rate["numerator"] == labels["review_label=store_fault"] + labels["review_label=pending"]
    assert any("excluded by review_label" in n for n in body["notes"])
    assert len(body["evidence_ids"]) > 0


def test_modifier_breakdown_puts_extra_sauce_first(client):
    r = post(client, "STORE-A", "claim-breakdown", {"filter": FULL, "group_by": "modifier"})
    assert r.status_code == 200
    body = r.json()
    first = body["metrics"][0]
    assert first["group"] == "modifier=Extra sauce"
    assert [m["name"] for m in body["metrics"][:3]] == ["claim_rate", "claim_share", "order_share"]
    assert any("no modifier_detail" in n for n in body["notes"])
    # deterministic: the same request returns the same evidence order
    again = post(client, "STORE-A", "claim-breakdown", {"filter": FULL, "group_by": "modifier"}).json()
    assert again["evidence_ids"] == body["evidence_ids"]


def test_store_b_large_dinner_orders_stand_out(client):
    body = post(
        client,
        "STORE-B",
        "claim-breakdown",
        {"filter": {"start": "2026-11-03", "end": "2026-11-15", "daypart": ["dinner"]}, "group_by": "item_count"},
    ).json()
    assert body["metrics"][0]["group"] == "item_count=5+"


def test_small_groups_get_null_rate(client):
    body = post(client, "STORE-I", "claim-breakdown", {"filter": FULL, "group_by": "daypart"}).json()
    rates = [m for m in body["metrics"] if m["name"] == "claim_rate"]
    assert all(m["value"] is None for m in rates if m["denominator"] < 30)


def test_compare_periods_target_and_control(client):
    body = post(
        client,
        "STORE-A",
        "compare-periods",
        {"split_date": "2026-11-01", "days_before": 7, "days_after": 14, "target": {"modifiers": ["Extra sauce"]}},
    ).json()
    groups = [(m["name"], m["group"]) for m in body["metrics"]]
    assert groups == [
        ("rate_before", "target"),
        ("rate_after", "target"),
        ("rate_before", "control"),
        ("rate_after", "control"),
    ]
    target_after, control_after = body["metrics"][1]["value"], body["metrics"][3]["value"]
    assert target_after > control_after


def test_cancellation_breakdown(client):
    body = post(
        client, "STORE-A", "cancellation-breakdown", {"filter": FULL, "group_by": "cancellation_category"}
    ).json()
    assert body["metrics"][0]["group"] == "cancellation_category=item_out_of_stock"
    assert all(i.startswith("EV-CXL-") for i in body["evidence_ids"])


def test_evidence_sample_is_limited_and_filled(client):
    body = post(
        client,
        "STORE-A",
        "evidence-sample",
        {"evidence_type": "claim", "filter": {**FULL, "modifiers": ["Extra sauce"]}, "limit": 3},
    ).json()
    assert len(body["evidence"]) == 3
    assert body["evidence_ids"] == [e["evidence_id"] for e in body["evidence"]]
    assert all(e["attributes"]["modifier_detail"] == "Extra sauce" for e in body["evidence"])


def test_events_oldest_first(client):
    body = client.get("/stores/STORE-A/diagnostics/events", headers=H).json()
    times = [e["occurred_at"] for e in body["evidence"]]
    assert times == sorted(times)
    assert body["metrics"] == []


def test_fraud_signals_flags_the_seeded_cluster(client):
    # The seed gives one STORE-A customer_ref 5 pending claims (Nov 6-15).
    body = client.get("/stores/STORE-A/diagnostics/fraud-signals", headers=H).json()
    assert len(body["metrics"]) == 1
    flagged = body["metrics"][0]
    assert flagged["name"] == "claim_count" and flagged["group"].startswith("customer_ref=")
    assert flagged["value"] >= 4
    assert len(body["evidence_ids"]) == flagged["value"]
    assert body["pending_claims"] >= flagged["value"]


def test_fraud_signals_nothing_in_normal_store(client):
    body = client.get("/stores/STORE-C/diagnostics/fraud-signals", headers=H).json()
    assert body["metrics"] == [] and body["evidence_ids"] == []


def test_small_groups_do_not_make_whole_breakdown_insufficient(client):
    week = {"start": "2026-11-09", "end": "2026-11-15"}
    body = post(client, "STORE-A", "claim-breakdown", {"filter": week, "group_by": "item_id"}).json()
    assert body["data_sufficient"] is True
    assert any(m["name"] == "claim_rate" and m["value"] is None for m in body["metrics"])  # small item groups
    cxl = post(client, "STORE-A", "cancellation-breakdown", {"filter": FULL, "group_by": "item_id"}).json()
    assert cxl["data_sufficient"] is True


def test_unknown_values_are_422(client):
    cases = [
        {"filter": {**FULL, "item_id": ["ITEM-B-001"]}, "group_by": "item_id"},  # other store's item
        {"filter": {**FULL, "modifiers": ["Gold leaf"]}, "group_by": "modifier"},
        {"filter": {**FULL, "daypart": ["brunch"]}, "group_by": "daypart"},
        {"filter": {"start": "2026-09-01", "end": "2026-11-15"}, "group_by": "day"},  # before the data
        {"filter": FULL, "group_by": "color"},
        {"filter": {**FULL, "typo_field": 1}, "group_by": "day"},
    ]
    for body in cases:
        r = post(client, "STORE-A", "claim-breakdown", body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_compare_periods_empty_before_still_sufficient(client):
    # Extra sauce only exists from Oct 30, so the target has no "before" orders.
    body = post(
        client,
        "STORE-A",
        "compare-periods",
        {"split_date": "2026-10-30", "days_before": 14, "days_after": 14, "target": {"modifiers": ["Extra sauce"]}},
    ).json()
    assert body["metrics"][0]["value"] is None  # target rate_before
    assert body["data_sufficient"] is True
    assert any("no orders before" in n for n in body["notes"])


def test_null_modifier_claims_stay_in_claim_share_total(client):
    body = post(client, "STORE-A", "claim-breakdown", {"filter": FULL, "group_by": "modifier"}).json()
    overview = client.get("/stores/STORE-A/overview", headers=H).json()
    share = body["metrics"][1]
    assert share["name"] == "claim_share"
    assert share["denominator"] == overview["metrics"][0]["numerator"]  # all attributable claims
