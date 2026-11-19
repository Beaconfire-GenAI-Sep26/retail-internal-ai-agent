"""Enums from contracts.md, with C-01 names and values exactly as C-01 defines them."""

from __future__ import annotations

from typing import Literal, get_args

ErrorCategory = Literal["missing_item", "incorrect_item", "ingredient_error", "wrong_order"]
ReviewLabel = Literal["store_fault", "not_store_fault", "fraud", "pending"]
CancellationCategory = Literal[
    "item_out_of_stock", "too_busy", "menu_data_mismatch", "pos_technical_error", "other"
]
Daypart = Literal["breakfast", "lunch", "dinner", "late_night"]
EventType = Literal["menu_change", "pos_change", "store_downtime", "promotion"]
CaseStatus = Literal[
    "open",
    "investigating",
    "awaiting_decision",
    "awaiting_merchant",
    "action_dispatched",
    "closed",
    "paused",
    "reopened",
    "analyst_review",
]
CauseCategory = Literal[
    "pos_modifier_mapping",
    "menu_change",
    "packing",
    "inventory",
    "dasher_handoff",
    "fraud_cluster",
    "other",
]
Role = Literal["viewer", "loe_analyst"]
InvestigationStatus = Literal[
    "running", "awaiting_approval", "awaiting_merchant", "completed", "unsure", "failed"
]
EvidenceType = Literal["claim", "cancellation", "operational_event", "merchant_reply"]
ItemCountBucket = Literal["1-2", "3-4", "5+"]
ProposalKind = Literal["merchant_question", "intervention", "handoff"]
ProposalStatus = Literal["pending", "approved", "rejected"]
HypothesisStatus = Literal["open", "supported", "ruled_out", "inconclusive"]
Confidence = Literal["low", "medium", "high"]
CheckKind = Literal["explore", "test", "challenge"]
OwnerTeam = Literal["merchant", "pos_team", "menu_team", "dasher_ops", "fraud_review", "analyst"]
ToolName = Literal[
    "store_overview",
    "event_log",
    "claim_breakdown",
    "compare_periods",
    "sample_evidence",
    "cancellation_breakdown",
    "fraud_signals",
    "merchant_replies",
    "action_catalog",
]
ClaimGroupBy = Literal[
    "item_id", "modifier", "daypart", "weekday", "item_count", "error_category", "review_label", "day"
]
CancellationGroupBy = Literal["cancellation_category", "item_id", "daypart", "weekday", "day"]
MatchOutcome = Literal["if_true", "if_false", "neither"]

ERROR_CATEGORIES: tuple[str, ...] = get_args(ErrorCategory)
REVIEW_LABELS: tuple[str, ...] = get_args(ReviewLabel)
CANCELLATION_CATEGORIES: tuple[str, ...] = get_args(CancellationCategory)
DAYPARTS: tuple[str, ...] = get_args(Daypart)
EVENT_TYPES: tuple[str, ...] = get_args(EventType)
CAUSE_CATEGORIES: tuple[str, ...] = get_args(CauseCategory)
INVESTIGATION_STATUSES: tuple[str, ...] = get_args(InvestigationStatus)
HYPOTHESIS_STATUSES: tuple[str, ...] = get_args(HypothesisStatus)
CONFIDENCE_LEVELS: tuple[str, ...] = get_args(Confidence)

DEFAULT_REVIEW_LABELS: tuple[str, ...] = ("store_fault", "pending")
ACTIVE_STATUSES: frozenset[str] = frozenset({"running", "awaiting_approval", "awaiting_merchant"})
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "unsure", "failed"})
