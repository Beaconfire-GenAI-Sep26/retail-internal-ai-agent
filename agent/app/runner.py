"""Runs investigations as background tasks and keeps the index in sync with the checkpoints."""

from __future__ import annotations

import asyncio
import logging
import time
from importlib.metadata import version
from typing import Any

from agent.app.config import Settings
from agent.app.contracts.enums import TERMINAL_STATUSES
from agent.app.contracts.models import InvestigationStatusUpdate
from agent.app.domain.client import DomainClient, DomainError
from agent.app.errors import INTERNAL, RUN_TIMEOUT
from agent.app.graph.build import run_config
from agent.app.graph.context import AgentContext
from agent.app.graph.nodes.common import now_iso
from agent.app.graph.state import initial_state
from agent.app.ids import IdFactory
from agent.app.llm.base import ReasonModel
from agent.app.llm.schemas import schema_hash
from agent.app.logs import case_id_var, investigation_id_var, log_event, request_id_var
from agent.app.prompts.render import prompt_hash
from agent.app.store import InvestigationRow, InvestigationStore
from agent.app.tools.registry import REGISTRY_VERSION

logger = logging.getLogger("agent.runner")
BACKSTOP_SECONDS = 30
# A status report that failed earlier is retried at most this often per investigation.
FLUSH_INTERVAL_SECONDS = 30


def run_config_record(settings: Settings, model: ReasonModel) -> dict[str, Any]:
    """What B-05 needs to reproduce a run. No secrets."""
    return {
        "model": settings.anthropic_model if model.name == "anthropic" else model.name,
        "effort": settings.agent_effort,
        "speed": settings.agent_speed,
        "max_steps": settings.agent_max_steps,
        "prompt_hash": prompt_hash(),
        "schema_hash": schema_hash(),
        "registry_version": REGISTRY_VERSION,
        "domain_mode": settings.agent_domain_mode,
        "sdk_version": version("anthropic"),
        "langgraph_version": version("langgraph"),
    }


