"""SQLAlchemy models for the Domain service (C-01).

Agent-visible tables live in the `domain` schema.
The answer key for evaluation lives in the `eval` schema and must never be
exposed through Domain APIs or agent tools (C-05 rule).

Conventions
- IDs are readable strings with a type prefix: STORE-A, ITEM-A-007, ORD-000123,
  EV-CLM-000123 (claim), EV-CXL-000045 (cancellation), EV-EVT-000010 (event),
  CASE-0001, GS-01.
- All timestamps are timezone-aware and stored in UTC.
- Enum values are stored as lowercase strings with a CHECK constraint.
"""
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DOMAIN_SCHEMA = "domain"
EVAL_SCHEMA = "eval"


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class OrderStatus(str, enum.Enum):
    DELIVERED = "delivered"
    CANCELED = "canceled"


class Daypart(str, enum.Enum):
    """Meal period by order time in the store's local time (not a staff shift)."""

    BREAKFAST = "breakfast"  # 05:00-10:59
    LUNCH = "lunch"  # 11:00-15:59
    DINNER = "dinner"  # 16:00-20:59
    LATE_NIGHT = "late_night"  # 21:00-04:59


class ErrorCategory(str, enum.Enum):
    MISSING_ITEM = "missing_item"
    INCORRECT_ITEM = "incorrect_item"
    INGREDIENT_ERROR = "ingredient_error"
    WRONG_ORDER = "wrong_order"


class ReviewLabel(str, enum.Enum):
    STORE_FAULT = "store_fault"
    NOT_STORE_FAULT = "not_store_fault"
    FRAUD = "fraud"
    PENDING = "pending"  # review not finished yet


class CancellationCategory(str, enum.Enum):
    ITEM_OUT_OF_STOCK = "item_out_of_stock"
    TOO_BUSY = "too_busy"
    MENU_DATA_MISMATCH = "menu_data_mismatch"
    POS_TECHNICAL_ERROR = "pos_technical_error"
    OTHER = "other"


class EventType(str, enum.Enum):
    MENU_CHANGE = "menu_change"
    POS_CHANGE = "pos_change"
    STORE_DOWNTIME = "store_downtime"
    PROMOTION = "promotion"


class CaseStatus(str, enum.Enum):
    """Business state of a case, set by the Domain Service (B-01 contracts).

    Not the same as the agent's investigation_status: a case exists before any
    investigation starts and can outlive several investigations.
    """

    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_DECISION = "awaiting_decision"
    AWAITING_MERCHANT = "awaiting_merchant"
    ACTION_DISPATCHED = "action_dispatched"
    CLOSED = "closed"
    PAUSED = "paused"
    REOPENED = "reopened"
    ANALYST_REVIEW = "analyst_review"


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Store an enum as VARCHAR + CHECK constraint using its lowercase values."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


TZ = DateTime(timezone=True)
MONEY = Numeric(10, 2)
RATE = Numeric(6, 4)


# ---------------------------------------------------------------------------
# Domain tables (agent-visible through Domain APIs)
# ---------------------------------------------------------------------------
class Store(Base):
    __tablename__ = "stores"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    store_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64))
    cuisine: Mapped[str] = mapped_column(String(40))
    opening_hours: Mapped[dict] = mapped_column(JSON)  # {"open": "11:00", "close": "22:00"}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarded_at: Mapped[datetime] = mapped_column(TZ)

    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="store")


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    item_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))  # entree / side / drink / dessert
    price: Mapped[Decimal] = mapped_column(MONEY)
    available_modifiers: Mapped[list] = mapped_column(JSON, default=list)

    store: Mapped[Store] = relationship(back_populates="menu_items")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    order_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    customer_ref: Mapped[str] = mapped_column(String(20), index=True)  # synthetic, e.g. CUST-004211
    placed_at: Mapped[datetime] = mapped_column(TZ, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "order_status"))
    daypart: Mapped[Daypart] = mapped_column(str_enum(Daypart, "daypart"))
    item_count: Mapped[int] = mapped_column(Integer)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    order_item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.orders.order_id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.menu_items.item_id"))
    quantity: Mapped[int] = mapped_column(Integer)
    modifiers: Mapped[list] = mapped_column(JSON, default=list)

    order: Mapped[Order] = relationship(back_populates="items")


