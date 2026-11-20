"""The seven model tools: prompt text, wire-to-contract conversion, canonical keys, Domain calls.

A contract request is a plain JSON dict shaped exactly as contracts.md sends it to Domain.
Empty wire values ("", [], 0) are dropped, so the dict only holds real constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from agent.app.contracts.enums import (
    CANCELLATION_CATEGORIES,
    DAYPARTS,
    DEFAULT_REVIEW_LABELS,
    ERROR_CATEGORIES,
    EVENT_TYPES,
    REVIEW_LABELS,
)
from agent.app.contracts.models import ToolResult
from agent.app.llm import schemas as w

if TYPE_CHECKING:
    from agent.app.domain.client import DomainPort

REGISTRY_VERSION = "2026-11-19.3"
MIN_GROUP_ORDERS_TEXT = "MIN_GROUP_ORDERS (30 by default)"

RATE_TOOLS = frozenset(
    {"store_overview", "claim_breakdown", "compare_periods", "cancellation_breakdown", "fraud_signals"}
)
RECORD_TOOLS = frozenset({"event_log", "sample_evidence"})
MODEL_TOOLS = RATE_TOOLS | RECORD_TOOLS
# Scope fields that select orders. Domain's rest_of_store control is every delivered order outside the
# target, so a target without one of these covers every order and leaves the control empty.
ORDER_LEVEL_FIELDS = frozenset({"item_id", "modifiers", "daypart", "weekday", "item_count_min", "item_count_max"})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    measures: str
    cannot_show: str
    arguments: str
    metrics: str
    notes: tuple[str, ...] = ()
    returns: str = ""  # overrides the "Returns" line of the prompt
    examples: tuple[str, ...] = ()  # request JSON, as the model writes it in plan.request

    @property
    def returns_rates(self) -> bool:
        return self.name in RATE_TOOLS


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="store_overview",
            measures="Overall claim rate, eligible orders, claims by review_label and error_category, "
            "and the daily rate, for a date range.",
            cannot_show="Why the rate moved.",
            arguments="start, end",
            metrics="claim_rate (group null); claim_count per review_label=<label>, all four labels "
            "including the excluded ones; claim_count per error_category=<category>; "
            "daily_claim_rate per day=<YYYY-MM-DD>",
            notes=(
                "Already run for the whole window at the start. It is the first check.",
                "Its evidence_ids list up to 200 claims in the range, newest first, of every review_label "
                "including fraud and not_store_fault; a note says when the list is cut.",
            ),
            examples=('{"tool": "store_overview", "start": "<start>", "end": "<end>"}',),
        ),
        ToolSpec(
            name="event_log",
            measures="Events of every event_type (menu_change, pos_change, store_downtime, promotion) "
            "with started_at, ended_at and description, oldest first.",
            cannot_show="Their effect. Pair an event with compare_periods.",
            arguments="start, end, event_type ([] for all types)",
            metrics="None. The events come back as records.",
            notes=(
                "It returns every event that overlaps the dates, including one that started earlier and "
                "has no ended_at, which means it is still in effect.",
                "A description is the only link from an event to an item or modifier.",
            ),
            examples=('{"tool": "event_log", "start": "<start>", "end": "<end>", "event_type": []}',),
        ),
        ToolSpec(
            name="claim_breakdown",
            measures="For one grouping within a filter: each group's claim rate, its share of claims "
            "and its share of orders.",
            cannot_show="Cause. Concentration is a lead, not proof.",
            arguments="filter (a claim filter), group_by: item_id, modifier, daypart, weekday, "
            "item_count, error_category, review_label or day",
            metrics="claim_rate, claim_share and order_share per group <group_by>=<value>. "
            "item_count groups are 1-2, 3-4 and 5+.",
            notes=(
                "Rows come ranked, not in natural order: groups with enough orders first, then by lift, "
                "highest first.",
                "Grouped by modifier, claims with no modifier_detail form no group. The note gives "
                "their count, and the shares don't add up to 1.",
                "Grouped by item_id, claims with no item_id fall into item_id=unknown, which has no "
                "order denominator, so its claim_rate and order_share are null.",
                "Grouped by error_category or review_label, every group's claim_rate uses all eligible "
                "orders in the filter, and order_share is null.",
                "An item_id or modifiers filter counts the orders that contain the value, and only the "
                "claims whose item_id or modifier_detail matches it.",
                "Lift is claim_share divided by order_share. Above 1 means more than a fair share "
                "of claims.",
            ),
            examples=(
                '{"tool": "claim_breakdown", "filter": {"start": "<start>", "end": "<end>", "daypart": ["<daypart>"]}, '
                '"group_by": "<group_by>"}',
            ),
        ),
        ToolSpec(
            name="compare_periods",
            measures="The claim rate before and after split_date, for a target and a control.",
            cannot_show="Whether an event caused the change, unless the control stays flat.",
            arguments="split_date (first day of the after period), days_before 1-28, days_after 1-28, "
            "target (a claim scope), control_mode rest_of_store or scope, control",
            metrics="rate_before and rate_after for the groups target and control",
            notes=(
                "rest_of_store compares the target against every other delivered order of the store, "
                "using the target's review_label filter. It splits orders, not claims, so the target needs "
                "an order-level field (item_id, modifiers, daypart, weekday, item_count_min or "
                "item_count_max); a target with only error_category or review_label covers every order "
                "and leaves no control.",
                "Enough data means the target's after period and both control periods each have at "
                "least " + MIN_GROUP_ORDERS_TEXT + " eligible orders.",
                "An empty target before period returns rate_before null with a note. A modifier "
                "first sold on date D has no orders before D, so challenge it against the "
                "rest-of-store control, or split later to test whether the rise persists.",
                "The before and after spans must both lie inside the investigation window.",
            ),
            examples=(
                '{"tool": "compare_periods", "split_date": "<date>", "days_before": 14, "days_after": 14, '
                '"target": {"modifiers": ["<menu modifier>"]}, "control_mode": "rest_of_store"}',
                '{"tool": "compare_periods", "split_date": "<date>", "days_before": 7, "days_after": 7, '
                '"target": {"daypart": ["<daypart>"]}, "control_mode": "scope", "control": {"daypart": ["<another daypart>"]}}',
            ),
        ),
        ToolSpec(
            name="sample_evidence",
            measures="Up to 10 claim or cancellation records for a filter, newest first, with "
            "customer_comments.",
            cannot_show="Frequency. Samples illustrate and don't measure.",
            arguments="evidence_type claim with a claim filter, or cancellation with a cancellation "
            "filter; limit 1-10",
            metrics="None. The records come back as evidence.",
            notes=("Use it to cite records from a group outside the first 20 IDs shown.",),
            examples=(
                '{"tool": "sample_evidence", "evidence_type": "claim", "filter": {"start": "<start>", "end": "<end>", '
                '"modifiers": ["<menu modifier>"]}, "limit": 5}',
                '{"tool": "sample_evidence", "evidence_type": "cancellation", "filter": {"start": "<start>", '
                '"end": "<end>", "cancellation_category": ["<cancellation_category>"]}, "limit": 5}',
            ),
        ),
        ToolSpec(
            name="cancellation_breakdown",
            measures="Cancellations grouped by cancellation_category, item_id, daypart, weekday or "
            "day, with each group's cancellation rate over placed orders.",
            cannot_show="M&I claims. Canceled orders never have claims.",
            arguments="filter (a cancellation filter), group_by",
            metrics="cancellation_rate and cancellation_count per group <group_by>=<value>",
            notes=(
                "cancellation_rate is cancellations over placed orders, delivered and canceled. A group's "
                "rate is null when it has fewer than " + MIN_GROUP_ORDERS_TEXT + " placed orders.",
                "A cancellation's item_id is set only when an item was out of stock. An item_id filter or "
                "grouping matches that field; item_id=unknown is rated over all placed orders.",
            ),
            examples=(
                '{"tool": "cancellation_breakdown", "filter": {"start": "<start>", "end": "<end>", '
                '"daypart": ["<daypart>"]}, "group_by": "<group_by>"}',
            ),
        ),
        ToolSpec(
            name="fraud_signals",
            measures="customer_ref values with at least FRAUD_MIN_PENDING_CLAIMS (4 by default) "
            "pending claims in the window.",
            cannot_show="Whether a claim is fraudulent. It flags and never judges.",
            arguments="start, end",
            metrics="claim_count per customer_ref=<ref>, flagged refs only",
            notes=(
                "Already run for the whole window at the start.",
                "An empty result means no ref reached that bar, not that no claim is fraudulent.",
            ),
            returns="counts (claim_count per flagged customer_ref), not rates; it still counts as a tool that "
            "returns rates for G3, G4 and K2",
            examples=('{"tool": "fraud_signals", "start": "<start>", "end": "<end>"}',),
        ),
    )
}


# --- Wire to contract ------------------------------------------------------------------------


def _date(value: str) -> str:
    """A date as YYYY-MM-DD.

    Domain parses an all-digit string such as "20261030" as Unix time and rejects it, so any value Python
    reads as a date is rewritten in ISO form. Anything else is kept for G10 to reject.
    """
    text = value.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return text


def _uniq(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for v in values:
        v = v.strip() if isinstance(v, str) else v
        if v not in out:
            out.append(v)
    return out


def _ordered(values: list[str], order: tuple[str, ...]) -> list[str]:
    vals = _uniq(values)
    return sorted(vals, key=lambda v: (order.index(v) if v in order else len(order), v))


def _claim_scope(src: w.ClaimScopeWire | w.ClaimFilterWire) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if src.item_id:
        out["item_id"] = sorted(_uniq(src.item_id))
    if src.modifiers:
        out["modifiers"] = sorted(_uniq(src.modifiers))
    if src.daypart:
        out["daypart"] = _ordered(list(src.daypart), DAYPARTS)
    if src.weekday:
        out["weekday"] = sorted(_uniq(src.weekday))
    if src.item_count_min != 0:
        out["item_count_min"] = src.item_count_min
    if src.item_count_max != 0:
        out["item_count_max"] = src.item_count_max
    if src.error_category:
        out["error_category"] = _ordered(list(src.error_category), ERROR_CATEGORIES)
    labels = _ordered(list(src.review_label), REVIEW_LABELS)
    if labels and set(labels) != set(DEFAULT_REVIEW_LABELS):
        out["review_label"] = labels
    return out


def _claim_filter(src: w.ClaimFilterWire) -> dict[str, Any]:
    return {"start": _date(src.start), "end": _date(src.end), **_claim_scope(src)}


def _cancellation_filter(src: w.CancellationFilterWire) -> dict[str, Any]:
    out: dict[str, Any] = {"start": _date(src.start), "end": _date(src.end)}
    if src.item_id:
        out["item_id"] = sorted(_uniq(src.item_id))
    if src.daypart:
        out["daypart"] = _ordered(list(src.daypart), DAYPARTS)
    if src.weekday:
        out["weekday"] = sorted(_uniq(src.weekday))
    if src.cancellation_category:
        out["cancellation_category"] = _ordered(list(src.cancellation_category), CANCELLATION_CATEGORIES)
    return out


def to_contract_request(req: w.ToolRequestWire) -> tuple[str, dict[str, Any]]:
    """Convert one wire request into (tool, contract request)."""
    if isinstance(req, (w.StoreOverviewRequestWire, w.FraudSignalsRequestWire)):
        return req.tool, {"start": _date(req.start), "end": _date(req.end)}
    if isinstance(req, w.EventLogRequestWire):
        return req.tool, {
            "start": _date(req.start),
            "end": _date(req.end),
            "event_type": _ordered(list(req.event_type), EVENT_TYPES),
        }
    if isinstance(req, w.ClaimBreakdownRequestWire):
        return req.tool, {"filter": _claim_filter(req.filter), "group_by": req.group_by}
    if isinstance(req, w.ComparePeriodsRequestWire):
        control = _claim_scope(req.control) if req.control_mode == "scope" else None
        return req.tool, {
            "split_date": _date(req.split_date),
            "days_before": req.days_before,
            "days_after": req.days_after,
            "target": _claim_scope(req.target),
            "control": control,
        }
    if isinstance(req, w.ClaimSampleRequestWire):
        return req.tool, {"evidence_type": "claim", "filter": _claim_filter(req.filter), "limit": req.limit}
    if isinstance(req, w.CancellationSampleRequestWire):
        return req.tool, {
            "evidence_type": "cancellation",
            "filter": _cancellation_filter(req.filter),
            "limit": req.limit,
        }
    if isinstance(req, w.CancellationBreakdownRequestWire):
        return req.tool, {"filter": _cancellation_filter(req.filter), "group_by": req.group_by}
    raise TypeError(f"unknown request type {type(req).__name__}")


# --- Keys and signatures ---------------------------------------------------------------------


def canonical_key(tool: str, request: dict[str, Any]) -> str:
    """The tool plus its normalized arguments. Equal keys mean the same Domain query."""
    return tool + ":" + json.dumps(request, sort_keys=True, separators=(",", ":"))


def scopes(tool: str, request: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every filter or scope in a request, with its role: filter, target or control."""
    if tool == "compare_periods":
        out = [("target", request.get("target") or {})]
        if request.get("control") is not None:
            out.append(("control", request["control"]))
        return out
    if "filter" in request:
        return [("filter", request["filter"])]
    return []


