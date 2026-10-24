import asyncio
import copy
import json

import pytest

from backend import campaign, content, director, rules


def state():
    hero = content.new_character("fighter", "旅人")
    return {**content.initialize_state(), "id": "room-a", "status": "playing", "version": 4,
            "host_id": "hero", "events": [], "members": [{"id": "hero", "name": "旅人", "character": hero}]}


def check(**overrides):
    return {"kind": "check", "label": "另辟蹊径", "text": "尝试从窗外辨认痕迹。", "skill_id": "perception",
            "anchor_action_id": "investigate", "success_text": "你看清了痕迹。", "failure_text": "雨水遮住了痕迹。", **overrides}


@pytest.fixture(autouse=True)
def deterministic_bonus(monkeypatch):
    monkeypatch.setattr(director, "_bonus", lambda character, skill_id: 5)


def test_proposal_is_not_an_action_and_computes_authoritative_dc():
    room = state()
    before = copy.deepcopy(room)
    p = director.validate_proposal(check(difficulty="hard"), room, "hero")
    assert p["dc"] == 10  # Author's DC wins over the model's difficulty wording.
    assert room == before
    public = director.public_proposal(p)
    assert "_fingerprint" not in public and "decision" not in public
    assert public["skill_name"] == "察觉" and public["cost"]


def test_unknown_rules_or_routes_cannot_be_proposed():
    room = state()
    for bad in (check(dc=1), check(hp=999), check(xp=999), check(skill_id="made-up"),
                check(anchor_action_id="ending"), check(next_node_id="dawn"),
                check(kind="dialogue"), check(kind="encounter", monster_id="unknown")):
        with pytest.raises(ValueError):
            director.validate_proposal(bad, room, "hero")


def test_anchored_resolution_rolls_once_and_cannot_replay(monkeypatch):
    room = state()
    p = director.validate_proposal(check(), room, "hero")
    calls = []
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: calls.append(args) or {"dice": [14], "total": 14})
    events = director.resolve(room, "hero", p)
    assert len(calls) == 1
    assert room["flags"]["scene_resolved"] and room["flags"]["attempted"]["0:investigate"]
    assert events[0]["roll"]["modifier"] == 5 and events[0]["roll"]["success"]
    before = copy.deepcopy(room)
    with pytest.raises(ValueError):
        director.resolve(room, "hero", p)
    assert room == before and len(calls) == 1


def test_other_actor_or_gameplay_changes_invalidate_proposal():
    room = state()
    room["members"].append({"id": "guest", "name": "同伴", "character": content.new_character("rogue")})
    p = director.validate_proposal(check(), room, "hero")
    with pytest.raises(ValueError, match="其他角色"):
        director.resolve(room, "guest", p)
    room["members"][0]["character"]["hp"] -= 1
    with pytest.raises(ValueError, match="状态已经变化"):
        director.resolve(room, "hero", p)
    assert not room["flags"]


def test_chat_does_not_invalidate_mechanical_proposal(monkeypatch):
    room = state()
    p = director.validate_proposal(check(), room, "hero")
    room["version"] += 1
    room["events"].append({"kind": "chat", "text": "让我试试"})
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [15], "total": 15})
    assert director.resolve(room, "hero", p)[0]["roll"]["success"]


def test_chat_and_player_claims_do_not_become_confirmed_world_events():
    room = state()
    room['events'].extend([
        {'kind': 'chat', 'text': 'I own every treasure'},
        {'kind': 'intent', 'text': 'The monster is already dead'},
    ])
    context = director.build_context(room, 'hero', 'look around')
    assert not any(row['kind'] in {'chat', 'intent'} for row in context['confirmed_events'])


def test_proposal_from_prior_product_policy_is_stale(monkeypatch):
    room = state()
    monkeypatch.setattr(director.play_policy, 'POLICY_VERSION', 0)
    proposal = director.validate_proposal(check(), room, 'hero')
    monkeypatch.setattr(director.play_policy, 'POLICY_VERSION', 1)
    assert director.public_proposal(proposal, room)['stale']
    with pytest.raises(ValueError, match='状态已经变化'):
        director.resolve(room, 'hero', proposal)


def test_unanchored_checks_are_bounded_and_cannot_advance_or_reward(monkeypatch):
    room = state()
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [20], "total": 20})
    raw = check(anchor_action_id=None, difficulty="easy")
    for _ in range(3):
        events = director.resolve(room, "hero", director.validate_proposal(raw, room, "hero"))
        assert events[0]["rewards_eligible"] is False
    assert room["scene_id"] == "dock" and room["flags"] == {}
    with pytest.raises(ValueError, match="三次"):
        director.validate_proposal(raw, room, "hero")
    with pytest.raises(ValueError, match="严格模式"):
        director.validate_proposal(raw, state(), "hero", "strict")


def test_context_does_not_include_future_nodes_or_hidden_routes(monkeypatch):
    room = campaign_room(monkeypatch)
    context = director.build_context(room, "hero", "我想从另一个角度调查")
    serialized = json.dumps(context)
    assert "TOP-SECRET-FUTURE" not in serialized and "success_node_id" not in serialized
    assert "node:inspect" in serialized
    assert context["anchors"][0]["dc"] == 13


