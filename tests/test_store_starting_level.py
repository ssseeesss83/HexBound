import json

import pytest

from backend.store import Store


def room(id="room", level=3, member=None):
    return {"id": id, "invite_code": id, "version": 1, "status": "lobby", "starting_level": level,
            "members": [member or {"id": "member", "name": "玩家", "character": {"level": 1}}]}


@pytest.mark.parametrize("user_id", [None, "owner"])
@pytest.mark.parametrize("target,ready", [(1, True), (3, False)])
def test_template_binding(tmp_path, user_id, target, ready):
    store = Store(str(tmp_path / "game.db"))
    state = room(level=target)
    store.create(state, "member", "token", user_id)
    member = store.get("room")["members"][0]
    assert member["build_ready"] is ready
    assert member["can_rebuild"] is True
    assert member["character_origin"] == "template"


@pytest.mark.parametrize("level,ready", [(1, False), (3, True)])
def test_existing_hero_uses_canonical_level(tmp_path, level, ready):
    store = Store(str(tmp_path / "game.db"))
    with store.connect() as db:
        db.execute("INSERT INTO heroes VALUES ('hero','owner',1,?,NULL)", (json.dumps({"level": level}),))
    member = {"id": "member", "name": "玩家", "hero_id": "hero", "character": {"level": 20}}
    state = room(member=member)
    store.create(state, "member", "token", "owner")
    bound = store.get("room")["members"][0]
    assert bound["character"]["level"] == level
    assert bound["build_ready"] is ready
    assert bound["can_rebuild"] is False
    assert bound["character_origin"] == "existing"


def test_high_level_rejected_atomically_on_join(tmp_path):
    store = Store(str(tmp_path / "game.db"))
    store.create(room(), "member", "token")
    with store.connect() as db:
        db.execute("INSERT INTO heroes VALUES ('hero','owner',7,?,NULL)", (json.dumps({"level": 4}),))
    before = store.get("room")
    with pytest.raises(ValueError, match="高于"):
        store.join("room", {"id": "new", "name": "玩家", "hero_id": "hero", "character": {"level": 1}}, "newtoken", "owner")
    assert store.get("room") == before
    with store.connect() as db:
        hero = db.execute("SELECT * FROM heroes WHERE id='hero'").fetchone()
        assert hero["active_room_id"] is None and hero["version"] == 7
        assert not db.execute("SELECT 1 FROM members WHERE id='new'").fetchone()


def test_legacy_room_target_is_one(tmp_path):
    store = Store(str(tmp_path / "game.db"))
    state = room()
    state.pop("starting_level")
    store.create(state, "member", "token")
    assert store.get("room")["members"][0]["build_ready"] is True


def test_migration_preserves_legacy_build_metadata(tmp_path, monkeypatch):
    from backend import characters
    monkeypatch.setattr(characters, "migrate_character", lambda character: character)
    store = Store(str(tmp_path / "game.db"))
    state = room()
    state.pop("starting_level")
    member = state["members"][0]
    member.update(build_ready=True, can_rebuild=False, character_origin="custom")
    with store.connect() as db:
        db.execute("INSERT INTO rooms VALUES (?,?,?,?)", ("room", "room", 1, json.dumps(state)))
        db.execute("INSERT INTO members VALUES ('member','room','hash','owner')")
    store.migrate_heroes()
    migrated = store.get("room")["members"][0]
    assert migrated["hero_id"]
    assert migrated["build_ready"] is True
    assert migrated["can_rebuild"] is False
    assert migrated["character_origin"] == "custom"
