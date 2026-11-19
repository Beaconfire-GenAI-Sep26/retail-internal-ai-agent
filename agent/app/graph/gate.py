"""The conclude gate, K1-K5, as pure functions. The control message shows the same checklist."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.graph.rules import from_rate_tool, parse_date, sufficient

EVENT_TYPES_FOR_CAUSE: dict[str, frozenset[str]] = {
    "pos_modifier_mapping": frozenset({"menu_change", "pos_change"}),
    "menu_change": frozenset({"menu_change", "pos_change"}),
    "other": frozenset({"menu_change", "pos_change", "store_downtime", "promotion"}),
}
EVENT_SPAN_DAYS = 7
EVENT_LEADER_DAYS = 1


def _condition(rule: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"rule": rule, "ok": ok, "detail": detail}


def k2_challenge(leader: str, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The first challenge that K2 accepts for the leader, if any."""
    support_sigs = {
        c.get("signature")
        for c in checks
        if c.get("kind") == "test" and c.get("matched", {}).get(leader) == "if_true"
    }
    for c in checks:
        if (
            c.get("kind") == "challenge"
            and c.get("challenges") == leader
            and sufficient(c)
            and from_rate_tool(c)
            and c.get("matched", {}).get(leader) == "if_true"
            and c.get("signature") not in support_sigs
        ):
            return c
    return None


def _event_span(rise: date, window: dict[str, str]) -> tuple[date, date]:
    lo, hi = rise - timedelta(days=EVENT_SPAN_DAYS), rise + timedelta(days=EVENT_SPAN_DAYS)
    w_lo, w_hi = parse_date(window.get("start", "")), parse_date(window.get("end", ""))
    if w_lo:
        lo = max(lo, w_lo)
    if w_hi:
        hi = min(hi, w_hi)
    return lo, hi


def event_log_covers(checks: list[dict[str, Any]], lo: date, hi: date) -> bool:
    for c in checks:
        if c.get("tool") != "event_log" or c.get("request", {}).get("event_type"):
            continue
        start, end = parse_date(c["request"].get("start", "")), parse_date(c["request"].get("end", ""))
        if start and end and start <= lo and end >= hi:
            return True
    return False


def unexplained_events(
    events: list[dict[str, Any]],
    hypotheses: dict[str, dict[str, Any]],
    leader: str | None,
    rise: date | None,
    lo: date,
    hi: date,
) -> list[str]:
    """Events overlapping [lo, hi] that no rival with a status and not the leader explains."""
    lead = hypotheses.get(leader or "")
    out = []
    for e in events:
        start = parse_date(e["start_date"])
        end = parse_date(e.get("end_date") or e["start_date"]) or start
        if start is None or end < lo or start > hi:
            continue
        eid = e["evidence_id"]
        by_rival = any(
            hid != leader
            and h["status"] != "open"
            and (eid in h["supporting_evidence_ids"] or eid in h["contradicting_evidence_ids"])
            for hid, h in hypotheses.items()
        )
        by_leader = bool(
            lead
            and rise
            and eid in lead["supporting_evidence_ids"]
            and e["event_type"] in EVENT_TYPES_FOR_CAUSE.get(lead["cause_category"], frozenset())
            and abs((start - rise).days) <= EVENT_LEADER_DAYS
        )
        if not (by_rival or by_leader):
            out.append(eid)
    return out