DATE_KEYS = frozenset({"start", "end"})


def signature(tool: str, request: dict[str, Any]) -> str:
    """Tool, group_by and filter keys, ignoring values and dates. The conclude gate's K2 uses it."""
    parts = []
    for role, scope in scopes(tool, request):
        keys = sorted(k for k in scope if k not in DATE_KEYS)
        parts.append(role + "(" + ",".join(keys) + ")")
    if tool == "compare_periods" and request.get("control") is None:
        parts.append("control(rest_of_store)")
    return "|".join([tool, str(request.get("group_by", "")), *parts])


def describe_request(tool: str, request: dict[str, Any]) -> str:
    """One line for the check history: the tool and its canonical arguments."""
    return tool + " " + json.dumps(request, sort_keys=True, separators=(",", ":"))


# --- Domain calls ----------------------------------------------------------------------------


async def call_tool(domain: DomainPort, store_id: str, tool: str, request: dict[str, Any]) -> ToolResult:
    if tool == "store_overview":
        return await domain.store_overview(store_id, request["start"], request["end"])
    if tool == "fraud_signals":
        return await domain.fraud_signals(store_id, request["start"], request["end"])
    if tool == "event_log":
        return await domain.event_log(store_id, request["start"], request["end"], request["event_type"])
    if tool == "claim_breakdown":
        return await domain.claim_breakdown(store_id, request)
    if tool == "compare_periods":
        return await domain.compare_periods(store_id, request)
    if tool == "sample_evidence":
        return await domain.evidence_sample(store_id, request)
    if tool == "cancellation_breakdown":
        return await domain.cancellation_breakdown(store_id, request)
    raise ValueError(f"{tool} is not a model tool")


