"""The structured-output schema for one `reason` turn.

Rules from the structured-outputs docs shape it:
- Every field is required and non-nullable. "Nothing" is "" for text, [] for lists, 0 for numbers.
- One union: `next_action` (3 variants).
- The tool request is a JSON object written as a string (`CheckPlanWire.request`). The API compiles the
  schema into a grammar, and the 8 per-tool request shapes make that grammar too large to compile, so the
  request is checked here instead: the string is decoded and validated against the request models below,
  picked by `tool` (and `evidence_type` for samples). A bad request is a SCHEMA rejection with the errors.
- No numeric or length constraints. The guard checks bounds.
- Single-value tags (`type`, `evidence_type` in the schema) are sent as one-value enums. The SDK's
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
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    WithJsonSchema,
    field_validator,
)

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


# The request models below are validated in code, not by the API's grammar, so a constraint the model
# leaves out of the request takes its "no constraint" default.


class ClaimScopeWire(WireModel):
    item_id: list[str] = Field(default_factory=list, description=ITEM_IDS)
    modifiers: list[str] = Field(default_factory=list, description=MODIFIERS)
    daypart: list[LDaypart] = Field(default_factory=list)
    weekday: list[int] = Field(default_factory=list, description=WEEKDAYS)
    item_count_min: int = Field(default=0, description=ITEM_MIN)
    item_count_max: int = Field(default=0, description=ITEM_MAX)
    error_category: list[LErrorCategory] = Field(default_factory=list)
    review_label: list[LReviewLabel] = Field(default_factory=list, description=LABELS)


class ClaimFilterWire(ClaimScopeWire):
    start: str = Field(description=DATE)
    end: str = Field(description=DATE + ", inclusive")


class CancellationFilterWire(WireModel):
    start: str = Field(description=DATE)
    end: str = Field(description=DATE + ", inclusive")
    item_id: list[str] = Field(default_factory=list)
    daypart: list[LDaypart] = Field(default_factory=list)
    weekday: list[int] = Field(default_factory=list, description="0 = Monday, store-local; [] for any")
    cancellation_category: list[LCancellationCategory] = Field(default_factory=list)


class StoreOverviewRequestWire(WireModel):
    tool: Annotated[Literal["store_overview"], BeforeValidator(_lower)]
    start: str = Field(description=DATE)
    end: str = Field(description=DATE)


class EventLogRequestWire(WireModel):
    tool: Annotated[Literal["event_log"], BeforeValidator(_lower)]
    start: str = Field(description=DATE)
    end: str = Field(description=DATE)
    event_type: list[LEventType] = Field(default_factory=list, description="[] for all types")


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
        default="rest_of_store", description="rest_of_store: every order outside the target. scope: the control below."
    )
    control: ClaimScopeWire = Field(default_factory=ClaimScopeWire,
                                    description="Used only when control_mode is scope; else all empty")


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


def _request_tag(value: Any) -> str | None:
    """Which request model applies: the tool, plus the evidence_type for samples."""
    if isinstance(value, dict):
        tool = str(value.get("tool", "")).strip().lower()
        kind = str(value.get("evidence_type", "")).strip().lower()
    else:
        tool, kind = getattr(value, "tool", ""), getattr(value, "evidence_type", "")
    if tool == "sample_evidence":
        return f"sample_evidence:{kind}"
    return tool or None


ToolRequestWire = Annotated[
    Union[
        Annotated[StoreOverviewRequestWire, Tag("store_overview")],
        Annotated[EventLogRequestWire, Tag("event_log")],
        Annotated[ClaimBreakdownRequestWire, Tag("claim_breakdown")],
        Annotated[ComparePeriodsRequestWire, Tag("compare_periods")],
        Annotated[ClaimSampleRequestWire, Tag("sample_evidence:claim")],
        Annotated[CancellationSampleRequestWire, Tag("sample_evidence:cancellation")],
        Annotated[CancellationBreakdownRequestWire, Tag("cancellation_breakdown")],
        Annotated[FraudSignalsRequestWire, Tag("fraud_signals")],
    ],
    Discriminator(
        _request_tag,
        custom_error_type="unknown_tool",
        custom_error_message="tool must be one of store_overview, event_log, claim_breakdown, compare_periods, "
        "sample_evidence (with evidence_type claim or cancellation), cancellation_breakdown, fraud_signals",
    ),
]

REQUEST_JSON_SCHEMA = {
    "type": "string",
    "description": "The tool request: one JSON object written as a string, with the field names shown "
    "under Tools, for example "
    '{"tool": "claim_breakdown", "filter": {"start": "<start>", "end": "<end>"}, "group_by": "<group_by>"}',
}


class CheckPlanWire(WireModel):
    kind: Annotated[CheckKind, BeforeValidator(_lower)]
    purpose: str = Field(description="One sentence, shown to the analyst")
    discriminates: list[str] = Field(description="Hypotheses this check separates. " + HYP_REF)
    expectations: list[ExpectationWire] = Field(description="One per hypothesis in discriminates")
    challenges: str = Field(description='For a challenge: the hypothesis it targets. Otherwise ""')
    request: Annotated[ToolRequestWire, WithJsonSchema(REQUEST_JSON_SCHEMA)]

    @field_validator("request", mode="before")
    @classmethod
    def _decode_request(cls, value: Any) -> Any:
        """The model sends the request as a JSON string; scripted turns and tests may pass the object."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise ValueError(f"request is not valid JSON ({exc})") from None
            if not isinstance(value, dict):
                raise ValueError("request must be a JSON object written as a string")
        return value


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
