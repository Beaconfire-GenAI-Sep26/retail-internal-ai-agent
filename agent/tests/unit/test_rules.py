"""Guard rules, table-driven against states captured from real fixture runs.

STORE-A IDs are deterministic: HYP-T0001 pos_modifier_mapping, HYP-T0002 menu_change,
HYP-T0003 inventory; CHK-T0001 overview, CHK-T0002 fraud signals, CHK-T0003 event_log,
CHK-T0004 the modifier breakdown.
"""

import copy

import pytest

from agent.app.graph.rules import evaluate_output
from agent.app.ids import CounterIdFactory
from agent.tests.conftest import capture_state
from agent.tests.scripts import (
    FULL,
    ask,
    breakdown,
    check,
    compare,
    conclude,
    event_log_request,
    exp,
    new,
    out,
    scope,
    store_a_turns,
    store_b_turns,
    upd,
)

POS, MENU, INV = "HYP-T0001", "HYP-T0002", "HYP-T0003"


@pytest.fixture(scope="module")
def a_first():
    import asyncio

    return asyncio.run(capture_state("STORE-A", []))


@pytest.fixture(scope="module")
def a_matched():
    """The turn after the modifier breakdown ran: matched is due for POS and MENU."""
    import asyncio

    return asyncio.run(capture_state("STORE-A", store_a_turns()[:2]))


@pytest.fixture(scope="module")
def b_matched():
    import asyncio

    return asyncio.run(capture_state("STORE-B", store_b_turns()[:2]))


def run(state, raw, **kw):
    params = {"max_steps": 12, "max_questions": 0, "ids": CounterIdFactory()}
    params.update(kw)
    return evaluate_output(copy.deepcopy(state), raw, **params)


def resolved(turn, state):
    """Resolve @-placeholders the way the scripted model does."""
    from agent.app.llm.scripted_model import _resolve

    return _resolve(copy.deepcopy(turn), state)


TWO = [new("N1", "pos_modifier_mapping", "A modifier is not reaching the kitchen."),
       new("N2", "menu_change", "A menu change confuses the kitchen.")]
EXPLORE = check("explore", "Read the events.", event_log_request())


def test_valid_first_turn_is_accepted(a_first):
    d = run(a_first, store_a_turns()[0])
    assert d.accepted, d.violations
    assert [h["status"] for h in d.hypotheses] == ["open", "open", "open"]
    assert d.action["plan"]["tool"] == "event_log"


FIRST_TURN_CASES = [
    ("G8", out("x", EXPLORE, new_hypotheses=TWO[:1])),
    ("G2", out("x", EXPLORE, new_hypotheses=[*TWO, new("N3", "menu_change", "Another menu change hypothesis.")])),
    ("G2", out("x", EXPLORE, new_hypotheses=[*TWO, new("N3", "other", "Too vague.")])),
    ("G2", out("x", EXPLORE, new_hypotheses=[new("HYP-1", "packing", "Large orders miss items."), TWO[1]])),
    ("G2", out("x", EXPLORE, new_hypotheses=TWO, updates=[upd("HYP-NOPE", "open", "r")])),
    ("G1", out("x", EXPLORE, new_hypotheses=[new("N1", "packing", "s", evidence=["EV-CLM-999999"]), TWO[1]])),
    ("G9", out("x", EXPLORE, new_hypotheses=TWO, matched=[("N1", "if_true")])),
    ("G10", out("x", check("explore", "p", compare("2026-11-01", 30, 7, scope(modifiers=["Extra sauce"]))),
                new_hypotheses=TWO)),
    ("G10", out("x", check("explore", "p", breakdown("day", "2026-11-15", "2026-10-05")), new_hypotheses=TWO)),
    ("G10", out("x", check("explore", "p", breakdown("day", *FULL, weekday=[7])), new_hypotheses=TWO)),
    # rest_of_store with a claim-only target: Domain's control would have no orders.
    ("G10", out("x", check("explore", "p", compare("2026-10-30", 14, 17, scope(error_category=["incorrect_item"]))),
                new_hypotheses=TWO)),
    ("G10", out("x", check("explore", "p", breakdown("day", "Oct 5", "2026-11-15")), new_hypotheses=TWO)),
    ("G11", out("x", check("explore", "p", breakdown("day", *FULL, modifiers=["Truffle oil"])), new_hypotheses=TWO)),
    ("G11", out("x", check("explore", "p", breakdown("day", "2026-09-01", "2026-11-15")), new_hypotheses=TWO)),
    ("G11", out("x", check("explore", "p", compare("2026-10-30", 28, 17, scope(modifiers=["Extra sauce"]))),
                new_hypotheses=TWO)),
    ("G12", out("x", check("test", "p", breakdown("modifier", *FULL)), new_hypotheses=TWO)),
    ("G12", out("x", check("test", "p", breakdown("modifier", *FULL), ["N1"], [exp("N2", "a", "b")]),
                new_hypotheses=TWO)),
    ("G12", out("x", check("challenge", "p", breakdown("modifier", *FULL), ["N1"], [exp("N1", "a", "b")]),
                new_hypotheses=TWO)),
    ("G12", out("x", check("explore", "p", breakdown("modifier", *FULL), challenges="N1"), new_hypotheses=TWO)),
    ("G14", out("x", check("explore", "p", {"tool": "store_overview", "start": FULL[0], "end": FULL[1]}),
                new_hypotheses=TWO)),
    ("G16", out("x", {"type": "ask_merchant", "question_text": "How do you bag large orders?",
                      "why_asked": "Separates packing from handoff.", "separates": ["N1", "N2"]},
                new_hypotheses=TWO)),
    ("P1", out("x", EXPLORE, new_hypotheses=[new("N1", "packing", "Email ops@example.com about it."), TWO[1]])),
    ("SCHEMA", {"assessment": "missing fields"}),
]


