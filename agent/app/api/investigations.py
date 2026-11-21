"""Agent Service endpoints from contracts.md: start, read, list and resume investigations."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from agent.app.auth import Principal, get_principal
from agent.app.contracts.enums import TERMINAL_STATUSES
from agent.app.contracts.models import (
    CheckSummary,
    ErrorInfo,
    Hypothesis,
    InvestigationResult,
    InvestigationStatusUpdate,
    InvestigationView,
    StartInvestigationRequest,
)
from agent.app.domain.client import DomainError
from agent.app.errors import UNAUTHENTICATED, UPSTREAM_UNAVAILABLE, AppError
from agent.app.graph.nodes.common import now_iso
from agent.app.logs import request_id_var
from agent.app.store import ActiveInvestigationError, InvestigationRow

router = APIRouter(tags=["investigations"])

# Case statuses that accept a fresh investigation (one without reopen_of).
STARTABLE_STATUSES = frozenset({"open", "investigating"})
# Investigation statuses that wait for a person: the analyst's decision, then the merchant's reply.
PAUSED_STATUSES = frozenset({"awaiting_approval", "awaiting_merchant"})


def _services(request: Request) -> Any:
    return request.app.state


def _check_summary(c: dict[str, Any]) -> CheckSummary:
    result = c.get("result", {})
    return CheckSummary(
        check_id=c["check_id"],
        kind=c["kind"],
        tool=c["tool"],
        purpose=c.get("purpose", ""),
        discriminates=c.get("discriminates", []),
        expectations=c.get("expectations", []),
        challenges=c.get("challenges"),
        matched=c.get("matched", {}),
        headline=result.get("headline", ""),
        data_sufficient=bool(result.get("data_sufficient")),
        evidence_ids=result.get("evidence_ids", []),
        at=c.get("at", ""),
    )


async def build_view(request: Request, row: InvestigationRow) -> InvestigationView:
    services = _services(request)
    values = await services.runner.state_values(row.investigation_id)
    checkpoint_status = values.get("status", row.status)
    if row.status in TERMINAL_STATUSES:
        status = row.status
    elif services.runner.is_active(row.investigation_id):
        # A segment is executing, so the UI keeps polling. finalize writes a terminal status before the proposal
        # is saved and the status reported; the run counts as finished only once the runner records it on the row.
        status = "running"
    elif checkpoint_status in TERMINAL_STATUSES:
        status = row.status
    else:
        status = checkpoint_status
    result = values.get("result")
    error = row.error or values.get("error")
    if status in PAUSED_STATUSES:
        pending = values.get("question_proposal_id")
    elif status == "completed" and result:
        pending = result.get("proposal_id")
    else:
        pending = None
    return InvestigationView(
        investigation_id=row.investigation_id,
        case_id=row.case_id,
        store_id=row.store_id,
        status=status,
        started_by=row.started_by,
        started_at=row.started_at,
        updated_at=row.updated_at,
        step_count=values.get("step_count", 0),
        max_steps=services.settings.agent_max_steps,
        reopen_of=row.reopen_of,
        hypotheses=[Hypothesis.model_validate(h) for h in values.get("hypotheses", [])],
        checks=[_check_summary(c) for c in values.get("checks", [])],
        pending_proposal_id=pending,
        result=InvestigationResult.model_validate(result) if result else None,
        error=ErrorInfo.model_validate(error) if error else None,
    )


def _resend_status_report(services: Any, principal: Principal, row: InvestigationRow) -> None:
    """Resend a finished run's failed status report in the background, so the case doesn't stay investigating.

    Only an analyst's request may: the report is an /internal/ write made with that analyst's JWT. The runner
    makes one attempt at most every FLUSH_INTERVAL_SECONDS per investigation.
    """
    if principal.is_analyst and row.domain_sync_pending and row.status in TERMINAL_STATUSES:
        services.runner.schedule_flush(row, token=principal.token, request_id=request_id_var.get() or "unknown")


def _not_found(case_id: str) -> AppError:
    return AppError(404, "CASE_NOT_FOUND", f"Case {case_id} was not found.")


@router.post("/investigations", status_code=202, response_model=InvestigationView)
async def start_investigation(
    body: StartInvestigationRequest, request: Request, principal: Principal = Depends(get_principal)
) -> InvestigationView:
    services = _services(request)
    settings = services.settings
    request_id = request_id_var.get() or "unknown"
    if not principal.is_analyst:
        raise AppError(403, "FORBIDDEN", "Only an LOE analyst can start an investigation.")
    if not getattr(services.runner.model, "configured", True):
        raise AppError(503, UPSTREAM_UNAVAILABLE, "ANTHROPIC_API_KEY is not configured.")
    if principal.expires_at - time.time() < settings.agent_run_timeout_seconds:
        raise AppError(401, UNAUTHENTICATED, "The token expires before the investigation could finish. Log in again.")
    domain = services.domain_client.bind(token=principal.token, request_id=request_id, investigation_id=None)
    try:
        case = await domain.get_case(body.case_id)
    except DomainError as exc:
        if exc.status in (403, 404):
            raise _not_found(body.case_id) from exc
        if exc.status == 401:
            raise AppError(401, UNAUTHENTICATED, "Domain rejected the token.") from exc
        raise AppError(503, UPSTREAM_UNAVAILABLE, "The Domain Service is unavailable.") from exc
    if not principal.can_see(case.store_id):
        raise _not_found(body.case_id)

    store = services.store
    async with store.lock_for(case.case_id):
        if body.reopen_of is not None:
            prior = store.get(body.reopen_of)
            already = any(r.reopen_of for r in store.list(case_id=case.case_id))
            if case.status != "reopened" or prior is None or prior.case_id != case.case_id or already:
                raise AppError(409, "REOPEN_NOT_ALLOWED",
                               "reopen_of is set, but this case isn't reopened or was already reopened once.")
        # Domain allows one pending proposal per case: a new run couldn't save its recommendation, and its failed
        # report would move the case back to open. An active run still answers INVESTIGATION_ACTIVE below.
        pending = next((p for p in case.proposals if p.status == "pending"), None)
        if pending is not None and store.active_for_case(case.case_id) is None:
            raise AppError(409, "PROPOSAL_PENDING",
                           f"Case {case.case_id} has a pending proposal, {pending.proposal_id}. Decide it first.",
                           {"proposal_id": pending.proposal_id})
        # A fresh run only on a case nobody has decided yet: open, or investigating with no run here (a run lost when
        # the agent restarted). A reopened case starts its second run with reopen_of, checked above.
        if (body.reopen_of is None and case.status not in STARTABLE_STATUSES
                and store.active_for_case(case.case_id) is None):
            raise AppError(409, "CASE_NOT_STARTABLE",
                           f"Case {case.case_id} is {case.status}, so it can't start a new investigation.",
                           {"case_status": case.status})
        now = now_iso()
        row = InvestigationRow(
            investigation_id=services.ids.new("INV"),
            case_id=case.case_id,
            store_id=case.store_id,
            status="running",
            started_by=principal.user_id,
            started_at=now,
            updated_at=now,
            reopen_of=body.reopen_of,
        )
        try:
            store.insert(row)
        except ActiveInvestigationError as exc:
            raise AppError(409, "INVESTIGATION_ACTIVE",
                           f"Case {case.case_id} already has investigation {exc.existing.investigation_id} running.",
                           {"investigation_id": exc.existing.investigation_id}) from exc
        # A newer investigation now owns the case status, so an older run's unsent report must not land later.
        for older in store.list(case_id=case.case_id):
            if older.investigation_id != row.investigation_id and older.domain_sync_pending:
                store.update(older.investigation_id, domain_sync_pending=False)

    # Best effort: one attempt, no retries. It is awaited before the run starts, so it can't land after the run's
    # final report, which means a slow Domain delays the 202 by up to one timeout (domain_timeout_seconds, 10 s).
    # A failure marks the row pending until the run's final report supersedes it.
    bound = services.domain_client.bind(token=principal.token, request_id=request_id,
                                        investigation_id=row.investigation_id, store_id=row.store_id,
                                        case_id=row.case_id, max_retries=0)
    try:
        await bound.report_investigation_status(
            case.case_id, InvestigationStatusUpdate(investigation_id=row.investigation_id, status="running",
                                                    error_code=None)
        )
    except DomainError as exc:
        if not exc.route_missing:
            row = store.update(row.investigation_id, domain_sync_pending=True) or row
    services.runner.start(row, token=principal.token, request_id=request_id)
    return await build_view(request, row)


@router.get("/investigations/{investigation_id}", response_model=InvestigationView)
async def get_investigation(
    investigation_id: str, request: Request, principal: Principal = Depends(get_principal)
) -> InvestigationView:
    services = _services(request)
    row = services.store.get(investigation_id)
    if row is None or not principal.can_see(row.store_id):
        raise AppError(404, "NOT_FOUND", f"Investigation {investigation_id} was not found.")
    _resend_status_report(services, principal, row)
    return await build_view(request, row)


@router.get("/investigations", response_model=list[InvestigationView])
async def list_investigations(
    request: Request,
    case_id: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
) -> list[InvestigationView]:
    services = _services(request)
    rows = [r for r in services.store.list(case_id=case_id) if principal.can_see(r.store_id)]
    # The case page lists runs instead of reading a finished one by ID, so a list resends failed reports too.
    for row in rows:
        _resend_status_report(services, principal, row)
    return [await build_view(request, r) for r in rows]


async def _domain_has_news(services: Any, principal: Principal, row: InvestigationRow, request_id: str) -> bool:
    """Whether Domain now shows what the paused run waits for: the analyst's decision, or the merchant's reply."""
    proposal_id = (await services.runner.state_values(row.investigation_id)).get("question_proposal_id")
    domain = services.domain_client.bind(token=principal.token, request_id=request_id,
                                         investigation_id=row.investigation_id, store_id=row.store_id,
                                         case_id=row.case_id, max_retries=0)
    try:
        if row.status == "awaiting_approval":
            return (await domain.get_proposal(proposal_id)).status != "pending"
        return any(r.proposal_id == proposal_id for r in await domain.list_merchant_replies(row.case_id))
    except DomainError as exc:
        if exc.route_missing:
            return False
        if exc.status == 401:
            raise AppError(401, UNAUTHENTICATED, "Domain rejected the token.") from exc
        if exc.status in (403, 404):
            raise AppError(404, "NOT_FOUND", f"Investigation {row.investigation_id} was not found.") from exc
        raise AppError(503, UPSTREAM_UNAVAILABLE, "The Domain Service is unavailable.") from exc


@router.post("/investigations/{investigation_id}/resume", status_code=202, response_model=InvestigationView)
async def resume_investigation(
    investigation_id: str, request: Request, principal: Principal = Depends(get_principal)
) -> InvestigationView:
    """Continue a paused run once Domain has the decision or the reply. The body is never read.

    Idempotent by state, not by Idempotency-Key: a resume with nothing new, or while a segment is executing,
    returns the current view and starts nothing. A finished run returns 409 INVESTIGATION_FINISHED.
    """
    services = _services(request)
    request_id = request_id_var.get() or "unknown"
    if not principal.is_analyst:
        raise AppError(403, "FORBIDDEN", "Only an LOE analyst can resume an investigation.")
    row = services.store.get(investigation_id)
    if row is None or not principal.can_see(row.store_id):
        raise AppError(404, "NOT_FOUND", f"Investigation {investigation_id} was not found.")
    if not getattr(services.runner.model, "configured", True):
        raise AppError(503, UPSTREAM_UNAVAILABLE, "ANTHROPIC_API_KEY is not configured.")
    if principal.expires_at - time.time() < services.settings.agent_run_timeout_seconds:
        raise AppError(401, UNAUTHENTICATED, "The token expires before the investigation could finish. Log in again.")
    # Decided and started under the case lock, so two resumes can't start two segments.
    async with services.store.lock_for(row.case_id):
        row = services.store.get(investigation_id) or row
        if row.status in TERMINAL_STATUSES:
            raise AppError(409, "INVESTIGATION_FINISHED", f"Investigation {investigation_id} has already finished.")
        if (row.status in PAUSED_STATUSES and not services.runner.is_active(investigation_id)
                and await _domain_has_news(services, principal, row, request_id)):
            services.runner.resume(row, token=principal.token, request_id=request_id)
    return await build_view(request, row)
