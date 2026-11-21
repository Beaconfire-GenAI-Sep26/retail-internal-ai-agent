"""Guard rules G1-G18 and P1, as pure functions over the state and one ReasonOutput.

`evaluate_output` returns every violation it finds, plus the hypotheses, `matched` and next action
the output would produce if accepted. The guard node applies them only when there is no violation.
G6 and G7 arrive with reopening and reply weighing. G16 rejects every question while AGENT_MAX_QUESTIONS is 0.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from agent.app.contracts.enums import DAYPARTS
from agent.app.graph.policy import policy_hits
from agent.app.ids import IdFactory
from agent.app.llm import schemas as w
from agent.app.tools.registry import (
    ORDER_LEVEL_FIELDS,
    RATE_TOOLS,
    canonical_key,
    scopes,
    signature,
    to_contract_request,
)

DATA_LIMIT_CAUSES = frozenset({"dasher_handoff"})
EXPLORE_CAP = 3
BUCKET_MIN = {"1-2": 1, "3-4": 3, "5+": 5}
QUESTION_CAP = 300  # characters, for question_text and why_asked (G17)


def question_key(text: str) -> str:
    """Compares questions for G16's repeat rule: case, spacing and punctuation don't count."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


@dataclass
class Violation:
    rule: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message}


@dataclass
class GuardDecision:
    violations: list[Violation] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    matched: dict[str, str] = field(default_factory=dict)
    action: dict[str, Any] | None = None
    new_ids: dict[str, str] = field(default_factory=dict)
    budget_spent: bool = False
    blocked_action: bool = False

    @property
    def accepted(self) -> bool:
        return not self.violations

    @property
    def rule_ids(self) -> list[str]:
        return sorted({v.rule for v in self.violations})


# --- Check predicates, shared with the gate and the prompt ------------------------------------


def sufficient(check: dict[str, Any]) -> bool:
    return bool(check.get("result", {}).get("data_sufficient"))


def from_rate_tool(check: dict[str, Any]) -> bool:
    return check.get("tool") in RATE_TOOLS and not check.get("domain_rejected")


def can_support(hid: str, check: dict[str, Any]) -> bool:
    return (
        check.get("kind") in ("test", "challenge")
        and sufficient(check)
        and from_rate_tool(check)
        and check.get("matched", {}).get(hid) == "if_true"
    )


def can_rule_out(hid: str, check: dict[str, Any]) -> bool:
    return (
        hid in check.get("discriminates", [])
        and sufficient(check)
        and from_rate_tool(check)
        and check.get("matched", {}).get(hid) == "if_false"
    )


def can_leave_inconclusive(hid: str, cause: str, check: dict[str, Any]) -> bool:
    if hid not in check.get("discriminates", []):
        return False
    return not sufficient(check) or check.get("matched", {}).get(hid) == "neither"


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


# --- Value normalization (G11) ---------------------------------------------------------------


@dataclass
class MenuIndex:
    items: dict[str, str]  # upper-case id or lower-case name -> item_id
    modifiers: dict[str, str]  # lower-case name -> menu spelling

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> MenuIndex:
        items: dict[str, str] = {}
        for item in state.get("menu", []):
            items[item["item_id"].upper()] = item["item_id"]
            items.setdefault(item["name"].strip().lower(), item["item_id"])
        for iid in state.get("known_items", []):
            items.setdefault(iid.upper(), iid)
        modifiers = {m.strip().lower(): m for m in state.get("known_modifiers", [])}
        return cls(items, modifiers)

    def item(self, value: str) -> str | None:
        v = value.strip()
        return self.items.get(v.upper()) or self.items.get(v.lower())

    def modifier(self, value: str) -> str | None:
        return self.modifiers.get(value.strip().lower())


def normalize_scope(scope: dict[str, Any], menu: MenuIndex) -> list[str]:
    """Rewrite item IDs and modifiers to the menu's spelling in place. Returns unknown values."""
    unknown: list[str] = []
    if "item_id" in scope:
        fixed = []
        for v in scope["item_id"]:
            iid = menu.item(str(v))
            if iid is None:
                unknown.append(f"item_id {v!r}")
            elif iid not in fixed:
                fixed.append(iid)
        scope["item_id"] = sorted(fixed)
    if "modifiers" in scope:
        fixed = []
        for v in scope["modifiers"]:
            mod = menu.modifier(str(v))
            if mod is None:
                unknown.append(f"modifier {v!r}")
            elif mod not in fixed:
                fixed.append(mod)
        scope["modifiers"] = sorted(fixed)
    return unknown