@pytest.mark.parametrize("rule, raw", FIRST_TURN_CASES)
def test_first_turn_rules(a_first, rule, raw):
    d = run(a_first, raw)
    assert rule in d.rule_ids, d.violations


# --- Merchant questions (G16, G17, P1), with questions on ---------------------------------------


def ask_out(question="How are large orders bagged?", why="Separates packing from a menu change.",
            separates=("N1", "N2")):
    return out("x", ask(question, why, list(separates)), new_hypotheses=TWO)


@pytest.fixture
def asking(a_first):
    """The first turn with questions available. The fixture Domain has no reply route, so load_case turned them off."""
    return {**a_first, "questions_asked": 0}


QUESTION_CASES = [
    ("G17", ask_out(question="Tell me how large orders are bagged.")),  # no question mark
    ("G17", ask_out(question="x" * 299 + "??")),  # 301 characters
    ("G17", ask_out(why="")),
    ("G17", ask_out(separates=())),
    ("G17", ask_out(separates=("N1", "N1"))),
    ("G17", ask_out(separates=("HYP-NOPE",))),
    ("P1", ask_out(question="Did you change the menu for Extra sauce?")),
    ("P1", ask_out(question="When Extra sauce ran out, did you disable it?")),
]


@pytest.mark.parametrize("rule, raw", QUESTION_CASES)
def test_question_rules(asking, rule, raw):
    assert rule in run(asking, raw, max_questions=2).rule_ids


def test_a_clear_question_is_accepted_with_its_hypotheses_resolved(asking):
    # The wording rule 7 of the system prompt suggests must pass P1.
    d = run(asking, ask_out(question="Since the last menu change, does the new modifier print on kitchen tickets?"),
            max_questions=2)
    assert d.accepted, d.violations
    assert d.action["separates"] == [d.new_ids["N1"], d.new_ids["N2"]]


def test_g16_blocks_a_repeat_an_open_question_and_a_question_with_no_turn_left(asking):
    assert "G16" not in run(asking, ask_out(), max_questions=2).rule_ids
    repeat = {**asking, "questions": [{"question_text": "how are LARGE orders bagged ?"}]}
    edited = {**asking, "questions": [{"question_text": "Something else?", "approved_text": "How are large orders bagged?"}]}
    open_one = {**asking, "question_open": True}
    late = {**asking, "reason_calls": 28}
    assert "G16" in run(repeat, ask_out(), max_questions=2).rule_ids
    assert "G16" in run(edited, ask_out(), max_questions=2).rule_ids  # the version the analyst sent counts too
    assert "G16" in run(open_one, ask_out(), max_questions=2).rule_ids
    assert "G16" in run(late, ask_out(), max_questions=2, max_reason_calls=28).rule_ids


