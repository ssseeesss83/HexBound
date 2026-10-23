import unittest
from unittest.mock import patch
from backend import content, rules


def room(players=1):
    s = content.initialize_state()
    s["members"] = [{"id": f"p{i}", "name": f"旅人{i}", "character": content.new_character("fighter")} for i in range(players)]
    s["host_member_id"] = "p0"
    return s


class DiceRulesTests(unittest.TestCase):
    def test_ability_floor(self):
        self.assertEqual(rules.modifier(9), -1)
        self.assertEqual(rules.modifier(16), 3)

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_check_natural_one_can_succeed(self, _):
        self.assertTrue(rules.check(10, 10)["success"])

    @patch("backend.rules.secrets.randbelow", return_value=19)
    def test_check_natural_twenty_can_fail(self, _):
        self.assertFalse(rules.check(-5, 20)["success"])

    @patch("backend.rules.secrets.randbelow", side_effect=[2, 17, 3])
    def test_advantage_and_cancellation(self, _):
        self.assertEqual(rules.check(0, 10, advantage=True)["selected"], 18)
        r = rules.check(0, 10, advantage=True, disadvantage=True)
        self.assertEqual(r["dice"], [4])

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_attack_one_always_misses(self, _):
        r = rules.attack_roll(99, 1, "1d8", 3)
        self.assertFalse(r["success"])
        self.assertEqual(r["damage"], 0)

    @patch("backend.rules.secrets.randbelow", side_effect=[19, 3, 4])
    def test_critical_doubles_dice_not_bonus(self, _):
        r = rules.attack_roll(-99, 99, "1d8", 3)
        self.assertTrue(r["success"])
        self.assertEqual(r["damage_dice"], [4, 5])
        self.assertEqual(r["damage"], 12)

    def test_invalid_dice(self):
        for expr in ("1000d20", "1d999", "__import__('os')", "0d6"):
            with self.assertRaises(ValueError):
                rules.roll_dice(expr)

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_death_save_nat_one_two_failures(self, _):
        c = content.new_character("fighter")
        c["hp"] = 0
        rules.death_save(c)
        self.assertEqual(c["death_failures"], 2)
        rules.death_save(c)
        self.assertTrue(c["dead"])

    @patch("backend.rules.secrets.randbelow", return_value=19)
    def test_death_save_twenty_restores_one(self, _):
        c = content.new_character("fighter")
        c.update(hp=0, death_failures=2)
        rules.death_save(c)
        self.assertEqual(c["hp"], 1)
        self.assertEqual(c["death_failures"], 0)

    def test_massive_damage(self):
        c = content.new_character("fighter")
        rules.damage_character(c, 24)
        self.assertTrue(c["dead"])

    @patch("backend.rules.secrets.randbelow", return_value=9)
    def test_stabilization(self, _):
        c = content.new_character("fighter")
        c["hp"] = 0
        for _ in range(3):
            rules.death_save(c)
        self.assertTrue(c["stable"])
        self.assertIsNone(rules.death_save(c))


