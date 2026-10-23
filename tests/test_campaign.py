import unittest
from copy import deepcopy
from unittest.mock import patch
from backend import campaign, content


def skill(sid, effect, target, **overrides):
    return {"id": sid, "name": sid, "description": "测试卡", "tags": [], "effect": effect, "target": target, "ability": "str", "dice": "1d8", "bonus": 0, "dc": 12, "uses": 2, **overrides}


def package():
    return {"scenario": {"id": "journey", "name": "岔路", "entry_node_id": "gate", "skill_ids": ["strike", "mend", "guard"], "monster_ids": ["wolf"], "nodes": [
        {"id": "gate", "title": "入口", "text": "两条路。", "monster_ids": [], "ending": False, "actions": [{"id": "read", "label": "解读石碑", "skill_id": "read", "success_node_id": "good", "failure_node_id": "bad"}, {"id": "enter", "label": "进入林地", "next_node_id": "battle"}]},
        {"id": "battle", "title": "林地", "text": "两只狼。", "monster_ids": ["wolf", "wolf"], "ending": False, "actions": [{"id": "leave", "label": "继续", "next_node_id": "good"}]},
        {"id": "good", "title": "晴日", "text": "晴日结局。", "monster_ids": [], "ending": True, "actions": []},
        {"id": "bad", "title": "风雨", "text": "风雨结局。", "monster_ids": [], "ending": True, "actions": []},
    ]}, "skills": {"read": skill("read", "check", "scene"), "strike": skill("strike", "attack", "enemy"), "mend": skill("mend", "heal", "ally"), "guard": skill("guard", "defend", "self")}, "monsters": {"wolf": {"id": "wolf", "name": "灰狼", "description": "野兽", "tags": [], "hp": 20, "ac": 10, "attack_bonus": 2, "damage_dice": "1d4", "damage_bonus": 0, "initiative_bonus": 0}}, "revisions": {"journey": 1, "wolf": 1}}


def room(players=1):
    return {"host_id": "p0", "members": [{"id": f"p{i}", "name": f"玩家{i}", "character": content.new_character("fighter")} for i in range(players)]}


