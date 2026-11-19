"""Graph tests with the scripted model and fixtures, one or more per B-02 acceptance criterion."""

import json
import logging

from app.domain.client import DomainError
from app.domain.fixtures import FixtureDomainClient
from app.errors import MODEL_REFUSED, RUN_TIMEOUT, UPSTREAM_UNAVAILABLE
from app.llm.base import ModelError
from app.llm.scripted_model import ScriptedReasonModel
from app.logs import JsonFormatter
from tests.conftest import FIXTURES, capture_state, make_settings, run_investigation
from tests.scripts import (
    FULL,
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


def sequence(state):
    return [(c["tool"], c["request"].get("group_by")) for c in state["checks"] if c["source"] == "reason"]


# --- Acceptance criterion 1: distinct routes ---------------------------------------------------


async def test_store_a_and_store_b_take_distinct_routes_to_their_causes():
    a, domain_a = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()), settings=make_settings())
    b, domain_b = await run_investigation("STORE-B", ScriptedReasonModel(store_b_turns()), settings=make_settings())
    assert a["status"] == b["status"] == "completed"
    assert a["result"]["cause_category"] == "pos_modifier_mapping"
    assert b["result"]["cause_category"] == "packing"
    assert sequence(a) != sequence(b)
    assert a["result"]["proposal_id"] == b["result"]["proposal_id"] == "PROP-0001"
    assert domain_a.misses == domain_b.misses == []
    assert domain_a.status_updates[-1]["status"] == "completed"


async def test_the_diagnosis_carries_the_catalog_action_and_the_tested_target():
    b, domain = await run_investigation("STORE-B", ScriptedReasonModel(store_b_turns()), settings=make_settings())
    rec = b["result"]["recommendation"]
    assert rec["action_id"] == "add_large_order_bag_check" and rec["owner_team"] == "merchant"
    assert rec["target"] == {"item_id": [], "modifiers": [], "daypart": ["dinner"], "item_count_min": 5}
    assert b["result"]["confidence"] == "medium"  # dasher_handoff stays inconclusive
    proposal = domain.proposals["PROP-0001"]
    assert proposal.kind == "intervention"
    assert "dinner orders" in proposal.content["instructions"]


# --- Acceptance criterion 2: state records everything, and the loop is bounded ------------------


async def test_state_records_checks_findings_and_ruled_out_hypotheses():
    b, _ = await run_investigation("STORE-B", ScriptedReasonModel(store_b_turns()), settings=make_settings())
    statuses = {h["cause_category"]: h["status"] for h in b["hypotheses"]}
    assert statuses == {"packing": "supported", "menu_change": "ruled_out", "other": "ruled_out",
                        "dasher_handoff": "inconclusive"}
    assert {r["cause_category"] for r in b["result"]["ruled_out"]} == {"menu_change", "other"}
    assert all(r["check_ids"] for r in b["result"]["ruled_out"])
    assert b["result"]["checks_tried"] == [c["check_id"] for c in b["checks"]]
    for c in b["checks"]:
        assert c["result"]["headline"] and c["canonical_key"]
    assert b["step_count"] == 5 and b["explore_count"] == 2
    assert len(b["challenge_check_ids"]) == 1


async def test_the_step_limit_ends_the_run_unsure():
    turns = store_a_turns()[:2] + [store_a_turns()[2]]
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(turns), settings=make_settings(agent_max_steps=2))
    assert final["end_reason"] == "budget_spent"
    assert final["status"] == "unsure"
    assert final["step_count"] == 2
    assert final["result"]["evidence_gaps"][0].startswith("All 2 checks were used")


BAD = out("x", check("explore", "p", event_log_request()),
          new_hypotheses=[new("N1", "packing", "s", evidence=["EV-CLM-999999"]),
                          new("N2", "menu_change", "A menu change.")])


async def test_two_rejections_in_a_row_end_the_run_unsure():
    final, domain = await run_investigation("STORE-A", ScriptedReasonModel([BAD, BAD]), settings=make_settings())
    assert final["end_reason"] == "guard_cap"
    assert final["status"] == "unsure"
    assert "Failed rules: G1" in final["result"]["evidence_gaps"]
    assert domain.status_updates[-1]["status"] == "unsure"


async def test_a_rejection_followed_by_a_valid_output_continues():
    turns = [BAD, *store_a_turns()]
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(turns), settings=make_settings())
    assert final["status"] == "completed"
    assert final["reason_calls"] == 6


def early_conclusion():
    return out("Extra sauce dominates.",
               conclude("@hyp:pos_modifier_mapping", "2026-10-30", "high", "Extra sauce orders run high.",
                        "fix_modifier_mapping", "Limited to the modifier.", modifiers=["Extra sauce"]))


async def test_two_failed_conclusions_end_the_run_unsure():
    first = store_a_turns()[2]
    first = {**first, "next_action": early_conclusion()["next_action"]}
    turns = [*store_a_turns()[:2], first, early_conclusion()]
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(turns), settings=make_settings())
    assert final["end_reason"] == "gate_cap"
    assert final["status"] == "unsure"
    assert final["gate_rejections"] == 2
    assert any(g.startswith("K2:") for g in final["result"]["evidence_gaps"])


