"""Investigation state. Every value is JSON-native, so checkpoints never hold custom types.

Record shapes (plain dicts):

Hypothesis: hypothesis_id, cause_category, statement, status, rationale,
    supporting_evidence_ids, contradicting_evidence_ids, check_ids
CheckRecord: check_id, source ("load_case" or "reason"), kind, tool, request, canonical_key,
    signature, purpose, discriminates, expectations, challenges, result (ToolResult),
    matched, needs_match, domain_rejected, at
Event (event_ledger): evidence_id, event_type, start_date, end_date, description
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def upsert_checks(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Merge check records by check_id, so the guard can write `matched` into an existing record."""
    out = list(left or [])
    index = {c["check_id"]: i for i, c in enumerate(out)}
    for record in right or []:
        i = index.get(record["check_id"])
        if i is None:
            index[record["check_id"]] = len(out)
            out.append(record)
        else:
            out[i] = {**out[i], **record}
    return out


def union_ids(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Order-preserving union."""
    out = list(left or [])
    seen = set(out)
    for value in right or []:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def upsert_events(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = list(left or [])
    known = {e["evidence_id"] for e in out}
    for event in right or []:
        if event["evidence_id"] not in known:
            known.add(event["evidence_id"])
            out.append(event)
    return sorted(out, key=lambda e: (e["start_date"], e["evidence_id"]))


def append(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    return list(left or []) + list(right or [])


class InvestigationState(TypedDict, total=False):
    # Identity, set when the run starts
    investigation_id: str
    case_id: str
    store_id: str
    started_by: str  # user_id only; the JWT is never stored
    started_at: str
    reopen_of: str | None
    status: str  # investigation_status
    run_config: dict[str, Any]

    # Case facts, written by load_case
    case: dict[str, Any]
    timezone: str
    window: dict[str, str]
    data_start: str
    menu: list[dict[str, Any]]
    known_items: list[str]
    known_modifiers: list[str]
    catalog: list[dict[str, Any]]
    excluded: dict[str, int]
    suspect_cluster: bool
    prior_hypotheses: list[dict[str, Any]]

    # Evidence
    checks: Annotated[list[dict[str, Any]], upsert_checks]
    retrieved_evidence_ids: Annotated[list[str], union_ids]
    event_ledger: Annotated[list[dict[str, Any]], upsert_events]
    challenge_check_ids: Annotated[list[str], append]
    latest_check_id: str | None

    # Reasoning
    hypotheses: list[dict[str, Any]]
    reason_output: dict[str, Any] | None  # the latest raw output, before validation
    next_action: dict[str, Any] | None
    rise_started_at: str | None

    # Control
    step_count: int
    explore_count: int
    reason_calls: int
    consecutive_rejections: int
    gate_rejections: int
    guard_feedback: dict[str, Any] | None
    gate_feedback: dict[str, Any] | None
    gate_result: dict[str, Any] | None
    end_reason: str | None  # gate_passed, budget_spent, guard_cap, gate_cap or reason_cap
    questions_asked: int
    question_open: bool
    question_proposal_id: str | None
    question_outcome: str | None
    asked_questions: list[str]
    reply_claims: list[str]

    # Outcome
    result: dict[str, Any] | None
    error: dict[str, str] | None
    domain_sync_pending: bool
    usage: dict[str, int]
    model_calls: Annotated[list[dict[str, Any]], append]


def initial_state(
    *,
    investigation_id: str,
    case_id: str,
    store_id: str,
    started_by: str,
    started_at: str,
    reopen_of: str | None,
    run_config: dict[str, Any],
) -> InvestigationState:
    return InvestigationState(
        investigation_id=investigation_id,
        case_id=case_id,
        store_id=store_id,
        started_by=started_by,
        started_at=started_at,
        reopen_of=reopen_of,
        status="running",
        run_config=run_config,
        prior_hypotheses=[],
        checks=[],
        retrieved_evidence_ids=[],
        event_ledger=[],
        challenge_check_ids=[],
        latest_check_id=None,
        hypotheses=[],
        reason_output=None,
        next_action=None,
        rise_started_at=None,
        step_count=0,
        explore_count=0,
        reason_calls=0,
        consecutive_rejections=0,
        gate_rejections=0,
        guard_feedback=None,
        gate_feedback=None,
        gate_result=None,
        end_reason=None,
        questions_asked=0,
        question_open=False,
        question_proposal_id=None,
        question_outcome=None,
        asked_questions=[],
        reply_claims=[],
        result=None,
        error=None,
        domain_sync_pending=False,
        usage={},
        model_calls=[],
    )


def check_by_id(state: InvestigationState, check_id: str | None) -> dict[str, Any] | None:
    if not check_id:
        return None
    return next((c for c in state.get("checks", []) if c["check_id"] == check_id), None)


def hypothesis_by_id(state: InvestigationState, hypothesis_id: str | None) -> dict[str, Any] | None:
    return next((h for h in state.get("hypotheses", []) if h["hypothesis_id"] == hypothesis_id), None)