class CampaignTests(unittest.TestCase):
    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_noncombat_healing_and_uses_persist_across_nodes(self, _):
        s, p = room(2), package()
        # Add a safe nonterminal node so recovery can be used across transitions.
        p["scenario"]["nodes"][0]["actions"].append({"id": "camp", "label": "前往营地", "next_node_id": "camp"})
        p["scenario"]["nodes"].append({"id": "camp", "title": "营地", "text": "暂时安全。", "actions": [{"id": "back", "label": "返回入口", "next_node_id": "gate"}], "monster_ids": [], "ending": False})
        campaign.start_campaign(s, p)
        s["members"][1]["character"].update(hp=0, stable=True, death_successes=3)
        action = next(a for a in campaign.available_actions(s, "p0") if a["id"] == "skill:mend")
        self.assertEqual(action["targets"], [{"id": "p1", "name": "玩家1"}])
        campaign.apply_action(s, "p0", "skill:mend", "p1")
        self.assertEqual(s["members"][1]["character"]["hp"], 1)
        self.assertFalse(s["members"][1]["character"]["stable"])
        campaign.apply_action(s, "p0", "node:camp")
        action = next(a for a in campaign.available_actions(s, "p0") if a["id"] == "skill:mend")
        self.assertEqual(action["uses_remaining"], 1)
        campaign.apply_action(s, "p0", "skill:mend", "p1")
        self.assertNotIn("skill:mend", [a["id"] for a in campaign.available_actions(s, "p0")])

    def test_noncombat_self_heal_only_lists_self(self):
        s, p = room(2), package()
        p["skills"]["mend"]["target"] = "self"
        campaign.start_campaign(s, p)
        s["members"][1]["character"]["hp"] = 1
        self.assertNotIn("skill:mend", [a["id"] for a in campaign.available_actions(s, "p0")])
        s["members"][0]["character"]["hp"] = 2
        action = next(a for a in campaign.available_actions(s, "p0") if a["id"] == "skill:mend")
        self.assertEqual(action["targets"], [{"id": "p0", "name": "玩家0"}])

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_dead_party_finishes_without_next_turn_loop(self, _):
        s = room()
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:enter")
        c = s["members"][0]["character"]
        c.update(hp=0, death_failures=2)
        with patch("backend.rules.secrets.randbelow", return_value=0):
            events = campaign.apply_action(s, "p0", "end_turn")
        self.assertTrue(c["dead"])
        self.assertTrue(s["completed"])
        self.assertFalse(s["combat"]["active"])
        self.assertEqual(events[-1]["kind"], "ending")
        self.assertEqual(campaign.available_actions(s, "p0"), [])

    def test_registry_covers_authoring_schema(self):
        from typing import get_args
        from backend.schemas import SkillCard
        self.assertEqual(set(get_args(SkillCard.model_fields["effect"].annotation)), set(campaign.EFFECT_HANDLERS))
        self.assertEqual(set(campaign.EFFECT_TARGETS), set(campaign.EFFECT_HANDLERS))

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_every_living_enemy_takes_automatic_turn(self, _):
        s = room()
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:enter")
        with patch("backend.rules.attack_roll", return_value={"damage": 0, "critical": False, "success": False}) as attack:
            events = campaign.apply_action(s, "p0", "end_turn")
        self.assertEqual(attack.call_count, 2)
        self.assertEqual(len([e for e in events if e["kind"] == "roll"]), 2)
        self.assertEqual(s["combat"]["turn_actor_id"], "p0")
        self.assertEqual(s["combat"]["round"], 2)

    def test_snapshot_is_immutable_from_source(self):
        s, p = room(), package()
        campaign.start_campaign(s, p)
        p["scenario"]["nodes"][0]["text"] = "mutated"
        p["skills"]["strike"]["bonus"] = 999
        self.assertEqual(s["scene"]["text"], "两条路。")
        self.assertEqual(s["campaign"]["package"]["skills"]["strike"]["bonus"], 0)
        self.assertNotIn("nodes", s["scene"])

    @patch("backend.rules.secrets.randbelow", return_value=19)
    def test_success_route(self, _):
        s = room()
        campaign.start_campaign(s, package())
        events = campaign.apply_action(s, "p0", "node:read")
        self.assertTrue(events[0]["roll"]["success"])
        self.assertEqual(s["scene_id"], "good")
        self.assertTrue(s["completed"])

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_failure_route(self, _):
        s = room()
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:read")
        self.assertEqual(s["scene_id"], "bad")
        self.assertEqual(s["campaign"]["spent"]["p0"]["read"], 1)

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_multi_enemy_ids_and_explicit_target(self, _):
        s = room()
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:enter")
        enemies = s["combat"]["enemies"]
        self.assertEqual(len({e["id"] for e in enemies}), 2)
        self.assertEqual(s["combat"]["turn_actor_id"], "p0")
        before = deepcopy(s)
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "skill:strike")
        self.assertEqual(s, before)
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "skill:strike", "p0")
        campaign.apply_action(s, "p0", "skill:strike", enemies[1]["id"])
        self.assertEqual(s["campaign"]["spent"]["p0"]["strike"], 1)
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "attack", enemies[0]["id"])

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_skill_uses_exhaust_and_are_per_character(self, _):
        s = room(2)
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:enter")
        enemy = s["combat"]["enemies"][0]["id"]
        for _ in range(2):
            campaign.apply_action(s, "p0", "skill:strike", enemy)
            campaign.apply_action(s, "p0", "end_turn")
            campaign.apply_action(s, "p1", "end_turn")
        actions = campaign.available_actions(s, "p0")
        self.assertNotIn("skill:strike", [a["id"] for a in actions])
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "skill:strike", enemy)
        campaign.apply_action(s, "p0", "end_turn")
        self.assertIn("skill:strike", [a["id"] for a in campaign.available_actions(s, "p1")])

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_heal_and_defend_real_effects(self, _):
        s = room(2)
        campaign.start_campaign(s, package())
        campaign.apply_action(s, "p0", "node:enter")
        target = s["members"][1]["character"]
        target.update(hp=0, death_failures=2)
        campaign.apply_action(s, "p0", "skill:mend", "p1")
        self.assertEqual(target["hp"], 2)
        self.assertEqual(target["death_failures"], 0)
        campaign.apply_action(s, "p0", "end_turn")
        campaign.apply_action(s, "p1", "skill:guard")
        self.assertIn("p1", s["combat"]["dodging"])

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_self_heal_cannot_target_other(self, _):
        s, p = room(2), package()
        p["skills"]["mend"]["target"] = "self"
        campaign.start_campaign(s, p)
        campaign.apply_action(s, "p0", "node:enter")
        s["members"][1]["character"]["hp"] = 1
        before = deepcopy(s)
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "skill:mend", "p1")
        self.assertEqual(s, before)

    @patch("backend.rules.secrets.randbelow", side_effect=lambda n: min(1, n - 1))
    def test_victory_opens_node_route(self, _):
        s, p = room(), package()
        p["monsters"]["wolf"]["hp"] = 1
        campaign.start_campaign(s, p)
        campaign.apply_action(s, "p0", "node:enter")
        with patch("backend.rules.attack_roll", return_value={"damage": 10, "critical": False, "success": True}):
            campaign.apply_action(s, "p0", "attack", s["combat"]["enemies"][0]["id"])
            campaign.apply_action(s, "p0", "end_turn")
            campaign.apply_action(s, "p0", "attack", s["combat"]["enemies"][1]["id"])
        self.assertFalse(s["combat"]["active"])
        campaign.apply_action(s, "p0", "node:leave")
        self.assertTrue(s["completed"])

    def test_dead_host_can_direct_companions(self):
        s = room(2)
        campaign.start_campaign(s, package())
        s["members"][0]["character"].update(hp=0, dead=True)
        actions = campaign.available_actions(s, "p0")
        self.assertEqual([a["id"] for a in actions], ["node:enter"])
        self.assertTrue(actions[0]["party_action"])

    def test_unregistered_skill_cannot_execute(self):
        s = room()
        campaign.start_campaign(s, package())
        with self.assertRaises(ValueError):
            campaign.apply_action(s, "p0", "skill:invented", "anyone")

    def test_runtime_rejects_executable_or_unsupported_content(self):
        p = package()
        p["skills"]["strike"]["effect"] = "python"
        with self.assertRaises(ValueError):
            campaign.start_campaign(room(), p)
        p = package()
        p["monsters"]["wolf"]["damage_dice"] = "__import__('os')"
        with self.assertRaises(ValueError):
            campaign.start_campaign(room(), p)

    def test_invalid_node_routes_rejected(self):
        p = package()
        p["scenario"]["nodes"][0]["actions"][0]["failure_node_id"] = "missing"
        with self.assertRaises(ValueError):
            campaign.start_campaign(room(), p)


if __name__ == "__main__":
    unittest.main()