def request_problems(
    tool: str, request: dict[str, Any], window: dict[str, str]
) -> tuple[list[str], list[str]]:
    """(G10 problems, G11 date problems) for one contract request."""
    g10: list[str] = []
    g11: list[str] = []
    lo, hi = parse_date(window["start"]), parse_date(window["end"])

    def in_window(label: str, d: date) -> None:
        if lo and hi and not lo <= d <= hi:
            g11.append(f"{label} {d.isoformat()} is outside the window {window['start']} to {window['end']}")

    def check_span(container: dict[str, Any], prefix: str) -> None:
        start, end = parse_date(container.get("start", "")), parse_date(container.get("end", ""))
        if start is None or end is None:
            g10.append(f"{prefix}start and end must be YYYY-MM-DD dates")
            return
        if start > end:
            g10.append(f"{prefix}start {start} is after end {end}")
        in_window(prefix + "start", start)
        in_window(prefix + "end", end)

    if tool == "compare_periods":
        split = parse_date(request.get("split_date", ""))
        before, after = request.get("days_before", 0), request.get("days_after", 0)
        if not 1 <= before <= 28:
            g10.append(f"days_before must be 1 to 28, not {before}")
        if not 1 <= after <= 28:
            g10.append(f"days_after must be 1 to 28, not {after}")
        if split is None:
            g10.append("split_date must be a YYYY-MM-DD date")
        elif 1 <= before <= 28 and 1 <= after <= 28:
            in_window("the before period's first day", split - timedelta(days=before))
            in_window("the after period's last day", split + timedelta(days=after - 1))
    elif "filter" in request:
        check_span(request["filter"], "filter ")
    else:
        check_span(request, "")
    if tool == "sample_evidence" and not 1 <= request.get("limit", 0) <= 10:
        g10.append(f"limit must be 1 to 10, not {request.get('limit')}")
    if tool == "compare_periods" and request.get("control") == {}:
        g10.append("control_mode scope needs at least one control field; use rest_of_store otherwise")
    if (tool == "compare_periods" and request.get("control") is None
            and not ORDER_LEVEL_FIELDS & set(request.get("target") or {})):
        g10.append("control_mode rest_of_store needs a target with an order-level field (item_id, modifiers, "
                   "daypart, weekday, item_count_min or item_count_max); otherwise the target covers every "
                   "order and the control is empty")
    for role, scope in scopes(tool, request):
        for wd in scope.get("weekday", []):
            if not 0 <= wd <= 6:
                g10.append(f"{role} weekday {wd} must be 0 to 6")
        lo_n, hi_n = scope.get("item_count_min", 0), scope.get("item_count_max", 0)
        if lo_n < 0 or hi_n < 0:
            g10.append(f"{role} item counts can't be negative")
        if lo_n > 0 and hi_n > 0 and lo_n > hi_n:
            g10.append(f"{role} item_count_min {lo_n} is above item_count_max {hi_n}")
    return g10, g11


# --- Target coverage (G18) -------------------------------------------------------------------


def _groups(check: dict[str, Any]) -> set[str]:
    return {m.get("group") for m in check.get("result", {}).get("metrics", []) if m.get("group")}


def target_gaps(target: dict[str, Any], leader: str, checks: list[dict[str, Any]]) -> list[str]:
    """Target values that no check supporting the leader filtered on or grouped by."""
    support = [c for c in checks if c.get("matched", {}).get(leader) == "if_true"]

    def covered(field: str, value: Any, group_by: str) -> bool:
        for c in support:
            for _, scope in scopes(c["tool"], c["request"]):
                if field == "item_count_min" and scope.get("item_count_min") == value:
                    return True
                if field != "item_count_min" and value in scope.get(field, []):
                    return True
            if c["request"].get("group_by") == group_by:
                groups = _groups(c)
                if field == "item_count_min":
                    if any(BUCKET_MIN.get(g.split("=", 1)[1]) == value for g in groups if g.startswith("item_count=")):
                        return True
                elif f"{group_by}={value}" in groups:
                    return True
        return False

    gaps = []
    for value in target.get("item_id", []):
        if not covered("item_id", value, "item_id"):
            gaps.append(f"item_id {value}")
    for value in target.get("modifiers", []):
        if not covered("modifiers", value, "modifier"):
            gaps.append(f"modifier {value}")
    for value in target.get("daypart", []):
        if not covered("daypart", value, "daypart"):
            gaps.append(f"daypart {value}")
    if target.get("item_count_min") and not covered("item_count_min", target["item_count_min"], "item_count"):
        gaps.append(f"item_count_min {target['item_count_min']}")
    return gaps


