"""Deterministic finalize: the truth table, confidence caps, and the InvestigationResult.

| How the loop ended                                        | Outcome                                  |
|-----------------------------------------------------------|------------------------------------------|
| gate_passed                                               | diagnosis, confidence after the caps     |
| budget_spent, final action conclude, K1, K2 and K5 hold   | diagnosis at most medium; K3/K4 -> gaps  |
| budget_spent otherwise, guard_cap, gate_cap, reason_cap   | unsure; candidate and failed rules -> gaps |
"""

from __future__ import annotations

from typing import Any

from app.graph.gate import evaluate_gate
from app.graph.rules import can_rule_out, can_support

LEVELS = ("low", "medium", "high")

END_REASON_TEXT = {
    "budget_spent": "All {max_steps} checks were used before the evidence supported a single cause.",
    "guard_cap": "Two outputs in a row broke the guard rules ({rules}).",
    "gate_cap": "The conclusion failed the conclude gate twice ({rules}).",
    "reason_cap": "The run reached its limit of {reason_calls} reasoning turns.",
}


def cap(confidence: str, ceiling: str) -> str:
    return LEVELS[min(LEVELS.index(confidence), LEVELS.index(ceiling))]


def mostly_pending(leader: str, checks: list[dict[str, Any]]) -> bool:
    """True when the checks that support the leader rest mostly on pending claims."""
    shares = []
    for c in checks:
        if can_support(leader, c):
            result = c.get("result", {})
            total = len(result.get("evidence_ids", []))
            if total:
                shares.append(result.get("pending_claims", 0) / total)
    return bool(shares) and sum(shares) / len(shares) > 0.5


def decide(state: dict[str, Any]) -> dict[str, Any]:
    """Which row of the truth table applies, with the gate evaluation behind it."""
    end = state.get("end_reason") or "reason_cap"
    action = state.get("next_action") or {}
    if end == "gate_passed":
        gate = state.get("gate_result") or evaluate_gate(state, action)
        return {"end_reason": end, "outcome": "diagnosis", "gate": gate, "capped": False}
    if end == "budget_spent" and action.get("type") == "conclude":
        gate = evaluate_gate(state, action)
        ok = {c["rule"]: c["ok"] for c in gate["conditions"]}
        if ok.get("K1") and ok.get("K2") and ok.get("K5"):
            return {"end_reason": end, "outcome": "diagnosis", "gate": gate, "capped": True}
        return {"end_reason": end, "outcome": "unsure", "gate": gate, "capped": True}
    gate = state.get("gate_result") if end == "gate_cap" else None
    return {"end_reason": end, "outcome": "unsure", "gate": gate, "capped": True}


def _ruled_out(state: dict[str, Any], invalid: set[str]) -> list[dict[str, Any]]:
    checks = state.get("checks", [])
    out = []
    for h in state.get("hypotheses", []):
        if h["status"] != "ruled_out":
            continue
        out.append({
            "cause_category": h["cause_category"],
            "reason": h["rationale"],
            "evidence_ids": [e for e in h["contradicting_evidence_ids"] if e not in invalid],
            "check_ids": [c["check_id"] for c in checks if can_rule_out(h["hypothesis_id"], c)],
        })
    return out


def _inconclusive_gaps(state: dict[str, Any], leader: str | None) -> list[str]:
    return [
        f"{h['cause_category']} ({h['hypothesis_id']}) stays inconclusive: {h['rationale']}"
        for h in state.get("hypotheses", [])
        if h["status"] == "inconclusive" and h["hypothesis_id"] != leader
    ]


def _candidate(state: dict[str, Any]) -> dict[str, Any] | None:
    hyps = state.get("hypotheses", [])
    action = state.get("next_action") or {}
    if action.get("type") == "conclude":
        lead = next((h for h in hyps if h["hypothesis_id"] == action.get("leading_hypothesis_id")), None)
        if lead:
            return lead
    for status in ("supported", "open", "inconclusive"):
        pool = [h for h in hyps if h["status"] == status]
        if pool:
            return max(pool, key=lambda h: len(h["supporting_evidence_ids"]))
    return None


