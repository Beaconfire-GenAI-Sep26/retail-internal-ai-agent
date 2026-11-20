"""Deterministic finalize: the truth table, confidence caps, and the InvestigationResult.

| How the loop ended                                        | Outcome                                  |
|-----------------------------------------------------------|------------------------------------------|
| gate_passed                                               | diagnosis, confidence after the caps     |
| budget_spent, final action conclude, K1, K2 and K5 hold   | diagnosis at most medium; K3/K4 -> gaps  |
| budget_spent otherwise, guard_cap, gate_cap, reason_cap   | unsure; candidate and failed rules -> gaps |
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from agent.app.graph.gate import evaluate_gate
from agent.app.graph.rules import can_rule_out, can_support
from agent.app.tools.registry import render_tool_catalog

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


def contradicting_ids(state: dict[str, Any], leader_id: str) -> list[str]:
    """Evidence against the leading cause: what contradicted it, plus what pointed to another cause (a ruled-out
    cause's is explained by its ruled_out entry). A record the leader cites, or that a check confirming the leader
    returned, isn't held against it. An event_log returns every event in its window, so it confirms none of them."""
    hyps = state.get("hypotheses", [])
    lead = next(h for h in hyps if h["hypothesis_id"] == leader_id)
    fits = set(lead["supporting_evidence_ids"])
    for c in state.get("checks", []):
        if (c.get("matched") or {}).get(leader_id) == "if_true" and c.get("tool") != "event_log":
            fits.update(c.get("result", {}).get("evidence_ids", []))
    rivals = [e for h in hyps if h["hypothesis_id"] != leader_id
              for e in h["supporting_evidence_ids"] if e not in fits]
    return list(dict.fromkeys([*lead["contradicting_evidence_ids"], *rivals]))


# Counts and rates in the result's text must appear in what the run saw: a check result or the case facts.
WITHHELD = "[withheld]"
_INT = r"(\d{1,3}(?:,\d{3})+|\d+)"
_PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")
_FRACTION = re.compile(rf"(?<![\w./-]){_INT}\s?/\s?{_INT}(?![\w/]|\.\d)")
_COUNT = re.compile(rf"(?<![\w./+-]){_INT}((?:\s+[A-Za-z_][\w-]*){{0,2}}?\s+(?:claims?|orders?|cancellations?))\b",
                    re.IGNORECASE)
_OF = re.compile(rf"(?<![\w./+-]){_INT}(?=(\s+of\s+(?:the\s+)?(?:\d{{1,3}}(?:,\d{{3}})+|\d+))\b)")  # n of "n of m"
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_DEFAULT = re.compile(r"\((\d+) by default\)")
_MONTH_BEFORE = re.compile(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                           r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s*$", re.IGNORECASE)


@lru_cache(maxsize=1)
def _catalog_thresholds() -> frozenset[int]:
    """Thresholds the tool catalog tells the model, such as MIN_GROUP_ORDERS (30 by default)."""
    return frozenset(int(n) for n in _DEFAULT.findall(render_tool_catalog()))


def supported_numbers(state: dict[str, Any]) -> tuple[list[float], set[int]]:
    """The rates (as percentages) and counts the run showed the model: the case facts, every check result with
    its records, and the tool catalog's thresholds."""
    case = state.get("case") or {}
    pcts = [case[k] * 100 for k in ("mi_rate", "baseline_rate", "goal_rate") if case.get(k) is not None]
    ints = {int(case[k]) for k in ("attributable_claims", "eligible_orders") if case.get(k) is not None}
    for c in state.get("checks", []):
        r = c.get("result", {})
        ints |= {int(r[k]) for k in ("eligible_orders", "pending_claims") if r.get(k) is not None}
        ints.add(len(r.get("evidence_ids", [])))
        for m in r.get("metrics", []):
            if m.get("value") is not None:
                if m.get("unit") in ("rate", "share"):
                    pcts.append(m["value"] * 100)
                else:
                    ints.add(round(m["value"]))
            ints |= {int(m[k]) for k in ("numerator", "denominator") if m.get(k) is not None}
        records = [t for e in r.get("evidence", [])
                   for t in (e.get("summary"), (e.get("attributes") or {}).get("description"))]
        for text in (r.get("headline"), *r.get("notes", []), *records):
            text = str(text or "")
            pcts += [float(p) for p in _PCT.findall(text)]
            ints |= {int(n.replace(",", "")) for n in _NUMBER.findall(text) if "." not in n}
    return pcts, ints | _catalog_thresholds()


def withhold_unsupported(result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Replaces each count or rate that no check result or case fact shows with [withheld], and lists them in the
    gaps. Derived numbers, such as a sum of two groups, count as unsupported."""
    pcts, ints = supported_numbers(state)
    withheld: list[str] = []

    def pct(m: re.Match[str]) -> str:
        p, places = float(m[1]), len(m[1].partition(".")[2])
        if any(abs(p - s) <= 0.5 * 10 ** -places + 1e-9 for s in pcts):
            return m[0]
        withheld.append(m[0])
        return WITHHELD

    def fraction(m: re.Match[str]) -> str:
        n, d = int(m[1].replace(",", "")), int(m[2].replace(",", ""))
        if (n <= 12 and d <= 31) or (n in ints and d in ints):  # a month/day date is left alone
            return m[0]
        withheld.append(m[0])
        return WITHHELD

    def count(m: re.Match[str]) -> str:
        if int(m[1].replace(",", "")) in ints or _MONTH_BEFORE.search(m.string[:m.start()]):  # "Oct 30 claims"
            return m[0]
        withheld.append(m[1] + m[2])
        return WITHHELD + m[2]

    def of(m: re.Match[str]) -> str:
        if int(m[1].replace(",", "")) in ints:
            return m[0]
        withheld.append(m[1] + m[2])
        return WITHHELD

    def clean(text: str) -> str:
        return _COUNT.sub(count, _OF.sub(of, _FRACTION.sub(fraction, _PCT.sub(pct, text))))

    result["summary"] = clean(result["summary"])
    if result.get("recommendation"):
        result["recommendation"]["rationale"] = clean(result["recommendation"]["rationale"])
    for entry in result["ruled_out"]:
        entry["reason"] = clean(entry["reason"])
    result["evidence_gaps"] = [clean(g) for g in result["evidence_gaps"]]
    if withheld:
        shown = dict.fromkeys(" ".join(w.split()) for w in withheld)
        result["evidence_gaps"].append("Withheld numbers that no check result shows: " + ", ".join(shown) + ".")
    return result


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
        return withhold_unsupported({
            **base,
            "outcome": "diagnosis",
            "cause_category": lead["cause_category"],
            "cause_started_at": action["rise_started_at"],
            "confidence": confidence,
            "summary": action["summary"],
            "supporting_evidence_ids": [e for e in lead["supporting_evidence_ids"] if e not in invalid],
            "contradicting_evidence_ids": [e for e in contradicting_ids(state, leader_id) if e not in invalid],
            "evidence_gaps": gaps,
            "recommendation": {
                "kind": entry["kind"],
                "action_id": entry["action_id"],
                "owner_team": entry["owner_team"],
                "rationale": action["recommendation"]["rationale"],
                "target": action["recommendation"]["target"],
                "recheck_after_days": entry["default_recheck_days"],
            },
        }, state)

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
    return withhold_unsupported({
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
    }, state)


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
