"""The investigation index. In memory until the agent.investigations table lands (M2)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any

from agent.app.contracts.enums import ACTIVE_STATUSES


@dataclass(frozen=True)
class InvestigationRow:
    investigation_id: str
    case_id: str
    store_id: str
    status: str
    started_by: str
    started_at: str
    updated_at: str
    reopen_of: str | None = None
    domain_sync_pending: bool = False
    error: dict[str, str] | None = field(default=None, compare=False)


class ActiveInvestigationError(Exception):
    def __init__(self, existing: InvestigationRow):
        super().__init__(existing.investigation_id)
        self.existing = existing


class InvestigationStore:
    def __init__(self) -> None:
        self._rows: dict[str, InvestigationRow] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock_for(self, case_id: str) -> asyncio.Lock:
        return self._locks[case_id]

    def active_for_case(self, case_id: str) -> InvestigationRow | None:
        return next((r for r in self._rows.values() if r.case_id == case_id and r.status in ACTIVE_STATUSES), None)

    def insert(self, row: InvestigationRow) -> None:
        existing = self.active_for_case(row.case_id)
        if existing is not None:
            raise ActiveInvestigationError(existing)
        self._rows[row.investigation_id] = row

    def get(self, investigation_id: str) -> InvestigationRow | None:
        return self._rows.get(investigation_id)

    def update(self, investigation_id: str, **fields: Any) -> InvestigationRow | None:
        row = self._rows.get(investigation_id)
        if row is None:
            return None
        row = replace(row, **fields)
        self._rows[investigation_id] = row
        return row

    def list(self, *, case_id: str | None = None) -> list[InvestigationRow]:
        rows = [r for r in self._rows.values() if case_id is None or r.case_id == case_id]
        return sorted(rows, key=lambda r: (r.started_at, r.investigation_id), reverse=True)

    def running(self) -> list[InvestigationRow]:
        return [r for r in self._rows.values() if r.status in ACTIVE_STATUSES]
