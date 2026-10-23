"""Scenario level survives authoring and frozen content publication."""
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.dm import DM
from backend.schemas import parse_card
from backend.store import Store
from backend.studio import FORMAT, compile_scenario, create_studio_router

AUTH = {"Authorization": "Bearer level-test"}


def book(**extra):
    return {"id": "level-book", "name": "等级冒险", "description": "公开摘要", "entry_node_id": "start", "nodes": [
        {"id": "start", "title": "起点", "text": "秘密正文", "actions": [{"id": "go", "label": "前进", "next_node_id": "end"}]},
        {"id": "end", "title": "终点", "text": "结束", "ending": True}], **extra}


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXBOUND_LEGACY_ADMIN_TOKEN", "1")
    monkeypatch.setenv("HEXBOUND_ADMIN_TOKEN", "level-test")
    store = Store(str(tmp_path / "content.sqlite3"))
    app = FastAPI()
    app.include_router(create_studio_router(store, DM()))
    with TestClient(app) as client:
        yield client, store


@pytest.mark.parametrize("value", [0, 21, 2.5, True, "3", None])
def test_invalid_starting_level(value):
    with pytest.raises(ValidationError):
        parse_card("scenario", book(starting_level=value))


@pytest.mark.parametrize("value", [1, 3, 20])
def test_valid_starting_level(value):
    assert parse_card("scenario", book(starting_level=value))["starting_level"] == value


def test_legacy_authoring_defaults_to_three():
    assert parse_card("scenario", book())["starting_level"] == 3


def test_publish_summary_and_frozen_versions(studio):
    client, store = studio
    draft = client.post("/api/studio/items", headers=AUTH, json={"kind": "scenario", "data": book()}).json()
    assert draft["draft"]["starting_level"] == 3
    published = client.post("/api/studio/items/level-book/publish", headers=AUTH, json={"expected_revision": draft["revision"]}).json()
    snapshot = compile_scenario(store, "level-book")
    updated = client.put("/api/studio/items/level-book", headers=AUTH, json={"expected_revision": published["revision"], "data": book(starting_level=7)}).json()
    response = client.post("/api/studio/items/level-book/publish", headers=AUTH, json={"expected_revision": updated["revision"]})
    assert response.status_code == 200, response.text
    assert snapshot["scenario"]["starting_level"] == 3
    assert compile_scenario(store, "level-book")["scenario"]["starting_level"] == 7
    public = client.get("/api/content?kind=scenario").json()["items"]
    assert next(item for item in public if item["id"] == "level-book")["starting_level"] == 7
    assert all("nodes" not in item for item in public)
    assert next(item for item in public if item["id"] == "book-last-lantern")["starting_level"] == 3


def test_import_export_and_invalid_package_atomic(studio):
    client, _ = studio
    package = {"format": FORMAT, "items": [{"kind": "scenario", "data": book(starting_level=20)}]}
    response = client.post("/api/studio/import", headers=AUTH, json={"package": package})
    assert response.status_code == 201, response.text
    exported = client.post("/api/studio/export", headers=AUTH, json={"ids": ["level-book"]}).json()
    assert exported["items"][0]["data"]["starting_level"] == 20
    exported["items"][0]["data"]["id"] = "roundtrip-book"
    response = client.post("/api/studio/import", headers=AUTH, json={"package": exported})
    assert response.status_code == 201 and response.json()["items"][0]["draft"]["starting_level"] == 20
    invalid = copy.deepcopy(package)
    invalid["items"][0]["data"].update(id="invalid-book", starting_level=21)
    assert client.post("/api/studio/import", headers=AUTH, json={"package": invalid}).status_code == 422
    assert client.get("/api/studio/items/invalid-book", headers=AUTH).status_code == 404


def test_legacy_published_summary_fallback_does_not_rewrite_snapshot(studio):
    client, store = studio
    with store.connect() as db:
        row = db.execute("SELECT published_json FROM content_items WHERE id='book-last-lantern'").fetchone()
        old = json.loads(row["published_json"])
        old.pop("starting_level", None)
        db.execute("UPDATE content_items SET published_json=? WHERE id='book-last-lantern'", (json.dumps(old),))
    public = client.get("/api/content?kind=scenario").json()["items"]
    assert public[0]["starting_level"] == 3
    assert "starting_level" not in compile_scenario(store, "book-last-lantern")["scenario"]
