"""What the LOE playbook works with: the case, Domain's read-only diagnostics, and the two results it can return.

Every diagnostic call is one check and is recorded in `Tools.checks`, so checks per case counts each query the same way
for the playbook and the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from agent.app.contracts.models import MenuItem, ToolResult
from agent.app.domain.client import DomainPort


@dataclass(frozen=True)
class Day:
    date: date
    rate: float | None  # None under 30 delivered orders
    claims: int
    orders: int


@dataclass(frozen=True)
class Case:
    case_id: str
    store_id: str
    trigger_rule: str  # over_goal or spike_vs_baseline
    start: date  # the 7-day window that opened the case: store-local dates, both days included
    end: date
    data_start: date  # the first and last day every tool accepts
    data_end: date
    rate: float  # the 7-day M&I rate
    baseline: float | None  # the rate over the 28 days before it; None under 30 orders
    goal: float
    claims: int  # store-attributable claims and delivered orders in the 7-day window
    orders: int
    daily: tuple[Day, ...]  # one entry per day, data_start to data_end
    menu: tuple[MenuItem, ...]  # item_id, name, category, available_modifiers


@dataclass(frozen=True)
class Reply:
    evidence_id: str
    outcome: str  # replied or no_reply
    text: str | None  # untrusted merchant text


@dataclass(frozen=True)
class Group:
    """One group of a claim_breakdown."""

    name: str  # the value without its prefix, such as dinner
    claims: int
    orders: int | None  # None where the grouping has no order side (error_category, review_label, unknown items)
    rate: float | None  # None under 30 orders
    claim_share: float  # share of the breakdown's claims
    order_share: float | None  # share of the breakdown's orders; None where `orders` has no order side

    @property
    def lift(self) -> float | None:
        """Share of claims over share of orders. Above 1 means more than a fair share."""
        return self.claim_share / self.order_share if self.order_share else None


@dataclass
class Question:
    """One question for the merchant. An analyst approves it before it goes out."""

    text: str
    why: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class RuledOut:
    cause: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Conclusion:
    cause: str | None  # None means unsure
    action_id: str | None  # a catalog action; None only when unsure
    confidence: str  # low, medium or high
    summary: str
    started_on: date | None = None
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    ruled_out: list[RuledOut] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    target: dict[str, Any] = field(default_factory=dict)  # item_id, modifiers, daypart, item_count_min


def groups(result: ToolResult) -> list[Group]:
    """A claim_breakdown's groups, in Domain's order."""
    rows: dict[str, dict[str, Any]] = {}
    for metric in result.metrics:
        if metric.group:
            rows.setdefault(metric.group, {})[metric.name] = metric
    out = []
    for label, found in rows.items():
        rate, claim_share, order_share = (found.get(n) for n in ("claim_rate", "claim_share", "order_share"))
        if claim_share is None:
            continue
        has_orders = order_share is not None and order_share.value is not None
        out.append(Group(
            name=label.split("=", 1)[-1], claims=int(claim_share.numerator or 0),
            orders=int(order_share.numerator or 0) if has_orders else None,
            rate=rate.value if rate else None, claim_share=claim_share.value or 0.0,
            order_share=order_share.value if has_orders else None))
    return out


def counts(result: ToolResult, name: str, prefix: str) -> dict[str, int]:
    """A result's count metrics by group value, such as claim_count by review_label or by customer_ref."""
    return {m.group.split("=", 1)[1]: int(m.value or 0) for m in result.metrics
            if m.name == name and m.group and m.group.startswith(prefix + "=")}


def value(result: ToolResult, name: str, group: str | None) -> float | None:
    """One metric's value, such as compare_periods' rate_after for the group target."""
    return next((m.value for m in result.metrics if m.name == name and m.group == group), None)


class Tools:
    """Domain's seven diagnostics for one case's store. `purpose` is a short note for the check's record."""

    def __init__(self, domain: DomainPort, case: Case, checks: list[dict[str, Any]]):
        self.domain, self.case, self.checks = domain, case, checks

    def _record(self, tool: str, purpose: str, request: dict[str, Any], result: ToolResult) -> ToolResult:
        self.checks.append({"check_id": f"LOE-{len(self.checks) + 1:02d}", "tool": tool, "purpose": purpose,
                            "request": request, "headline": result.headline,
                            "data_sufficient": result.data_sufficient, "evidence_ids": list(result.evidence_ids)})
        return result

    def _span(self, start: date | None, end: date | None) -> dict[str, str]:
        return {"start": (start or self.case.start).isoformat(), "end": (end or self.case.end).isoformat()}

    async def overview(self, purpose: str, start: date | None = None, end: date | None = None) -> ToolResult:
        span = self._span(start, end)
        result = await self.domain.store_overview(self.case.store_id, span["start"], span["end"])
        return self._record("store_overview", purpose, span, result)

    async def events(self, purpose: str, start: date, end: date) -> ToolResult:
        span = self._span(start, end)
        result = await self.domain.event_log(self.case.store_id, span["start"], span["end"], [])
        return self._record("event_log", purpose, span, result)

    async def claims_by(self, purpose: str, group_by: str, start: date | None = None, end: date | None = None,
                        **scope: Any) -> ToolResult:
        request = {"filter": {**self._span(start, end), **scope}, "group_by": group_by}
        result = await self.domain.claim_breakdown(self.case.store_id, request)
        return self._record("claim_breakdown", purpose, request, result)

    async def compare(self, purpose: str, split_date: date, days_before: int, days_after: int,
                      target: dict[str, Any], control: dict[str, Any] | None = None) -> ToolResult:
        request = {"split_date": split_date.isoformat(), "days_before": days_before, "days_after": days_after,
                   "target": target, "control": control}
        result = await self.domain.compare_periods(self.case.store_id, request)
        return self._record("compare_periods", purpose, request, result)

    async def sample_claims(self, purpose: str, start: date | None = None, end: date | None = None, limit: int = 10,
                            **scope: Any) -> ToolResult:
        request = {"evidence_type": "claim", "filter": {**self._span(start, end), **scope}, "limit": limit}
        result = await self.domain.evidence_sample(self.case.store_id, request)
        return self._record("sample_evidence", purpose, request, result)

    async def sample_cancellations(self, purpose: str, start: date | None = None, end: date | None = None,
                                   limit: int = 10, **scope: Any) -> ToolResult:
        request = {"evidence_type": "cancellation", "filter": {**self._span(start, end), **scope}, "limit": limit}
        result = await self.domain.evidence_sample(self.case.store_id, request)
        return self._record("sample_evidence", purpose, request, result)

    async def cancellations_by(self, purpose: str, group_by: str, start: date | None = None, end: date | None = None,
                               **scope: Any) -> ToolResult:
        request = {"filter": {**self._span(start, end), **scope}, "group_by": group_by}
        result = await self.domain.cancellation_breakdown(self.case.store_id, request)
        return self._record("cancellation_breakdown", purpose, request, result)

    async def fraud(self, purpose: str, start: date | None = None, end: date | None = None) -> ToolResult:
        span = self._span(start, end)
        result = await self.domain.fraud_signals(self.case.store_id, span["start"], span["end"])
        return self._record("fraud_signals", purpose, span, result)
