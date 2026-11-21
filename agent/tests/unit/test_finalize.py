"""One test per row of the finalize truth table, plus the confidence caps."""

from agent.app.graph.finalize import action_content, build_result, cap, decide
from agent.app.graph.gate import evaluate_gate
from agent.tests.unit.builders import EVENT_LOG, C, H, conclusion, passing_state


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


def test_contradicting_evidence_adds_what_pointed_to_other_causes():
    state = passing_state(hypotheses=[
        H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005", "EV-CLM-000101"), con=("EV-CLM-000102",)),
        H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000005", "EV-EVT-000006")),
        H("HYP-3", "dasher_handoff", "inconclusive", sup=("EV-CLM-000103",)),
    ])
    result = build_result(finished(state, "gate_passed", conclusion()), max_steps=12, invalid_ids={"EV-CLM-000103"})
    # The leader's own contradiction, then what pointed elsewhere. Shared support and failed citations drop out.
    assert result["contradicting_evidence_ids"] == ["EV-CLM-000102", "EV-EVT-000006"]


def test_counts_and_rates_no_check_shows_are_withheld():
    state = passing_state(case={"mi_rate": 0.0837, "baseline_rate": 0.053, "attributable_claims": 37,
                                "eligible_orders": 442})
    state["checks"][1]["result"]["metrics"] = [{"name": "claim_rate", "group": "modifier=Extra sauce", "value": 0.1932,
                                                "numerator": 103, "denominator": 533, "unit": "rate"}]
    action = conclusion()
    action["summary"] = ("Since Oct 30, Extra sauce claims ran at 19.3% (103/533) against 5.3% before, with 41 claims "
                         "on 2,104 orders elsewhere and 37 claims in the last week.")
    action["recommendation"] = {**action["recommendation"], "rationale": "The rate is 12.4% above the store's."}
    result = build_result(finished(state, "gate_passed", action), max_steps=12)
    assert result["summary"] == ("Since Oct 30, Extra sauce claims ran at 19.3% (103/533) against 5.3% before, with "
                                 "[withheld] claims on [withheld] orders elsewhere and 37 claims in the last week.")
    assert result["recommendation"]["rationale"] == "The rate is [withheld] above the store's."
    assert result["evidence_gaps"][-1] == "Withheld numbers that no check result shows: 41 claims, 2,104 orders, 12.4%."


def test_the_number_check_reads_records_thresholds_dates_and_n_of_m():
    state = passing_state()
    state["checks"][0]["result"]["evidence"] = [{"evidence_id": "EV-EVT-000007", "type": "operational_event",
                                                 "summary": "Promotion: 20% off family meals (Nov 3-9).",
                                                 "attributes": {}}]
    state["checks"][1]["result"]["metrics"] = [{"name": "claim_share", "group": "modifier=Extra sauce", "value": 0.8583,
                                                "numerator": 103, "denominator": 120, "unit": "share"}]
    action = conclusion()
    action["summary"] = ("The 20% off promotion ran Nov 3-9. Since Oct 30 orders with Extra sauce carry 103 of 120 "
                         "claims, and only 27 of 120 claims are pending. Groups under 30 eligible orders get no rate; "
                         "rates fell, marking 412 claims since the launch.")
    result = build_result(finished(state, "gate_passed", action), max_steps=12)
    assert result["summary"] == ("The 20% off promotion ran Nov 3-9. Since Oct 30 orders with Extra sauce carry 103 of "
                                 "120 claims, and only [withheld] of 120 claims are pending. Groups under 30 eligible "
                                 "orders get no rate; rates fell, marking [withheld] claims since the launch.")
    assert result["evidence_gaps"][-1] == "Withheld numbers that no check result shows: 27 of 120, 412 claims."


def test_cap_never_raises_confidence():
    assert cap("low", "medium") == "low"
    assert cap("high", "medium") == "medium"


def test_decide_defaults_to_unsure_without_an_end_reason():
    assert decide(passing_state())["outcome"] == "unsure"


def question(outcome, separates=("HYP-1", "HYP-2"), reply="EV-RPL-000001"):
    return {"proposal_id": "PROP-0001", "separates": list(separates), "outcome": outcome, "reply_evidence_id": reply}


def test_no_reply_to_a_question_about_the_leader_lowers_confidence_one_level():
    state = finished(passing_state(questions=[question("no_reply")]), "gate_passed", conclusion())
    result = build_result(state, max_steps=12)
    assert result["confidence"] == "medium"
    assert any("didn't answer question PROP-0001" in g for g in result["evidence_gaps"])
    # A question about other causes doesn't weaken the leader.
    other = finished(passing_state(questions=[question("no_reply", separates=("HYP-2",))]), "gate_passed",
                     conclusion())
    assert build_result(other, max_steps=12)["confidence"] == "high"


def test_a_reply_cited_against_the_leader_lowers_confidence_and_one_that_agrees_does_not():
    agrees = finished(passing_state(questions=[question("replied")]), "gate_passed", conclusion())
    assert build_result(agrees, max_steps=12)["confidence"] == "high"
    hypotheses = [H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005", "EV-CLM-000101"),
                    con=("EV-RPL-000001",)),
                  H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000006",))]
    state = finished(passing_state(hypotheses=hypotheses, questions=[question("replied")]), "gate_passed",
                     conclusion(confidence="medium"))
    result = build_result(state, max_steps=12)
    assert result["confidence"] == "low"
    assert "EV-RPL-000001" in result["contradicting_evidence_ids"]
    assert any("conflicts with the leading cause" in g for g in result["evidence_gaps"])


def test_action_content_fills_title_and_instructions_from_the_catalog():
    state = finished(passing_state(), "gate_passed", conclusion())
    result = build_result(state, max_steps=12)
    content = action_content(result, state)
    assert content["title"] == "Fix the mapping"
    assert "orders with the modifier Extra sauce" in content["instructions"]
    assert content["recheck_after_days"] == 14
