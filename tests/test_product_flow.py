"""Author -> publish -> frozen room -> rules -> ending, across module boundaries."""
import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXBOUND_ADMIN_TOKEN", "test-author-secret")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    app = create_app(str(tmp_path / "product.db"))
    with TestClient(app) as client:
        yield app, client, {"Authorization": "Bearer test-author-secret"}


def publish(client, admin, kind, data):
    item = client.post("/api/studio/items", headers=admin, json={"kind": kind, "data": data})
    assert item.status_code == 201, item.text
    response = client.post(f"/api/studio/items/{data['id']}/publish", headers=admin,
                           json={"expected_revision": item.json()["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def room(client, **kwargs):
    response = client.post("/api/rooms", json={"starting_level": 1, "player_name": "旅人", "character_id": "fighter", **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def command(client, session, kind, payload=None):
    headers = {"Authorization": "Bearer " + session["token"]}
    url = "/api/rooms/" + session["room"]["id"]
    current = client.get(url, headers=headers).json()
    return client.post(url + "/commands", headers=headers, json={"command_id": uuid.uuid4().hex,
                        "expected_version": current["version"], "type": kind, "payload": payload or {}})


def test_authored_cards_publish_and_play_with_frozen_versions(setup, monkeypatch):
    app, client, admin = setup
    skill = {"id": "test-strike", "name": "晶刃", "effect": "attack", "ability": "str", "dice": "1d4", "bonus": 1, "uses": 2, "target": "enemy"}
    published_skill = publish(client, admin, "skill", skill)
    publish(client, admin, "monster", {"id": "test-wisp", "name": "晶屑", "hp": 1, "ac": 5, "damage_dice": "1d4"})
    book = {"id": "test-book", "name": "晶洞岔路", "entry_node_id": "gate", "skill_ids": ["test-strike"], "monster_ids": ["test-wisp"], "nodes": [
        {"id": "gate", "title": "晶洞", "text": "两道门扉。", "actions": [{"id": "enter", "label": "进入守卫室", "next_node_id": "battle"}, {"id": "leave", "label": "沿海岸离开", "next_node_id": "end"}]},
        {"id": "battle", "title": "守卫室", "text": "晶屑从地面升起。", "monster_ids": ["test-wisp"], "actions": [{"id": "finish", "label": "走向黎明", "next_node_id": "end"}]},
        {"id": "end", "title": "隐藏的结局", "text": "不可提前公开的秘密尾声", "ending": True}]}
    published_book = publish(client, admin, "scenario", book)
    session = room(client, scenario_id="test-book")
    assert "不可提前公开" not in str(session)
    assert "campaign_package" not in session["room"]
    changed = copy.deepcopy(published_skill["draft"])
    changed["dice"] = "1d12"
    edit = client.put("/api/studio/items/test-strike", headers=admin, json={"expected_revision": published_skill["revision"], "data": changed}).json()
    assert client.post("/api/studio/items/test-strike/publish", headers=admin, json={"expected_revision": edit["revision"]}).status_code == 200
    assert command(client, session, "start").status_code == 200
    state = app.state.store.get(session["room"]["id"])
    assert state["campaign"]["package"]["skills"]["test-strike"]["dice"] == "1d4"
    # Deterministic highest dice: player initiative wins, card attack kills the 1HP enemy.
    monkeypatch.setattr("backend.rules.secrets.randbelow", lambda sides: sides - 1)
    fight = command(client, session, "action", {"action_id": "node:enter"}).json()["room"]
    target = fight["combat"]["enemies"][0]["id"]
    attack = command(client, session, "action", {"action_id": "skill:test-strike", "target_id": target})
    assert attack.status_code == 200, attack.text
    result = attack.json()["room"]
    assert result["combat"]["enemies"][0]["hp"] == 0
    roll = [e["roll"] for e in result["events"] if e.get("roll", {}).get("kind") == "attack"][-1]
    assert roll["damage_dice"] == [4, 4]  # old frozen d4, not new d12
    assert client.post("/api/studio/items/test-book/archive", headers=admin, json={"expected_revision": published_book["revision"]}).status_code == 200
    assert client.post("/api/rooms", json={"starting_level": 1, "player_name": "新人", "character_id": "fighter", "scenario_id": "test-book"}).status_code != 201
    end = command(client, session, "action", {"action_id": "node:finish"}).json()["room"]
    assert end["status"] == "finished" and end["scene"]["id"] == "end"


def test_freeform_authoring_is_host_only_and_does_not_change_rules(setup):
    app, client, _ = setup
    host = room(client, scenario_id="book-last-lantern", interaction_mode="freeform")
    guest = client.post("/api/rooms/join", json={"invite_code": host["invite_code"], "player_name": "同伴", "character_id": "rogue"}).json()
    before = command(client, host, "start").json()["room"]
    patch = {"title": "共同写下的新标题", "text": "潮汐暂时安静下来。", "objective": "观察周围"}
    assert command(client, guest, "scene_edit", patch).status_code == 403
    edited = command(client, host, "scene_edit", patch).json()["room"]
    assert edited["party"] == before["party"]
    assert edited["available_actions"] == before["available_actions"]
    assert edited["scene"]["text"] == patch["text"]
    assert command(client, host, "scene_edit", {**patch, "hp": 999}).status_code == 422
    assert command(client, host, "narrate", {"text": "我举起手灯。"}).json()["room"]["events"][-1]["kind"] == "intent"
    assert command(client, guest, "set_interaction", {"mode": "assisted"}).status_code == 403
    assert command(client, host, "set_interaction", {"mode": "guided"}).status_code == 200
    assert command(client, host, "scene_edit", patch).status_code == 409


def test_assisted_mode_proposes_but_never_executes_action(setup):
    app, client, _ = setup
    app.state.dm.configured = True
    async def narrator(scene, intent, recent, actions):
        return "可以试着解读石碑。", "llm", actions[0]["id"]
    app.state.dm.narrate = narrator
    session = room(client, scenario_id="book-last-lantern", interaction_mode="assisted")
    started = command(client, session, "start").json()["room"]
    assert started["scene"]["id"] == "dock"
    assert started["events"][-1]["suggested_action_id"].startswith("node:")
    assert not any(e.get("roll") for e in started["events"])
    assert started["party"][0]["hp"] == started["party"][0]["max_hp"]
