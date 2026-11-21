"""Builds one reason turn from graph state: S1 and U1 (cached), U2 and C (per turn).

Every function here is deterministic, so S1 and U1 stay byte-identical across the turns of one
investigation and the prompt cache holds. Domain-supplied text is escaped and capped, and sits
inside <data> blocks. The control message C carries only counters, IDs, rule IDs and checklists.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agent.app.config import Settings
from agent.app.graph.gate import checklist
from agent.app.graph.rules import EXPLORE_CAP, can_rule_out, can_support
from agent.app.llm.base import RenderedPrompt
from agent.app.tools.registry import describe_request, render_tool_catalog

TEXT_CAP = 300
NOTE_CAP = 500  # an analyst's decision note
REPLY_CAP = 1500  # a merchant's reply
SHOWN_EVIDENCE_IDS = 20
SHOWN_HYPOTHESIS_IDS = 10
# An item_id or modifier group counts the claims that name the value over the orders that contain it.
NAMING_GROUP_PREFIXES = ("item_id=", "modifier=")


def _count(k: int, noun: str) -> str:
    return f"{k} {noun}" + ("" if k == 1 else "s")


def _naming_fraction(name: str | None, n: int, d: int) -> str | None:
    """The fraction of an item_id or modifier group in words, for the claim breakdown metrics."""
    if name == "claim_rate":
        return f"{_count(n, 'claim')} naming it / {_count(d, 'order')} containing it"
    if name == "claim_share":
        return f"{n} of {_count(d, 'claim')} name it"
    if name == "order_share":
        return f"{n} of {_count(d, 'order')} contain it"
    return None


@lru_cache
def system_prompt() -> str:
    template = (Path(__file__).parent / "system.md").read_text(encoding="utf-8")
    return template.replace("{tool_catalog}", render_tool_catalog().rstrip())


def prompt_hash() -> str:
    return hashlib.sha256(system_prompt().encode()).hexdigest()[:16]


def esc(value: Any, cap: int = TEXT_CAP) -> str:
    """Escape Domain text so it can't close a tag, and cap its length."""
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) > cap:
        text = text[: cap - 1] + "…"
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(value: float | None) -> str:
    return "null" if value is None else f"{value * 100:.1f}%"


def _local_date(ts: str | None, tz: str) -> str:
    if not ts:
        return "?"
    if len(ts) == 10:
        return ts
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date().isoformat()
    except ValueError:
        return esc(ts)


# --- U1: case facts --------------------------------------------------------------------------


def render_case_facts(state: dict[str, Any]) -> str:
    case = state.get("case", {})
    tz = state.get("timezone", "UTC")
    window = state.get("window", {})
    excluded = state.get("excluded", {})
    store = case.get("store", {})
    lines = ["<case>"]
    lines.append(f"case_id: {esc(state.get('case_id'))}")
    lines.append(f"store_id: {esc(state.get('store_id'))}")
    lines.append(f"timezone: {esc(tz)}")
    lines.append(
        f"investigation window: {window.get('start')} to {window.get('end')} (store-local dates). "
        f"Store data starts {state.get('data_start')}."
    )
    lines.append(
        f"trigger: {esc(case.get('trigger_rule'))}. The 7-day rate was {pct(case.get('mi_rate'))} "
        f"({case.get('attributable_claims', '?')} attributable claims on {case.get('eligible_orders', '?')} "
        f"eligible orders) from {_local_date(case.get('window_start'), tz)} to {_local_date(case.get('window_end'), tz)}. "
        f"28-day baseline {pct(case.get('baseline_rate'))}, goal {pct(case.get('goal_rate'))}."
    )
    lines.append(
        f"excluded from every rate in the window: {excluded.get('fraud', 0)} fraud claims and "
        f"{excluded.get('not_store_fault', 0)} not_store_fault claims."
    )
    if state.get("suspect_cluster"):
        lines.append("suspect cluster: yes. fraud_signals flagged at least one customer_ref; see the first checks.")
    else:
        lines.append("suspect cluster: no. fraud_signals flagged no customer_ref.")
    lines.append("</case>")
    lines.append(
        f'<data kind="store">name: {esc(store.get("name"))}; city: {esc(store.get("city"))}; '
        f'cuisine: {esc(store.get("cuisine"))}</data>'
    )
    lines.append('<data kind="menu">')
    lines.append("item_id | name | category | modifiers")
    for item in state.get("menu", []):
        mods = ", ".join(esc(m) for m in item.get("available_modifiers", [])) or "none"
        lines.append(f"{esc(item['item_id'])} | {esc(item['name'])} | {esc(item.get('category'))} | {mods}")
    lines.append("</data>")
    lines.append('<data kind="catalog">')
    lines.append("action_id | kind | owner_team | applies_to | recheck days | title")
    for entry in state.get("catalog", []):
        lines.append(
            f"{esc(entry['action_id'])} | {esc(entry['kind'])} | {esc(entry['owner_team'])} | "
            f"{', '.join(esc(c) for c in entry.get('applies_to', []))} | {entry.get('default_recheck_days')} | "
            f"{esc(entry.get('title'))}"
        )
    lines.append("</data>")
    prior = state.get("prior_hypotheses", [])
    if prior:
        lines.append("<prior_rulings>")
        lines.append("The case was reopened: the action the earlier run recommended didn't bring the rate down. "
                     "Its hypotheses, with their final status:")
        for h in prior:
            lines.append(f"{h['hypothesis_id']} | {h['cause_category']} | {h['status']} | {esc(h.get('rationale'))}")
        lines.append("</prior_rulings>")
    else:
        lines.append("<prior_rulings>none: this is the case's first investigation</prior_rulings>")
    return "\n".join(lines) + "\n"


