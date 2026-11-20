"""Agent-issued IDs: INV-, CHK- and HYP- plus a ULID (contracts.md, IDs)."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from ulid import ULID


class IdFactory(Protocol):
    def new(self, prefix: str) -> str: ...


class UlidIdFactory:
    def new(self, prefix: str) -> str:
        return f"{prefix}-{ULID()}"


class CounterIdFactory:
    """Deterministic IDs for tests and snapshots: HYP-T0001, CHK-T0001, ..."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def new(self, prefix: str) -> str:
        self._counts[prefix] += 1
        return f"{prefix}-T{self._counts[prefix]:04d}"
