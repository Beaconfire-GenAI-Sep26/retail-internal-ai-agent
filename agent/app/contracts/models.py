"""DTOs from contracts.md.

Models for data the agent reads from Domain are tolerant: unknown fields are ignored, the
contract's "addition" fields are optional, and `baseline_rate` is nullable. Models for data the
agent sends or serves follow the contract exactly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.enums import (
    CauseCategory,
    CheckKind,
    Confidence,
    HypothesisStatus,
    InvestigationStatus,
    MatchOutcome,
    OwnerTeam,
    ProposalKind,
)


class Tolerant(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Stores, cases and evidence -------------------------------------------------------------


class StoreSummary(Tolerant):
    store_id: str
    name: str = ""
    city: str = ""
    timezone: str
    cuisine: str = ""


class MenuItem(Tolerant):
    item_id: str
    store_id: str
    name: str
    category: str = ""
    price: float | None = None
    available_modifiers: list[str] = Field(default_factory=list)


class DailyRate(Tolerant):
    date: str
    rate: float | None = None
    claims: int = 0
    eligible_orders: int = 0


class Proposal(Tolerant):
    proposal_id: str
    case_id: str
    investigation_id: str | None = None
    kind: str
    version: int = 1
    status: str
    content: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    decision_note: str | None = None
    dispatch: dict[str, Any] | None = None


class CaseSummary(Tolerant):
    case_id: str
    store_id: str
    store_name: str = ""
    status: str
    trigger_rule: str = ""
    window_start: str
    window_end: str
    mi_rate: float | None = None
    baseline_rate: float | None = None
    eligible_orders: int | None = None
    attributable_claims: int | None = None  # addition
    goal_rate: float | None = None  # addition
    opened_at: str | None = None
    updated_at: str | None = None
    active_investigation_id: str | None = None  # addition
    reopen_count: int = 0  # addition
    last_error: str | None = None  # addition


class CaseDetail(CaseSummary):
    store: StoreSummary
    daily_rates: list[DailyRate] = Field(default_factory=list)
    investigation_ids: list[str] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    rechecks: list[dict[str, Any]] = Field(default_factory=list)


class Evidence(Tolerant):
    evidence_id: str
    type: str
    store_id: str = ""
    occurred_at: str | None = None
    summary: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvidenceResolveResponse(Tolerant):
    valid: list[str] = Field(default_factory=list)
    invalid: list[dict[str, Any]] = Field(default_factory=list)


# --- Diagnostics -----------------------------------------------------------------------------


class ClaimFilter(Strict):
    start: str
    end: str
    item_id: list[str] | None = None
    modifiers: list[str] | None = None
    daypart: list[str] | None = None
    weekday: list[int] | None = None
    item_count_min: int | None = None
    item_count_max: int | None = None
    error_category: list[str] | None = None
    review_label: list[str] | None = None


class CancellationFilter(Strict):
    start: str
    end: str
    item_id: list[str] | None = None
    daypart: list[str] | None = None
    weekday: list[int] | None = None
    cancellation_category: list[str] | None = None


class Window(Tolerant):
    start: str
    end: str


class Metric(Tolerant):
    name: str
    group: str | None = None
    value: float | None = None
    numerator: float | None = None
    denominator: float | None = None
    unit: str = "rate"


class ToolResult(Tolerant):
    tool: str
    store_id: str
    window: Window
    eligible_orders: int = 0
    pending_claims: int = 0
    data_sufficient: bool = False
    headline: str = ""
    metrics: list[Metric] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ActionCatalogEntry(Tolerant):
    action_id: str
    kind: Literal["intervention", "handoff"]
    owner_team: str
    title: str
    applies_to: list[str] = Field(default_factory=list)
    default_recheck_days: int = 14


# --- Investigations, UI-facing ---------------------------------------------------------------


class StartInvestigationRequest(Strict):
    case_id: str
    reopen_of: str | None = None


class Expectation(BaseModel):
    hypothesis_id: str
    if_true: str
    if_false: str


class Hypothesis(BaseModel):
    hypothesis_id: str
    cause_category: CauseCategory
    statement: str
    status: HypothesisStatus
    rationale: str
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    check_ids: list[str]


class CheckSummary(BaseModel):
    check_id: str
    kind: CheckKind
    tool: str
    purpose: str
    discriminates: list[str]
    expectations: list[Expectation]
    challenges: str | None
    matched: dict[str, MatchOutcome]
    headline: str
    data_sufficient: bool
    evidence_ids: list[str]
    at: str


class Target(BaseModel):
    item_id: list[str]
    modifiers: list[str]
    daypart: list[str]
    item_count_min: int | None


class Recommendation(BaseModel):
    kind: Literal["intervention", "handoff"]
    action_id: str
    owner_team: OwnerTeam
    rationale: str
    target: Target
    recheck_after_days: int


class RuledOut(BaseModel):
    cause_category: CauseCategory
    reason: str
    evidence_ids: list[str]
    check_ids: list[str]


class InvestigationResult(BaseModel):
    outcome: Literal["diagnosis", "unsure"]
    cause_category: CauseCategory | None
    cause_started_at: str | None
    confidence: Confidence
    summary: str
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    ruled_out: list[RuledOut]
    evidence_gaps: list[str]
    checks_tried: list[str]
    challenge_check_ids: list[str]
    unverified_reply_claims: list[str]
    recommendation: Recommendation | None
    proposal_id: str | None


class ErrorInfo(BaseModel):
    code: str
    message: str


class InvestigationView(BaseModel):
    investigation_id: str
    case_id: str
    store_id: str
    status: InvestigationStatus
    started_by: str
    started_at: str
    updated_at: str
    step_count: int
    max_steps: int
    reopen_of: str | None
    hypotheses: list[Hypothesis]
    checks: list[CheckSummary]
    pending_proposal_id: str | None
    result: InvestigationResult | None
    error: ErrorInfo | None


# --- Proposals and status --------------------------------------------------------------------


class ActionContent(BaseModel):
    action_id: str
    owner_team: str
    title: str
    instructions: str
    rationale: str
    target: Target
    recheck_after_days: int


class MerchantQuestionContent(BaseModel):
    question_text: str
    why_asked: str


class ProposalCreate(BaseModel):
    investigation_id: str
    kind: ProposalKind
    content: ActionContent | MerchantQuestionContent
    evidence_ids: list[str]


class InvestigationStatusUpdate(BaseModel):
    investigation_id: str
    status: InvestigationStatus
    error_code: str | None