class AdventureTests(unittest.TestCase):
    def test_dead_host_can_advance_with_conscious_companion(self):
        s = room(2)
        s["members"][0]["character"].update(hp=0, dead=True)
        s["flags"]["scene_resolved"] = True
        actions = content.available_actions(s, "p0")
        self.assertEqual([a["id"] for a in actions], ["advance"])
        self.assertTrue(actions[0]["party_action"])
        rules.apply_action(s, "p0", "advance")
        self.assertEqual(s["scene_id"], "customs")
        self.assertTrue(s["members"][0]["character"]["dead"])

    def test_downed_host_can_order_rest_for_conscious_party(self):
        s = room(2)
        s["members"][0]["character"].update(hp=0, stable=True)
        rules.apply_action(s, "p0", "rest")
        self.assertEqual(s["members"][0]["character"]["hp"], 12)
        self.assertTrue(s["rest_used"])

    def test_dead_host_rest_heals_companion_but_not_dead(self):
        s = room(2)
        s["members"][0]["character"].update(hp=0, dead=True)
        s["members"][1]["character"]["hp"] = 3
        rules.apply_action(s, "p0", "rest")
        self.assertEqual(s["members"][0]["character"]["hp"], 0)
        self.assertTrue(s["members"][0]["character"]["dead"])
        self.assertEqual(s["members"][1]["character"]["hp"], 12)

    def test_no_conscious_party_cannot_advance_or_rest(self):
        s = room(2)
        for member in s["members"]:
            member["character"].update(hp=0, stable=True)
        s["flags"]["scene_resolved"] = True
        self.assertEqual(content.available_actions(s, "p0"), [])
        with self.assertRaises(ValueError):
            rules.apply_action(s, "p0", "advance")

    @patch("backend.rules.secrets.randbelow", return_value=9)
    def test_oath_changes_final_check_and_ending(self, _):
        s = room()
        s["scene_index"] = 3
        s["flags"]["oath"] = True
        s["members"][0]["character"]["abilities"]["wis"] = 18
        events = rules.apply_action(s, "p0", "parley")
        self.assertTrue(events[0]["roll"]["advantage"])
        rules.apply_action(s, "p0", "advance")
        self.assertEqual(s["scene"]["title"], "不必再独自守夜")

    def test_distinct_ending_consequences(self):
        s = room()
        s["flags"].update(resolution="fight", pressure=2)
        scene = content.ending_scene(s)
        self.assertEqual(scene["title"], "破壳后的火")
        self.assertIn("船底", scene["text"])

    @patch("backend.rules.secrets.randbelow", return_value=9)
    def test_noncombat_complete_adventure(self, _):
        s = room()
        for action in ("investigate", "parley", "investigate", "repair"):
            # Ensure this route succeeds without randomness manipulating the scenario.
            s["members"][0]["character"]["abilities"] = {k: 20 for k in ("str", "dex", "con", "int", "wis", "cha")}
            rules.apply_action(s, "p0", action)
            rules.apply_action(s, "p0", "advance")
        self.assertTrue(s["completed"])
        self.assertEqual(s["scene_id"], "dawn")

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_failure_keeps_path_and_cannot_reroll(self, _):
        s = room()
        rules.apply_action(s, "p0", "investigate")
        self.assertTrue(s["flags"]["scene_resolved"])
        with self.assertRaises(ValueError):
            rules.apply_action(s, "p0", "investigate")
        rules.apply_action(s, "p0", "advance")
        self.assertEqual(s["scene_id"], "customs")

    @patch("backend.rules.secrets.randbelow", return_value=1)
    def test_combat_turn_and_action_budget(self, _):
        s = room(2)
        rules.start_combat(s)
        actor = s["combat"]["turn_actor_id"]
        other = "p1" if actor == "p0" else "p0"
        with self.assertRaises(ValueError):
            rules.apply_action(s, other, "attack")
        rules.apply_action(s, actor, "attack")
        with self.assertRaises(ValueError):
            rules.apply_action(s, actor, "attack")
        rules.apply_action(s, actor, "end_turn")
        self.assertNotEqual(s["combat"]["turn_actor_id"], actor)

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_potion_cost_and_target(self, _):
        s = room(2)
        target = s["members"][1]["character"]
        target.update(hp=0, death_failures=2)
        rules.apply_action(s, "p0", "heal", "p1")
        self.assertEqual(target["hp"], 4)
        self.assertEqual(target["death_failures"], 0)
        self.assertEqual(s["members"][0]["character"]["potions"], 1)

    def test_rest_once_and_host_only(self):
        s = room(2)
        s["members"][0]["character"]["hp"] = 3
        with self.assertRaises(ValueError):
            rules.apply_action(s, "p1", "rest")
        rules.apply_action(s, "p0", "rest")
        s["members"][0]["character"]["hp"] = 3
        with self.assertRaises(ValueError):
            rules.apply_action(s, "p0", "rest")

    @patch("backend.rules.secrets.randbelow", return_value=0)
    def test_dead_party_ends_encounter(self, _):
        s = room()
        rules.start_combat(s)
        c = s["members"][0]["character"]
        c.update(hp=0, death_failures=2)
        rules.apply_action(s, "p0", "end_turn")
        self.assertTrue(s["completed"])
        self.assertFalse(s["combat"]["active"])


if __name__ == "__main__":
    unittest.main()