async def test_the_reasoning_turn_cap_ends_the_run_unsure():
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()),
                                       settings=make_settings(agent_max_reason_calls=3))
    assert final["end_reason"] == "reason_cap"
    assert final["status"] == "unsure"
    assert final["reason_calls"] == 3


async def test_flat_store_ends_unsure_on_insufficient_evidence():
    menu, other = "@hyp:menu_change", "@hyp:other"
    turns = [
        out("The rate is flat near 1.3%.", check("explore", "Read the events.", event_log_request()),
            new_hypotheses=[new("N1", "menu_change", "The Oct 15 crust change raised claims on pizzas."),
                            new("N2", "other", "Ordinary week to week noise with no store-side cause.")]),
        out("One menu change on Oct 15.",
            check("test", "Compare gluten-free crust orders around Oct 15.",
                  compare("2026-10-15", 10, 28, scope(modifiers=["Gluten-free crust"])), [menu],
                  [exp(menu, "Crust orders rise after Oct 15", "Crust orders stay flat")]),
            updates=[upd(menu, "open", "The change landed on Oct 15.", ["@event:Gluten-free"])]),
        out("Crust orders stayed near 1%.",
            conclude(other, "2026-10-15", "low", "No store-side cause stands out.", "analyst_review",
                     "Nothing to act on."),
            matched=[(menu, "if_false")], updates=[upd(menu, "ruled_out", "Crust orders didn't rise.")]),
        out("Still nothing.", conclude(other, "2026-10-15", "low", "No store-side cause stands out.",
                                       "analyst_review", "Nothing to act on.")),
    ]
    final, _ = await run_investigation("STORE-C", ScriptedReasonModel(turns), settings=make_settings())
    assert final["status"] == "unsure"
    assert final["end_reason"] == "gate_cap"
    assert final["result"]["recommendation"] is None
    assert final["result"]["ruled_out"][0]["cause_category"] == "menu_change"


async def test_a_domain_422_is_a_wasted_step_fed_back_as_data():
    domain = FixtureDomainClient(FIXTURES, faults={
        "claim_breakdown": DomainError(422, "VALIDATION_ERROR", "Unknown modifier.")})
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()[:2]), settings=make_settings(),
                                       domain=domain)
    rejected = [c for c in final["checks"] if c.get("domain_rejected")]
    assert len(rejected) == 1 and final["step_count"] == 2
    assert rejected[0]["result"]["data_sufficient"] is False
    assert "Unknown modifier." in rejected[0]["result"]["notes"]


async def test_fraud_signals_set_the_suspect_cluster():
    domain = FixtureDomainClient(FIXTURES, variants={"STORE-B": {"fraud_signals": "fraud_signals_flagged.json"}})
    state = await capture_state("STORE-B", [], domain=domain)
    assert state["suspect_cluster"] is True
    flagged = next(c for c in state["checks"] if c["tool"] == "fraud_signals")
    assert set(flagged["result"]["evidence_ids"]) <= set(state["retrieved_evidence_ids"])


# --- Acceptance criterion 3: operational failures are structured ---------------------------------


def failure_lines(caplog):
    return [json.loads(JsonFormatter().format(r)) for r in caplog.records if r.getMessage() == "investigation failed"]


async def test_domain_unavailable_fails_with_a_structured_log_line(caplog):
    caplog.set_level(logging.ERROR)
    domain = FixtureDomainClient(FIXTURES, faults={
        "claim_breakdown": DomainError(503, "UPSTREAM_UNAVAILABLE", "Domain is unavailable.")})
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()), settings=make_settings(),
                                       domain=domain)
    assert final["status"] == "failed"
    assert final["error"]["code"] == UPSTREAM_UNAVAILABLE
    line = failure_lines(caplog)[-1]
    assert line["code"] == UPSTREAM_UNAVAILABLE and line["level"] == "error"
    assert domain.status_updates[-1] == {"case_id": "CASE-0001", "investigation_id": "INV-TEST-STORE-A",
                                         "status": "failed", "error_code": UPSTREAM_UNAVAILABLE}


async def test_a_refusal_fails_with_a_structured_log_line(caplog):
    caplog.set_level(logging.ERROR)
    model = ScriptedReasonModel([ModelError(MODEL_REFUSED, "The model declined the turn (category bio).")])
    final, _ = await run_investigation("STORE-A", model, settings=make_settings())
    assert final["status"] == "failed"
    assert final["error"]["code"] == MODEL_REFUSED
    assert failure_lines(caplog)[-1]["code"] == MODEL_REFUSED


async def test_a_passed_deadline_fails_with_run_timeout():
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()), settings=make_settings(),
                                       deadline_seconds=-1)
    assert final["status"] == "failed"
    assert final["error"]["code"] == RUN_TIMEOUT


async def test_load_case_failure_is_reported():
    domain = FixtureDomainClient(FIXTURES, faults={"get_menu": DomainError(503, "UPSTREAM_UNAVAILABLE", "down")})
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel([]), settings=make_settings(), domain=domain)
    assert final["status"] == "failed" and "load_case" in final["error"]["message"]


async def test_state_is_json_native():
    final, _ = await run_investigation("STORE-A", ScriptedReasonModel(store_a_turns()), settings=make_settings())
    json.dumps(final)
