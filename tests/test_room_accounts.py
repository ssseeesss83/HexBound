"""Account-owned room seats, migration and live-session authorization."""
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app
from backend.store import Store, token_hash


PASSWORD = "Correct-Horse-Secret-123!"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("HEXBOUND_ALLOW_GUESTS", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    return create_app(str(tmp_path / "accounts-room.sqlite3"))


def register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "display_name": username})
    assert r.status_code in (200, 201), r.text
    # Registration may create the session; logging in also exercises new-device recovery.
    if not client.cookies.get("hexbound_session"):
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    client.headers["X-CSRF-Token"] = me.json()["csrf_token"]
    return me.json()


def create(client):
    response = client.post("/api/rooms", json={"starting_level": 1, "name": "账号冒险", "player_name": "旅人", "character_id": "fighter"})
    assert response.status_code == 201, response.text
    return response.json()


def join(client, invite):
    return client.post("/api/rooms/join", json={"invite_code": invite, "player_name": "同伴", "character_id": "rogue"})


def command(client, room_id, command_type, payload=None):
    room = client.get(f"/api/rooms/{room_id}").json()
    return client.post(f"/api/rooms/{room_id}/commands", json={"command_id": uuid.uuid4().hex, "expected_version": room["version"], "type": command_type, "payload": payload or {}})


def test_secure_default_requires_account(app):
    with TestClient(app) as c:
        assert c.get("/api/catalog").json()["auth"]["allow_guests"] is False
        assert c.post("/api/rooms", json={"starting_level": 1, "player_name": "旅人", "character_id": "fighter"}).status_code == 401
        assert join(c, "ANYTHING").status_code == 401
        assert c.get("/api/my/rooms").status_code == 401


def test_account_seat_cookie_and_csrf(app):
    with TestClient(app) as c:
        register(c, "player_a")
        session = create(c)
        rid = session["room"]["id"]
        assert session["token"] is None
        assert c.get(f"/api/rooms/{rid}").status_code == 200
        assert command(c, rid, "chat", {"text": "已登录"}).status_code == 200
        csrf = c.headers.pop("X-CSRF-Token")
        assert c.post(f"/api/rooms/{rid}/resume").status_code == 403
        c.headers["X-CSRF-Token"] = csrf
        listing = c.get("/api/my/rooms").json()["items"]
        assert listing[0]["room_id"] == rid
        assert listing[0]["member_id"] == session["member_id"]
        assert listing[0]["player_name"] == "旅人"


def test_cross_device_login_restores_same_member(app):
    with TestClient(app) as first, TestClient(app) as second:
        register(first, "traveler")
        session = create(first)
        rid = session["room"]["id"]
        response = second.post("/api/auth/login", json={"username": "traveler", "password": PASSWORD})
        assert response.status_code == 200, response.text
        second.headers["X-CSRF-Token"] = second.get("/api/auth/me").json()["csrf_token"]
        restored = second.post(f"/api/rooms/{rid}/resume")
        assert restored.status_code == 200, restored.text
        assert restored.json()["member_id"] == session["member_id"]
        assert restored.json()["token"] is None
        assert len(restored.json()["room"]["party"]) == 1


def test_repeated_concurrent_join_does_not_allocate_new_seat(app):
    with TestClient(app) as host, TestClient(app) as player:
        register(host, "roomhost")
        register(player, "oneplayer")
        session = create(host)
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(lambda _: join(player, session["invite_code"]), range(5)))
        assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
        assert len({r.json()["member_id"] for r in responses}) == 1
        assert len(host.get(f"/api/rooms/{session['room']['id']}").json()["party"]) == 2


def test_other_account_cannot_use_room_or_host_commands(app):
    with TestClient(app) as host, TestClient(app) as outsider:
        register(host, "hostowner")
        register(outsider, "outsider")
        session = create(host)
        rid = session["room"]["id"]
        assert outsider.get(f"/api/rooms/{rid}").status_code == 403
        assert outsider.post(f"/api/rooms/{rid}/resume").status_code == 403
        join(outsider, session["invite_code"])
        assert command(outsider, rid, "start").status_code == 403


