"""Check Uvicorn's root-path handling with the paths forwarded by the gateway."""
import asyncio
import socket
from http.client import HTTPConnection

import httpx
import pytest
import uvicorn

from agent.app.main import create_app as agent_app
from auth.app.main import create_app as auth_app
from domain.app.main import create_app as domain_app


@pytest.mark.parametrize("service", ["auth", "agent", "domain"])
@pytest.mark.parametrize("behind_proxy", [False, True])
def test_server_root_path_preserves_health_docs_and_auth(service, behind_proxy, engine, settings):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as upstream:
            if service == "auth":
                app = auth_app(engine, settings, seed=False)
                protected_path = "/me"
            elif service == "domain":
                app = domain_app(engine, settings, service_token="test-service-token")
                protected_path = "/stores/STORE-A"
            else:
                app = agent_app(settings, upstream, service_token="test-service-token")
                protected_path = "/investigations?case_id=CASE-0001"

            root_path = f"/{service}" if behind_proxy else ""
            server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=0, root_path=root_path,
                log_config=None, access_log=False, lifespan="on",
            ))
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                task = asyncio.create_task(server.serve(sockets=[listener]))
                try:
                    async with asyncio.timeout(10):
                        while not server.started:
                            if task.done():
                                await task
                                pytest.fail("Uvicorn stopped before startup completed")
                            await asyncio.sleep(0.01)
                    def get(path):
                        connection = HTTPConnection("127.0.0.1", listener.getsockname()[1], timeout=5)
                        try:
                            connection.request("GET", path)
                            response = connection.getresponse()
                            return httpx.Response(response.status, content=response.read())
                        finally:
                            connection.close()

                    # Nginx strips /auth, /agent or /domain before forwarding.
                    health = await asyncio.to_thread(get, "/health")
                    assert health.status_code == 200
                    assert health.json() == {"status": "ok", "service": service}
                    if service != "agent":
                        assert (await asyncio.to_thread(get, "/ready")).status_code == 200
                    docs = await asyncio.to_thread(get, "/docs")
                    assert docs.status_code == 200
                    assert f"url: '{root_path}/openapi.json'" in docs.text
                    schema = await asyncio.to_thread(get, "/openapi.json")
                    assert schema.status_code == 200
                    if root_path:
                        assert schema.json()["servers"] == [{"url": root_path}]
                    response = await asyncio.to_thread(get, protected_path)
                    assert response.status_code == 401
                    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
                finally:
                    server.should_exit = True
                    try:
                        await asyncio.wait_for(task, timeout=10)
                    finally:
                        if not task.done():
                            task.cancel()

    asyncio.run(run())
