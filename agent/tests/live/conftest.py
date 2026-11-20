"""Setup for the live tests against a running, seeded Domain Service.

They run only when AGENT_IT_DOMAIN_URL and AGENT_IT_JWT_SECRET are set (see agent/README.md), and skip
otherwise. AGENT_IT_SERVICE_TOKEN defaults to the agent's INTERNAL_SERVICE_TOKEN (environment, then agent/.env).
AGENT_IT_JWT_ISSUER defaults to mi-auth.

The harness stands in for Auth and the frontend: it mints user tokens with the shared JWT_SECRET, the way
Domain's own tests do, and runs the monitor and looks up cases with plain httpx. In "Domain API: Who Calls
What" those are frontend calls, so they never become agent code. Everything the agent itself does goes
through HttpDomainClient with a forwarded user token.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
import pytest

from agent.app.config import get_settings

DOMAIN_URL = os.environ.get("AGENT_IT_DOMAIN_URL", "").rstrip("/")
JWT_SECRET = os.environ.get("AGENT_IT_JWT_SECRET", "")
JWT_ISSUER = os.environ.get("AGENT_IT_JWT_ISSUER", "mi-auth")
SERVICE_TOKEN = (os.environ.get("AGENT_IT_SERVICE_TOKEN") or get_settings().internal_service_token
                 or "change-me-internal")
AS_OF = "2026-11-15"
CASE_STORES = ("STORE-A", "STORE-B")
ALL_STORES = tuple(f"STORE-{c}" for c in "ABCDEFGHIJ")


def mint(role: str = "loe_analyst", stores: tuple[str, ...] = ALL_STORES, sub: str = "USR-901",
         ttl: int = 3600) -> str:
    now = int(time.time())
    claims = {"sub": sub, "name": "Live Test", "role": role, "store_ids": list(stores), "iss": JWT_ISSUER,
              "iat": now, "exp": now + ttl}
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass(frozen=True)
class LiveDomain:
    url: str
    cases: dict[str, str]  # store_id -> an open case_id


def pending_proposals(live: LiveDomain, case_id: str) -> list[dict[str, Any]]:
    with httpx.Client(base_url=live.url, timeout=30) as http:
        case = http.get(f"/cases/{case_id}", headers=auth(mint())).json()
    return [p for p in case.get("proposals", []) if p.get("status") == "pending"]


def release_proposals(live: LiveDomain, case_id: str, investigation_ids: set[str]) -> None:
    """As the frontend: reject the pending proposals these test runs saved, so the next run on the case can save
    its own. A no-op while Domain has no proposals route."""
    for proposal in pending_proposals(live, case_id):
        if proposal.get("investigation_id") not in investigation_ids:
            continue
        with httpx.Client(base_url=live.url, timeout=30) as http:
            http.post(f"/proposals/{proposal['proposal_id']}/decision",
                      json={"version": proposal.get("version", 1), "decision": "reject", "note": "live test cleanup"},
                      headers={**auth(mint()), "Idempotency-Key": str(uuid.uuid4())}).raise_for_status()


@pytest.fixture(scope="session")
def live() -> LiveDomain:
    if not (DOMAIN_URL and JWT_SECRET):
        pytest.skip("set AGENT_IT_DOMAIN_URL and AGENT_IT_JWT_SECRET to run the live Domain tests")
    analyst = auth(mint())
    with httpx.Client(base_url=DOMAIN_URL, timeout=30) as http:
        try:
            ready = http.get("/ready")
        except httpx.HTTPError:
            pytest.skip(f"Domain is not reachable at {DOMAIN_URL}")
        if ready.status_code != 200:
            pytest.skip(f"Domain at {DOMAIN_URL} is not ready: {ready.text[:200]}")
        # As the frontend's "run monitor" button: opens the seeded cases, or finds them already open.
        run = http.post("/monitor/run", json={"as_of": AS_OF},
                        headers={**analyst, "Idempotency-Key": "agent-live-tests"})
        if run.status_code == 422:
            pytest.skip("Domain has no order data; run `python -m domain.scripts.reset_and_seed` from the repo root")
        run.raise_for_status()
        cases: dict[str, str] = {}
        for store in CASE_STORES:
            rows = http.get("/cases", params={"store_id": store}, headers=analyst).json()
            open_rows = [r for r in rows if r["status"] != "closed"]
            if not open_rows:
                pytest.skip(f"no open case for {store}; reseed Domain and rerun the monitor")
            cases[store] = open_rows[0]["case_id"]
    return LiveDomain(url=DOMAIN_URL, cases=cases)