class MIClaim(Base):
    """One missing/incorrect item claim. Fields follow the public
    Menu Item Error merchant report."""

    __tablename__ = "mi_claims"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    evidence_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # EV-CLM-000123
    order_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.orders.order_id"), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.menu_items.item_id"), nullable=True
    )
    item_name: Mapped[str] = mapped_column(String(120))
    error_category: Mapped[ErrorCategory] = mapped_column(str_enum(ErrorCategory, "error_category"))
    modifier_detail: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_charge: Mapped[Decimal] = mapped_column(MONEY)
    reported_at: Mapped[datetime] = mapped_column(TZ, index=True)
    review_label: Mapped[ReviewLabel] = mapped_column(str_enum(ReviewLabel, "review_label"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)  # null while pending


class Cancellation(Base):
    __tablename__ = "cancellations"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    evidence_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # EV-CXL-000045
    order_id: Mapped[str] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.orders.order_id"), unique=True
    )
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.menu_items.item_id"), nullable=True
    )  # the out-of-stock item, when known
    cancellation_category: Mapped[CancellationCategory] = mapped_column(
        str_enum(CancellationCategory, "cancellation_category")
    )
    canceled_at: Mapped[datetime] = mapped_column(TZ, index=True)


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    evidence_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # EV-EVT-000010
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    started_at: Mapped[datetime] = mapped_column(TZ)
    ended_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    description: Mapped[str] = mapped_column(Text)


class Case(Base):
    """Case opened by the C-02 monitor; empty after seeding.

    C-03 adds the investigation columns. C-04 adds reopen_count.
    """

    __tablename__ = "cases"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    case_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # CASE-0001
    store_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.stores.store_id"), index=True)
    status: Mapped[CaseStatus] = mapped_column(str_enum(CaseStatus, "case_status"))
    trigger_rule: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[datetime] = mapped_column(TZ)
    window_end: Mapped[datetime] = mapped_column(TZ)
    mi_rate: Mapped[Decimal] = mapped_column(RATE)
    baseline_rate: Mapped[Decimal | None] = mapped_column(RATE, nullable=True)
    eligible_orders: Mapped[int] = mapped_column(Integer)
    attributable_claims: Mapped[int] = mapped_column(Integer)  # numerator of mi_rate (C-02)
    goal_rate: Mapped[Decimal] = mapped_column(RATE)  # MONITOR_GOAL_RATE at open time (C-02)
    opened_at: Mapped[datetime] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ)
    # C-03: reported by the agent through PUT /internal/cases/{case_id}/investigation
    active_investigation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    investigation_ids: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))  # oldest first
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class IdempotencyRecord(Base):
    """Stored response for a request that carried an Idempotency-Key header.

    A repeat with the same key and route returns the stored response and writes nothing.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    route: Mapped[str] = mapped_column(String(120), primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZ)


# ---------------------------------------------------------------------------
# Proposals, decisions, dispatch, rechecks and audit (C-03)
# ---------------------------------------------------------------------------
class ProposalKind(str, enum.Enum):
    MERCHANT_QUESTION = "merchant_question"
    INTERVENTION = "intervention"
    HANDOFF = "handoff"


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RecheckStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    IMPROVED = "improved"
    NOT_IMPROVED = "not_improved"
    INSUFFICIENT_DATA = "insufficient_data"


# ID sequences (created by the C-03 migration). Postgres sequences never hand out the same
# number twice, even to two requests at the same moment. A rolled-back request leaves a gap.
PROPOSAL_SEQ = Sequence("proposal_id_seq", schema=DOMAIN_SCHEMA, metadata=Base.metadata)
DISPATCH_SEQ = Sequence("dispatch_id_seq", schema=DOMAIN_SCHEMA, metadata=Base.metadata)
RECHECK_SEQ = Sequence("recheck_id_seq", schema=DOMAIN_SCHEMA, metadata=Base.metadata)
AUDIT_SEQ = Sequence("audit_id_seq", schema=DOMAIN_SCHEMA, metadata=Base.metadata)


class Proposal(Base):
    """A merchant question or a recommended action, created by the agent, decided by an analyst.

    The text lives in proposal_versions. An edit adds a version; a decision must name the
    current version, so an analyst never approves text they have not seen.
    """

    __tablename__ = "proposals"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    proposal_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # PROP-0001
    case_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.cases.case_id"), index=True)
    investigation_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[ProposalKind] = mapped_column(str_enum(ProposalKind, "proposal_kind"))
    status: Mapped[ProposalStatus] = mapped_column(str_enum(ProposalStatus, "proposal_status"))
    current_version: Mapped[int] = mapped_column(Integer)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TZ)
    decided_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    decided_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProposalVersion(Base):
    """Every version of a proposal's content is kept, never overwritten."""

    __tablename__ = "proposal_versions"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    proposal_id: Mapped[str] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.proposals.proposal_id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(20))  # user_id, or svc_agent for version 1
    created_at: Mapped[datetime] = mapped_column(TZ)


