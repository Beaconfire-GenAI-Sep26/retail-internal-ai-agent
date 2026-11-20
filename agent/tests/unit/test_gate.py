import copy

import pytest

from agent.app.graph.gate import checklist, evaluate_gate
from agent.tests.unit.builders import EVENT_LOG, C, H, conclusion, passing_state


def unmet(state, conclude=None):
    return [c["rule"] for c in evaluate_gate(state, conclude or conclusion())["unmet"]]


def test_a_complete_investigation_passes():
    result = evaluate_gate(passing_state(), conclusion())
    assert result["passed"], result["unmet"]


def with_checks(*checks):
    return passing_state(checks=[EVENT_LOG, *checks])


TEST = C("CHK-T", "test", "claim_breakdown", {"HYP-1": "if_true", "HYP-2": "if_false"}, discriminates=("HYP-1", "HYP-2"))


def challenge(**kw):
    base = dict(discriminates=("HYP-1",), challenges="HYP-1", signature="compare_periods||target(modifiers)")
    base.update(kw)
    matched = base.pop("matched", {"HYP-1": "if_true"})
    tool = base.pop("tool", "compare_periods")
    return C("CHK-C", "challenge", tool, matched, **base)


@pytest.mark.parametrize(
    "state, rule",
    [
        (passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "open", sup=("EV-EVT-000005",)),
                                   H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000006",))]), "K1"),
        (with_checks(TEST), "K2"),
        (with_checks(TEST, challenge(sufficient=False)), "K2"),
        (with_checks(TEST, challenge(tool="sample_evidence")), "K2"),
        (with_checks(TEST, challenge(matched={"HYP-1": "if_false"})), "K2"),
        (with_checks(TEST, challenge(signature=TEST["signature"])), "K2"),
        (passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005",)),
                                   H("HYP-2", "menu_change", "open", sup=("EV-EVT-000006",))]), "K3"),
        (passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005",)),
                                   H("HYP-2", "menu_change", "inconclusive", sup=("EV-EVT-000006",), rationale="")]),
         "K3"),
        (passing_state(checks=passing_state()["checks"][1:]), "K4"),
        (passing_state(hypotheses=[H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005",)),
                                   H("HYP-2", "menu_change", "ruled_out")]), "K4"),
    ],
)
def test_each_condition_can_fail(state, rule):
    assert rule in unmet(state)


def test_typed_event_log_doesnt_cover_the_span():
    state = passing_state()
    state["checks"][0] = copy.deepcopy(EVENT_LOG)
    state["checks"][0]["request"]["event_type"] = ["menu_change"]
    assert "K4" in unmet(state)


def test_leader_explains_a_fitting_event_only_near_the_rise():
    state = passing_state()
    assert "K4" not in unmet(state, conclusion(rise="2026-10-31"))
    assert "K4" in unmet(state, conclusion(rise="2026-11-02"))


def test_other_cause_needs_the_analyst_handoff():
    state = passing_state(hypotheses=[H("HYP-1", "other", "supported", sup=("EV-EVT-000005",)),
                                      H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000006",))])
    assert "K5" in unmet(state, conclusion(action_id="fix_modifier_mapping"))
    assert "K5" not in unmet(state, conclusion(action_id="analyst_review"))


def test_checklist_reports_progress_without_quoted_text():
    items = {c["rule"]: c for c in checklist(passing_state())}
    assert items["K1"]["ok"] and items["K2"]["ok"] and items["K3"]["ok"]
    empty = checklist(passing_state(hypotheses=[H("HYP-1", "packing", "open")]))
    assert empty == [{"rule": "K1", "ok": False, "detail": "no hypothesis is supported yet"}]
