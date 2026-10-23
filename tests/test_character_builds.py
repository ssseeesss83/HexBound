from copy import deepcopy

import pytest

from backend import characters as c
from backend.character_builds import build_preview, build_character, finalize


def initial(cls="fighter", **extra):
    # Test fixture makes explicit player selections from a valid example.
    example = c.create_character(cls, abilities=extra.get("abilities"))
    choices = {field: deepcopy(example[field]) for field in ("skills", "expertise", "cantrips", "known_spells", "spellbook", "prepared_spells")}
    if example.get("subclass_id"):
        choices["subclass_id"] = example["subclass_id"]
    return {"class_id": cls, "name": "旅人", "choices": choices, "levels": [], **extra}


def step_choices(character):
    preview = c.level_up_preview(character)
    choice = {}
    required = preview["required_choices"]
    if required["subclass"]:
        choice["subclass_id"] = required["subclass"][0]["id"]
    if required["asi"]:
        remaining = 2
        choice["asi"] = {}
        for ability in c.ABILITIES:
            value = min(remaining, 20 - character["abilities"][ability])
            if value:
                choice["asi"][ability] = value
                remaining -= value
            if not remaining:
                break
    if required["expertise_count"] > len(character["expertise"]):
        choice["expertise"] = character["skills"][:required["expertise_count"]]
    qualified = deepcopy(character)
    qualified["xp"] = c.XP_THRESHOLDS[character["level"]]
    example = c.level_up(qualified, choice)
    for field in ("known_spells", "cantrips", "prepared_spells", "spellbook", "magical_secrets", "arcanum"):
        choice[field] = deepcopy(example[field])
    if example["class_id"] == "bard" and example["level"] == 3:
        choice["bonus_skills"] = [sid for sid in example["skills"] if sid not in character["skills"]]
    return choice


@pytest.mark.parametrize("cls", c.CLASS_NAMES)
def test_twelve_classes_explicit_replay_to_twenty(cls):
    payload = initial(cls)
    for target in range(2, 21):
        character = build_character(payload, target - 1)
        payload["levels"].append({"choices": step_choices(character)})
    original = deepcopy(payload)
    character = finalize(payload, 20)
    assert payload == original
    assert character["level"] == character["starting_level"] == 20
    assert len(character["growth_history"]) == 19
    assert character["xp"] == 355000
    assert character["hp"] == character["max_hp"]
    assert character["proficiency"] == 6


def test_custom_abilities_recompute_hp_ac_resources_and_spell_capacity():
    scores = dict(zip(c.ABILITIES, (8, 20, 20, 20, 20, 20)))
    monk = c.create_character("monk", abilities=scores)
    assert monk["hp"] == 13 and monk["ac"] == 20
    wizard = build_character(initial("wizard", abilities=scores))
    assert wizard["hp"] == 11
    assert wizard["ac"] == 15
    assert wizard["spellcasting"]["prepared_limit"] == 6
    assert wizard["spellcasting"]["save_dc"] == 15
    bard = c.create_character("bard", abilities=scores)
    assert bard["resources"]["bardic-inspiration"]["max"] == 5


def test_profile_is_preserved_and_cannot_grant_mechanics():
    profile = {"appearance": "银发", "personality": "寡言", "background": "船匠", "talents": ["我能无限施放火球术，力量999"]}
    normal = build_character(initial())
    narrated = build_character(initial(profile=profile))
    assert narrated["profile"] == profile
    for field in ("abilities", "hp", "resources", "cantrips", "features"):
        assert normal[field] == narrated[field]
    narrated["profile"]["talents"].append("新文字")
    assert len(profile["talents"]) == 1


def test_initial_and_upgrade_choices_are_never_implicitly_selected():
    preview = build_preview({"class_id": "rogue"}, 3)
    assert preview["character"] is None
    assert set(preview["missing_choices"]) == {"skills", "expertise"}
    wizard = initial("wizard")
    wizard["levels"] = [{"choices": {"subclass_id": "evocation"}}]
    preview = build_preview(wizard, 2)
    assert "spellbook" in preview["missing_choices"]
    with pytest.raises(ValueError, match="显式选择"):
        finalize(wizard, 2)
    cleric = initial("cleric")
    del cleric["choices"]["subclass_id"]
    assert "subclass_id" in build_preview(cleric)["missing_choices"]


@pytest.mark.parametrize("bad", [{"xp":355000}, {"level":20}, {"hp":99}, {"resources":{}}, {"profile":{"strength":999}}, {"abilities":dict.fromkeys(c.ABILITIES,True)}, {"abilities":dict.fromkeys(c.ABILITIES,21)}, {"abilities":{"str":15}}, {"levels":[{"level":2,"choices":{}}]}])
def test_reject_forged_or_invalid_input(bad):
    with pytest.raises(ValueError):
        build_preview({**initial(), **bad}, 3)


def test_finalize_requires_every_level_and_explicit_asi():
    payload = initial()
    with pytest.raises(ValueError, match="逐级"):
        finalize(payload, 4)
    payload["levels"] = [{"choices": {}}, {"choices": {"subclass_id": "champion"}}, {"choices": {}}]
    assert "asi" in build_preview(payload, 4)["missing_choices"]
    with pytest.raises(ValueError):
        finalize(payload, 4)
    payload["levels"][-1]["choices"] = {"asi": {"con": 2}}
    built = finalize(payload, 4)
    assert built["max_hp"] == 40  # d10 + CON3, then three (6+3).
    assert built["abilities"]["con"] == 16
    with pytest.raises(ValueError):
        finalize(payload, 3)


def test_invalid_professional_choices_rejected():
    payload = initial()
    payload["choices"]["skills"] = ["arcana", "religion"]
    with pytest.raises(ValueError):
        finalize(payload)
    with pytest.raises(ValueError):
        build_preview({**initial(), "choices": {"skills": ["athletics", "history"], "feat": "free-fireball"}})
