"""The structured-output schema for one `reason` turn.

Rules from the structured-outputs docs shape it:
- Every field is required and non-nullable. "Nothing" is "" for text, [] for lists, 0 for numbers.
- Exactly two unions: `next_action` (3 variants) and `CheckPlanWire.request` (8 variants).
- No numeric or length constraints. The guard checks bounds.
- Single-value tags (`type`, `tool`, `evidence_type`) are sent as one-value enums. The SDK's
  `transform_schema` drops `const`, which would leave the tags unconstrained.
- Enum values are lowercased before validation.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from typing import Annotated, Any, Literal, Union

import anthropic
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from agent.app.contracts.enums import (
    CancellationCategory,
    CancellationGroupBy,
    CauseCategory,
    CheckKind,
    ClaimGroupBy,
    Confidence,
    Daypart,
    ErrorCategory,
    EventType,
    HypothesisStatus,
    MatchOutcome,
    ReviewLabel,
)


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


LDaypart = Annotated[Daypart, BeforeValidator(_lower)]
LErrorCategory = Annotated[ErrorCategory, BeforeValidator(_lower)]
LReviewLabel = Annotated[ReviewLabel, BeforeValidator(_lower)]
LCancellationCategory = Annotated[CancellationCategory, BeforeValidator(_lower)]
LEventType = Annotated[EventType, BeforeValidator(_lower)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


DATE = "Store-local date, YYYY-MM-DD, inside the investigation window"
HYP_REF = "An existing HYP- id, or a ref from new_hypotheses in this output"


class MatchedEntry(WireModel):
    hypothesis_id: str = Field(description="A hypothesis in the latest check's expectations")
    outcome: Annotated[MatchOutcome, BeforeValidator(_lower)]


class HypothesisUpdateWire(WireModel):
    hypothesis_id: str = Field(description="An existing HYP- id")
    status: Annotated[HypothesisStatus, BeforeValidator(_lower)]
    statement: str = Field(description='A narrower statement, or "" to keep the current one')
    add_supporting: list[str] = Field(description="Retrieved evidence IDs that support it")
    add_contradicting: list[str] = Field(description="Retrieved evidence IDs that contradict it")
    rationale: str = Field(description="One sentence. Required for ruled_out and inconclusive.")


class NewHypothesisWire(WireModel):
    ref: str = Field(description='A short ref such as "N1"')
    cause_category: Annotated[CauseCategory, BeforeValidator(_lower)]
    statement: str = Field(description="Specific and testable. Required detail when cause is other.")
    rationale: str = Field(description="One sentence")
    evidence: list[str] = Field(description="Retrieved evidence IDs that support it, or []")


class ExpectationWire(WireModel):
    hypothesis_id: str = Field(description=HYP_REF)
    if_true: str = Field(description="The result this hypothesis predicts")
    if_false: str = Field(description="The result that would count against it")


ITEM_IDS = "Menu item IDs; [] for any"
MODIFIERS = "Menu modifier names such as Extra sauce; [] for any"
WEEKDAYS = "0 = Monday, store-local; [] for any"
ITEM_MIN = "Minimum orders.item_count; 0 for none"
ITEM_MAX = "Maximum orders.item_count; 0 for none"
LABELS = '[] means the default ["store_fault", "pending"]'


class ClaimScopeWire(WireModel):
    item_id: list[str] = Field(description=ITEM_IDS)
    modifiers: list[str] = Field(description=MODIFIERS)
    daypart: list[LDaypart]
    weekday: list[int] = Field(description=WEEKDAYS)
    item_count_min: int = Field(description=ITEM_MIN)
    item_count_max: int = Field(description=ITEM_MAX)
    error_category: list[LErrorCategory]
    review_label: list[LReviewLabel] = Field(description=LABELS)


class ClaimFilterWire(WireModel):
    start: str = Field(description=DATE)
    end: str = Field(description=DATE + ", inclusive")
    item_id: list[str] = Field(description=ITEM_IDS)
    modifiers: list[str] = Field(description=MODIFIERS)
    daypart: list[LDaypart]
    weekday: list[int] = Field(description=WEEKDAYS)
    item_count_min: int = Field(description=ITEM_MIN)
    item_count_max: int = Field(description=ITEM_MAX)
    error_category: list[LErrorCategory]
    review_label: list[LReviewLabel] = Field(description=LABELS)


class CancellationFilterWire(WireModel):
    start: str = Field(description=DATE)
    end: str = Field(description=DATE + ", inclusive")
    item_id: list[str]
    daypart: list[LDaypart]
    weekday: list[int] = Field(description="0 = Monday, store-local; [] for any")
    cancellation_category: list[LCancellationCategory]


class StoreOverviewRequestWire(WireModel):
    tool: Annotated[Literal["store_overview"], BeforeValidator(_lower)]
    start: str = Field(description=DATE)
    end: str = Field(description=DATE)


class EventLogRequestWire(WireModel):
    tool: Annotated[Literal["event_log"], BeforeValidator(_lower)]
    start: str = Field(description=DATE)
    end: str = Field(description=DATE)
    event_type: list[LEventType] = Field(description="[] for all types")


class ClaimBreakdownRequestWire(WireModel):
    tool: Annotated[Literal["claim_breakdown"], BeforeValidator(_lower)]
    filter: ClaimFilterWire
    group_by: Annotated[ClaimGroupBy, BeforeValidator(_lower)]


class ComparePeriodsRequestWire(WireModel):
    tool: Annotated[Literal["compare_periods"], BeforeValidator(_lower)]
    split_date: str = Field(description="First day of the after period. " + DATE)
    days_before: int = Field(description="1 to 28")
    days_after: int = Field(description="1 to 28")
    target: ClaimScopeWire
    control_mode: Annotated[Literal["rest_of_store", "scope"], BeforeValidator(_lower)] = Field(
        description="rest_of_store: every order outside the target. scope: the control below."
    )
    control: ClaimScopeWire = Field(description="Used only when control_mode is scope; else all empty")


class ClaimSampleRequestWire(WireModel):
    tool: Annotated[Literal["sample_evidence"], BeforeValidator(_lower)]
    evidence_type: Annotated[Literal["claim"], BeforeValidator(_lower)]
    filter: ClaimFilterWire
    limit: int = Field(description="1 to 10")


class CancellationSampleRequestWire(WireModel):
    tool: Annotated[Literal["sample_evidence"], BeforeValidator(_lower)]
    evidence_type: Annotated[Literal["cancellation"], BeforeValidator(_lower)]
    filter: CancellationFilterWire
    limit: int = Field(description="1 to 10")


class CancellationBreakdownRequestWire(WireModel):
    tool: Annotated[Literal["cancellation_breakdown"], BeforeValidator(_lower)]
    filter: CancellationFilterWire
    group_by: Annotated[CancellationGroupBy, BeforeValidator(_lower)]


class FraudSignalsRequestWire(WireModel):
    tool: Annotated[Literal["fraud_signals"], BeforeValidator(_lower)]
    start: str = Field(description=DATE)
    end: str = Field(description=DATE)


ToolRequestWire = Union[
    StoreOverviewRequestWire,
    EventLogRequestWire,
    ClaimBreakdownRequestWire,
    ComparePeriodsRequestWire,
    ClaimSampleRequestWire,
    CancellationSampleRequestWire,
    CancellationBreakdownRequestWire,
    FraudSignalsRequestWire,
]


class CheckPlanWire(WireModel):
    kind: Annotated[CheckKind, BeforeValidator(_lower)]
    purpose: str = Field(description="One sentence, shown to the analyst")
    discriminates: list[str] = Field(description="Hypotheses this check separates. " + HYP_REF)
    expectations: list[ExpectationWire] = Field(description="One per hypothesis in discriminates")
    challenges: str = Field(description='For a challenge: the hypothesis it targets. Otherwise ""')
    request: ToolRequestWire


class CheckAction(WireModel):
    type: Annotated[Literal["check"], BeforeValidator(_lower)]
    plan: CheckPlanWire


class AskMerchantAction(WireModel):
    type: Annotated[Literal["ask_merchant"], BeforeValidator(_lower)]
    question_text: str
    why_asked: str = Field(description="Which hypotheses the answer separates")


class TargetWire(WireModel):
    item_id: list[str]
    modifiers: list[str]
    daypart: list[LDaypart]
    item_count_min: int = Field(description="0 for none")


class RecommendationWire(WireModel):
    action_id: str = Field(description="An action_id from the catalog that applies to the cause")
    rationale: str = Field(description="One or two sentences")
    target: TargetWire


class ConcludeAction(WireModel):
    type: Annotated[Literal["conclude"], BeforeValidator(_lower)]
    leading_hypothesis_id: str = Field(description=HYP_REF)
    rise_started_at: str = Field(description="The date the rise began. " + DATE)
    confidence: Annotated[Confidence, BeforeValidator(_lower)]
    summary: str = Field(description="At most four sentences, citing numbers from the results")
    recommendation: RecommendationWire


NextActionWire = Union[CheckAction, AskMerchantAction, ConcludeAction]


class ReasonOutputWire(WireModel):
    assessment: str = Field(description="One to three sentences on what the latest result shows")
    matched: list[MatchedEntry] = Field(
        description="One entry per hypothesis in the latest check's expectations, else []"
    )
    hypothesis_updates: list[HypothesisUpdateWire]
    new_hypotheses: list[NewHypothesisWire]
    next_action: NextActionWire


# --- Schema sent to the API --------------------------------------------------------------------


def _tags_to_enums(node: Any) -> Any:
    """Turn `const` into one-value `enum`s and drop `title`s, recursively."""
    if isinstance(node, list):
        return [_tags_to_enums(v) for v in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title":
            continue
        if key == "const":
            out["enum"] = [value]
        elif key in ("properties", "$defs"):
            out[key] = {name: _tags_to_enums(sub) for name, sub in value.items()}
        else:
            out[key] = _tags_to_enums(value)
    return out


@lru_cache
def reason_output_schema() -> dict[str, Any]:
    raw = ReasonOutputWire.model_json_schema()
    return anthropic.transform_schema(_tags_to_enums(raw))


def schema_json() -> str:
    return json.dumps(reason_output_schema(), sort_keys=True, separators=(",", ":"))


def schema_hash() -> str:
    return hashlib.sha256(schema_json().encode()).hexdigest()[:16]


def output_config_format() -> dict[str, Any]:
    return {"type": "json_schema", "schema": copy.deepcopy(reason_output_schema())}


def parse_reason_output(raw: Any) -> ReasonOutputWire:
    """Validate a parsed JSON object. Raises pydantic.ValidationError."""
    return ReasonOutputWire.model_validate(raw)