class Dispatch(Base):
    """The mock send after approval. proposal_id is unique, so a proposal is dispatched at most once."""

    __tablename__ = "dispatches"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    dispatch_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # DSP-000001
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.proposals.proposal_id"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # dispatched / failed
    channel: Mapped[str] = mapped_column(String(20))  # mock_merchant / mock_team_queue
    owner_team: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)  # what was "sent": the approved content
    dispatched_by: Mapped[str] = mapped_column(String(20))
    dispatched_at: Mapped[datetime] = mapped_column(TZ)


class Recheck(Base):
    """Planned follow-up after an approved intervention or handoff. C-03 schedules it; C-04 runs it."""

    __tablename__ = "rechecks"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    recheck_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # RCK-0001
    case_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.cases.case_id"), index=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey(f"{DOMAIN_SCHEMA}.proposals.proposal_id"), unique=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(TZ)
    status: Mapped[RecheckStatus] = mapped_column(str_enum(RecheckStatus, "recheck_status"))
    target: Mapped[dict] = mapped_column(JSON)
    before: Mapped[dict] = mapped_column(JSON)  # RateWindow
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    control: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data_sufficient: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ran_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)


class AuditEntry(Base):
    """Append-only log of who did what to a case. Rows are only ever inserted."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": DOMAIN_SCHEMA}

    audit_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # AUD-000001
    case_id: Mapped[str] = mapped_column(ForeignKey(f"{DOMAIN_SCHEMA}.cases.case_id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(20))  # USR-001, svc_agent or svc_monitor
    actor_role: Mapped[str] = mapped_column(String(20))  # viewer / loe_analyst / service
    action: Mapped[str] = mapped_column(String(40))  # proposal.created, proposal.approved, dispatch.sent ...
    proposal_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(TZ)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Evaluation answer key (hidden from the agent)
# ---------------------------------------------------------------------------
class GoldenScenario(Base):
    __tablename__ = "golden_scenarios"
    __table_args__ = {"schema": EVAL_SCHEMA}

    scenario_id: Mapped[str] = mapped_column(String(10), primary_key=True)  # GS-01
    store_id: Mapped[str] = mapped_column(String(20))  # no FK: keep eval independent of domain
    split: Mapped[str] = mapped_column(String(10))  # dev / holdout
    cause_category: Mapped[str] = mapped_column(String(20))  # contracts cause_category, or none when no case should open
    true_cause: Mapped[str] = mapped_column(String(64))
    cause_started_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    expected_outcome: Mapped[str] = mapped_column(String(20))  # diagnosis / unsure / no_case (InvestigationResult.outcome)
    expected_owner: Mapped[str] = mapped_column(String(20))  # contracts owner_team
    expected_action: Mapped[str] = mapped_column(String(80))  # catalog action_id (app/catalog.py), or no_case
    key_evidence: Mapped[list] = mapped_column(JSON, default=list)  # descriptions for a person to read
    # C-04: the evidence IDs behind the label (signal claims, cause events and cancellations).
    # The seed is fixed, so the same IDs come back on every reset; the B-05 runner compares
    # the agent's supporting_evidence_ids with them.
    key_evidence_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    distractors: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")


class WorkflowScenario(Base):
    """C-04: expected workflow and safety behavior (sprint plan page 5, "Workflow and safety").

    Each row says what the system must do after a sequence of steps on a seeded case. The B-05 runner
    and the Domain tests read `expected`; nothing the agent can reach reads this table.
    """
    __tablename__ = "workflow_scenarios"
    __table_args__ = {"schema": EVAL_SCHEMA}

    scenario_id: Mapped[str] = mapped_column(String(10), primary_key=True)  # W-01
    title: Mapped[str] = mapped_column(String(120))
    based_on: Mapped[str | None] = mapped_column(String(10), nullable=True)  # GS-xx, or null for any case
    store_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tickets: Mapped[list] = mapped_column(JSON, default=list)  # tickets whose code makes it pass, e.g. ["C-03"]
    steps: Mapped[list] = mapped_column(JSON, default=list)  # what is done, in order
    expected: Mapped[list] = mapped_column(JSON, default=list)  # what must be true afterwards
    notes: Mapped[str] = mapped_column(Text, default="")
