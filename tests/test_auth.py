import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from auth.app.main import create_app
from auth.app.repository import sessions, users, digest_token

PASSWORD = "Password123!"


@pytest.fixture
def auth(engine, settings):
    app = create_app(engine, settings, seed=False, cookie_secure=False)
    with TestClient(app, base_url="http://testserver", root_path="/auth") as client:
        app.state.repo.seed(PASSWORD, PASSWORD)
        yield app, client


def login(client, username="analyst", **extra):
    return client.post("/auth/login", json={"username": username, "password": PASSWORD, **extra})


def test_login_contract_cookie_and_hashed_storage(auth, settings):
    app, client = auth
    response = login(client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["token_type"] == "bearer" and data["expires_at"].endswith("Z")
    assert data["user"] == {"user_id": "USR-001", "display_name": "Demo LOE Analyst", "role": "loe_analyst", "store_ids": ["STORE-A", "STORE-B"]}
    claims = jwt.decode(data["access_token"], settings.secret, algorithms=["HS256"], issuer=settings.issuer)
    assert claims["exp"] - claims["iat"] == 3600
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/auth" in cookie and "SameSite=lax" in cookie
    assert response.headers["cache-control"] == "no-store"
    raw = client.cookies.get("refresh_token")
    with app.state.repo.engine.connect() as conn:
        account = conn.execute(select(users)).mappings().first()
        stored = conn.execute(select(sessions)).mappings().first()
    assert PASSWORD not in account["password_hash"]
    assert stored["token_hash"] == digest_token(raw) and stored["token_hash"] != raw
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.json() == data["user"]


@pytest.mark.parametrize("username,password", [("analyst", "wrong"), ("missing", PASSWORD)])
def test_bad_login(auth, username, password):
    _, client = auth
    result = client.post("/auth/login", json={"username": username, "password": password})
    assert result.status_code == 401 and result.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert result.headers["www-authenticate"] == "Bearer"


def test_no_client_selected_grants_and_validation_does_not_echo_password(auth):
    _, client = auth
    result = login(client, role="loe_analyst", store_ids=["STORE-C"])
    assert result.status_code == 422
    assert PASSWORD not in result.text


def test_rotate_replay_and_logout(auth):
    _, client = auth
    login(client)
    first = client.cookies.get("refresh_token")
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    second = client.cookies.get("refresh_token")
    assert first != second
    # Explicit Cookie header replays a stolen/old token and revokes its family.
    replay = client.post("/auth/refresh", headers={"Cookie": f"refresh_token={first}"})
    assert replay.status_code == 401 and "Max-Age=0" in replay.headers["set-cookie"]
    assert client.post("/auth/refresh", headers={"Cookie": f"refresh_token={second}"}).status_code == 401
    login(client)
    active = client.cookies.get("refresh_token")
    assert client.post("/auth/logout", headers={"Authorization": "Bearer expired"}).status_code == 204
    assert client.post("/auth/refresh", headers={"Cookie": f"refresh_token={active}"}).status_code == 401
    assert client.post("/auth/logout").status_code == 204


def test_refresh_uses_current_grants_and_disabled_users(auth):
    app, client = auth
    login(client)
    with app.state.repo.engine.begin() as conn:
        conn.execute(update(users).where(users.c.user_id == "USR-001").values(role="viewer", store_ids=["STORE-B"]))
    refreshed = client.post("/auth/refresh")
    assert refreshed.json()["user"]["role"] == "viewer"
    assert refreshed.json()["user"]["store_ids"] == ["STORE-B"]
    with app.state.repo.engine.begin() as conn:
        conn.execute(update(users).where(users.c.user_id == "USR-001").values(active=False))
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_expiry_and_absent_cookie(auth):
    app, client = auth
    assert client.post("/auth/refresh").status_code == 401
    login(client)
    with app.state.repo.engine.begin() as conn:
        conn.execute(update(sessions).values(expires_at=int(time.time()) - 1))
    assert client.post("/auth/refresh").status_code == 401


def test_session_persists_across_service_restart(auth, settings):
    app, client = auth
    login(client)
    raw = client.cookies.get("refresh_token")
    restarted = create_app(app.state.engine, settings, seed=False, cookie_secure=False)
    with TestClient(restarted, root_path="/auth") as other:
        assert other.post("/auth/refresh", headers={"Cookie": f"refresh_token={raw}"}).status_code == 200


def test_seed_is_idempotent(auth):
    app, _ = auth
    app.state.repo.seed("different-password", "different-password")
    assert app.state.repo.login("analyst", PASSWORD).store_ids == ["STORE-A", "STORE-B"]


@pytest.mark.parametrize("path", ["/auth/login", "/auth/refresh", "/auth/logout"])
def test_csrf_rejected(auth, path):
    _, client = auth
    assert client.post(path, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_secure_cookie_and_same_origin(engine, settings):
    app = create_app(engine, settings, seed=False, cookie_secure=True)
    with TestClient(app, base_url="https://testserver", root_path="/auth") as client:
        app.state.repo.seed(PASSWORD, PASSWORD)
        response = client.post("/auth/login", json={"username": "viewer", "password": PASSWORD},
                               headers={"Origin": "https://testserver", "X-Request-ID": "test-request"})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
        assert response.headers["x-request-id"] == "test-request"


def test_expired_access_can_refresh(auth, settings):
    _, client = auth
    data = login(client).json()
    claims = jwt.decode(data["access_token"], settings.secret, algorithms=["HS256"], issuer=settings.issuer)
    claims.update(iat=int(time.time()) - 120, exp=int(time.time()) - 1)
    expired = jwt.encode(claims, settings.secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    fresh = client.post("/auth/refresh")
    assert fresh.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}).status_code == 200