# --- Prompt text -----------------------------------------------------------------------------


def render_tool_catalog() -> str:
    lines = [
        "Every tool is read-only and scoped to the case's store. Rates follow these rules: eligible "
        "orders are delivered orders; store-attributable claims have review_label store_fault or "
        "pending; fraud and not_store_fault claims are excluded. A group's rate is null when it has "
        "fewer than " + MIN_GROUP_ORDERS_TEXT + " eligible orders. data_sufficient describes the "
        "whole result. Every result reports pending_claims.",
        "",
        "Claim filter fields: start, end, item_id, modifiers, daypart, weekday, item_count_min, "
        "item_count_max, error_category, review_label. A claim scope is the same without start and "
        "end. Cancellation filter fields: start, end, item_id, daypart, weekday, "
        "cancellation_category.",
        f"Field values: daypart {', '.join(DAYPARTS)}; weekday 0 (Monday) to 6 (Sunday); error_category "
        f"{', '.join(ERROR_CATEGORIES)}; review_label {', '.join(REVIEW_LABELS)}; cancellation_category "
        f"{', '.join(CANCELLATION_CATEGORIES)}.",
        "",
        "Each tool lists its request as the JSON you write, as a string, in plan.request. Replace the <...> "
        "placeholders with real values. Inside a filter or scope, leave out any field you don't constrain.",
        "",
    ]
    for spec in TOOLS.values():
        lines.append(f"### {spec.name}")
        lines.append(f"- Measures: {spec.measures}")
        lines.append(f"- Can't show: {spec.cannot_show}")
        lines.append(f"- Arguments: {spec.arguments}")
        lines.append(f"- Metrics: {spec.metrics}")
        returns = spec.returns or ("yes" if spec.returns_rates else "no, only records")
        lines.append(f"- Returns rates: {returns}")
        lines.extend(f"- {note}" for note in spec.notes)
        lines.extend(f"- Request: {example}" for example in spec.examples)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