def evaluate_gate(state: dict[str, Any], conclude: dict[str, Any]) -> dict[str, Any]:
    hypotheses = {h["hypothesis_id"]: h for h in state.get("hypotheses", [])}
    checks = state.get("checks", [])
    leader = conclude.get("leading_hypothesis_id")
    lead = hypotheses.get(leader or "")
    rise = parse_date(conclude.get("rise_started_at", ""))
    conditions = []

    conditions.append(
        _condition("K1", bool(lead and lead["status"] == "supported"),
                   f"{leader} is {lead['status'] if lead else 'missing'}; the leader must be supported")
    )
    challenge = k2_challenge(leader, checks) if lead else None
    conditions.append(
        _condition("K2", challenge is not None,
                   f"challenge {challenge['check_id']} survived" if challenge
                   else f"no sufficient rate-tool challenge on {leader} has matched if_true with a signature "
                        "different from the checks that supported it")
    )
    open_rivals = [
        hid for hid, h in hypotheses.items()
        if hid != leader and not (h["status"] == "ruled_out" or (h["status"] == "inconclusive" and h["rationale"]))
    ]
    conditions.append(
        _condition("K3", not open_rivals,
                   "every rival is ruled out or inconclusive with its gap" if not open_rivals
                   else "rivals still open or supported: " + ", ".join(open_rivals))
    )
    if rise is None:
        conditions.append(_condition("K4", False, "rise_started_at is not a date"))
    else:
        lo, hi = _event_span(rise, state.get("window", {}))
        covered = event_log_covers(checks, lo, hi)
        missing = unexplained_events(state.get("event_ledger", []), hypotheses, leader, rise, lo, hi)
        detail = []
        if not covered:
            detail.append(f"run an all-types event_log covering {lo} to {hi}")
        if missing:
            detail.append("explain these events with a rival that has a status, or cite them on the leader "
                          "when their type fits its cause and they start within a day of the rise: " + ", ".join(missing))
        conditions.append(_condition("K4", covered and not missing, "; ".join(detail) or "every nearby event is explained"))
    entry = next((e for e in state.get("catalog", []) if e["action_id"] == conclude.get("recommendation", {}).get("action_id")), None)
    k5_ok = not (lead and lead["cause_category"] == "other") or bool(
        entry and entry["kind"] == "handoff" and entry["owner_team"] == "analyst"
    )
    conditions.append(_condition("K5", k5_ok, "a cause of other can only end in an analyst handoff"
                                 if not k5_ok else "the action fits the cause"))
    return {
        "passed": all(c["ok"] for c in conditions),
        "leader": leader,
        "conditions": conditions,
        "unmet": [c for c in conditions if not c["ok"]],
    }


def checklist(state: dict[str, Any]) -> list[dict[str, Any]]:
    """K1-K5 for the best current candidate, for the control message. No quoted values."""
    hypotheses = state.get("hypotheses", [])
    supported = [h for h in hypotheses if h["status"] == "supported"]
    if not supported:
        return [_condition("K1", False, "no hypothesis is supported yet")]
    checks = state.get("checks", [])
    lead = max(supported, key=lambda h: sum(1 for c in checks if c.get("matched", {}).get(h["hypothesis_id"]) == "if_true"))
    leader = lead["hypothesis_id"]
    items = [_condition("K1", True, f"{leader} is supported")]
    challenge = k2_challenge(leader, checks)
    items.append(_condition("K2", challenge is not None,
                            f"{challenge['check_id']} challenged {leader} and it survived" if challenge
                            else f"no qualifying challenge on {leader} yet"))
    rivals = [h["hypothesis_id"] for h in hypotheses if h["hypothesis_id"] != leader
              and not (h["status"] == "ruled_out" or (h["status"] == "inconclusive" and h["rationale"]))]
    items.append(_condition("K3", not rivals, "all rivals accounted for" if not rivals
                            else "still to rule out or leave inconclusive: " + ", ".join(rivals)))
    has_all_types = any(c.get("tool") == "event_log" and not c.get("request", {}).get("event_type") for c in checks)
    by_id = {h["hypothesis_id"]: h for h in hypotheses}
    uncited = [
        e["evidence_id"] for e in state.get("event_ledger", [])
        if not any(e["evidence_id"] in h["supporting_evidence_ids"] + h["contradicting_evidence_ids"]
                   and (h["status"] != "open" or hid == leader) for hid, h in by_id.items())
    ]
    k4 = "an all-types event_log has run" if has_all_types else "no all-types event_log has run yet"
    if uncited:
        k4 += "; events not yet tied to a hypothesis with a status: " + ", ".join(uncited)
    items.append(_condition("K4", has_all_types and not uncited, k4 + " (the span is the rise date plus or minus 7 days)"))
    items.append(_condition("K5", lead["cause_category"] != "other",
                            "a cause of other can only end in the analyst handoff" if lead["cause_category"] == "other"
                            else "no restriction for this cause"))
    return items
