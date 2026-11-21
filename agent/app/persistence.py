"""Postgres checkpoints (AGENT_CHECKPOINTER=postgres), and the investigation index rebuilt from them at startup.

The index has no table of its own: every row field lives in the run's checkpoint state, so after a restart
the index is read back from the checkpoints. A paused run comes back paused and can be resumed. A run cut off
mid-segment, or after finalize but before its proposal was saved, can't continue, because its task and token
are gone: it comes back failed with AGENT_RESTARTED. A run whose final report may not have reached Domain is
marked for a report, which an analyst's next read sends, but only for each case's newest run, so an older run
never overwrites a newer one's case status.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.app.config import Settings
from agent.app.errors import AGENT_RESTARTED
from agent.app.logs import log_event
from agent.app.store import InvestigationRow, InvestigationStore

logger = logging.getLogger("agent.persistence")
PAUSED = ("awaiting_approval", "awaiting_merchant")


def conninfo(settings: Settings) -> str:
    """DATABASE_URL, or the POSTGRES_* variables Compose sets for agent_svc. Those are read from the process
    environment only: the repository-root .env uses the same names for the database admin."""
    if settings.database_url:
        return settings.psycopg_url
    env = os.environ
    return make_conninfo(host=env.get("POSTGRES_HOST", "postgres"), port=env.get("POSTGRES_PORT", "5432"),
                         dbname=env.get("POSTGRES_DB", ""), user=env.get("POSTGRES_USER", ""),
                         password=env.get("POSTGRES_PASSWORD", ""))


async def open_postgres(settings: Settings) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """The checkpointer on a connection pool. setup() creates its tables once; agent_svc owns the agent schema."""
    pool = AsyncConnectionPool(conninfo(settings), open=False, check=AsyncConnectionPool.check_connection,
                               kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    await pool.open(wait=True, timeout=15)
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver, pool


async def _thread_ids(saver: BaseCheckpointSaver, pool: AsyncConnectionPool | None) -> list[str]:
    if pool is not None:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''")
            return [row["thread_id"] for row in await cur.fetchall()]
    return list(dict.fromkeys([c.config["configurable"]["thread_id"] async for c in saver.alist(None)]))


async def restore_index(graph: Any, store: InvestigationStore, saver: BaseCheckpointSaver,
                        pool: AsyncConnectionPool | None = None) -> None:
    rows: list[InvestigationRow] = []
    cut_off = 0
    for thread_id in await _thread_ids(saver, pool):
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values or {}
        if not values.get("investigation_id"):
            continue
        status, error = values.get("status", "running"), values.get("error")
        left = set(snapshot.next or ())  # nodes still to run; a paused run waits in one
        if status == "running" or "submit_recommendation" in left:
            error = {"code": AGENT_RESTARTED, "message": "The Agent Service restarted during the run."}
            # The unsaved diagnosis goes too: the run failed, and no proposal backs it.
            await graph.aupdate_state(config, {"status": "failed", "error": error, "domain_sync_pending": True,
                                               "result": None}, as_node="fail")
            status = "failed"
            cut_off += 1
        # Its final report may not have reached Domain: report_status hadn't run, or a report failed.
        pending = bool(values.get("domain_sync_pending")) or bool(left and status not in PAUSED)
        rows.append(InvestigationRow(
            investigation_id=values["investigation_id"], case_id=values["case_id"], store_id=values["store_id"],
            status=status, started_by=values.get("started_by", ""), started_at=values.get("started_at", ""),
            updated_at=snapshot.created_at or values.get("started_at", ""), reopen_of=values.get("reopen_of"),
            domain_sync_pending=pending, error=error,
        ))
    # As when a run starts: a case's newest run owns its status, so older runs never report.
    newest = {r.case_id: r.investigation_id for r in sorted(rows, key=lambda r: (r.started_at, r.investigation_id))}
    for row in rows:
        store.restore(row if newest[row.case_id] == row.investigation_id else replace(row, domain_sync_pending=False))
    if rows:
        log_event(logger, logging.INFO, "investigations restored", count=len(rows), cut_off=cut_off)
