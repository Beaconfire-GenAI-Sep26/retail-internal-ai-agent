"""Postgres checkpoints (AGENT_CHECKPOINTER=postgres), and the investigation index rebuilt from them at startup.

The index has no table of its own: every row field lives in the run's checkpoint state, so after a restart
the index is read back from the checkpoints. A paused run comes back paused and can be resumed. A run that was
mid-segment when the service stopped can't continue, because its task and token are gone, so it comes back
failed with AGENT_RESTARTED and an analyst's next read reports that to Domain.
"""

from __future__ import annotations

import logging
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


def conninfo(settings: Settings) -> str:
    if settings.database_url:
        return settings.psycopg_url
    return make_conninfo(host=settings.postgres_host, port=settings.postgres_port, dbname=settings.postgres_db,
                         user=settings.postgres_user, password=settings.postgres_password)


async def open_postgres(settings: Settings) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """The checkpointer on a connection pool. setup() creates its tables once; agent_svc owns the agent schema."""
    pool = AsyncConnectionPool(conninfo(settings), open=False,
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
    restored = cut_off = 0
    for thread_id in await _thread_ids(saver, pool):
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values or {}
        if not values.get("investigation_id"):
            continue
        status, error = values.get("status", "running"), values.get("error")
        pending = bool(values.get("domain_sync_pending"))
        if status == "running":  # the service stopped mid-segment
            error = {"code": AGENT_RESTARTED, "message": "The Agent Service restarted during the run."}
            await graph.aupdate_state(config, {"status": "failed", "error": error}, as_node="fail")
            status, pending = "failed", True  # an analyst's next read reports it to Domain
            cut_off += 1
        store.restore(InvestigationRow(
            investigation_id=values["investigation_id"], case_id=values["case_id"], store_id=values["store_id"],
            status=status, started_by=values.get("started_by", ""), started_at=values.get("started_at", ""),
            updated_at=snapshot.created_at or values.get("started_at", ""), reopen_of=values.get("reopen_of"),
            domain_sync_pending=pending, error=error,
        ))
        restored += 1
    if restored:
        log_event(logger, logging.INFO, "investigations restored", count=restored, cut_off=cut_off)
