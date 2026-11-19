from app.llm import schemas as w
from app.tools.registry import TOOLS, canonical_key, render_tool_catalog, signature, to_contract_request
from tests.scripts import breakdown, compare, cxl_filter, scope


def convert(request: dict):
    parsed = w.ReasonOutputWire.model_validate({
        "assessment": "", "matched": [], "hypothesis_updates": [], "new_hypotheses": [],
        "next_action": {"type": "check", "plan": {"kind": "explore", "purpose": "p", "discriminates": [],
                                                  "expectations": [], "challenges": "", "request": request}},
    })
    return to_contract_request(parsed.next_action.plan.request)


def test_empty_wire_values_are_dropped():
    tool, req = convert(breakdown("modifier", "2026-10-05", "2026-11-15"))
    assert tool == "claim_breakdown"
    assert req == {"filter": {"start": "2026-10-05", "end": "2026-11-15"}, "group_by": "modifier"}


def test_lists_are_sorted_and_default_labels_dropped():
    _, req = convert(breakdown("day", "2026-10-05", "2026-11-15", daypart=["dinner", "lunch"],
                               weekday=[4, 1, 4], review_label=["pending", "store_fault"]))
    assert req["filter"]["daypart"] == ["lunch", "dinner"]
    assert req["filter"]["weekday"] == [1, 4]
    assert "review_label" not in req["filter"]


def test_rest_of_store_control_becomes_null():
    _, req = convert(compare("2026-10-30", 14, 17, scope(modifiers=["Extra sauce"])))
    assert req["control"] is None
    assert req["target"] == {"modifiers": ["Extra sauce"]}


def test_scope_control_is_kept():
    request = compare("2026-11-03", 14, 13, scope(daypart=["dinner"], item_count_min=5))
    request["control_mode"] = "scope"
    request["control"] = scope(daypart=["lunch"], item_count_min=5)
    _, req = convert(request)
    assert req["control"] == {"daypart": ["lunch"], "item_count_min": 5}


def test_sample_variants_keep_their_evidence_type():
    tool, req = convert({"tool": "sample_evidence", "evidence_type": "cancellation",
                         "filter": cxl_filter("2026-10-05", "2026-11-15", cancellation_category=["too_busy"]),
                         "limit": 5})
    assert tool == "sample_evidence"
    assert req == {"evidence_type": "cancellation", "limit": 5,
                   "filter": {"start": "2026-10-05", "end": "2026-11-15", "cancellation_category": ["too_busy"]}}


def test_canonical_key_ignores_list_order():
    _, a = convert(breakdown("day", "2026-10-05", "2026-11-15", modifiers=["No onion", "Extra sauce"]))
    _, b = convert(breakdown("day", "2026-10-05", "2026-11-15", modifiers=["Extra sauce", "No onion"]))
    assert canonical_key("claim_breakdown", a) == canonical_key("claim_breakdown", b)


def test_signature_ignores_values_and_dates():
    _, a = convert(breakdown("modifier", "2026-10-05", "2026-11-15"))
    _, b = convert(breakdown("modifier", "2026-10-30", "2026-11-15"))
    _, c = convert(breakdown("modifier", "2026-10-30", "2026-11-15", daypart=["dinner"]))
    assert signature("claim_breakdown", a) == signature("claim_breakdown", b)
    assert signature("claim_breakdown", a) != signature("claim_breakdown", c)


def test_catalog_text_covers_every_model_tool_and_the_contract_rules():
    text = render_tool_catalog()
    for name in TOOLS:
        assert f"### {name}" in text
    assert "claims with no modifier_detail form no group" in text
    assert "FRAUD_MIN_PENDING_CLAIMS (4 by default)" in text
    assert "An empty target before period returns rate_before null" in text
