"""Tests run against the seeded database (python -m scripts.reset_and_seed first).

They delete rows from domain.cases and domain.idempotency_keys, which the seed leaves empty.
"""
import time
import os

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import make_url

if not os.getenv("DOMAIN_TEST_DATABASE_URL"):
    raise pytest.UsageError("Set DOMAIN_TEST_DATABASE_URL to an isolated seeded retail_merge_test_* database.")
if not (make_url(os.environ["DOMAIN_TEST_DATABASE_URL"]).database or "").startswith("retail_merge_test_"):
    raise RuntimeError("Domain integration tests delete test cases; use an isolated retail_merge_test_* database.")
os.environ["DATABASE_URL"] = os.environ["DOMAIN_TEST_DATABASE_URL"]
os.environ.setdefault("JWT_SECRET", "domain-test-signing-secret-at-least-32-bytes")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "domain-test-service-token")

from domain.app.db import SessionLocal
from domain.app.main import app
from domain.app.models import Case, IdempotencyRecord
from domain.app.settings import settings

ALL_STORES = [f"STORE-{c}" for c in "ABCDEFGHIJ"]


def make_token(role="loe_analyst", store_ids=None, **overrides):
    claims = {
        "sub": "USR-001",
        "name": "Test Analyst",
        "role": role,
        "store_ids": ALL_STORES if store_ids is None else store_ids,
        "iss": settings.jwt_issuer,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def auth(**kw):
    return {"Authorization": f"Bearer {make_token(**kw)}",
            "X-Service-Token": os.environ.get("INTERNAL_SERVICE_TOKEN", "domain-test-service-token")}


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def clean_cases():
    def wipe():
        with SessionLocal() as s:
            s.execute(delete(IdempotencyRecord))
            s.execute(delete(Case))
            s.commit()

    wipe()
    yield
    wipe()