# --- U2: turn state --------------------------------------------------------------------------


def _ids(values: list[str], cap: int) -> str:
    if not values:
        return "none"
    shown = ", ".join(values[:cap])
    return shown + (f" (+{len(values) - cap} more)" if len(values) > cap else "")


def _metric_line(m: dict[str, Any]) -> str:
    unit, value = m.get("unit"), m.get("value")
    if unit == "count":
        shown = "null" if value is None else str(int(value))
    elif value is None:
        shown = "null"
    else:
        shown = f"{value:.4f} ({pct(value)})"
    frac = ""
    num, den = m.get("numerator"), m.get("denominator")
    if num is not None and den is not None:
        naming = str(m.get("group") or "").startswith(NAMING_GROUP_PREFIXES)
        words = _naming_fraction(m.get("name"), int(num), int(den)) if naming else None
        frac = " = " + (words or f"{int(num)}/{int(den)}")
    return f"  {esc(m.get('name'))} {esc(m.get('group') or '-')}: {shown}{frac}"


def _named(scope: dict[str, Any] | None) -> tuple[str, str]:
    """The item_id and modifier values a claim scope names, and the pronoun for them; ("", "") for none."""
    if not scope:
        return "", ""
    parts, count = [], 0
    for key, label in (("item_id", "item_id"), ("modifiers", "modifier")):
        values = [esc(v) for v in scope.get(key) or []]
        if values:
            parts.append(f"{label} {' or '.join(values)}")
            count += len(values)
    return " and ".join(parts), ("it" if count == 1 else "them")


def count_notes(tool: str, request: dict[str, Any]) -> list[str]:
    """What a claim result counts when an item or modifier narrows it.

    Domain counts the claims that name the value over the orders that contain it, so a count here is
    never every claim on those orders.
    """
    notes: list[str] = []
    if tool == "claim_breakdown":
        group_by = request.get("group_by")
        if group_by in ("item_id", "modifier"):
            what = "item" if group_by == "item_id" else "modifier"
            notes.append(
                f"each {group_by} group counts the claims that name that {what}, over the orders that contain it, "
                "not every claim on those orders"
            )
        named, pronoun = _named(request.get("filter"))
        if named:
            notes.append(f"only claims that name {named} count, over the orders that contain {pronoun}")
    elif tool == "compare_periods":
        named, pronoun = _named(request.get("target"))
        if named:
            notes.append(f"the target counts the claims that name {named}, over the orders that contain {pronoun}")
            if request.get("control") is None:
                notes.append("the control counts every claim on the store's other orders")
        named, pronoun = _named(request.get("control"))
        if named:
            notes.append(f"the control counts the claims that name {named}, over the orders that contain {pronoun}")
    elif tool == "sample_evidence" and request.get("evidence_type") == "claim":
        named, _ = _named(request.get("filter"))
        if named:
            notes.append(f"only claims that name {named} are sampled")
    return notes


