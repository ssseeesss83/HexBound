import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI, Request, WebSocket
from client_sessions import TestClient

from backend import accounts
from backend.accounts import COOKIE_NAME, authenticate_websocket, create_accounts_router, get_account_service, require_user
from backend.store import Store

PASSWORD = "Strong-Password-42"
ADMIN_PASSWORD = "Initial-Admin-Password-42"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("HEXBOUND_ALLOW_REGISTRATION", "true")
    monkeypatch.delenv("HEXBOUND_COOKIE_SECURE", raising=False)
    store = Store(str(tmp_path / "accounts.sqlite3"))
    app = FastAPI()
    app.state.store = store
    app.include_router(create_accounts_router(store))
    @app.post("/protected")
    async def protected(request: Request):
        return require_user(request)
    @app.get("/creator")
    async def creator(request: Request):
        return require_user(request, roles={"creator", "admin"})
    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        try:
            user = authenticate_websocket(ws)
        except Exception:
            await ws.close(code=1008)
            return
        await ws.accept()
        await ws.send_json(user)
        await ws.close()
    with TestClient(app) as client:
        yield app, client, store


def register(client, username="traveler", **extra):
    response = client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "display_name": "旅人", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def login(client, username="owner", password=ADMIN_PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def csrf(session):
    return {"X-CSRF-Token": session["csrf_token"]}


def test_registration_player_scrypt_and_opaque_session(setup):
    _, client, store = setup
    session = register(client, "Traveler")
    user = session["user"]
    assert user["username"] == "traveler" and user["role"] == "player"
    assert "password_hash" not in str(session) and PASSWORD not in str(session) and "session" not in session
    raw = client.cookies.get(COOKIE_NAME)
    with store.connect() as db:
        saved = db.execute("SELECT * FROM accounts WHERE id=?", (user["id"],)).fetchone()
        stored_session = db.execute("SELECT * FROM account_sessions WHERE user_id=?", (user["id"],)).fetchone()
    assert saved["password_hash"].startswith("scrypt$16384$8$5$")
    assert PASSWORD not in saved["password_hash"]
    assert accounts.verify_password(PASSWORD, saved["password_hash"])
    assert stored_session["id"] != raw and stored_session["id"] == accounts.digest_token(raw)
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["csrf_token"] == session["csrf_token"]
    assert client.post("/api/auth/register", json={"username": "TRAVELER", "password": PASSWORD}).status_code == 409


def test_registration_cannot_self_promote_or_accept_weak_password(setup):
    _, client, _ = setup
    assert client.post("/api/auth/register", json={"username": "hacker", "password": PASSWORD, "role": "admin"}).status_code == 422
    for password in ("short", " " * 12, "a" * 129):
        assert client.post("/api/auth/register", json={"username": "hacker", "password": password}).status_code == 422
    for username in ("ab", "<script>", "张三", "a" * 33):
        assert client.post("/api/auth/register", json={"username": username, "password": PASSWORD}).status_code == 422


def test_registration_switch_and_bootstrap_not_repeated(setup, monkeypatch):
    _, client, store = setup
    monkeypatch.setenv("HEXBOUND_ALLOW_REGISTRATION", "false")
    assert client.get("/api/auth/status").json()["registration_enabled"] is False
    assert client.post("/api/auth/register", json={"username": "new-user", "password": PASSWORD}).status_code == 403
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD", "Changed-Env-Password")
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME", "second-admin")
    accounts.AccountService(store)
    assert login(client)["user"]["role"] == "admin"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM accounts WHERE role='admin'").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM accounts WHERE username='second-admin'").fetchone() is None


