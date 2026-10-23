import copy
import json
import types

import pytest

from backend import compendium as c


def test_pinned_raw_source_integrity_and_complete_counts():
    assert c.SOURCE["source_commit"] == "a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f"
    assert c.SOURCE["upstream_directory"] == "src/2014/en"
    assert c.EDITION == "2014" and c.SRD_VERSION == "5.1"
    assert c.verify_source_integrity() == []
    assert len(c.SOURCE["files"]) == 25
    assert sum(item["records"] for item in c.SOURCE["files"]) == 2317
    assert len(c.CLASSES) == 12
    assert len(c.SKILLS) == 18
    assert len(c.SPELLS) == 319
    assert len(c.SUBCLASSES) == 12
    assert len(c.FEATURES) == 407
    assert len(c.MONSTERS) == 334


def test_every_core_class_has_all_twenty_progression_records():
    expected = {"barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard"}
    assert set(c.CLASSES) == expected
    for class_id in expected:
        assert set(c.CLASS_LEVELS[class_id]) == set(range(1, 21))
        assert c.CLASSES[class_id]["hit_die"] in {6, 8, 10, 12}
        assert c.CLASSES[class_id]["name_zh"]
        for level, record in c.CLASS_LEVELS[class_id].items():
            assert record["level"] == level
            assert record["class"]["index"] == class_id
            assert record["prof_bonus"] == 2 + (level - 1) // 4
            assert all(feature["index"] in c.FEATURES for feature in record["features"])
    assert sum(len(records) for records in c.SUBCLASS_LEVELS.values()) == 50


def test_spellcasting_tables_preserve_half_and_pact_caster_rules():
    assert all(value == 0 for key, value in c.CLASS_LEVELS["paladin"][1].get("spellcasting", {}).items() if key.startswith("spell_slots_level_"))
    assert c.class_level("paladin", 2)["spellcasting"]["spell_slots_level_1"] == 2
    wizard = c.class_level("wizard", 20)["spellcasting"]
    assert wizard["spell_slots_level_1"] == 4 and wizard["spell_slots_level_9"] == 1
    warlock = c.class_level("warlock", 5)
    assert warlock["spellcasting"]["spell_slots_level_3"] == 2
    assert warlock["spellcasting"]["spell_slots_level_1"] == 0
    assert warlock["class_specific"]["invocations_known"] == 3
    assert c.CLASS_CASTING_ABILITIES["wizard"] == "int"
    assert c.CLASS_CASTING_ABILITIES["warlock"] == "cha"
    assert c.CLASS_CASTING_ABILITIES["cleric"] == "wis"


def test_complete_spell_text_and_mechanics_are_not_truncated_or_reshaped():
    raw = json.loads((c.DATA_DIR / "srd2014/5e-SRD-Spells.json").read_text())
    for original in raw:
        spell = c.SPELLS[original["index"]]
        for field, value in original.items():
            assert spell[field] == value
        assert all(field in spell for field in ("level", "classes", "casting_time", "concentration", "duration", "components", "desc", "higher_level"))
        assert spell["desc"] and all(isinstance(paragraph, str) for paragraph in spell["desc"])
        assert all(reference["index"] in c.CLASSES for reference in spell["classes"])
        assert all(reference["index"] in c.SUBCLASSES for reference in spell.get("subclasses", []))
    assert isinstance(c.SPELLS["fireball"]["damage"], list)
    assert c.SPELLS["fireball"]["damage"][0]["damage_at_slot_level"]["3"] == "8d6"
    assert c.SPELLS["shield"]["casting_time"].startswith("1 reaction")


def test_raw_2014_data_has_no_2024_url_or_non_srd_spell_injection():
    for file in c.SOURCE["files"]:
        raw = (c.DATA_DIR / file["file"]).read_text()
        assert "/api/2024/" not in raw
    assert "artificer" not in c.CLASSES
    assert "chromatic-orb" not in c.SPELLS
    assert "starry-wisp" not in c.SPELLS


def test_all_eighteen_skills_have_source_ability_and_chinese_labels():
    assert set(c.SKILL_NAMES_ZH) == set(c.SKILLS)
    for skill in c.SKILLS.values():
        assert skill["ability_score"]["index"] in c.ABILITY_SCORES
        assert skill["name_zh"] and skill["desc"]
    assert c.SKILLS["perception"]["ability_score"]["index"] == "wis"
    assert c.SKILLS["athletics"]["ability_score"]["index"] == "str"
    assert c.SKILLS["investigation"]["ability_score"]["index"] == "int"


