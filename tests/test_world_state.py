"""Server-only authority contract, before runtime hooks or public group APIs."""
from copy import deepcopy
import json
import sqlite3
import pytest

from backend import session_scope as scope, world_state as world


def room():
    state = scope.initialize({"status": "playing", "members": [{"id": "a"}, {"id": "b"}], "events": [],
        "member_contexts": {"a": {"scene_instance_id": "one", "epoch": 1}, "b": {"scene_instance_id": "two", "epoch": 1}},
        "scene_instances": {sid: {"id": sid, "place_id": "hall", "channel_id": channel,
            "local": {"action_revision": 0, "progression_clock": {"world_minutes": 0}, "combat": None}}
            for sid, channel in (("one", "party-main"), ("two", "side"))}})
    state["text_scope"]["channels"]["side"] = {"id": "side"}
    state["text_scope"]["members"]["b"]["channel"] = "side"
    world.add_place(state, "hall")
    world.add_place(state, "yard")
    world.add_entity(state, "door", "hall", "object", {"hp": 12, "burning": False}, {"object_id": "door"})
    world.add_entity(state, "guard-1", "hall", "creature", {"hp": 20}, {"monster_id": "guard", "slot": 1})
    world.add_entity(state, "guard-2", "hall", "creature", {"hp": 20}, {"monster_id": "guard", "slot": 2})
    return state


def test_shared_entity_updates_are_versioned_and_partial_writes_never_commit():
    state = room()
    world.write_entities(state, "a", {"door": {"hp": 4, "burning": True}}, {"door": 0})
    assert state["world_entities"]["door"]["state"] == {"hp": 4, "burning": True}
    assert state["world_entities"]["door"]["revision"] == 1
    before = deepcopy(state)
    with pytest.raises(world.WorldConflict, match="版本"):
        world.write_entities(state, "b", {"guard-1": {"hp": 1}, "door": {"hp": 0}}, {"guard-1": 0, "door": 0})
    assert state == before
    # Two guards using the same template still have separate physical identity.
    assert state["world_entities"]["guard-2"]["state"]["hp"] == 20


def test_enter_read_set_is_checked_before_any_rules_or_resource_change(monkeypatch):
    from backend import rules
    monkeypatch.setattr(rules, "check", lambda *a, **k: pytest.fail("must not roll"))
    state = room()
    plan = world.prepare_enter(state, "a", "yard")
    world.add_entity(state, "yard-object", "yard", "object", {"hp": 3}, {"object_id": "crate"})
    before = deepcopy(state)
    with pytest.raises(world.WorldConflict, match="过期"):
        world.commit_enter(state, plan)
    assert state == before
    world.commit_enter(state, world.prepare_enter(state, "a", "yard"))
    assert state["scene_instances"]["one"]["place_id"] == "yard"


def test_unique_encounter_claim_replay_release_and_dead_entity_do_not_respawn():
    state = room()
    assert not world.claim_encounter(state, "a", ["guard-1"], "encounter-one", {"guard-1": 0})["replayed"]
    before = deepcopy(state)
    with pytest.raises(world.WorldConflict, match="遭遇"):
        world.claim_encounter(state, "b", ["guard-1"], "encounter-two", {"guard-1": 1})
    assert state == before
    assert world.claim_encounter(state, "a", ["guard-1"], "encounter-one", {"guard-1": 0})["replayed"]
    assert state == before
    with pytest.raises(world.WorldConflict):
        world.claim_encounter(state, "a", ["guard-2"], "encounter-one", {"guard-2": 0})
    world.write_entities(state, "a", {"guard-1": {"hp": 0}}, {"guard-1": 1}, encounter_id="encounter-one")
    world.release_encounter(state, "a", "encounter-one")
    assert world.claim_encounter(state, "a", ["guard-1"], "encounter-one", {"guard-1": 0}) == {"replayed": True, "encounter_id": "encounter-one", "active": False}
    with pytest.raises(world.WorldConflict, match="死亡"):
        world.claim_encounter(state, "a", ["guard-1"], "encounter-new", {"guard-1": 3})