def test_legacy_claim_once_and_bearer_disabled_after_binding(app, monkeypatch):
    monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "1")
    with TestClient(app) as guest, TestClient(app) as owner, TestClient(app) as thief:
        legacy = create(guest)
        rid = legacy["room"]["id"]
        headers = {"Authorization": "Bearer " + legacy["token"]}
        assert guest.get(f"/api/rooms/{rid}", headers=headers).status_code == 200
        register(owner, "claimowner")
        register(thief, "claimthief")
        monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "0")
        assert guest.get(f"/api/rooms/{rid}", headers=headers).status_code == 401
        claim = owner.post(f"/api/rooms/{rid}/claim", json={"token": legacy["token"]})
        assert claim.status_code == 200, claim.text
        assert claim.json()["member_id"] == legacy["member_id"]
        assert claim.json()["token"] is None
        assert thief.post(f"/api/rooms/{rid}/claim", json={"token": legacy["token"]}).status_code == 409
        assert owner.post(f"/api/rooms/{rid}/claim", json={"token": legacy["token"]}).status_code == 409
        monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "1")
        assert guest.get(f"/api/rooms/{rid}", headers=headers).status_code == 401
        assert thief.get(f"/api/rooms/{rid}", headers=headers).status_code == 403


def test_logout_revokes_websocket_and_http(app):
    with TestClient(app) as c:
        register(c, "socketowner")
        session = create(c)
        rid = session["room"]["id"]
        with c.websocket_connect(f"/api/rooms/{rid}/ws") as ws:
            ws.send_json({"token": None})
            assert ws.receive_json()["type"] == "snapshot"
            response = c.post("/api/auth/logout")
            assert response.status_code == 200, response.text
            ws.send_text("ping")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert c.get(f"/api/rooms/{rid}").status_code == 401


def test_disabled_account_websocket_stops_and_guest_mode_cannot_bypass(app, monkeypatch):
    with TestClient(app) as c:
        account = register(c, "disabledplayer")["user"]
        session = create(c)
        rid = session["room"]["id"]
        with c.websocket_connect(f"/api/rooms/{rid}/ws") as ws:
            ws.send_json({"token": None})
            assert ws.receive_json()["type"] == "snapshot"
            with app.state.store.connect() as db:
                db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (account["id"],))
            ws.send_text("ping")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "1")
        assert c.get(f"/api/rooms/{rid}").status_code in (401, 403)
        assert c.post("/api/rooms", json={"starting_level": 1, "player_name": "降级尝试", "character_id": "fighter"}).status_code in (401, 403)


def test_account_room_survives_app_restart(app):
    with TestClient(app) as c:
        register(c, "persistentplayer")
        session = create(c)
        cookie = c.cookies.get("hexbound_session")
    restored_app = create_app(app.state.store.path)
    with TestClient(restored_app) as c:
        c.cookies.set("hexbound_session", cookie)
        c.headers["X-CSRF-Token"] = c.get("/api/auth/me").json()["csrf_token"]
        response = c.post(f"/api/rooms/{session['room']['id']}/resume")
        assert response.status_code == 200, response.text
        assert response.json()["member_id"] == session["member_id"]


def test_anonymous_schema_migrates_and_unique_account_index(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE rooms(id TEXT PRIMARY KEY,invite_code TEXT UNIQUE,version INTEGER,state TEXT); CREATE TABLE members(id TEXT PRIMARY KEY,room_id TEXT,token_hash TEXT UNIQUE);")
        db.execute("INSERT INTO rooms VALUES ('r','INVITE',0,?)", (json.dumps({"id": "r"}),))
        db.execute("INSERT INTO members VALUES ('m','r',?)", (token_hash("old-token"),))
    store = Store(path)
    assert store.authenticate("r", "old-token") == "m"
    assert store.claim("r", "old-token", "user1") == "m"
    assert store.authenticate("r", "old-token") is None
    assert store.account_member("r", "user1") == "m"
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO members(id,room_id,token_hash,user_id) VALUES('m2','r','other','user1')")