def test_only_known_translation_names_are_added():
    assert set(c.SPELL_NAMES_ZH) <= set(c.SPELLS)
    assert c.SPELLS["fireball"]["display_name"] == "火球术"
    untranslated = next(row for row in c.SPELLS.values() if row["id"] not in c.SPELL_NAMES_ZH)
    assert "name_zh" not in untranslated and untranslated["display_name"] == untranslated["name"]


def test_explicit_life_domain_erratum_preserves_original_archive():
    raw = json.loads((c.DATA_DIR / "srd2014/5e-SRD-Subclasses.json").read_text())
    original = next(row for row in raw if row["index"] == "life")
    assert len(original["spells"]) == 9
    corrected = c.SUBCLASSES["life"]
    assert len(corrected["spells"]) == 10
    added = next(row for row in corrected["spells"] if row["spell"]["index"] == "guardian-of-faith")
    assert added["prerequisites"][0]["index"] == "cleric-7"
    assert "life-domain-guardian-of-faith" in corrected["source_corrections"]
    assert c.ERRATA["corrections"][0]["source_page"] == 17


def test_xp_thresholds_match_character_advancement_table():
    assert len(c.XP_THRESHOLDS) == 20
    assert c.XP_THRESHOLDS[1] == 0 and c.XP_THRESHOLDS[2] == 300
    assert c.XP_THRESHOLDS[5] == 6500 and c.XP_THRESHOLDS[11] == 85000
    assert c.XP_THRESHOLDS[17] == 225000 and c.XP_THRESHOLDS[20] == 355000
    assert list(c.XP_THRESHOLDS.values()) == sorted(set(c.XP_THRESHOLDS.values()))


def test_catalog_search_filters_and_pagination_preserve_full_records():
    overview = c.get_catalog()
    assert len(overview["classes"]) == 12 and overview["counts"]["spells"] == 319
    spells = c.get_catalog("spells", class_id="wizard", level=3, school="evocation", limit=2)
    assert len(spells["items"]) == 2 and spells["total"] >= 2
    for spell in spells["items"]:
        assert spell["level"] == 3 and spell["school"]["index"] == "evocation"
        assert any(row["index"] == "wizard" for row in spell["classes"])
        assert spell["desc"] and "automation_status" in spell
    assert c.get_catalog("spells", q="火球术")["items"][0]["id"] == "fireball"
    assert c.get_catalog("spells", q="FIREBALL")["total"] >= 1
    assert c.get_catalog("spells", offset=319)["items"] == []


def test_lookup_and_progression_results_are_detached_copies():
    spell = c.lookup("spell", "fireball")
    original = copy.deepcopy(c.SPELLS["fireball"])
    spell["desc"][0] = "not a real rule"
    spell["damage"][0]["damage_at_slot_level"]["3"] = "999d20"
    assert c.SPELLS["fireball"] == original
    level = c.class_level("fighter", 20)
    level["prof_bonus"] = 999
    assert c.CLASS_LEVELS["fighter"][20]["prof_bonus"] == 6
    overview = c.get_catalog()
    overview["skills"][0]["desc"].clear()
    assert c.SKILLS[overview["skills"][0]["id"]]["desc"]


def test_automation_is_resolved_from_handler_registry_not_data_presence(monkeypatch):
    def fake_import(name, package=None):
        return types.SimpleNamespace(spell_automation=lambda spell_id: {"status": "automated" if spell_id == "fireball" else "reference", "reason": "handler check"})
    monkeypatch.setattr(c.importlib, "import_module", fake_import)
    assert c.lookup("spells", "fireball")["automation_status"] == "automated"
    assert c.lookup("spells", "wish")["automation_status"] == "reference"
    assert c.lookup("spells", "wish")["automation_reason"] == "handler check"
    assert "automation_status" not in c.SPELLS["wish"]


def test_missing_automation_module_falls_back_to_reference(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ImportError("not installed")
    monkeypatch.setattr(c.importlib, "import_module", unavailable)
    assert c.lookup("spells", "fireball")["automation_status"] == "reference"
    assert c.lookup("features", "rage")["automation_status"] == "reference"


@pytest.mark.parametrize("kind,kwargs", [("unknown", {}), ("spells", {"limit": 501}), ("spells", {"offset": -1}), ("spells", {"class_id": "artificer"}), ("spells", {"school": "unknown"})])
def test_invalid_catalog_filters_rejected(kind, kwargs):
    with pytest.raises(ValueError):
        c.get_catalog(kind, **kwargs)


@pytest.mark.parametrize("level", [0, 21, True, 1.0, "1"])
def test_invalid_class_level_rejected(level):
    with pytest.raises(ValueError):
        c.class_level("fighter", level)