@pytest.mark.parametrize("failure", ["place", "time", "combat", "choice", "reaction", "entity"])
def test_unsafe_merge_is_rejected_without_mutation(failure):
    state = room()
    second = state["scene_instances"]["two"]
    if failure == "place":
        second["place_id"] = "yard"
    elif failure == "time":
        second["local"]["progression_clock"]["world_minutes"] = 1
    elif failure == "combat":
        second["local"]["combat"] = {"active": True}
    elif failure == "choice":
        second["local"]["pending_transition"] = {"status": "waiting"}
    elif failure == "reaction":
        second["local"]["reaction_windows"] = [{"id": "window"}]
    else:
        world.claim_encounter(state, "a", ["guard-1"], "encounter-one", {"guard-1": 0})
    before = deepcopy(state)
    with pytest.raises(world.WorldConflict):
        world.prepare_merge(state, "one", "two")
    assert state == before


def test_merge_updates_both_epochs_cancels_requests_and_is_idempotent():
    state = room()
    for scene in state["scene_instances"].values():
        scene["local"].update(dm_pending="old-request", director={"proposals": {"actor": {"id": "old"}}, "memory": [{"secret": True}]})
    old_cursor = scope.history_cursor(state, "a", 0)
    plan = world.prepare_merge(state, "one", "two")
    result = world.commit_merge(state, plan, "merge-command")
    assert result["members"] == ["a"] and not result["replayed"]
    assert state["member_contexts"]["a"] == {"scene_instance_id": "two", "epoch": 2}
    assert state["text_scope"]["members"]["a"]["channel"] == "side"
    assert state["text_scope"]["members"]["a"]["epoch"] == 2
    with pytest.raises(ValueError, match="cursor"):
        scope.read_cursor(state, "a", old_cursor)
    for scene in state["scene_instances"].values():
        assert scene["local"]["dm_pending"] is None and not scene["local"]["director"]["proposals"]
        assert scene["local"]["director"]["memory"] == [{"secret": True}]  # No memory concatenation.
    before = deepcopy(state)
    assert world.commit_merge(state, plan, "merge-command")["replayed"]
    assert state == before


def test_store_merge_transaction_rolls_back_all_changes_if_receipt_fails(tmp_path):
    from backend.store import Store
    from backend.scene_storage import pack, MAIN_SCENE
    store = Store(str(tmp_path / "merge.sqlite3"))
    state = room()
    state.update(id="room", invite_code="INVITE", version=0, host_id="a")
    state["scene_instances"][MAIN_SCENE] = state["scene_instances"].pop("one")
    state["scene_instances"][MAIN_SCENE]["id"] = MAIN_SCENE
    state["member_contexts"]["a"]["scene_instance_id"] = MAIN_SCENE
    payload = json.dumps(pack(state))
    with store.connect() as db:
        db.execute("INSERT INTO rooms VALUES ('room','INVITE',0,?)", (payload,))
        db.execute("CREATE TRIGGER fail_merge_receipt BEFORE INSERT ON commands BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
    with pytest.raises(world.WorldConflict, match="房主"):
        store.prepare_scene_merge("room", "b", MAIN_SCENE, "two")
    plan = store.prepare_scene_merge("room", "a", MAIN_SCENE, "two")
    with pytest.raises(sqlite3.IntegrityError, match="receipt failed"):
        store.commit_scene_merge("room", "a", plan, "merge-command")
    with store.connect() as db:
        assert db.execute("SELECT state FROM rooms").fetchone()[0] == payload
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_merge_receipt")
    result = store.commit_scene_merge("room", "a", plan, "merge-command")
    assert not result["replayed"]
    after = store.get("room")
    assert after["member_contexts"]["a"]["scene_instance_id"] == "two"
    assert after["version"] == 1 and len(after["events"]) == 1
    assert store.commit_scene_merge("room", "a", plan, "merge-command")["replayed"]
    assert store.get("room") == after
