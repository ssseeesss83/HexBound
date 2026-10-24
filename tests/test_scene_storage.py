"""Scene migration preserves fixed rolls and leaves shared data with one owner."""
from copy import deepcopy
import json
from pathlib import Path

from backend import scene_storage as scenes
from backend.store import Store


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/legacy_room_v06.json").read_text(encoding="utf-8"))


def test_full_legacy_fixture_roundtrip_preserves_all_original_fields():
    original = fixture()
    before = deepcopy(original)
    packed = scenes.pack(original)
    assert original == before
    assert all(key not in packed for key in scenes.LOCAL_FIELDS)
    assert "node_id" not in packed["campaign"] and "visited" not in packed["campaign"]
    assert packed["campaign"]["spent"] == original["campaign"]["spent"]
    assert packed["reward_ledger"] == original["reward_ledger"]
    assert "members" not in packed["scene_instances"][scenes.MAIN_SCENE]["local"]
    unpacked = scenes.unpack(packed)
    assert scenes.legacy_shape(unpacked) == original
    assert scenes.pack(unpacked) == packed


def test_replacement_and_removal_in_execution_view_persist_without_resurrecting_state():
    packed = scenes.pack(fixture())
    view = scenes.unpack(packed)
    view["combat"] = {"active": False, "round": 9}
    view.pop("director", None)
    view["campaign"]["node_id"] = "new-node"
    view["members"][0]["character"]["hp"] = 1
    saved = scenes.pack(view)
    assert saved["scene_instances"][scenes.MAIN_SCENE]["local"]["combat"] == view["combat"]
    assert "director" not in scenes.unpack(saved)
    assert saved["members"][0]["character"]["hp"] == 1
    assert saved["scene_instances"][scenes.MAIN_SCENE]["local"]["campaign_cursor"]["node_id"] == "new-node"
    assert packed != saved


def test_store_migrates_in_progress_scene_once_without_entering_or_rolling(tmp_path, monkeypatch):
    from backend import campaign, rules
    def forbidden(*args, **kwargs):
        raise AssertionError("Migration must not enter a scene or roll dice")
    monkeypatch.setattr(campaign, "_enter", forbidden)
    monkeypatch.setattr(campaign, "_start_combat", forbidden)
    monkeypatch.setattr(rules, "check", forbidden)
    path = str(tmp_path / "scene.sqlite3")
    initial = Store(path)
    original = fixture()
    with initial.connect() as db:
        db.execute("INSERT INTO rooms VALUES(?,?,?,?)", (original["id"], original["invite_code"], original["version"], json.dumps(original)))
    migrated = Store(path)
    view = migrated.get(original["id"])
    assert scenes.legacy_shape(view)["combat"] == original["combat"]
    assert view["director"] == original["director"]
    assert view["reward_ledger"] == original["reward_ledger"]
    assert view["members"] == original["members"]
    assert all(row["scene_instance_id"] == scenes.MAIN_SCENE for row in view["member_contexts"].values())
    assert Store(path).get(original["id"]) == view
    with migrated.connect() as db:
        canonical = json.loads(db.execute("SELECT state FROM rooms").fetchone()[0])
        assert "combat" not in canonical and "director" not in canonical
        saved_combat = canonical["scene_instances"][scenes.MAIN_SCENE]["local"]["combat"]
        assert "enemies" not in saved_combat and saved_combat["enemy_refs"]
        assert scenes.legacy_shape(scenes.unpack(canonical))["combat"] == original["combat"]
