"""Scripted reason turns for graph and API tests. Placeholders are resolved by ScriptedReasonModel."""

from __future__ import annotations

from typing import Any

FULL = ("2026-10-05", "2026-11-15")


def scope(**kw: Any) -> dict[str, Any]:
    base = {"item_id": [], "modifiers": [], "daypart": [], "weekday": [], "item_count_min": 0,
            "item_count_max": 0, "error_category": [], "review_label": []}
    base.update(kw)
    return base


def claim_filter(start: str, end: str, **kw: Any) -> dict[str, Any]:
    return {"start": start, "end": end, **scope(**kw)}


def cxl_filter(start: str, end: str, **kw: Any) -> dict[str, Any]:
    base = {"start": start, "end": end, "item_id": [], "daypart": [], "weekday": [], "cancellation_category": []}
    base.update(kw)
    return base


def new(ref: str, cause: str, statement: str, rationale: str = "Fits the overview.", evidence: list[str] | None = None):
    return {"ref": ref, "cause_category": cause, "statement": statement, "rationale": rationale,
            "evidence": evidence or []}


def upd(hid: str, status: str, rationale: str, supporting: list[str] | None = None,
        contradicting: list[str] | None = None, statement: str = "") -> dict[str, Any]:
    return {"hypothesis_id": hid, "status": status, "statement": statement, "add_supporting": supporting or [],
            "add_contradicting": contradicting or [], "rationale": rationale}


def exp(hid: str, if_true: str, if_false: str) -> dict[str, str]:
    return {"hypothesis_id": hid, "if_true": if_true, "if_false": if_false}


def check(kind: str, purpose: str, request: dict[str, Any], discriminates: list[str] | None = None,
          expectations: list[dict[str, str]] | None = None, challenges: str = "") -> dict[str, Any]:
    return {"type": "check", "plan": {"kind": kind, "purpose": purpose, "discriminates": discriminates or [],
                                      "expectations": expectations or [], "challenges": challenges,
                                      "request": request}}


def event_log_request(start: str = FULL[0], end: str = FULL[1]) -> dict[str, Any]:
    return {"tool": "event_log", "start": start, "end": end, "event_type": []}


def breakdown(group_by: str, start: str, end: str, **kw: Any) -> dict[str, Any]:
    return {"tool": "claim_breakdown", "filter": claim_filter(start, end, **kw), "group_by": group_by}


def compare(split: str, before: int, after: int, target: dict[str, Any]) -> dict[str, Any]:
    return {"tool": "compare_periods", "split_date": split, "days_before": before, "days_after": after,
            "target": target, "control_mode": "rest_of_store", "control": scope()}


def conclude(leader: str, rise: str, confidence: str, summary: str, action_id: str, rationale: str,
             **target: Any) -> dict[str, Any]:
    t = {"item_id": [], "modifiers": [], "daypart": [], "item_count_min": 0}
    t.update(target)
    return {"type": "conclude", "leading_hypothesis_id": leader, "rise_started_at": rise, "confidence": confidence,
            "summary": summary, "recommendation": {"action_id": action_id, "rationale": rationale, "target": t}}


def out(assessment: str, next_action: dict[str, Any], *, matched: list[tuple[str, str]] | None = None,
        updates: list[dict[str, Any]] | None = None, new_hypotheses: list[dict[str, Any]] | None = None):
    return {"assessment": assessment,
            "matched": [{"hypothesis_id": h, "outcome": o} for h, o in (matched or [])],
            "hypothesis_updates": updates or [], "new_hypotheses": new_hypotheses or [],
            "next_action": next_action}


POS, MENU, INV = "@hyp:pos_modifier_mapping", "@hyp:menu_change", "@hyp:inventory"


def store_a_turns() -> list[dict[str, Any]]:
    return [
        out("The rate rose from about 1% to over 10% from Oct 30, mostly incorrect_item and ingredient_error.",
            check("explore", "Read every event in the window to find what changed near the rise.", event_log_request()),
            new_hypotheses=[
                new("N1", "pos_modifier_mapping", "A modifier is not reaching the kitchen, so items come out wrong."),
                new("N2", "menu_change", "A recent menu change confuses the kitchen on the affected items."),
                new("N3", "inventory", "Out-of-stock items forced substitutions that customers report as wrong."),
            ]),
        out("Two menu changes landed on Oct 30: the Extra sauce modifier and a drink rename.",
            check("test", "Check whether claims concentrate on one modifier.", breakdown("modifier", *FULL),
                  [POS, MENU], [exp(POS, "Extra sauce carries far more than its share of claims",
                                    "No modifier carries more than its share of claims"),
                                exp(MENU, "Claims spread with no modifier concentration",
                                    "Claims concentrate on one modifier")]),
            updates=[upd(POS, "open", "The Extra sauce modifier was added on Oct 30.", ["@event:Extra sauce"]),
                     upd(MENU, "open", "The drink was renamed the same morning.", ["@event:Renamed"])]),
        out("Extra sauce has about 79% of claims on about 20% of orders, a lift near 4.",
            check("test", "Find the day the rise started, to test the Oct 24-26 stock-outs.", breakdown("day", *FULL),
                  [INV], [exp(INV, "The daily rate rises from Oct 24", "The daily rate stays flat until Oct 30")]),
            matched=[(POS, "if_true"), (MENU, "if_false")],
            updates=[upd(POS, "supported", "Claims concentrate on Extra sauce orders.", ["@latest_ev:5"]),
                     upd(MENU, "ruled_out", "Claims sit on the modifier, not on the renamed drink.")]),
        out("The daily rate stays near 1% until Oct 29 and jumps from Oct 30.",
            check("challenge", "Compare Extra sauce orders with the rest of the store around Oct 30.",
                  compare("2026-10-30", 14, 17, scope(modifiers=["Extra sauce"])), [POS],
                  [exp(POS, "Extra sauce orders run far above a flat rest of store",
                       "The rest of the store rises as much as Extra sauce orders")], challenges=POS),
            matched=[(INV, "if_false")],
            updates=[upd(INV, "ruled_out", "The rise starts on Oct 30, after the stock-outs ended.")]),
        out("Extra sauce orders run at about 18.5% after Oct 30 while the rest of the store stays near 1%.",
            conclude(POS, "2026-10-30", "high",
                     "Since Oct 30, about 1 in 5 orders with Extra sauce got an incorrect_item or ingredient_error "
                     "claim, while the rest of the store stayed near 1%.",
                     "fix_modifier_mapping", "The rise starts with the Oct 30 modifier and is limited to it.",
                     modifiers=["Extra sauce"]),
            matched=[(POS, "if_true")]),
    ]