def test_login_cookie_flags_and_invalid_password(setup, monkeypatch):
    _, client, _ = setup
    response = client.post("/api/auth/login", json={"username": "owner", "password": ADMIN_PASSWORD})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    wrong = client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"})
    missing = client.post("/api/auth/login", json={"username": "missing", "password": "wrong-password"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    monkeypatch.setenv("HEXBOUND_COOKIE_SECURE", "true")
    secure = client.post("/api/auth/login", json={"username": "owner", "password": ADMIN_PASSWORD})
    assert "Secure" in secure.headers["set-cookie"]


def test_csrf_origin_and_json_protection(setup):
    _, client, _ = setup
    for origin in ("https://evil.invalid", "https://testserver", "null", "http://[invalid"):
        response = client.post("/api/auth/login", headers={"Origin": origin}, json={"username": "owner", "password": ADMIN_PASSWORD})
        assert response.status_code == 403
    response = client.post("/api/auth/login", content=json.dumps({"username": "owner", "password": ADMIN_PASSWORD}))
    assert response.status_code in (415, 422)
    session = register(client)
    assert client.post("/protected").status_code == 403
    assert client.post("/protected", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/protected", headers={**csrf(session), "Origin": "http://evil.invalid"}).status_code == 403
    assert client.post("/protected", headers={**csrf(session), "Origin": "http://testserver"}).status_code == 200


def test_expiry_logout_and_logout_all_devices(setup):
    app, client, store = setup
    session = register(client)
    with TestClient(app) as other:
        other_session = login(other, "traveler", PASSWORD)
        assert client.post("/api/auth/logout", headers=csrf(session)).status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert other.get("/api/auth/me").status_code == 200
        session = login(client, "traveler", PASSWORD)
        assert client.post("/api/auth/logout-all", headers=csrf(session)).status_code == 200
        assert other.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 401
    login(client)
    with store.connect() as db:
        db.execute("UPDATE account_sessions SET expires_at=?", (time.time() - 1,))
    assert client.get("/api/auth/me").status_code == 401


def test_user_change_password_rotates_current_and_revokes_others(setup):
    app, client, _ = setup
    session = register(client)
    old_token = client.cookies.get(COOKIE_NAME)
    with TestClient(app) as other:
        login(other, "traveler", PASSWORD)
        changed = client.post("/api/auth/change-password", headers=csrf(session), json={"current_password": PASSWORD, "new_password": "New-Strong-Password-43"})
        assert changed.status_code == 200
        assert client.cookies.get(COOKIE_NAME) != old_token
        assert changed.json()["csrf_token"] != session["csrf_token"]
        assert client.get("/api/auth/me").status_code == 200
        assert other.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "traveler", "password": PASSWORD}).status_code == 401
    assert login(client, "traveler", "New-Strong-Password-43")["user"]["role"] == "player"


def test_roles_disabled_and_version_revoke_sessions_immediately(setup):
    app, client, _ = setup
    player = register(client)
    assert client.get("/creator").status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    with TestClient(app) as admin_client:
        admin = login(admin_client)
        url = "/api/admin/users/" + player["user"]["id"]
        promoted = admin_client.patch(url, headers=csrf(admin), json={"expected_version": 1, "role": "creator"})
        assert promoted.status_code == 200 and promoted.json()["version"] == 2
        assert client.get("/api/auth/me").status_code == 401
        login(client, "traveler", PASSWORD)
        assert client.get("/creator").status_code == 200
        assert client.get("/api/admin/users").status_code == 403
        assert admin_client.patch(url, headers=csrf(admin), json={"expected_version": 1, "disabled": True}).status_code == 409
        assert admin_client.patch(url, headers=csrf(admin), json={"expected_version": 2, "disabled": True}).status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/login", json={"username": "traveler", "password": PASSWORD}).status_code == 401
        assert admin_client.patch(url, headers=csrf(admin), json={"expected_version": 3, "disabled": False}).status_code == 200
        assert login(client, "traveler", PASSWORD)["user"]["role"] == "creator"


def test_last_admin_protection(setup):
    _, client, _ = setup
    admin = login(client)
    url = "/api/admin/users/" + admin["user"]["id"]
    for mutation in ({"role": "player"}, {"disabled": True}):
        assert client.patch(url, headers=csrf(admin), json={"expected_version": 1, **mutation}).status_code == 409
    assert client.get("/api/auth/me").json()["user"]["role"] == "admin"


def test_reset_password_forces_change_and_blocks_rest_of_app(setup):
    app, client, _ = setup
    player = register(client)
    with TestClient(app) as admin_client:
        admin = login(admin_client)
        reset = admin_client.post("/api/admin/users/" + player["user"]["id"] + "/reset-password", headers=csrf(admin), json={"expected_version": 1, "new_password": "Temporary-Password-45"})
        assert reset.status_code == 200 and reset.json()["must_change_password"]
    assert client.get("/api/auth/me").status_code == 401
    temporary = login(client, "traveler", "Temporary-Password-45")
    assert temporary["user"]["must_change_password"]
    assert client.post("/protected", headers=csrf(temporary)).status_code == 403
    assert client.get("/creator").status_code == 403
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    changed = client.post("/api/auth/change-password", headers=csrf(temporary), json={"current_password": "Temporary-Password-45", "new_password": "Personal-New-Password-46"})
    assert changed.status_code == 200 and not changed.json()["user"]["must_change_password"]
    assert client.post("/protected", headers=csrf(changed.json())).status_code == 200


def test_admin_pagination_filters_and_secret_free_audit(setup):
    _, client, _ = setup
    register(client, "alpha")
    register(client, "beta")
    admin = login(client)
    page = client.get("/api/admin/users?page=2&page_size=1&role=player").json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["page"] == 2
    assert client.get("/api/admin/users?q=alpha").json()["total"] == 1
    assert client.get("/api/admin/users?page_size=1000").status_code == 422
    events = client.get("/api/admin/audit?page_size=100").json()
    assert any(row["action"] == "bootstrap_admin" for row in events["items"])
    serialized = json.dumps(events)
    for secret in (PASSWORD, ADMIN_PASSWORD, admin["csrf_token"], client.cookies.get(COOKIE_NAME), "password_hash", "scrypt$"):
        assert secret not in serialized
    assert "password_hash" not in json.dumps(page)


def test_hash_salt_and_legacy_verification():
    first, second = accounts.hash_password(PASSWORD), accounts.hash_password(PASSWORD)
    assert first != second and accounts.verify_password(PASSWORD, first)
    assert not accounts.verify_password("incorrect", first)
    salt = bytes(range(16))
    digest = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    legacy = "scrypt$16384$8$1$" + salt.hex() + "$" + digest.hex()
    assert accounts.verify_password(PASSWORD, legacy)
    assert not accounts.verify_password(PASSWORD, legacy.replace("16384", "1073741824"))


def test_login_throttle_precedes_expensive_hash(setup, monkeypatch):
    _, client, store = setup
    called = []
    monkeypatch.setattr(accounts, "verify_password", lambda *args: called.append(True) or False)
    for _ in range(12):
        assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"}).status_code == 429
    assert len(called) == 12


def test_websocket_same_origin_and_session_auth(setup):
    _, client, _ = setup
    user = register(client)
    with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["id"] == user["user"]["id"]
    for origin in ("https://evil.invalid", "https://testserver"):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws", headers={"Origin": origin}) as ws:
                ws.receive_json()


def test_admin_reset_inflight_revocation_prevents_write(setup, monkeypatch):
    app, _, store = setup
    original_hash = accounts.hash_password
    reached, release = threading.Event(), threading.Event()
    def slow_hash(password):
        reached.set()
        release.wait(timeout=5)
        return original_hash(password)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            signed = (await client.post("/api/auth/login", json={"username": "owner", "password": ADMIN_PASSWORD})).json()
            user = signed["user"]
            monkeypatch.setattr(accounts, "hash_password", slow_hash)
            task = asyncio.create_task(client.post(f"/api/admin/users/{user['id']}/reset-password", headers=csrf(signed), json={"expected_version": user["version"], "new_password": "Unexpected-Password-42"}))
            assert await asyncio.to_thread(reached.wait, 2)
            assert (await client.post("/api/auth/logout-all", headers=csrf(signed))).status_code == 200
            release.set()
            assert (await task).status_code == 401
            with store.connect() as db:
                row = db.execute("SELECT * FROM accounts WHERE id=?", (user["id"],)).fetchone()
                assert row["version"] == user["version"] and not row["must_change_password"]
    asyncio.run(run())


def test_change_password_inflight_revocation_cannot_create_new_session(setup, monkeypatch):
    app, _, store = setup
    original_hash = accounts.hash_password
    reached, release = threading.Event(), threading.Event()
    def slow_hash(password):
        reached.set()
        release.wait(timeout=5)
        return original_hash(password)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            signed = (await client.post("/api/auth/login", json={"username": "owner", "password": ADMIN_PASSWORD})).json()
            monkeypatch.setattr(accounts, "hash_password", slow_hash)
            task = asyncio.create_task(client.post("/api/auth/change-password", headers=csrf(signed), json={"current_password": ADMIN_PASSWORD, "new_password": "Unexpected-Password-42"}))
            assert await asyncio.to_thread(reached.wait, 2)
            assert (await client.post("/api/auth/logout-all", headers=csrf(signed))).status_code == 200
            release.set()
            assert (await task).status_code == 401
            with store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM account_sessions").fetchone()[0] == 0
    asyncio.run(run())


def test_two_admin_concurrent_demotion_preserves_one(setup):
    app, client, store = setup
    second = register(client, "second-admin")
    owner = login(client)
    promoted = client.patch("/api/admin/users/" + second["user"]["id"], headers=csrf(owner), json={"expected_version": 1, "role": "admin"}).json()
    with TestClient(app) as other:
        second_session = login(other, "second-admin", PASSWORD)
        def demote(pair):
            browser, session, version = pair
            return browser.patch("/api/admin/users/" + session["user"]["id"], headers=csrf(session), json={"expected_version": version, "role": "player"}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(demote, [(client, owner, owner["user"]["version"]), (other, second_session, promoted["version"])]))
        assert sorted(statuses) == [200, 409]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND disabled=0").fetchone()[0] == 1


def test_production_validation_errors_do_not_echo_passwords(tmp_path, monkeypatch):
    from backend.app import create_app
    monkeypatch.delenv("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    app = create_app(str(tmp_path / "redacted.sqlite3"))
    cases = [
        ("/api/auth/register", {"username": "valid-user", "password": "LEAK123"}),
        ("/api/auth/change-password", {"current_password": "SECRET-CURRENT", "new_password": "LEAK123"}),
        ("/api/admin/users/unknown/reset-password", {"expected_version": 1, "new_password": "LEAK123"}),
    ]
    with TestClient(app) as client:
        for path, body in cases:
            response = client.post(path, json=body)
            assert response.status_code == 422
            assert "LEAK123" not in response.text and "SECRET-CURRENT" not in response.text
            assert "input" not in response.text and "ctx" not in response.text