def _failed_rules(state: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    if decision["end_reason"] == "guard_cap":
        return list((state.get("guard_feedback") or {}).get("rule_ids", []))
    gate = decision.get("gate")
    if gate:
        return [c["rule"] for c in gate["unmet"]]
    return []


def build_result(
    state: dict[str, Any],
    *,
    max_steps: int,
    invalid_ids: set[str] | None = None,
) -> dict[str, Any]:
    invalid = set(invalid_ids or ())
    decision = decide(state)
    checks = state.get("checks", [])
    base = {
        "checks_tried": [c["check_id"] for c in checks],
        "challenge_check_ids": list(state.get("challenge_check_ids", [])),
        "unverified_reply_claims": list(state.get("reply_claims", [])),
        "ruled_out": _ruled_out(state, invalid),
        "proposal_id": None,
    }
    gaps: list[str] = []
    if invalid:
        gaps.append("Dropped citations that failed the evidence check: " + ", ".join(sorted(invalid)))

    if decision["outcome"] == "diagnosis":
        action = state["next_action"]
        leader_id = action["leading_hypothesis_id"]
        lead = next(h for h in state["hypotheses"] if h["hypothesis_id"] == leader_id)
        entry = next(e for e in state.get("catalog", []) if e["action_id"] == action["recommendation"]["action_id"])
        confidence = action["confidence"]
        rivals_inconclusive = any(
            h["status"] == "inconclusive" and h["hypothesis_id"] != leader_id for h in state["hypotheses"]
        )
        if rivals_inconclusive or decision["capped"] or mostly_pending(leader_id, checks):
            confidence = cap(confidence, "medium")
        if decision["capped"]:
            for c in decision["gate"]["unmet"]:
                gaps.append(f"{c['rule']} not met when the checks ran out: {c['detail']}")
        gaps += _inconclusive_gaps(state, leader_id)
        return {
            **base,
            "outcome": "diagnosis",
            "cause_category": lead["cause_category"],
            "cause_started_at": action["rise_started_at"],
            "confidence": confidence,
            "summary": action["summary"],
            "supporting_evidence_ids": [e for e in lead["supporting_evidence_ids"] if e not in invalid],
            "contradicting_evidence_ids": [e for e in lead["contradicting_evidence_ids"] if e not in invalid],
            "evidence_gaps": gaps,
            "recommendation": {
                "kind": entry["kind"],
                "action_id": entry["action_id"],
                "owner_team": entry["owner_team"],
                "rationale": action["recommendation"]["rationale"],
                "target": action["recommendation"]["target"],
                "recheck_after_days": entry["default_recheck_days"],
            },
        }

    rules = _failed_rules(state, decision)
    reason = END_REASON_TEXT.get(decision["end_reason"], "The evidence could not support a single cause.").format(
        max_steps=max_steps, rules=", ".join(rules) or "see the gaps", reason_calls=state.get("reason_calls", 0)
    )
    candidate = _candidate(state)
    summary = "The evidence could not support a single cause. " + reason
    if candidate:
        summary += f" The leading candidate was {candidate['cause_category']}: {candidate['statement']}"
        gaps.append(f"Leading candidate {candidate['hypothesis_id']} ({candidate['cause_category']}) "
                    f"ended {candidate['status']}.")
    gaps.insert(0, reason)
    if rules:
        gaps.append("Failed rules: " + ", ".join(rules))
    if decision.get("gate"):
        gaps += [f"{c['rule']}: {c['detail']}" for c in decision["gate"]["unmet"]]
    gaps += _inconclusive_gaps(state, None)
    return {
        **base,
        "outcome": "unsure",
        "cause_category": None,
        "cause_started_at": None,
        "confidence": "low",
        "summary": summary,
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "evidence_gaps": gaps,
        "recommendation": None,
    }


def describe_target(target: dict[str, Any], menu: list[dict[str, Any]]) -> str:
    names = {m["item_id"]: m["name"] for m in menu}
    parts = []
    if target.get("modifiers"):
        parts.append("orders with the modifier " + " or ".join(target["modifiers"]))
    if target.get("item_id"):
        parts.append("orders with " + " or ".join(names.get(i, i) for i in target["item_id"]))
    if target.get("daypart"):
        parts.append(" or ".join(target["daypart"]) + " orders")
    if target.get("item_count_min"):
        parts.append(f"orders with {target['item_count_min']} or more items")
    return " and ".join(parts) if parts else "all orders at the store"


def action_content(result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The ActionContent for the recommendation's proposal."""
    rec = result["recommendation"]
    entry = next(e for e in state.get("catalog", []) if e["action_id"] == rec["action_id"])
    scope = describe_target(rec["target"], state.get("menu", []))
    return {
        "action_id": rec["action_id"],
        "owner_team": rec["owner_team"],
        "title": entry["title"],
        "instructions": f"{entry['title']}. Scope: {scope}. A recheck runs {rec['recheck_after_days']} days "
                        "after dispatch.",
        "rationale": rec["rationale"],
        "target": rec["target"],
        "recheck_after_days": rec["recheck_after_days"],
    }