class Runner:
    def __init__(
        self,
        *,
        graph: Any,
        store: InvestigationStore,
        settings: Settings,
        domain_client: DomainClient,
        model: ReasonModel,
        ids: IdFactory,
    ):
        self.graph = graph
        self.store = store
        self.settings = settings
        self.domain_client = domain_client
        self.model = model
        self.ids = ids
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.flush_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_flush: dict[str, float] = {}

    def config(self, investigation_id: str) -> dict[str, Any]:
        return run_config(investigation_id, self.settings.recursion_limit)

    def start(self, row: InvestigationRow, *, token: str, request_id: str) -> None:
        task = asyncio.create_task(self._run(row, token=token, request_id=request_id))
        self.tasks[row.investigation_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(row.investigation_id, None))

    async def _run(self, row: InvestigationRow, *, token: str, request_id: str) -> None:
        investigation_id_var.set(row.investigation_id)
        case_id_var.set(row.case_id)
        request_id_var.set(request_id)
        domain = self.domain_client.bind(token=token, request_id=request_id, investigation_id=row.investigation_id, store_id=row.store_id, case_id=row.case_id)
        ctx = AgentContext(
            domain=domain,
            model=self.model,
            ids=self.ids,
            settings=self.settings,
            user_id=row.started_by,
            request_id=request_id,
            deadline=time.monotonic() + self.settings.agent_run_timeout_seconds,
        )
        state = initial_state(
            investigation_id=row.investigation_id,
            case_id=row.case_id,
            store_id=row.store_id,
            started_by=row.started_by,
            started_at=row.started_at,
            reopen_of=row.reopen_of,
            run_config=run_config_record(self.settings, self.model),
        )
        config = self.config(row.investigation_id)
        log_event(logger, logging.INFO, "investigation started", store_id=row.store_id)
        try:
            await asyncio.wait_for(
                self.graph.ainvoke(state, config, context=ctx, durability="sync"),
                timeout=self.settings.agent_run_timeout_seconds + BACKSTOP_SECONDS,
            )
        except TimeoutError:
            await self._record_failure(row, domain, RUN_TIMEOUT, "The investigation ran past its time limit.")
        except asyncio.CancelledError:
            await self._record_failure(row, domain, INTERNAL, "The investigation was stopped.")
            raise
        except Exception as exc:  # unexpected: record it as failed and keep the service up
            logger.exception("investigation crashed")
            await self._record_failure(row, domain, INTERNAL, f"Unexpected {type(exc).__name__}. See the service log.")
        finally:
            await self.sync_row(row.investigation_id)
            log_event(logger, logging.INFO, "investigation segment ended",
                      status=(self.store.get(row.investigation_id) or row).status)

    async def _record_failure(self, row: InvestigationRow, domain: Any, code: str, message: str) -> None:
        error = {"code": code, "message": message}
        log_event(logger, logging.ERROR, "investigation failed", code=code, error_message=message)
        try:
            await self.graph.aupdate_state(self.config(row.investigation_id), {"status": "failed", "error": error},
                                           as_node="fail")
        except Exception:  # the checkpoint may not exist yet
            logger.exception("could not write the failure to the checkpoint")
        pending = False
        try:
            await domain.report_investigation_status(
                row.case_id, InvestigationStatusUpdate(investigation_id=row.investigation_id, status="failed",
                                                       error_code=code)
            )
        except DomainError as exc:
            pending = not exc.route_missing
        self.store.update(row.investigation_id, status="failed", error=error, domain_sync_pending=pending,
                          updated_at=now_iso())

    async def state_values(self, investigation_id: str) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self.config(investigation_id))
        return dict(snapshot.values or {})

    async def sync_row(self, investigation_id: str) -> None:
        row = self.store.get(investigation_id)
        if row is None:
            return
        values = await self.state_values(investigation_id)
        if row.status in TERMINAL_STATUSES and row.status == "failed" and row.error:
            return
        status = values.get("status") or row.status
        self.store.update(
            investigation_id,
            status=status,
            error=values.get("error"),
            # The graph's last report supersedes an earlier failed one, such as the "running" report at start.
            domain_sync_pending=bool(values.get("domain_sync_pending")),
            updated_at=now_iso(),
        )

    def schedule_flush(self, row: InvestigationRow, *, token: str, request_id: str) -> None:
        """Retry a failed status report in the background, so the caller never waits on Domain.

        One attempt at most every FLUSH_INTERVAL_SECONDS per investigation. The caller passes the JWT of the
        analyst whose request triggered the flush; it lives only in the task, never in the row or a checkpoint.
        """
        investigation_id = row.investigation_id
        if not row.domain_sync_pending or investigation_id in self.flush_tasks:
            return
        now = time.monotonic()
        last = self._last_flush.get(investigation_id)
        if last is not None and now - last < FLUSH_INTERVAL_SECONDS:
            return
        self._last_flush[investigation_id] = now
        task = asyncio.create_task(self.flush_status(row, token=token, request_id=request_id))
        self.flush_tasks[investigation_id] = task
        task.add_done_callback(lambda _: self.flush_tasks.pop(investigation_id, None))

    async def flush_status(self, row: InvestigationRow, *, token: str, request_id: str) -> None:
        """One attempt at a status report that failed earlier, with the current analyst's token."""
        if not row.domain_sync_pending:
            return
        domain = self.domain_client.bind(token=token, request_id=request_id, investigation_id=row.investigation_id,
                                         store_id=row.store_id, case_id=row.case_id, max_retries=0)
        error_code = (row.error or {}).get("code") if row.status == "failed" else None
        try:
            await domain.report_investigation_status(
                row.case_id,
                InvestigationStatusUpdate(investigation_id=row.investigation_id, status=row.status, error_code=error_code),
            )
        except DomainError as exc:
            if not exc.route_missing:
                log_event(logger, logging.WARNING, "status flush failed", status=row.status, code=exc.code,
                          investigation_id=row.investigation_id, case_id=row.case_id)
                return
        self.store.update(row.investigation_id, domain_sync_pending=False)

    async def shutdown(self) -> None:
        tasks = [*self.tasks.values(), *self.flush_tasks.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
