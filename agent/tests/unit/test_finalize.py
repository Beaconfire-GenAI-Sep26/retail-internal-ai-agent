"""One test per row of the finalize truth table, plus the confidence caps."""

from app.graph.finalize import action_content, build_result, cap, decide
from app.graph.gate import evaluate_gate
from tests.unit.builders import EVENT_LOG, C, H, conclusion, passing_state


def finished(state, end_reason, action=None):
    state = {**state, "end_reason": end_reason, "next_action": action}
    if end_reason == "gate_passed":
        state["gate_result"] = evaluate_gate(state, action)
    return state


def test_gate_passed_gives_a_diagnosis_at_the_stated_confidence():
    state = finished(passing_state(), "gate_passed", conclusion())
    result = build_result(state, max_steps=12)
    assert result["outcome"] == "diagnosis"
    assert result["confidence"] == "high"
    assert result["cause_category"] == "pos_modifier_mapping"
    assert result["recommendation"]["owner_team"] == "pos_team"
    assert result["recommendation"]["recheck_after_days"] == 14
    assert result["ruled_out"][0]["cause_category"] == "menu_change"
    assert result["ruled_out"][0]["check_ids"] == ["CHK-T"]
    assert result["evidence_gaps"] == []


def test_budget_spent_conclusion_with_k1_k2_k5_is_a_capped_diagnosis():
    state = passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005",)),
                                      H("HYP-2", "menu_change", "open", sup=("EV-EVT-000006",))])
    state = finished(state, "budget_spent", conclusion())
    result = build_result(state, max_steps=3)
    assert result["outcome"] == "diagnosis"
    assert result["confidence"] == "medium"
    assert any(g.startswith("K3 not met") for g in result["evidence_gaps"])


def test_budget_spent_conclusion_without_a_challenge_is_unsure():
    state = passing_state(checks=[EVENT_LOG, C("CHK-T", "test", "claim_breakdown", {"HYP-1": "if_true"},
                                                discriminates=("HYP-1",))])
    result = build_result(finished(state, "budget_spent", conclusion()), max_steps=2)
    assert result["outcome"] == "unsure"
    assert result["recommendation"] is None
    assert "Failed rules: K2" in result["evidence_gaps"]


def test_budget_spent_on_a_check_is_unsure():
    result = build_result(finished(passing_state(), "budget_spent", {"type": "check", "plan": None}), max_steps=3)
    assert result["outcome"] == "unsure"
    assert result["evidence_gaps"][0] == "All 3 checks were used before the evidence supported a single cause."
    assert result["confidence"] == "low"


def test_guard_cap_is_unsure_with_the_failed_rules():
    state = finished(passing_state(guard_feedback={"rule_ids": ["G1", "G9"], "violations": []}), "guard_cap")
    result = build_result(state, max_steps=12)
    assert result["outcome"] == "unsure"
    assert "Failed rules: G1, G9" in result["evidence_gaps"]
    assert "Two outputs in a row broke the guard rules (G1, G9)." in result["summary"]


def test_gate_cap_is_unsure_with_the_unmet_conditions():
    state = passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "open"), H("HYP-2", "menu_change", "open")])
    action = conclusion()
    state = {**state, "end_reason": "gate_cap", "next_action": action, "gate_result": evaluate_gate(state, action)}
    result = build_result(state, max_steps=12)
    assert result["outcome"] == "unsure"
    assert any(g.startswith("K1:") for g in result["evidence_gaps"])


def test_reason_cap_is_unsure():
    result = build_result(finished(passing_state(), "reason_cap"), max_steps=12)
    assert result["outcome"] == "unsure"
    assert "reasoning turns" in result["evidence_gaps"][0]


def test_inconclusive_rival_caps_confidence_and_becomes_a_gap():
    state = passing_state(hypotheses=[
        H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005",)),
        H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000006",)),
        H("HYP-3", "dasher_handoff", "inconclusive", rationale="No Dasher data."),
    ])
    result = build_result(finished(state, "gate_passed", conclusion()), max_steps=12)
    assert result["confidence"] == "medium"
    assert result["evidence_gaps"] == ["dasher_handoff (HYP-3) stays inconclusive: No Dasher data."]


def test_support_resting_on_pending_claims_caps_confidence():
    state = passing_state()
    for c in state["checks"]:
        c["result"]["pending_claims"] = 8
    result = build_result(finished(state, "gate_passed", conclusion()), max_steps=12)
    assert result["confidence"] == "medium"


def test_unresolvable_citations_are_dropped_and_reported():
    state = finished(passing_state(), "gate_passed", conclusion())
    result = build_result(state, max_steps=12, invalid_ids={"EV-CLM-000101"})
    assert "EV-CLM-000101" not in result["supporting_evidence_ids"]
    assert result["evidence_gaps"][0].startswith("Dropped citations")


def test_cap_never_raises_confidence():
    assert cap("low", "medium") == "low"
    assert cap("high", "medium") == "medium"


def test_decide_defaults_to_unsure_without_an_end_reason():
    assert decide(passing_state())["outcome"] == "unsure"


def test_action_content_fills_title_and_instructions_from_the_catalog():
    state = finished(passing_state(), "gate_passed", conclusion())
    result = build_result(state, max_steps=12)
    content = action_content(result, state)
    assert content["title"] == "Fix the mapping"
    assert "orders with the modifier Extra sauce" in content["instructions"]
    assert content["recheck_after_days"] == 14
