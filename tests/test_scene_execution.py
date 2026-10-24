"""Two server-seeded scenes through real authenticated actions; no split UI."""
from copy import deepcopy
import asyncio
import uuid
import httpx

from backend import scene_storage as scenes, rules
from test_core_integration import env, room, cmd


def setup_scenes(env):
    a, b, store, _ = env
    created = room(a).json()
    rid = created["room"]["id"]
    joined = b.post("/api/rooms/join", json={"invite_code": created["invite_code"], "player_name": "Side player", "character_id": "fighter"}).json()
    assert cmd(a, rid, "start")[0].status_code == 200
    state = store.get(rid)
    previous = state["version"]
    canonical = scenes.pack(state)
    secondary = deepcopy(canonical["scene_instances"][scenes.MAIN_SCENE])
    secondary.update(id="side", channel_id="side")
    secondary["local"].update(scene={"id": "side-site", "title": "SIDE_SECRET", "text": "SIDE_SECRET"},
                               scene_id="side-site", action_revision=7, completed=False)
    canonical["scene_instances"]["side"] = secondary
    side_id = joined["member_id"]
    canonical["member_contexts"][side_id] = {"scene_instance_id": "side", "epoch": 2}
    canonical["text_scope"]["channels"]["side"] = {"id": "side", "name": "Side group"}
    canonical["text_scope"]["members"][side_id].update(channel="side", epoch=2, seq=0)
    canonical["version"] += 1
    store.save(scenes.unpack(canonical), previous)
    for sid in (scenes.MAIN_SCENE, "side"):
        state = scenes.for_scene(store.get(rid), sid)
        previous = state["version"]
        rules.start_combat(state)
        actor = state["members"][0]["id"]
        combat = state["combat"]
        combat.update(order=[actor, "enemy"], index=0, turn_actor_id=actor, action_used=False)
        combat["enemy"].update(hp=100, max_hp=100, ac=1, name="SIDE_SECRET" if sid == "side" else "Main enemy")
        combat["enemies"] = [combat["enemy"]]
        state["version"] += 1
        store.save(state, previous)
    return a, b, store, rid, created["member_id"], side_id


def send(client, rid, frame, kind="action", payload=None, command_id=None):
    """Select and explicitly confirm scene actions; raw failures remain visible."""
    response = client.post(f"/api/rooms/{rid}/commands", json={
        "command_id": command_id or uuid.uuid4().hex, "type": kind, "payload": payload or {"action_id": "attack", "target_id": "enemy"},
        "expected_version": frame["version"], "expected_action_revision": frame["action_revision"],
        "expected_scene_instance_id": frame["scene_instance_id"], "expected_membership_epoch": frame["membership_epoch"]})
    if kind == 'action' and response.status_code == 200 and not response.json().get('replayed'):
        result = response.json()['room']
        proposal = result['director_proposals'][0]
        return send(client, rid, result, 'director_resolve', {'proposal_id':proposal['id']})
    return response


def test_independent_combat_actions_views_and_history(env, monkeypatch):
    monkeypatch.setattr(rules.secrets, "randbelow", lambda n: min(6, n - 1))
    a, b, store, rid, host, side = setup_scenes(env)
    first = a.get(f"/api/rooms/{rid}").json()
    second = b.get(f"/api/rooms/{rid}").json()
    assert [member["id"] for member in first["party"]] == [host]
    assert [member["id"] for member in second["party"]] == [side]
    assert "SIDE_SECRET" not in str(first)
    assert a.get(f"/api/rooms/{rid}/characters/{side}").status_code == 404
    before_side = deepcopy(scenes.for_scene(store.get(rid), "side")["combat"])
    assert send(a, rid, first).status_code == 200
    assert scenes.for_scene(store.get(rid), "side")["combat"] == before_side
    invalid = send(b, rid, second, payload={"action_id": "heal", "target_id": host})
    assert invalid.status_code == 422
    # The first scene changed storage version, but the second scene's action is valid.
    result = send(b, rid, second)
    assert result.status_code == 200, result.text
    assert result.json()["room"]["combat"]["enemies"][0]["hp"] < 100
    assert "SIDE_SECRET" not in a.get(f"/api/rooms/{rid}/events").text


