"""Small synthetic states for the gate and finalize tests."""

from __future__ import annotations

from typing import Any

CATALOG = [
    {"action_id": "fix_modifier_mapping", "kind": "handoff", "owner_team": "pos_team", "title": "Fix the mapping",
     "applies_to": ["pos_modifier_mapping"], "default_recheck_days": 14},
    {"action_id": "analyst_review", "kind": "handoff", "owner_team": "analyst", "title": "Analyst review",
     "applies_to": ["pos_modifier_mapping", "menu_change", "packing", "inventory", "dasher_handoff",
                    "fraud_cluster", "other"], "default_recheck_days": 14},
]


def H(hid: str, cause: str, status: str, sup: tuple[str, ...] = (), con: tuple[str, ...] = (),
      rationale: str = "A one-sentence rationale.") -> dict[str, Any]:
    return {"hypothesis_id": hid, "cause_category": cause, "statement": f"{cause} statement", "status": status,
            "rationale": rationale, "supporting_evidence_ids": list(sup), "contradicting_evidence_ids": list(con),
            "check_ids": []}


def C(cid: str, kind: str, tool: str, matched: dict[str, str], *, discriminates: tuple[str, ...] = (),
      challenges: str | None = None, sufficient: bool = True, request: dict[str, Any] | None = None,
      signature: str | None = None, pending: int = 0, evidence: int = 10) -> dict[str, Any]:
    request = request or {"filter": {"start": "2026-10-05", "end": "2026-11-15"}, "group_by": "modifier"}
    return {"check_id": cid, "source": "reason", "kind": kind, "tool": tool, "request": request,
            "canonical_key": f"{tool}:{cid}", "signature": signature or f"{tool}|{request.get('group_by', '')}",
            "purpose": "p", "discriminates": list(discriminates), "expectations": [], "challenges": challenges,
            "result": {"data_sufficient": sufficient, "headline": "h", "metrics": [], "pending_claims": pending,
                       "evidence_ids": [f"EV-CLM-{cid[-4:]}{i:02d}" for i in range(evidence)], "evidence": []},
            "matched": matched, "needs_match": False, "domain_rejected": False, "at": "2026-11-18T00:00:00Z"}


EVENT_LOG = C("CHK-E", "explore", "event_log", {}, request={"start": "2026-10-05", "end": "2026-11-15", "event_type": []})
EVENTS = [
    {"evidence_id": "EV-EVT-000005", "event_type": "menu_change", "start_date": "2026-10-30", "end_date": None,
     "description": "Added Extra sauce"},
    {"evidence_id": "EV-EVT-000006", "event_type": "menu_change", "start_date": "2026-10-30", "end_date": None,
     "description": "Renamed a drink"},
]


def passing_state(**overrides: Any) -> dict[str, Any]:
    """A STORE-A-shaped state whose conclusion passes K1-K5."""
    state = {
        "window": {"start": "2026-10-05", "end": "2026-11-15"},
        "catalog": CATALOG,
        "menu": [],
        "hypotheses": [
            H("HYP-1", "pos_modifier_mapping", "supported", sup=("EV-EVT-000005", "EV-CLM-000101")),
            H("HYP-2", "menu_change", "ruled_out", sup=("EV-EVT-000006",)),
        ],
        "checks": [
            EVENT_LOG,
            C("CHK-T", "test", "claim_breakdown", {"HYP-1": "if_true", "HYP-2": "if_false"},
              discriminates=("HYP-1", "HYP-2")),
            C("CHK-C", "challenge", "compare_periods", {"HYP-1": "if_true"}, discriminates=("HYP-1",),
              challenges="HYP-1", request={"split_date": "2026-10-30", "days_before": 14, "days_after": 17,
                                           "target": {"modifiers": ["Extra sauce"]}, "control": None},
              signature="compare_periods||target(modifiers)|control(rest_of_store)"),
        ],
        "event_ledger": EVENTS,
        "retrieved_evidence_ids": ["EV-EVT-000005", "EV-EVT-000006", "EV-CLM-000101"],
        "challenge_check_ids": ["CHK-C"],
        "reply_claims": [],
        "reason_calls": 5,
        "step_count": 3,
    }
    state.update(overrides)
    return state


def conclusion(leader: str = "HYP-1", rise: str = "2026-10-30", action_id: str = "fix_modifier_mapping",
               confidence: str = "high") -> dict[str, Any]:
    return {"type": "conclude", "leading_hypothesis_id": leader, "rise_started_at": rise, "confidence": confidence,
            "summary": "Extra sauce orders run far above the rest of the store.",
            "recommendation": {"action_id": action_id, "rationale": "Limited to the modifier.",
                               "target": {"item_id": [], "modifiers": ["Extra sauce"], "daypart": [],
                                          "item_count_min": None}}}
