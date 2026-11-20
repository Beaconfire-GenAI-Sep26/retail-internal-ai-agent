"""The bundled action catalog (`app/data/catalog.json`).

Domain owns the catalog (`GET /catalog/actions`). The agent ships a copy with the same entries, which it
uses when Domain doesn't have that route yet and in fixtures mode.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from agent.app.contracts.models import ActionCatalogEntry

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


@lru_cache(maxsize=1)
def _entries() -> tuple[ActionCatalogEntry, ...]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return tuple(ActionCatalogEntry.model_validate(entry) for entry in data)


def load_bundled_catalog() -> list[ActionCatalogEntry]:
    """Fresh copies of the bundled entries, so callers can't change the cached ones."""
    return [entry.model_copy(deep=True) for entry in _entries()]