def test_g7_a_reply_alone_cant_make_a_hypothesis_supported(a_matched):
    state = copy.deepcopy(a_matched)
    state["retrieved_evidence_ids"] = [*state["retrieved_evidence_ids"], "EV-RPL-000001"]
    inventory = next(h["hypothesis_id"] for h in state["hypotheses"] if h["cause_category"] == "inventory")
    raw = out("The merchant says the sauce ran out.", EXPLORE, new_hypotheses=[],
              updates=[upd(inventory, "supported", "The merchant confirmed it.", ["EV-RPL-000001"])])
    assert "G3" in run(state, raw).rule_ids  # no check supports it, and a reply is not a check


def test_g6_a_cause_the_earlier_run_ruled_out_needs_evidence_from_this_runs_checks(a_matched):
    earlier = {"hypothesis_id": "HYP-OLD", "cause_category": "packing", "status": "ruled_out",
               "supporting_evidence_ids": [], "contradicting_evidence_ids": []}
    state = {**a_matched, "prior_hypotheses": [earlier]}
    own = [e for c in state["checks"] if c["source"] == "reason" for e in c["result"]["evidence_ids"]]
    overview_id = next(e for e in state["checks"][0]["result"]["evidence_ids"] if e not in own)  # load_case's only
    own_id = own[0]
    for evidence, blocked in (([], True), ([overview_id], True), ([own_id], False)):
        raw = out("x", EXPLORE, new_hypotheses=[new("N1", "packing", "Large orders lose a bag.", evidence=evidence)])
        assert ("G6" in run(state, raw).rule_ids) is blocked, evidence


def test_g17_rejects_a_ruled_out_hypothesis(a_matched):
    state = copy.deepcopy(a_matched)
    state["hypotheses"][1]["status"] = "ruled_out"
    ids = [h["hypothesis_id"] for h in state["hypotheses"][:2]]
    assert "G17" in run(state, out("x", ask("How are large orders bagged?", "Separates them.", ids)),
                        max_questions=2).rule_ids


def test_explore_cap(a_first):
    state = {**a_first, "explore_count": 3}
    d = run(state, out("x", EXPLORE, new_hypotheses=TWO))
    assert "G13" in d.rule_ids


def test_modifiers_are_matched_case_insensitively(a_first):
    raw = out("x", check("explore", "p", breakdown("day", *FULL, modifiers=["extra SAUCE"])), new_hypotheses=TWO)
    d = run(a_first, raw)
    assert d.accepted, d.violations
    assert d.action["plan"]["request"]["filter"]["modifiers"] == ["Extra sauce"]


def test_item_names_map_to_menu_ids(a_first):
    raw = out("x", check("explore", "p", breakdown("day", *FULL, item_id=["bubble milk tea"])), new_hypotheses=TWO)
    d = run(a_first, raw)
    assert d.accepted, d.violations
    assert d.action["plan"]["request"]["filter"]["item_id"] == ["ITEM-A-011"]


def test_check_without_budget_ends_the_run(a_first):
    state = {**a_first, "step_count": 12}
    d = run(state, out("x", EXPLORE, new_hypotheses=TWO))
    assert d.accepted and d.budget_spent


def test_refs_resolve_inside_the_same_output(a_first):
    raw = out("x", check("test", "p", breakdown("modifier", *FULL), ["N1", "N2"],
                         [exp("N1", "a", "b"), exp("N2", "c", "d")]), new_hypotheses=TWO)
    d = run(a_first, raw)
    assert d.accepted, d.violations
    assert d.action["plan"]["discriminates"] == [d.new_ids["N1"], d.new_ids["N2"]]


# --- After the modifier breakdown -------------------------------------------------------------

NEXT = check("test", "Find the day the rise started.", breakdown("day", *FULL), [INV],
             [exp(INV, "rises from Oct 24", "flat until Oct 30")])


def test_valid_third_turn_is_accepted(a_matched):
    d = run(a_matched, resolved(store_a_turns()[2], a_matched))
    assert d.accepted, d.violations
    assert d.matched == {POS: "if_true", MENU: "if_false"}
    statuses = {h["hypothesis_id"]: h["status"] for h in d.hypotheses}
    assert statuses == {POS: "supported", MENU: "ruled_out", INV: "open"}