# --- The guard -------------------------------------------------------------------------------


def _summarize_validation(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:6]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', '')}")
    return "The output doesn't match the response schema: " + "; ".join(parts)


def evaluate_output(
    state: dict[str, Any],
    raw: Any,
    *,
    max_steps: int,
    max_questions: int,
    ids: IdFactory,
    max_reason_calls: int | None = None,
) -> GuardDecision:
    decision = GuardDecision()
    v = decision.violations
    try:
        out = w.parse_reason_output(raw)
    except ValidationError as exc:
        v.append(Violation("SCHEMA", _summarize_validation(exc)))
        return decision

    before = {h["hypothesis_id"]: h for h in state.get("hypotheses", [])}
    retrieved = set(state.get("retrieved_evidence_ids", []))
    checks = state.get("checks", [])
    latest = next((c for c in checks if c["check_id"] == state.get("latest_check_id")), None)
    window = state.get("window") or {"start": "", "end": ""}
    menu = MenuIndex.from_state(state)

    # G2: refs for new hypotheses
    refs: dict[str, str] = {}
    for nh in out.new_hypotheses:
        ref = nh.ref.strip()
        if not ref or ref in refs or ref in before or ref.upper().startswith("HYP-"):
            v.append(Violation("G2", f"new hypothesis ref {ref!r} must be unique and must not be a HYP- id"))
            continue
        refs[ref] = ids.new("HYP")
    decision.new_ids = refs

    def resolve(value: str) -> str:
        value = value.strip()
        return refs.get(value, value)

    # G2: updates name existing hypotheses, once each
    seen_updates: set[str] = set()
    for u in out.hypothesis_updates:
        if u.hypothesis_id not in before:
            v.append(Violation("G2", f"hypothesis_updates names {u.hypothesis_id}, which doesn't exist. "
                                     "Open new hypotheses in new_hypotheses."))
        elif u.hypothesis_id in seen_updates:
            v.append(Violation("G2", f"{u.hypothesis_id} is updated twice in one output"))
        seen_updates.add(u.hypothesis_id)

    # G2: new hypotheses are specific and don't duplicate an open cause
    open_causes = {h["cause_category"]: hid for hid, h in before.items() if h["status"] in ("open", "supported")}
    new_causes: set[str] = set()
    for nh in out.new_hypotheses:
        if not nh.statement.strip():
            v.append(Violation("G2", f"new hypothesis {nh.ref!r} needs a statement"))
        if nh.cause_category == "other" and len(nh.statement.split()) < 5:
            v.append(Violation("G2", f"new hypothesis {nh.ref!r} has cause other and needs a specific statement"))
        if nh.cause_category != "other":
            if nh.cause_category in open_causes:
                v.append(Violation("G2", f"{nh.cause_category} is already open as {open_causes[nh.cause_category]}. "
                                         "Update its statement to narrow it instead of opening another."))
            elif nh.cause_category in new_causes:
                v.append(Violation("G2", f"two new hypotheses share cause {nh.cause_category}"))
            new_causes.add(nh.cause_category)

    # G1: citations come from the retrieved set
    cited = [e for u in out.hypothesis_updates for e in (*u.add_supporting, *u.add_contradicting)]
    cited += [e for nh in out.new_hypotheses for e in nh.evidence]
    unknown = sorted({e.strip() for e in cited if e.strip() not in retrieved})
    if unknown:
        v.append(Violation("G1", "cited evidence IDs that no check returned: " + ", ".join(unknown[:10])))

    # G9: matched covers exactly the latest check's expectations while it is unmatched
    expected = [e["hypothesis_id"] for e in latest.get("expectations", [])] if latest and latest.get("needs_match") else []
    given = [m.hypothesis_id.strip() for m in out.matched]
    if sorted(given) != sorted(set(expected)) or len(given) != len(set(given)):
        want = ", ".join(expected) if expected else "nothing"
        v.append(Violation("G9", f"matched must cover exactly: {want}. It covered: {', '.join(given) or 'nothing'}."))
        matched: dict[str, str] = {}
    else:
        matched = {m.hypothesis_id.strip(): m.outcome for m in out.matched}
    decision.matched = matched

    # Apply the hypothesis changes to a copy
    after = {hid: copy.deepcopy(h) for hid, h in before.items()}
    for nh in out.new_hypotheses:
        hid = refs.get(nh.ref.strip())
        if hid is None:
            continue
        after[hid] = {
            "hypothesis_id": hid,
            "cause_category": nh.cause_category,
            "statement": nh.statement.strip(),
            "status": "open",
            "rationale": nh.rationale.strip(),
            "supporting_evidence_ids": list(dict.fromkeys(e.strip() for e in nh.evidence)),
            "contradicting_evidence_ids": [],
            "check_ids": [],
        }
    for u in out.hypothesis_updates:
        h = after.get(u.hypothesis_id)
        if h is None:
            continue
        h["status"] = u.status
        if u.statement.strip():
            h["statement"] = u.statement.strip()
        if u.rationale.strip():
            h["rationale"] = u.rationale.strip()
        h["supporting_evidence_ids"] = list(dict.fromkeys([*h["supporting_evidence_ids"], *(e.strip() for e in u.add_supporting)]))
        h["contradicting_evidence_ids"] = list(
            dict.fromkeys([*h["contradicting_evidence_ids"], *(e.strip() for e in u.add_contradicting)])
        )

    checks_after = [
        {**c, "matched": matched, "needs_match": False} if latest and c["check_id"] == latest["check_id"] and expected else c
        for c in checks
    ]

    # G3, G4, G4b, G5 on every status change
    rationale_by_id = {u.hypothesis_id: u.rationale.strip() for u in out.hypothesis_updates}
    for hid, h in after.items():
        old = before.get(hid, {}).get("status")
        new = h["status"]
        if new == old:
            continue
        cause = h["cause_category"]
        if cause in DATA_LIMIT_CAUSES and new in ("supported", "ruled_out"):
            v.append(Violation("G5", f"{hid} is {cause}, which platform data can't support or rule out"))
        elif new == "supported" and not any(can_support(hid, c) for c in checks_after):
            v.append(Violation("G3", f"{hid} can't be supported: no sufficient test or challenge check from a "
                                     f"rate tool has matched {hid} = if_true"))
        elif new == "ruled_out":
            if not any(can_rule_out(hid, c) for c in checks_after):
                v.append(Violation("G4", f"{hid} can't be ruled out: no sufficient rate-tool check that lists it in "
                                         f"discriminates has matched {hid} = if_false"))
            if not rationale_by_id.get(hid):
                v.append(Violation("G4", f"ruling out {hid} needs a rationale"))
        elif new == "inconclusive":
            if not (cause in DATA_LIMIT_CAUSES or any(can_leave_inconclusive(hid, cause, c) for c in checks_after)):
                v.append(Violation("G4b", f"{hid} can be inconclusive only after a check on it was insufficient or "
                                          "matched neither, or when its cause is a data limit"))
            if not rationale_by_id.get(hid) and not h["rationale"]:
                v.append(Violation("G4b", f"{hid} needs its gap written in the rationale"))

    # G8
    if len(after) < 2:
        v.append(Violation("G8", f"keep at least two hypotheses; this output leaves {len(after)}"))

    # P1 on free text the analyst sees
    for hid, h in after.items():
        for label, text in (("statement", h["statement"]), ("rationale", h["rationale"])):
            hits = policy_hits(text, actions=False)
            if hits:
                v.append(Violation("P1", f"{hid} {label} contains {', '.join(hits)}"))
                decision.blocked_action = True

    for hid, h in after.items():
        h["check_ids"] = [
            c["check_id"]
            for c in checks_after
            if hid in c.get("discriminates", []) or c.get("challenges") == hid
        ]
    decision.hypotheses = [after[hid] for hid in [*before, *[r for r in refs.values()]] if hid in after]

    action = out.next_action
    if isinstance(action, w.CheckAction):
        if state.get("step_count", 0) >= max_steps:
            decision.budget_spent = True
            decision.action = {"type": "check", "plan": None}
            return decision
        decision.action = _check_action(state, action.plan, after, resolve, menu, window, checks, v)
    elif isinstance(action, w.AskMerchantAction):
        question, why = action.question_text.strip(), action.why_asked.strip()
        # G16: a question left, none open, not asked before, and a turn left to use the answer
        if max_questions <= state.get("questions_asked", 0):
            v.append(Violation("G16", "merchant questions are not available in this run"))
        elif state.get("question_open"):
            v.append(Violation("G16", "a merchant question is already open"))
        elif question_key(question) in {question_key(q["question_text"]) for q in state.get("questions", [])}:
            v.append(Violation("G16", "this question was already asked in this run. Don't ask it again."))
        elif max_reason_calls is not None and state.get("reason_calls", 0) >= max_reason_calls:
            v.append(Violation("G16", "no reasoning turn is left to use an answer"))
        # G17: one clear question that names what it separates
        if not 0 < len(question) <= QUESTION_CAP or "?" not in question:
            v.append(Violation("G17", f"question_text must be one question of 1 to {QUESTION_CAP} characters, "
                                      "with a question mark"))
        if not 0 < len(why) <= QUESTION_CAP:
            v.append(Violation("G17", f"why_asked must be 1 to {QUESTION_CAP} characters"))
        separates = [resolve(s) for s in action.separates]
        if not 1 <= len(separates) <= 3 or len(set(separates)) != len(separates):
            v.append(Violation("G17", "separates must list 1 to 3 different hypotheses"))
        for hid in dict.fromkeys(separates):
            if hid not in after:
                v.append(Violation("G17", f"separates names {hid}, which doesn't exist"))
            elif after[hid]["status"] == "ruled_out":
                v.append(Violation("G17", f"separates names {hid}, which is ruled out"))
        for label, text in (("question_text", question), ("why_asked", why)):
            hits = policy_hits(text, actions=True)
            if hits:
                v.append(Violation("P1", f"{label} contains {', '.join(hits)}"))
                decision.blocked_action = True
        decision.action = {"type": "ask_merchant", "question_text": question, "why_asked": why,
                           "separates": separates}
    else:
        decision.action = _conclude_action(state, action, after, resolve, menu, window, checks_after, v, decision)
    return decision