def _record_line(e: dict[str, Any]) -> str:
    a = e.get("attributes", {})
    parts = [esc(e.get("evidence_id")), esc(e.get("type")), esc(e.get("occurred_at")), esc(e.get("summary"))]
    for key in ("item_id", "modifier_detail", "error_category", "review_label", "daypart", "item_count",
                "cancellation_category", "event_type", "started_at", "ended_at"):
        if a.get(key) is not None:
            parts.append(f"{key} {esc(a[key])}")
    line = " | ".join(parts)
    if a.get("customer_comments"):
        line += f" | comment: {esc(a['customer_comments'])}"
    if a.get("description"):
        line += f" | description: {esc(a['description'])}"
    return "  " + line


def render_hypotheses(state: dict[str, Any]) -> list[str]:
    hyps = state.get("hypotheses", [])
    checks = state.get("checks", [])
    lines = ["<hypotheses>"]
    if not hyps:
        lines.append("none yet")
    for h in hyps:
        hid = h["hypothesis_id"]
        lines.append(f"{hid} | {h['cause_category']} | {h['status']}")
        lines.append(f"  statement: {esc(h['statement'])}")
        lines.append(f"  rationale: {esc(h['rationale'])}")
        lines.append(
            f"  supporting: {len(h['supporting_evidence_ids'])} IDs ({_ids(h['supporting_evidence_ids'], SHOWN_HYPOTHESIS_IDS)}) | "
            f"contradicting: {len(h['contradicting_evidence_ids'])} IDs ({_ids(h['contradicting_evidence_ids'], SHOWN_HYPOTHESIS_IDS)})"
        )
        support = [c["check_id"] for c in checks if can_support(hid, c)]
        rule_out = [c["check_id"] for c in checks if can_rule_out(hid, c)]
        lines.append(f"  checks that allow supported: {_ids(support, 10)} | checks that allow ruled_out: {_ids(rule_out, 10)}")
    lines.append("</hypotheses>")
    return lines


def render_checks(state: dict[str, Any]) -> list[str]:
    lines = ["<checks>"]
    for c in state.get("checks", []):
        result = c.get("result", {})
        kind = "load_case" if c.get("source") == "load_case" else c.get("kind")
        parts = [c["check_id"], kind, esc(describe_request(c["tool"], c["request"]), 600)]
        counts = count_notes(c["tool"], c["request"])
        if counts:
            parts.append("counts: " + "; ".join(counts))
        if c.get("discriminates"):
            parts.append("discriminates " + ", ".join(c["discriminates"]))
        if c.get("challenges"):
            parts.append(f"challenges {c['challenges']}")
        parts.append("enough data" if result.get("data_sufficient") else "NOT enough data")
        parts.append(f"{len(result.get('evidence_ids', []))} evidence IDs")
        if c.get("matched"):
            parts.append("matched " + ", ".join(f"{k}={v}" for k, v in c["matched"].items()))
        elif c.get("needs_match"):
            parts.append("matched: pending")
        if c.get("domain_rejected"):
            parts.append("Domain rejected it")
        parts.append(f"headline: {esc(result.get('headline'))}")
        lines.append(" | ".join(parts))
    lines.append("</checks>")
    return lines


def render_events(state: dict[str, Any]) -> list[str]:
    events = state.get("event_ledger", [])
    ran = any(c.get("tool") == "event_log" for c in state.get("checks", []))
    lines = ["<events>"]
    if not events:
        lines.append("an event_log ran and returned no events" if ran else "no event_log has run yet")
    hyps = state.get("hypotheses", [])
    for e in events:
        cited = [
            f"{h['hypothesis_id']} ({'supporting' if e['evidence_id'] in h['supporting_evidence_ids'] else 'contradicting'})"
            for h in hyps
            if e["evidence_id"] in h["supporting_evidence_ids"] or e["evidence_id"] in h["contradicting_evidence_ids"]
        ]
        lines.append(
            f"{e['evidence_id']} | {e['event_type']} | {e['start_date']} to {e.get('end_date') or '-'} | "
            f"cited by: {', '.join(cited) or 'nobody'} | <data>{esc(e.get('description'))}</data>"
        )
    lines.append("</events>")
    return lines