MATCHED_CASES = [
    ("G9", out("x", NEXT, matched=[(POS, "if_true")])),
    ("G3", out("x", NEXT, matched=[(POS, "if_false"), (MENU, "if_false")], updates=[upd(POS, "supported", "r")])),
    ("G4", out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_true")], updates=[upd(MENU, "ruled_out", "r")])),
    ("G4", out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_false")], updates=[upd(MENU, "ruled_out", "")])),
    ("G4b", out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_false")], updates=[upd(MENU, "inconclusive", "r")])),
    ("G18", out("x", conclude("HYP-NOPE", "2026-10-30", "high", "s", "fix_modifier_mapping", "r",
                              modifiers=["Extra sauce"]), matched=[(POS, "if_true"), (MENU, "if_false")])),
    ("G18", out("x", conclude(POS, "2026-10-30", "high", "s", "add_large_order_bag_check", "r"),
                matched=[(POS, "if_true"), (MENU, "if_false")])),
    ("G18", out("x", conclude(POS, "2026-12-01", "high", "s", "fix_modifier_mapping", "r", modifiers=["Extra sauce"]),
                matched=[(POS, "if_true"), (MENU, "if_false")])),
    ("G18", out("x", conclude(POS, "2026-10-30", "high", "s", "fix_modifier_mapping", "r", item_id=["ITEM-A-011"]),
                matched=[(POS, "if_true"), (MENU, "if_false")])),
    ("P1", out("x", conclude(POS, "2026-10-30", "high", "Refund the customers and charge the store.",
                             "fix_modifier_mapping", "r", modifiers=["Extra sauce"]),
               matched=[(POS, "if_true"), (MENU, "if_false")])),
]


@pytest.mark.parametrize("rule, raw", MATCHED_CASES)
def test_rules_after_a_test(a_matched, rule, raw):
    d = run(a_matched, raw)
    assert rule in d.rule_ids, d.violations


def test_g3_supported_needs_a_supporting_evidence_id(a_matched):
    # B-05 found fraud diagnoses with no cited record: a matching check alone no longer makes a cause supported.
    state = copy.deepcopy(a_matched)
    next(h for h in state["hypotheses"] if h["hypothesis_id"] == POS)["supporting_evidence_ids"] = []
    bare = out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_false")], updates=[upd(POS, "supported", "r")])
    d = run(state, bare)
    assert any(v.rule == "G3" and "without evidence" in v.message for v in d.violations), d.violations
    neither = out("x", NEXT, matched=[(POS, "if_false"), (MENU, "if_false")], updates=[upd(POS, "supported", "r")])
    assert [v.rule for v in run(state, neither).violations].count("G3") == 2  # one rejection lists both problems
    state["retrieved_evidence_ids"].append("EV-RPL-000001")  # a merchant reply alone doesn't count as evidence
    reply_only = out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_false")],
                     updates=[upd(POS, "supported", "r", ["EV-RPL-000001"])])
    assert any(v.rule == "G3" and "without evidence" in v.message for v in run(state, reply_only).violations)
    cited = out("x", NEXT, matched=[(POS, "if_true"), (MENU, "if_false")],
                updates=[upd(POS, "supported", "r", [state["retrieved_evidence_ids"][0]])])
    assert "G3" not in run(state, cited).rule_ids


def test_conclusion_with_tested_target_passes_the_guard(a_matched):
    raw = out("x", conclude(POS, "2026-10-30", "high", "Extra sauce orders run far above the store.",
                            "fix_modifier_mapping", "The rise is limited to the modifier.", modifiers=["Extra sauce"]),
              matched=[(POS, "if_true"), (MENU, "if_false")],
              updates=[upd(POS, "supported", "Concentrated on Extra sauce.")])
    d = run(a_matched, raw)
    assert d.accepted, d.violations
    assert d.action["recommendation"]["target"]["modifiers"] == ["Extra sauce"]
    assert d.action["recommendation"]["target"]["item_count_min"] is None


def test_dasher_handoff_is_never_supported(b_matched):
    dash = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "dasher_handoff")
    pack = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "packing")
    menu = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "menu_change")
    raw = out("x", NEXT, matched=[(pack, "if_true"), (menu, "if_false")], updates=[upd(dash, "supported", "r")])
    d = run(b_matched, raw)
    assert "G5" in d.rule_ids


def test_dasher_handoff_can_be_inconclusive_as_a_data_limit(b_matched):
    dash = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "dasher_handoff")
    pack = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "packing")
    menu = next(h["hypothesis_id"] for h in b_matched["hypotheses"] if h["cause_category"] == "menu_change")
    raw = out("x", check("explore", "p", breakdown("weekday", *FULL)), matched=[(pack, "if_true"), (menu, "if_false")],
              updates=[upd(dash, "inconclusive", "No Dasher data.")])
    d = run(b_matched, raw)
    assert d.accepted, d.violations
