"""Text-scope foundation: no voice and no split-scene runtime claim."""
from copy import deepcopy
import json

import pytest

from backend import session_scope as s
from backend.store import Store


def room():
    return s.initialize({"id": "room", "members": [{"id": "host"}, {"id": "other"}],
                         "events": [{"id": 1, "text": "old shared fact"}]})


def append(state, text, audience=None):
    event = {"id": len(state["events"]) + 1, "text": text, "kind": "chat"}
    s.stamp_event(state, event, audience=audience)
    state["events"].append(event)
    return event


def test_private_event_not_visible_to_host_or_common_dm_memory():
    state = room()
    append(state, "a private fact", {"other"})
    append(state, "another shared fact")
    host = s.history_page(state, "host")
    other = s.history_page(state, "other")
    assert [row["text"] for row in host["events"]] == ["old shared fact", "another shared fact"]
    assert [row["id"] for row in host["events"]] == [1, 2]
    assert host["last_event_seq"] == 2 and other["last_event_seq"] == 3
    assert "a private fact" not in json.dumps(s.common_memory(state, {"host", "other"}))
    assert "a private fact" in json.dumps(s.common_memory(state, {"other"}))
    assert "_audience" not in json.dumps(host)


def test_join_does_not_grant_previous_history_and_migration_is_idempotent():
    state = room()
    before = deepcopy(state)
    assert s.initialize(state) == before
    state["members"].append({"id": "new"})
    s.add_member(state, "new")
    assert s.visible_events(state, "new") == []
    append(state, "after joining")
    assert [row["text"] for row in s.visible_events(state, "new")] == ["after joining"]
    assert s.visible_events(state, "new")[0]["id"] == 1
    with pytest.raises(ValueError, match="immutable"):
        s.stamp_event(state, state["events"][0])


def test_cursor_is_bound_to_viewer_room_epoch_and_channel():
    state = room()
    cursor = s.history_page(state, "host")["cursor"]
    assert s.read_cursor(state, "host", cursor) == 1
    for other, viewer, token in ((state, "other", cursor), (room(), "host", cursor),
                                  (state, "host", cursor[:-2] + "AA")):
        with pytest.raises(ValueError, match="cursor"):
            s.read_cursor(other, viewer, token)
    state["text_scope"]["members"]["host"]["epoch"] += 1
    with pytest.raises(ValueError, match="cursor"):
        s.read_cursor(state, "host", cursor)
    assert not s.visible_events(state, "host")


def test_hidden_events_cannot_change_nonrecipient_history_response():
    state = room()
    baseline = s.history_page(state, "host")
    append(state, "hidden event", {"other"})
    assert s.history_page(state, "host") == baseline
    with pytest.raises(ValueError, match="membership"):
        s.history_page(state, "stranger")


def test_channel_and_audience_validation():
    state = room()
    with pytest.raises(ValueError, match="audience"):
        append(state, "invalid", {"stranger"})
    with pytest.raises(ValueError, match="channel"):
        s.stamp_event(state, {}, channel="absent")
    state["members"] = [{"id": "host"}]
    item = append(state, "after removal")
    assert "other" not in item["_audience"]


def test_storage_migrates_old_room_without_changing_action_state(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    store = Store(path)
    state = {"id": "old", "invite_code": "OLD", "version": 4, "members": [{"id": "host"}],
             "events": [{"id": 1, "text": "original"}], "combat": {"round": 3, "hp": 2}}
    with store.connect() as db:
        db.execute("INSERT INTO rooms VALUES (?,?,?,?)", ("old", "OLD", 4, json.dumps(state)))
    reopened = Store(path)
    migrated = reopened.get("old")
    assert migrated["version"] == 4 and migrated["combat"] == state["combat"]
    assert s.history_page(migrated, "host")["events"][0]["text"] == "original"
    assert Store(path).get("old") == migrated
