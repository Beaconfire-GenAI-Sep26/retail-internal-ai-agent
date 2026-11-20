import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.security import JWTSettings, User, issue_token


@pytest.fixture
def settings():
    return JWTSettings("test-signing-secret-with-at-least-32-bytes")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    yield engine
    engine.dispose()


@pytest.fixture
def identities(settings):
    def token(role="loe_analyst", stores=("STORE-A", "STORE-B")):
        user = User(user_id="USR-001" if role == "loe_analyst" else "USR-002",
                    display_name="Test user", role=role, store_ids=list(stores))
        return issue_token(user, settings)["access_token"]
    return token


@pytest.fixture
def domain_engine(engine):
    with engine.begin() as conn:
        for ddl in [
            "CREATE TABLE stores (store_id TEXT PRIMARY KEY, name TEXT, city TEXT, timezone TEXT, cuisine TEXT)",
            "CREATE TABLE menu_items (item_id TEXT PRIMARY KEY, store_id TEXT, name TEXT, category TEXT, price NUMERIC, available_modifiers TEXT)",
            "CREATE TABLE cases (case_id TEXT PRIMARY KEY, store_id TEXT, status TEXT, opened_at TEXT)",
            "CREATE TABLE proposals (proposal_id TEXT PRIMARY KEY, case_id TEXT)",
            "CREATE TABLE rechecks (recheck_id TEXT PRIMARY KEY, case_id TEXT)",
            "CREATE TABLE mi_claims (evidence_id TEXT PRIMARY KEY, store_id TEXT)",
        ]:
            conn.execute(text(ddl))
        for letter in "ABC":
            conn.execute(text("INSERT INTO stores VALUES (:id, :name, 'City', 'America/New_York', 'pizza')"),
                         {"id": f"STORE-{letter}", "name": f"Store {letter}"})
        conn.execute(text("INSERT INTO cases VALUES ('CASE-0001', 'STORE-A', 'open', '2026-11-15'), ('CASE-0002', 'STORE-B', 'open', '2026-11-15'), ('CASE-0003', 'STORE-C', 'open', '2026-11-15')"))
        conn.execute(text("INSERT INTO proposals VALUES ('PROP-0001', 'CASE-0001'), ('PROP-0002', 'CASE-0002'), ('PROP-0003', 'CASE-0003')"))
        conn.execute(text("INSERT INTO rechecks VALUES ('RCK-0001', 'CASE-0001'), ('RCK-0002', 'CASE-0002')"))
        conn.execute(text("INSERT INTO mi_claims VALUES ('EV-CLM-000001', 'STORE-A'), ('EV-CLM-000002', 'STORE-B')"))
    return engine
