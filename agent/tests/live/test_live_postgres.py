"""The restart test on a real Postgres: a paused run carries over to a new service process.

Runs only when AGENT_IT_DATABASE_URL names a database with "test" in its name, because it drops the
checkpoint tables first. Connect as agent_svc, or any role that may create tables in its search_path.
psycopg's async mode can't use Windows' default ProactorEventLoop, so on Windows the app runs on a selector loop.
"""

import asyncio
import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.ids import UlidIdFactory
from agent.app.llm.scripted_model import ScriptedReasonModel
from agent.app.main import create_app
from agent.tests.api.test_api import auth, token, wait_for
from agent.tests.conftest import FIXTURES, make_settings
from agent.tests.scripts import store_b_question_turns

DATABASE_URL = os.environ.get("AGENT_IT_DATABASE_URL", "")
LOOP = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
pytestmark = pytest.mark.live_db


@pytest.fixture
def pg_settings():
    if not DATABASE_URL:
        pytest.skip("set AGENT_IT_DATABASE_URL to run the live Postgres test")
    url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    if "test" not in conninfo_to_dict(url).get("dbname", ""):
        pytest.skip("AGENT_IT_DATABASE_URL must name a test database: this test drops the checkpoint tables")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations")
    return make_settings(agent_max_questions=2, agent_checkpointer="postgres", database_url=DATABASE_URL)


def test_a_paused_run_survives_a_new_service_process(pg_settings):
    domain, analyst = FixtureDomainClient(FIXTURES, replies=True), token()
    model, ids = ScriptedReasonModel(store_b_question_turns()), UlidIdFactory()

    def service():  # each one opens its own pool, checkpointer and index: only Postgres carries the run over
        return TestClient(create_app(pg_settings, domain_client=domain, model=model, ids=ids, configure_logs=False),
                          backend_options=LOOP)

    with service() as client:
        inv_id = client.post("/investigations", json={"case_id": "CASE-0002"},
                             headers=auth(analyst)).json()["investigation_id"]
        pid = wait_for(client, inv_id, analyst, statuses=("awaiting_approval",))["pending_proposal_id"]
    domain.decide(pid, "approve")
    with service() as client:
        assert client.get(f"/investigations/{inv_id}", headers=auth(analyst)).json()["status"] == "awaiting_approval"
        assert client.post(f"/investigations/{inv_id}/resume", headers=auth(analyst)).status_code == 202
        wait_for(client, inv_id, analyst, statuses=("awaiting_merchant",))
    domain.record_reply(pid, "replied", "Large orders go out in two bags; the second is sometimes left behind.")
    with service() as client:
        assert client.post(f"/investigations/{inv_id}/resume", headers=auth(analyst)).status_code == 202
        done = wait_for(client, inv_id, analyst)
    assert done["status"] == "completed" and done["result"]["outcome"] == "diagnosis"
