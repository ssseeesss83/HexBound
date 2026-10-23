from copy import deepcopy
from unittest.mock import patch

import pytest

from backend import characters as chars, content, compendium


def advance(c, target):
    while c["level"] < target:
        c = chars.add_xp(c, max(0, chars.XP_THRESHOLDS[c["level"]] - c["xp"]))
        preview = chars.level_up_preview(c)
        choices = {}
        if preview["required_choices"]["subclass"]:
            choices["subclass_id"] = preview["required_choices"]["subclass"][0]["id"]
        if preview["required_choices"]["asi"]:
            remaining = 2
            choices["asi"] = {}
            for ability in chars.ABILITIES:
                add = min(remaining, 20 - c["abilities"][ability])
                choices["asi"][ability] = add
                remaining -= add
                if remaining == 0:
                    break
        count = preview["required_choices"]["expertise_count"]
        if count > len(c["expertise"]):
            choices["expertise"] = c["skills"][:count]
        c = chars.level_up(c, choices)
    return c


@pytest.mark.parametrize("class_id", chars.CLASS_NAMES)
def test_all_twelve_classes_create_and_advance_to_twenty(class_id):
    c = chars.create_character(class_id, "测试者")
    assert sorted(c["abilities"].values()) == [8, 10, 12, 13, 14, 15]
    assert c["max_hp"] >= 6
    assert c["proficiency"] == 2
    assert len(c["skill_modifiers"]) == 18
    c = advance(c, 20)
    assert c["level"] == 20
    assert c["proficiency"] == 6
    assert c["hit_dice"]["max"] == 20
    assert len(c["growth_history"]) == 19
    assert c["features"]
    assert all("automated" in f and "note" in f for f in c["features"])
    assert not chars.level_up_preview(c)["eligible"]
    with pytest.raises(ValueError):
        chars.level_up(c)


def test_derived_fields_and_illegal_choices_rejected():
    for forged in ({"level": 20}, {"hp": 999}, {"xp": 355000}, {"proficiency": 99}, {"asi": {"str": 2}}):
        with pytest.raises(ValueError):
            chars.create_character("fighter", choices=forged)
    with pytest.raises(ValueError):
        chars.create_character("fighter", choices={"skills": ["arcana", "religion"]})
    with pytest.raises(ValueError):
        chars.create_character("rogue", choices={"expertise": ["perception", "perception"]})
    with pytest.raises(ValueError):
        chars.create_character("wizard", choices={"subclass_id": "life"})


def test_xp_and_milestone_qualification_and_copy_on_write():
    c = chars.create_character("fighter")
    original = deepcopy(c)
    with pytest.raises(ValueError):
        chars.level_up(c)
    with pytest.raises(ValueError):
        chars.level_up(c, progression="milestone")
    assert c == original
    c["milestone_credits"] = 1
    assert chars.level_up_preview(c)["eligible"]
    upgraded = chars.level_up(c, progression="milestone")
    assert upgraded["level"] == 2
    assert c["level"] == 1
    # Account/room transaction consumes the credit, not this pure function.
    assert upgraded["milestone_credits"] == 1


def test_subclass_cannot_be_skipped_or_foreign():
    c = advance(chars.create_character("fighter"), 2)
    c = chars.add_xp(c, 1000)
    for choices in ({}, {"subclass_id": "evocation"}):
        with pytest.raises(ValueError):
            chars.level_up(c, choices)
    c = chars.level_up(c, {"subclass_id": "champion"})
    c = chars.add_xp(c, 5000)
    with pytest.raises(ValueError):
        chars.level_up(c, {"subclass_id": "evocation", "asi": {"str": 2}})


def test_con_asi_retroactive_hp_and_wounds_preserved():
    c = advance(chars.create_character("fighter"), 3)
    c["hp"] -= 5
    old_max = c["max_hp"]
    c = chars.add_xp(c, 5000)
    upgraded = chars.level_up(c, {"asi": {"con": 2}})
    assert upgraded["abilities"]["con"] == 16
    assert upgraded["max_hp"] - old_max == 6 + 3 + 3  # d10 average + new CON + three previous levels
    assert upgraded["max_hp"] - upgraded["hp"] == 5
    c["abilities"]["str"] = 20
    with pytest.raises(ValueError):
        chars.level_up(c, {"asi": {"str": 2}})
    with pytest.raises(ValueError):
        chars.level_up(c, {"asi": {"str": True, "dex": 1}})


def test_extra_fighter_and_rogue_asi_levels():
    fighter = advance(chars.create_character("fighter"), 5)
    rogue = advance(chars.create_character("rogue"), 9)
    wizard = advance(chars.create_character("wizard"), 5)
    assert chars.level_up_preview(fighter)["required_choices"]["asi"]
    assert chars.level_up_preview(rogue)["required_choices"]["asi"]
    assert chars.level_up_preview(wizard)["required_choices"]["asi"] is None


def test_proficiency_expertise_and_jack_of_all_trades():
    rogue = chars.create_character("rogue")
    sid = rogue["expertise"][0]
    assert chars.skill_bonus(rogue, sid) == chars.modifier(rogue["abilities"][chars.SKILL_ABILITIES[sid]]) + 4
    bard = advance(chars.create_character("bard"), 2)
    sid = next(s for s in chars.SKILL_ABILITIES if s not in bard["skills"])
    assert chars.skill_bonus(bard, sid) == chars.modifier(bard["abilities"][chars.SKILL_ABILITIES[sid]]) + 1
    monk = advance(chars.create_character("monk"), 14)
    assert set(monk["saving_throws"]) == set(chars.ABILITIES)