def _check_action(
    state: dict[str, Any],
    plan: w.CheckPlanWire,
    after: dict[str, dict[str, Any]],
    resolve: Any,
    menu: MenuIndex,
    window: dict[str, str],
    checks: list[dict[str, Any]],
    v: list[Violation],
) -> dict[str, Any]:
    tool, request = to_contract_request(plan.request)
    request = copy.deepcopy(request)
    unknown: list[str] = []
    for _, scope in scopes(tool, request):
        unknown += normalize_scope(scope, menu)
    g10, g11 = request_problems(tool, request, window)
    for problem in g10:
        v.append(Violation("G10", problem))
    if unknown:
        v.append(Violation("G11", "values not on the store's menu: " + ", ".join(unknown)))
    for problem in g11:
        v.append(Violation("G11", problem))

    discriminates = list(dict.fromkeys(resolve(x) for x in plan.discriminates if x.strip()))
    expectations = [
        {"hypothesis_id": resolve(e.hypothesis_id), "if_true": e.if_true.strip(), "if_false": e.if_false.strip()}
        for e in plan.expectations
    ]
    challenges = resolve(plan.challenges) if plan.challenges.strip() else None
    missing = [h for h in [*discriminates, *(e["hypothesis_id"] for e in expectations)] if h not in after]
    if missing:
        v.append(Violation("G12", "the plan names hypotheses that don't exist: " + ", ".join(sorted(set(missing)))))
    if plan.kind in ("test", "challenge"):
        exp_ids = [e["hypothesis_id"] for e in expectations]
        if not discriminates:
            v.append(Violation("G12", f"a {plan.kind} check must name the hypotheses it separates"))
        if sorted(exp_ids) != sorted(discriminates):
            v.append(Violation("G12", "give exactly one expectation per hypothesis in discriminates"))
        if any(not e["if_true"] or not e["if_false"] for e in expectations):
            v.append(Violation("G12", "every expectation needs both if_true and if_false"))
    if plan.kind == "challenge":
        if challenges is None or challenges not in discriminates:
            v.append(Violation("G12", "a challenge must name its target in challenges and in discriminates"))
        elif after.get(challenges, {}).get("status") not in ("open", "supported"):
            v.append(Violation("G12", f"a challenge targets an open or supported hypothesis, not {challenges}"))
    elif challenges is not None:
        v.append(Violation("G12", 'challenges is only for challenge checks; use ""'))
    if plan.kind == "explore" and state.get("explore_count", 0) >= EXPLORE_CAP:
        v.append(Violation("G13", f"the run already used its {EXPLORE_CAP} explore checks; plan a test or challenge"))
    key = canonical_key(tool, request)
    if any(c.get("canonical_key") == key for c in checks):
        v.append(Violation("G14", f"this exact query already ran: {tool} with the same arguments"))
    for label, text in (("purpose", plan.purpose),
                        *(("expectation", t) for e in expectations for t in (e["if_true"], e["if_false"]))):
        hits = policy_hits(text, actions=False)
        if hits:
            v.append(Violation("P1", f"{label} contains {', '.join(hits)}"))
    return {
        "type": "check",
        "plan": {
            "kind": plan.kind,
            "tool": tool,
            "request": request,
            "canonical_key": key,
            "signature": signature(tool, request),
            "purpose": plan.purpose.strip(),
            "discriminates": discriminates,
            "expectations": expectations,
            "challenges": challenges,
        },
    }


