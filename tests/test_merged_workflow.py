"""Regression checks for wiring B-02/C-02 into the A-02 security boundary."""
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.app.config import Settings
from agent.app.domain.client import DomainError, HttpDomainClient
from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.ids import CounterIdFactory
from agent.app.llm.scripted_model import ScriptedReasonModel
from agent.app.main import create_app
from agent.tests.scripts import store_a_turns
from domain.app.main import create_app as domain_app

FIXTURES = Path(__file__).resolve().parents[1] / 'agent/tests/fixtures/domain'


def test_production_investigation_routes_enforce_shared_jwt(settings, identities):
    config = Settings(_env_file=None, jwt_secret=settings.secret, agent_domain_mode='fixtures',
                      agent_checkpointer='memory', agent_run_timeout_seconds=600)
    domain = FixtureDomainClient(FIXTURES)
    app = create_app(config, domain_client=domain,
                     model=ScriptedReasonModel(store_a_turns()), ids=CounterIdFactory(), configure_logs=False)
    with TestClient(app) as client:
        assert client.post('/investigations', json={'case_id':'CASE-0001'}).status_code == 401
        viewer = {'Authorization':'Bearer '+identities('viewer', ['STORE-A'])}
        assert client.post('/investigations', headers=viewer, json={'case_id':'CASE-0001'}).status_code == 403
        headers = {'Authorization':'Bearer '+identities()}
        response = client.post('/investigations', headers=headers, json={'case_id':'CASE-0001'})
        assert response.status_code == 202, response.text
        investigation_id = response.json()['investigation_id']
        assert client.get('/investigations/'+investigation_id, headers=viewer).status_code == 200
        outsider = {'Authorization':'Bearer '+identities('viewer', ['STORE-B'])}
        assert client.get('/investigations/'+investigation_id, headers=outsider).status_code == 404
        assert client.get('/unreviewed-operation', headers=headers).status_code == 403
        # Reads re-resolve Domain ownership, rather than trusting only the old row.
        domain.stores['STORE-A'].case = domain.stores['STORE-A'].case.model_copy(update={'store_id':'STORE-B'})
        assert client.get('/investigations/'+investigation_id, headers=viewer).status_code == 404


def test_typed_workflow_domain_client_keeps_a02_scope(settings, identities):
    seen = []
    async def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'tool':'claim_breakdown','store_id':'STORE-A',
            'window':{'start':'2026-10-05','end':'2026-11-15'},'headline':'test',
            'data_sufficient':True,'eligible_orders':100,'pending_claims':0,
            'metrics':[],'evidence_ids':[],'evidence':[],'notes':[]})
    async def run():
        client = HttpDomainClient('http://domain', 'service-test', jwt_settings=settings,
                                  transport=httpx.MockTransport(respond), max_retries=0)
        try:
            bound = client.bind(token=identities(), request_id='merge-request', investigation_id='INV-TEST',
                                store_id='STORE-A', case_id='CASE-0001')
            await bound.claim_breakdown('STORE-A', {'filter':{'start':'2026-10-05','end':'2026-11-15'}, 'group_by':'daypart'})
            with pytest.raises(DomainError) as error:
                await bound.claim_breakdown('STORE-B', {})
            assert error.value.status == 403
            with pytest.raises(DomainError):
                await bound._call('POST', '/proposals/PROP-0001/decision')
        finally:
            await client.aclose()
    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].headers['X-Store-ID'] == 'STORE-A'
    assert seen[0].headers['X-Request-ID'] == 'merge-request'
    assert 'X-Service-Token' not in seen[0].headers


def test_domain_business_routers_are_registered_and_protected(engine, settings):
    app = domain_app(engine, settings, 'service-test')
    paths = set(app.openapi()['paths'])
    assert {'/cases', '/cases/{case_id}', '/stores/{store_id}/overview',
            '/stores/{store_id}/diagnostics/claim-breakdown', '/monitor/run', '/evidence/resolve'} <= paths
    with TestClient(app) as client:
        assert client.get('/cases').status_code == 401
        assert client.post('/monitor/run', json={}).status_code == 401
