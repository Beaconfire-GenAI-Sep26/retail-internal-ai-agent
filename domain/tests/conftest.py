"""Tests run against the seeded database (python -m scripts.reset_and_seed first).

They delete rows from domain.cases and domain.idempotency_keys, which the seed leaves empty.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import Case, IdempotencyRecord
from app.settings import settings

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
    return {"Authorization": f"Bearer {make_token(**kw)}"}


@pytest.fixture
def client():
    return TestClient(app)


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