def test_legacy_migration_idempotent_no_healing_or_hp_addition():
    c = content.new_character("warden")
    c["hp"] = 2
    before = deepcopy(c)
    migrated = chars.migrate_character(c)
    assert migrated["class_id"] == "cleric"
    assert migrated["hp"] == 2
    assert migrated["max_hp"] == before["max_hp"]
    assert migrated["abilities"] == before["abilities"]
    assert migrated["ac"] == before["ac"]
    assert chars.migrate_character(migrated) == migrated
    assert c == before
    wizard = chars.migrate_character(content.new_character("scholar"))
    assert wizard["class_id"] == "wizard"


def test_spent_resources_not_restored_by_normalize_or_level_up():
    wizard = chars.create_character("wizard")
    chars.consume_spell_slot(wizard, 1)
    chars.consume_spell_slot(wizard, 1)
    chars.consume_resource(wizard, "arcane-recovery")
    assert chars.normalize_character(wizard)["spell_slots"]["1"]["current"] == 0
    wizard = chars.add_xp(wizard, 300)
    wizard = chars.level_up(wizard, {"subclass_id": "evocation"})
    assert wizard["spell_slots"]["1"] == {"max": 3, "current": 1, "recharge": "long"}
    assert wizard["resources"]["arcane-recovery"]["current"] == 0


def test_spell_legality_and_preparation_only_edits():
    wizard = chars.create_character("wizard")
    assert "magic-missile" in wizard["spellbook"]
    before = deepcopy(wizard)
    with pytest.raises(ValueError):
        chars.manage_spells(wizard, {"known_spells": ["wish"]})
    with pytest.raises(ValueError):
        chars.manage_spells(wizard, {"prepared_spells": ["cure-wounds"]})
    with pytest.raises(ValueError):
        chars.manage_spells(wizard, {"prepared_spells": ["magic-missile", "magic-missile"]})
    selected = wizard["spellbook"][:wizard["spellcasting"]["prepared_limit"]]
    assert chars.manage_spells(wizard, {"prepared_spells": selected})["prepared_spells"] == selected
    assert wizard == before
    bard = chars.create_character("bard")
    with pytest.raises(ValueError):
        chars.manage_spells(bard, {"prepared_spells": []})


def test_known_spell_replacement_limit_and_cantrip_permanence():
    bard = chars.create_character("bard")
    bard = chars.add_xp(bard, 300)
    future = deepcopy(bard)
    future["level"] = 2
    chars._derived(future)
    pool = [s for s in chars.eligible_spells(future) if s not in bard["known_spells"]]
    with pytest.raises(ValueError):
        chars.level_up(bard, {"known_spells": pool[:5]})
    new_cantrip = next(s for s in chars.eligible_spells(bard, cantrips=True) if s not in bard["cantrips"])
    with pytest.raises(ValueError):
        chars.level_up(bard, {"cantrips": [bard["cantrips"][0], new_cantrip]})


def test_warlock_slots_short_rest_and_wizard_slots_long_rest():
    warlock = advance(chars.create_character("warlock"), 5)
    assert warlock["pact_slots"]["level"] == 3
    chars.consume_spell_slot(warlock, 3, pact=True)
    assert chars.short_rest(warlock)["pact_slots"]["current"] == warlock["pact_slots"]["max"]
    wizard = chars.create_character("wizard")
    chars.consume_spell_slot(wizard, 1)
    assert chars.short_rest(wizard)["spell_slots"]["1"]["current"] == 1
    assert chars.long_rest(wizard)["spell_slots"]["1"]["current"] == 2


@patch("backend.characters.secrets.randbelow", return_value=3)
def test_hit_dice_and_long_rest_recovery(_):
    c = advance(chars.create_character("fighter"), 4)
    c["hp"] = 1
    rested = chars.short_rest(c, 3)
    assert rested["hit_dice"]["current"] == 1
    assert rested["hp"] == 1 + 3 * (4 + chars.modifier(c["abilities"]["con"]))
    assert c["hit_dice"]["current"] == 4
    assert chars.long_rest(rested)["hit_dice"]["current"] == 3
    with pytest.raises(ValueError):
        chars.short_rest(rested, 2)
    rested.update(hp=0, stable=True)
    with pytest.raises(ValueError):
        chars.long_rest(rested)


def test_sheet_contains_only_owned_spells_and_all_skills():
    wizard = chars.create_character("wizard")
    sheet = chars.character_sheet(wizard)
    assert len(sheet["skill_details"]) == 18
    assert len(sheet["save_details"]) == 6
    owned = set(wizard["spellbook"] + wizard["cantrips"])
    assert {s["id"] for s in sheet["spell_details"]} == owned
    assert len(sheet["spell_details"]) < len(compendium.SPELLS)
    assert any(not f["automated"] for f in sheet["features"])


def test_pre_subclass_character_does_not_receive_other_classes_features():
    fighter = chars.create_character("fighter")
    feature_ids = {f["id"] for f in fighter["features"]}
    assert "second-wind" in feature_ids
    assert "arcane-recovery" not in feature_ids
    assert "pact-magic" not in feature_ids
    assert "rage" not in feature_ids
    sorcerer = chars.create_character("sorcerer")
    assert "dragon-ancestor" in {f["id"] for f in sorcerer["features"]}
    assert not any(f["id"].startswith("dragon-ancestor-") for f in sorcerer["features"])


def test_high_level_spell_choice_preview_is_explicit():
    bard = advance(chars.create_character("bard"), 5)
    preview = chars.level_up_preview(bard)
    assert preview["required_choices"]["magical_secrets_count"] == 2
    assert "fireball" in preview["eligible_magical_secrets"]
    warlock = advance(chars.create_character("warlock"), 10)
    preview = chars.level_up_preview(warlock)
    assert "6" in preview["arcanum_choices"]
    assert all(compendium.SPELLS[s]["level"] == 6 for s in preview["arcanum_choices"]["6"])