def _conclude_action(
    state: dict[str, Any],
    action: w.ConcludeAction,
    after: dict[str, dict[str, Any]],
    resolve: Any,
    menu: MenuIndex,
    window: dict[str, str],
    checks: list[dict[str, Any]],
    v: list[Violation],
    decision: GuardDecision,
) -> dict[str, Any]:
    leader = resolve(action.leading_hypothesis_id)
    hyp = after.get(leader)
    if hyp is None:
        v.append(Violation("G18", f"the leading hypothesis {leader} doesn't exist"))
    rise = parse_date(action.rise_started_at)
    lo, hi = parse_date(window.get("start", "")), parse_date(window.get("end", ""))
    if rise is None:
        v.append(Violation("G18", "rise_started_at must be a YYYY-MM-DD date"))
    elif lo and hi and not lo <= rise <= hi:
        v.append(Violation("G18", f"rise_started_at {rise} is outside the window {window['start']} to {window['end']}"))
    rec = action.recommendation
    entry = next((e for e in state.get("catalog", []) if e["action_id"] == rec.action_id.strip()), None)
    if entry is None:
        v.append(Violation("G18", f"action {rec.action_id!r} is not in the catalog"))
    elif hyp is not None and hyp["cause_category"] not in entry.get("applies_to", []):
        v.append(Violation("G18", f"action {entry['action_id']} doesn't apply to {hyp['cause_category']}"))
    target = {
        "item_id": list(rec.target.item_id),
        "modifiers": list(rec.target.modifiers),
        "daypart": sorted(set(rec.target.daypart), key=DAYPARTS.index),
        "item_count_min": rec.target.item_count_min,
    }
    unknown = normalize_scope(target, menu)
    if unknown:
        v.append(Violation("G18", "target values not on the store's menu: " + ", ".join(unknown)))
    if target["item_count_min"] < 0:
        v.append(Violation("G18", "target item_count_min can't be negative"))
    if hyp is not None and not unknown:
        gaps = target_gaps(target, leader, checks)
        if gaps:
            v.append(Violation("G18", "target values no supporting check tested: " + ", ".join(gaps)))
    for label, text in (("summary", action.summary), ("recommendation rationale", rec.rationale)):
        hits = policy_hits(text, actions=True)
        if hits:
            v.append(Violation("P1", f"{label} contains {', '.join(hits)}"))
            decision.blocked_action = True
    return {
        "type": "conclude",
        "leading_hypothesis_id": leader,
        "rise_started_at": rise.isoformat() if rise else action.rise_started_at.strip(),
        "confidence": action.confidence,
        "summary": action.summary.strip(),
        "recommendation": {
            "action_id": rec.action_id.strip(),
            "rationale": rec.rationale.strip(),
            "target": {**target, "item_count_min": target["item_count_min"] or None},
        },
    }