PACK, OTHER, DASH = "@hyp:packing", "@hyp:other", "@hyp:dasher_handoff"
B_POST = ("2026-11-03", "2026-11-15")


def store_b_turns() -> list[dict[str, Any]]:
    return [
        out("The rate rose in early November, mostly missing_item claims.",
            check("explore", "Read every event in the window.", event_log_request()),
            new_hypotheses=[
                new("N1", "packing", "Large orders leave the store with items or whole bags missing."),
                new("N2", "menu_change", "A recent menu change led to missing items."),
                new("N3", "other", "Promotion volume overloaded the kitchen during the promotion week."),
                new("N4", "dasher_handoff", "Whole bags are lost at the Dasher handoff."),
            ]),
        out("A dessert price change on Nov 1 and a promotion from Nov 3 to Nov 9.",
            check("test", "Check whether claims concentrate on large orders since Nov 3.",
                  breakdown("item_count", *B_POST), [PACK, MENU],
                  [exp(PACK, "The 5+ bucket carries far more than its share of claims", "No size concentration"),
                   exp(MENU, "Claims concentrate on the repriced dessert", "Claims concentrate on large orders")]),
            updates=[upd(MENU, "open", "The dessert price changed on Nov 1.", ["@event:Pecan Pie"]),
                     upd(OTHER, "open", "The promotion started on Nov 3.", ["@event:Promotion"])]),
        out("Since Nov 3, 5+ item orders hold about 81% of claims on 17% of orders.",
            check("test", "Check which daypart the large-order claims sit in.",
                  breakdown("daypart", *B_POST, item_count_min=5), [PACK],
                  [exp(PACK, "Dinner holds most large-order claims", "Large-order claims spread across dayparts")]),
            matched=[(PACK, "if_true"), (MENU, "if_false")],
            updates=[upd(PACK, "supported", "Claims concentrate on 5+ item orders.", ["@latest_ev:5"]),
                     upd(MENU, "ruled_out", "A price change can't explain missing items on large orders.")]),
        out("Dinner holds about 98% of the large-order claims.",
            check("challenge", "Test whether the large dinner rate falls after the promotion ends on Nov 10.",
                  compare("2026-11-10", 7, 6, scope(daypart=["dinner"], item_count_min=5)), [PACK, OTHER],
                  [exp(PACK, "The rate stays high after Nov 10", "The rate falls back after Nov 10"),
                   exp(OTHER, "The rate falls back after Nov 10", "The rate stays high after Nov 10")],
                  challenges=PACK),
            matched=[(PACK, "if_true")],
            updates=[upd(PACK, "supported", "The concentration is in dinner orders with 5+ items.",
                         statement="Dinner orders with 5+ items leave the store with items or a bag missing.")]),
        out("The large dinner rate stays near 39% after the promotion, against a flat 1% elsewhere.",
            check("explore", "Check dinner cancellations by weekday for a busy-night pattern.",
                  {"tool": "cancellation_breakdown", "filter": cxl_filter(*FULL, daypart=["dinner"]),
                   "group_by": "weekday"}),
            matched=[(PACK, "if_true"), (OTHER, "if_false")],
            updates=[upd(OTHER, "ruled_out", "The rate stays high after the promotion ended."),
                     upd(DASH, "inconclusive", "There is no Dasher data, so handoff can't be tested.")]),
        out("Friday dinners show too_busy cancellations across the whole window, unrelated to the rise.",
            conclude(PACK, "2026-11-03", "high",
                     "Since Nov 3, dinner orders with 5 or more items ran a claim rate near 39%, against about 1% "
                     "for the rest of the store, and it persisted after the promotion ended.",
                     "large_order_bag_check", "Missing items concentrate on large dinner orders.",
                     daypart=["dinner"], item_count_min=5)),
    ]