def test_rewards_time_and_completion_only_affect_scene_participants(env, monkeypatch):
    monkeypatch.setattr(rules.secrets, "randbelow", lambda n: min(6, n - 1))
    a, b, store, rid, host, side = setup_scenes(env)
    current = scenes.for_scene(store.get(rid), scenes.MAIN_SCENE)
    previous = current["version"]
    current["combat"]["enemy"]["hp"] = 1
    current["combat"]["enemies"] = [current["combat"]["enemy"]]
    current["version"] += 1
    store.save(current, previous)
    frame = a.get(f"/api/rooms/{rid}").json()
    receipt = uuid.uuid4().hex
    response = send(a, rid, frame, command_id=receipt)
    assert response.status_code == 200, response.text
    state = store.get(rid)
    members = {member["id"]: member for member in state["members"]}
    assert members[host]["character"]["xp"] == 150
    assert members[side]["character"]["xp"] == 0
    assert scenes.for_scene(state, "side")["combat"]["active"]
    assert send(a, rid, frame, command_id=receipt).json()["replayed"]
    assert len(store.get(rid)["reward_ledger"]) == 2
    frame = a.get(f"/api/rooms/{rid}").json()
    assert send(a, rid, frame, payload={"action_id": "advance"}).status_code == 200
    assert scenes.for_scene(store.get(rid), scenes.MAIN_SCENE)["progression"]["world_minutes"] == 60
    assert scenes.for_scene(store.get(rid), "side")["progression"]["world_minutes"] == 0
    current = scenes.for_scene(store.get(rid), scenes.MAIN_SCENE)
    previous = current["version"]
    current.update(completed=True, status="finished", ending="main ending")
    current["version"] += 1
    store.save(current, previous)
    assert store.get(rid)["status"] == "playing"
    assert b.get(f"/api/rooms/{rid}").json()["combat"]["active"]


def test_stale_scene_binding_and_foreign_chat_channel_are_rejected(env):
    a, b, _, rid, _, _ = setup_scenes(env)
    frame = b.get(f"/api/rooms/{rid}").json()
    forged = {**frame, "scene_instance_id": scenes.MAIN_SCENE}
    assert send(b, rid, forged, "chat", {"text": "must not enter a different scene"}).status_code == 409
    forged = {**frame, "membership_epoch": 1}
    assert send(b, rid, forged).status_code == 409


def test_other_scene_action_does_not_discard_pending_intent_or_receive_its_text(env, monkeypatch):
    a, b, _, rid, _, _ = setup_scenes(env)
    async def run():
        reached, release = asyncio.Event(), asyncio.Event()
        from backend import director
        import json
        original = director.propose
        class Model:
            configured = True
            async def _complete(self, *args, **kwargs):
                return json.dumps({"kind":"dialogue", "label":"观察", "text":"MAIN_ONLY_DM_RESULT"})
        async def slow(dm, state, actor, intent, *args, **kwargs):
            reached.set()
            await release.wait()
            return await original(Model(), state, actor, intent, *args, **kwargs)
        monkeypatch.setattr(director, 'propose', slow)
        main = a.get(f"/api/rooms/{rid}").json()
        side = b.get(f"/api/rooms/{rid}").json()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a.app), base_url="http://testserver",
                                     cookies=a.cookies, headers={"X-CSRF-Token": a.headers["X-CSRF-Token"]}) as client:
            body = {"command_id": uuid.uuid4().hex, "type": "narrate", "payload": {"text": "观察眼前场景"},
                    "expected_version": main["version"], "expected_action_revision": main["action_revision"],
                    "expected_scene_instance_id": main["scene_instance_id"], "expected_membership_epoch": main["membership_epoch"]}
            task = asyncio.create_task(client.post(f"/api/rooms/{rid}/commands", json=body))
            await asyncio.wait_for(reached.wait(), 2)
            reply = send(b, rid, side)
            assert reply.status_code == 200, reply.text
            release.set()
            response = await asyncio.wait_for(task, 3)
            assert response.status_code == 200, response.text
            assert "MAIN_ONLY_DM_RESULT" in response.text
        assert "MAIN_ONLY_DM_RESULT" not in b.get(f"/api/rooms/{rid}").text
    asyncio.run(run())


def test_proposal_fingerprint_ignores_unrelated_scene_usage(env):
    from backend.director import _fingerprint
    _, _, store, rid, host, side = setup_scenes(env)
    state = scenes.for_scene(store.get(rid), scenes.MAIN_SCENE)
    state["campaign"] = {"package": {"id": "frozen"}, "node_id": "main", "visited": ["main"],
                         "spent": {host: {"card": 1}, side: {"card": 1}}, "cleared": []}
    original = _fingerprint(state)
    state["campaign"]["spent"][side]["card"] = 2
    state["campaign"]["cleared"].append("other-location")
    assert _fingerprint(state) == original
    state["campaign"]["spent"][host]["card"] = 2
    assert _fingerprint(state) != original
