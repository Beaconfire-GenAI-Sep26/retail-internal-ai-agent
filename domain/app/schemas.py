"""Request and response models, named and shaped as in contracts.md (B-01)."""
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CancellationCategory, CaseStatus, Daypart, ErrorCategory, ReviewLabel

Weekday = Annotated[int, Field(ge=0, le=6, description="0 = Monday, store local time")]
IdList = Annotated[list[str], Field(max_length=200)]


class Strict(BaseModel):
    """Unknown fields are rejected with 422, so a typo in a filter never passes silently."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Diagnostic requests
# ---------------------------------------------------------------------------
class ClaimScope(Strict):
    item_id: IdList | None = None
    modifiers: IdList | None = Field(default=None, description='Menu names, e.g. ["Extra sauce"]')
    daypart: list[Daypart] | None = None
    weekday: list[Weekday] | None = None
    item_count_min: int | None = Field(default=None, ge=1)
    item_count_max: int | None = Field(default=None, ge=1)
    error_category: list[ErrorCategory] | None = None
    review_label: list[ReviewLabel] | None = Field(
        default=None, description='Default ["store_fault", "pending"]'
    )


class ClaimFilter(ClaimScope):
    start: date
    end: date = Field(description="Inclusive")

    @model_validator(mode="after")
    def check_dates(self):
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self


class CancellationFilter(Strict):
    start: date
    end: date = Field(description="Inclusive")
    item_id: IdList | None = None
    daypart: list[Daypart] | None = None
    weekday: list[Weekday] | None = None
    cancellation_category: list[CancellationCategory] | None = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self


ClaimGroupBy = Literal[
    "item_id", "modifier", "daypart", "weekday", "item_count", "error_category", "review_label", "day"
]
CancellationGroupBy = Literal["cancellation_category", "item_id", "daypart", "weekday", "day"]


class ClaimBreakdownRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"filter": {"start": "2026-10-05", "end": "2026-11-15"}, "group_by": "modifier"}]})

    filter: ClaimFilter
    group_by: ClaimGroupBy


class ComparePeriodsRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"split_date": "2026-10-30", "days_before": 14, "days_after": 14, "target": {"modifiers": ["Extra sauce"]}, "control": None}]})

    split_date: date = Field(description='First day of the "after" period')
    days_before: int = Field(ge=1, le=28)
    days_after: int = Field(ge=1, le=28)
    target: ClaimScope
    control: ClaimScope | None = Field(
        default=None, description="null: the same store, every order outside the target"
    )


class EvidenceSampleRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"evidence_type": "claim", "filter": {"start": "2026-11-01", "end": "2026-11-15", "modifiers": ["Extra sauce"]}, "limit": 3}]})

    evidence_type: Literal["claim", "cancellation"]
    filter: ClaimFilter | CancellationFilter
    limit: int = Field(ge=1, le=10)

    @model_validator(mode="before")
    @classmethod
    def parse_filter_by_type(cls, data: Any):
        # Pick the filter model from evidence_type, so a claim-only field on a
        # cancellation sample (or the reverse) is a 422, not silently ignored.
        if isinstance(data, dict) and isinstance(data.get("filter"), dict):
            model = CancellationFilter if data.get("evidence_type") == "cancellation" else ClaimFilter
            data = {**data, "filter": model.model_validate(data["filter"])}
        return data


class CancellationBreakdownRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"filter": {"start": "2026-10-05", "end": "2026-11-15"}, "group_by": "cancellation_category"}]})

    filter: CancellationFilter
    group_by: CancellationGroupBy


class MonitorRunRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"as_of": "2026-11-15"}]})

    as_of: date | None = Field(
        default=None, description="Last day of the 7-day window. Default: the last day of data."
    )


class EvidenceResolveRequest(Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"store_id": "STORE-A", "evidence_ids": ["EV-CLM-000001", "EV-CLM-999999"]}]})

    store_id: str
    evidence_ids: IdList


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
class Metric(BaseModel):
    name: str
    group: str | None
    value: float | None
    numerator: int | None
    denominator: int | None
    unit: Literal["rate", "share", "count"]


class Evidence(BaseModel):
    evidence_id: str
    type: Literal["claim", "cancellation", "operational_event", "merchant_reply"]
    store_id: str
    occurred_at: datetime
    summary: str
    attributes: dict[str, Any]


class Window(BaseModel):
    start: date
    end: date


class ToolResult(BaseModel):
    tool: str
    store_id: str
    window: Window
    eligible_orders: int
    pending_claims: int
    data_sufficient: bool
    headline: str
    metrics: list[Metric]
    evidence_ids: list[str]
    evidence: list[Evidence]
    notes: list[str]


class StoreSummary(BaseModel):
    store_id: str
    name: str
    city: str
    timezone: str
    cuisine: str


class MenuItemOut(BaseModel):
    item_id: str
    store_id: str
    name: str
    category: str
    price: float
    available_modifiers: list[str]


class CaseSummary(BaseModel):
    case_id: str
    store_id: str
    store_name: str
    status: CaseStatus
    trigger_rule: Literal["over_goal", "spike_vs_baseline"]
    window_start: datetime
    window_end: datetime
    mi_rate: float
    baseline_rate: float | None
    eligible_orders: int
    attributable_claims: int
    goal_rate: float
    opened_at: datetime
    updated_at: datetime
    active_investigation_id: str | None
    reopen_count: int
    last_error: str | None


class DailyRate(BaseModel):
    date: date
    rate: float | None
    claims: int
    eligible_orders: int


class CaseDetail(CaseSummary):
    store: StoreSummary
    daily_rates: list[DailyRate]
    investigation_ids: list[str]
    proposals: list[dict[str, Any]]
    rechecks: list[dict[str, Any]]


class SkippedStore(BaseModel):
    store_id: str
    reason: Literal["open_case_exists", "low_volume", "below_threshold"]


class MonitorRunResponse(BaseModel):
    run_id: str
    as_of: date
    evaluated_store_ids: list[str]
    opened_case_ids: list[str]
    skipped: list[SkippedStore]


class InvalidEvidence(BaseModel):
    evidence_id: str
    reason: Literal["not_found", "other_store"]


class EvidenceResolveResponse(BaseModel):
    valid: list[str]
    invalid: list[InvalidEvidence]
