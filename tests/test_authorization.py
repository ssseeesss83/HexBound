"""Exercise account/studio authorization in the assembled production app."""
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD", "Owner-Password-12345")
    monkeypatch.setenv("HEXBOUND_ADMIN_TOKEN", "old-shared-secret")
    monkeypatch.setenv("HEXBOUND_LEGACY_ADMIN_TOKEN", "0")
    monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "0")
    monkeypatch.setenv("HEXBOUND_ALLOW_REGISTRATION", "1")
    app = create_app(str(tmp_path / "authorization.sqlite3"))
    with TestClient(app) as player, TestClient(app) as admin:
        signed = player.post("/api/auth/register", json={"username": "traveler", "password": "Player-Password-12345"}).json()
        owner = admin.post("/api/auth/login", json={"username": "owner", "password": "Owner-Password-12345"}).json()
        yield app, player, admin, signed, owner


def test_shared_secret_cannot_bypass_roles_or_secure_defaults(setup, monkeypatch):
    app, player, _, _, _ = setup
    bearer = {"Authorization": "Bearer old-shared-secret"}
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/studio/items", headers=bearer).status_code == 401
    assert player.get("/api/studio/items", headers=bearer).status_code == 403
    monkeypatch.setenv("HEXBOUND_LEGACY_ADMIN_TOKEN", "1")
    # Even explicit legacy mode must not override a signed-in player's role.
    assert player.get("/api/studio/items", headers=bearer).status_code == 403


def test_creator_can_write_with_csrf_but_cannot_administer_users(setup):
    _, player, admin, signed, owner = setup
    promoted = admin.patch("/api/admin/users/" + signed["user"]["id"], headers={"X-CSRF-Token": owner["csrf_token"]}, json={"expected_version": signed["user"]["version"], "role": "creator"})
    assert promoted.status_code == 200
    assert player.get("/api/auth/me").status_code == 401
    signed = player.post("/api/auth/login", json={"username": "traveler", "password": "Player-Password-12345"}).json()
    assert player.get("/api/admin/users").status_code == 403
    assert player.get("/api/studio/items").status_code == 200
    card = {"kind": "skill", "data": {"id": "account-check", "name": "账号创作的检定", "effect": "check", "ability": "wis", "target": "scene", "dc": 12}}
    assert player.post("/api/studio/items", json=card).status_code == 403
    saved = player.post("/api/studio/items", headers={"X-CSRF-Token": signed["csrf_token"]}, json=card)
    assert saved.status_code == 201, saved.text
    disabled = admin.patch("/api/admin/users/" + signed["user"]["id"], headers={"X-CSRF-Token": owner["csrf_token"]}, json={"expected_version": promoted.json()["version"], "disabled": True})
    assert disabled.status_code == 200
    assert player.get("/api/studio/items").status_code == 401