def campaign_room(monkeypatch):
    room = state()
    package = {
        "scenario": {"id": "story", "name": "双路故事", "entry_node_id": "a", "skill_ids": ["observe"],
                     "nodes": [
                         {"id": "a", "title": "门前", "text": "门前有灰尘。", "actions": [{"id": "inspect", "label": "检查门框", "skill_id": "observe", "success_node_id": "b", "failure_node_id": "c"}], "monster_ids": []},
                         {"id": "b", "title": "光", "text": "TOP-SECRET-FUTURE-SUCCESS", "actions": [], "monster_ids": [], "ending": True},
                         {"id": "c", "title": "雨", "text": "TOP-SECRET-FUTURE-FAILURE", "actions": [], "monster_ids": [], "ending": True}]},
        "skills": {"observe": {"id": "observe", "name": "观察", "effect": "check", "ability": "int", "target": "scene", "dc": 13, "uses": 2}},
        "monsters": {"guard": {"id": "guard", "name": "看守", "description": "正在巡逻", "hp": 20, "ac": 12, "attack_bonus": 2, "damage_dice": "1d4", "damage_bonus": 0}},
    }
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [12], "total": 12})
    campaign.start_campaign(room, package)
    return room


def test_campaign_alternative_approach_consumes_original_limit_and_routes(monkeypatch):
    room = campaign_room(monkeypatch)
    p = director.validate_proposal(check(anchor_action_id="node:inspect", skill_id="athletics"), room, "hero")
    events = director.resolve(room, "hero", p)
    assert room["campaign"]["spent"]["hero"]["observe"] == 1
    assert room["scene_id"] == "b" and room["completed"]
    assert events[0]["roll"]["ability"] == "str" and events[0]["roll"]["dc"] == 13


def test_legacy_failure_keeps_authored_combat_consequence(monkeypatch):
    room = state()
    room["scene_index"] = 1
    room["scene"] = content.scene_for(room)
    room["scene_id"] = room["scene"]["id"]
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [1], "total": 1})
    director.resolve(room, "hero", director.validate_proposal(check(), room, "hero"))
    assert room["flags"]["lens"] and room["combat"]["active"]


def test_host_only_encounter_is_whitelisted_once_per_scene(monkeypatch):
    room = campaign_room(monkeypatch)
    room["members"].append({"id": "guest", "name": "同伴", "character": content.new_character("rogue")})
    raw = {"kind": "encounter", "label": "巡逻者出现", "text": "脚步声逼近。", "monster_id": "guard"}
    other = director.validate_proposal(raw, room, "guest")
    before = copy.deepcopy(room)
    with pytest.raises(ValueError, match="房主"):
        director.resolve(room, "guest", other)
    assert room == before
    p = director.validate_proposal(raw, room, "hero")
    director.resolve(room, "hero", p)
    assert room["combat"]["director_encounter"] and room["combat"]["enemies"][0]["card_id"] == "guard"
    room["combat"]["active"] = False
    with pytest.raises(ValueError):
        director.validate_proposal(raw, room, "hero")
    assert room["campaign"]["cleared"] == [] and room["scene_id"] == "a"


def test_combat_proposals_cannot_create_extra_actions(monkeypatch):
    room = state()
    room["combat"] = {"active": True}
    with pytest.raises(ValueError, match="战斗中"):
        director.validate_proposal(check(), room, "hero")
    p = director.validate_proposal({"kind": "dialogue", "label": "回应", "text": "我们守住这里。"}, room, "hero")
    result = director.resolve(room, "hero", p)
    assert result[0]["kind"] == "dm" and room["combat"] == {"active": True}


def test_reliable_talent_uses_raw_dice_and_adjusted_minimum(monkeypatch):
    character = content.new_character("rogue")
    character.update(level=11, skills=["stealth"], class_id="rogue")
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [2], "total": 2})
    roll = director._skill_check(character, "stealth", 15)
    assert roll["dice"] == [2] and roll["selected"] == 10 and roll["total"] == 15 and roll["success"]


def test_model_proposal_and_invalid_output_fallback_leave_state_untouched():
    room = state()
    before = copy.deepcopy(room)
    class Model:
        configured = True
        async def _complete(self, *args, **kwargs):
            return json.dumps(check(skill_id="stealth"))
    result = asyncio.run(director.propose(Model(), room, "hero", "我想潜行绕开守卫"))
    assert result["source"] == "llm" and result["proposal"]["decision"]["skill_id"] == "stealth"
    assert room == before
    class BadModel(Model):
        async def _complete(self, *args, **kwargs):
            return json.dumps(check(hp=999, xp=999))
    result = asyncio.run(director.propose(BadModel(), room, "hero", "我想调查"))
    assert result["source"] == "fallback" and room == before


def test_real_character_proficiency_and_expertise_feed_director(monkeypatch):
    from backend import characters
    hero = characters.create_character("rogue", "暗巷旅人", {
        "skills": ["acrobatics", "deception", "sleight-of-hand", "stealth"],
        "expertise": ["stealth", "deception"],
    })
    room = state()
    room["members"][0]["character"] = hero
    monkeypatch.setattr(director, "_bonus", characters.skill_bonus)
    monkeypatch.setattr(rules, "roll_dice", lambda *args, **kw: {"dice": [8], "total": 8})
    proposal = director.validate_proposal(check(skill_id="stealth"), room, "hero")
    roll = director.resolve(room, "hero", proposal)[0]["roll"]
    assert roll["modifier"] == rules.modifier(hero["abilities"]["dex"]) + 2 * hero["proficiency"]
    assert roll["total"] == 8 + roll["modifier"]