QUESTION_OUTCOMES = {
    "pending": "waiting for the analyst",
    "approved": "approved and sent, waiting for the merchant",
    "rejected": "the analyst rejected it",
    "replied": "the merchant replied",
    "no_reply": "the merchant did not reply",
    "unavailable": "not sent, because Domain can't take merchant questions",
}


def render_questions(state: dict[str, Any]) -> list[str]:
    questions = state.get("questions", [])
    if not questions:
        return []
    lines = ["<questions>"]
    for q in questions:
        parts = [q.get("proposal_id") or "not saved", QUESTION_OUTCOMES.get(q["outcome"], q["outcome"]),
                 "separates " + ", ".join(q.get("separates", [])),
                 f'asked: <data kind="question">{esc(q.get("approved_text") or q["question_text"])}</data>']
        if q.get("decision_note"):
            parts.append(f'analyst note: <data kind="decision_note">{esc(q["decision_note"], NOTE_CAP)}</data>')
        if q.get("reply_evidence_id"):
            parts.append(f"evidence {q['reply_evidence_id']}")
        if q.get("reply_text"):
            parts.append(f'reply: <data kind="merchant_reply">{esc(q["reply_text"], REPLY_CAP)}</data>')
        lines.append(" | ".join(parts))
    lines.append("</questions>")
    return lines


def render_latest(state: dict[str, Any]) -> list[str]:
    # A question outcome reason hasn't acted on yet is the latest finding; <questions> has its details.
    if state.get("question_outcome") in ("rejected", "replied", "no_reply", "unavailable") and state.get("questions"):
        q = state["questions"][-1]
        return [f'<latest_result kind="question" proposal="{q.get("proposal_id") or "none"}">',
                f"{QUESTION_OUTCOMES[q['outcome']]}. The details are in <questions>.",
                "</latest_result>"]
    latest = next((c for c in state.get("checks", []) if c["check_id"] == state.get("latest_check_id")), None)
    if latest is None:
        return ["<latest_result>none</latest_result>"]
    r = latest.get("result", {})
    kind = "load_case" if latest.get("source") == "load_case" else latest.get("kind")
    lines = [f'<latest_result check="{latest["check_id"]}" tool="{latest["tool"]}" kind="{kind}">']
    lines.append("request: " + esc(describe_request(latest["tool"], latest["request"]), 800))
    lines.extend(f"counts: {note}" for note in count_notes(latest["tool"], latest["request"]))
    if latest.get("purpose"):
        lines.append(f"purpose: {esc(latest['purpose'])}")
    for e in latest.get("expectations", []):
        lines.append(f"expectation {e['hypothesis_id']}: if_true {esc(e['if_true'])} | if_false {esc(e['if_false'])}")
    window = r.get("window", {})
    lines.append(
        f"window {window.get('start')} to {window.get('end')} | eligible_orders {r.get('eligible_orders')} | "
        f"pending_claims {r.get('pending_claims')} | data_sufficient {str(bool(r.get('data_sufficient'))).lower()}"
    )
    lines.append('<data kind="result">')
    lines.append(f"headline: {esc(r.get('headline'))}")
    metrics = r.get("metrics", [])
    if metrics:
        lines.append("metrics:")
        lines.extend(_metric_line(m) for m in metrics)
    notes = r.get("notes", [])
    if notes:
        lines.append("notes:")
        lines.extend(f"  - {esc(n)}" for n in notes)
    ids = r.get("evidence_ids", [])
    lines.append(
        f"evidence_ids: the first {min(len(ids), SHOWN_EVIDENCE_IDS)} of {len(ids)}: {', '.join(ids[:SHOWN_EVIDENCE_IDS]) or 'none'}"
    )
    records = r.get("evidence", [])
    if records:
        lines.append("records:")
        lines.extend(_record_line(e) for e in records)
    lines.append("</data>")
    lines.append("</latest_result>")
    return lines


def render_feedback(state: dict[str, Any]) -> list[str]:
    guard = state.get("guard_feedback")
    gate = state.get("gate_feedback")
    if not guard and not gate:
        return []
    lines = ['<data kind="feedback">']
    if guard:
        lines.append("Your last output was rejected. Problems:")
        lines.extend(f"- {v['rule']}: {esc(v['message'], 600)}" for v in guard.get("violations", []))
        if guard.get("rejected_action"):
            lines.append("The rejected next_action: " + esc(guard["rejected_action"], 800))
    if gate:
        lines.append("Your last conclusion did not pass the conclude gate. Unmet:")
        lines.extend(f"- {c['rule']}: {esc(c['detail'], 600)}" for c in gate.get("unmet", []))
    lines.append("</data>")
    return lines


def render_turn_state(state: dict[str, Any]) -> str:
    lines = [
        *render_hypotheses(state),
        *render_checks(state),
        *render_events(state),
        *render_questions(state),
        *render_latest(state),
        *render_feedback(state),
    ]
    return "\n".join(lines) + "\n"


# --- C: control ------------------------------------------------------------------------------


def render_control(state: dict[str, Any], settings: Settings) -> str:
    steps, max_steps = state.get("step_count", 0), settings.agent_max_steps
    calls = state.get("reason_calls", 0)
    lines = [
        f"Turn {calls + 1} of at most {settings.max_reason_calls}. Checks used: {steps} of {max_steps} "
        f"({max(0, max_steps - steps)} left). Explore checks used: {state.get('explore_count', 0)} of {EXPLORE_CAP}.",
    ]
    if settings.agent_max_questions <= state.get("questions_asked", 0):
        lines.append("Merchant questions: not available in this run.")
    else:
        lines.append(
            f"Merchant questions: {settings.agent_max_questions - state.get('questions_asked', 0)} left, "
            f"{'one is open' if state.get('question_open') else 'none open'}."
        )
    latest = next((c for c in state.get("checks", []) if c["check_id"] == state.get("latest_check_id")), None)
    if latest and latest.get("needs_match"):
        ids = ", ".join(e["hypothesis_id"] for e in latest.get("expectations", []))
        lines.append(f"matched: give exactly one entry for each of {ids} (the expectations of {latest['check_id']}).")
    else:
        lines.append("matched: must be [] this turn.")
    if not state.get("hypotheses"):
        lines.append("First turn: open at least two hypotheses from the overview, then choose the first check.")
    guard = state.get("guard_feedback")
    if guard:
        lines.append(
            f"Rejected last turn: {', '.join(guard.get('rule_ids', []))}. Fix every listed problem; the details are "
            f"in the feedback block. Rejections in a row: {state.get('consecutive_rejections', 0)} of 2."
        )
    gate = state.get("gate_feedback")
    if gate:
        lines.append(
            f"Conclude gate failed on {', '.join(c['rule'] for c in gate.get('unmet', []))}. "
            f"Gate failures so far: {state.get('gate_rejections', 0)} of 2."
        )
    items = checklist(state)
    lines.append(
        "Conclude checklist: "
        + "; ".join(f"{c['rule']} {'ok' if c['ok'] else 'missing'}: {c['detail']}" for c in items)
    )
    if steps >= max_steps:
        lines.append(
            "No checks left: this is the final turn. Conclude with your best-supported leader, or the run ends unsure."
        )
    return "\n".join(lines)


def render_prompt(state: dict[str, Any], settings: Settings) -> RenderedPrompt:
    return RenderedPrompt(
        system=system_prompt(),
        case_facts=render_case_facts(state),
        turn_state=render_turn_state(state),
        control=render_control(state, settings),
    )


def prompt_debug_dump(prompt: RenderedPrompt) -> str:
    return json.dumps(
        {"system": prompt.system, "case_facts": prompt.case_facts, "turn_state": prompt.turn_state,
         "control": prompt.control},
        indent=1,
    )
