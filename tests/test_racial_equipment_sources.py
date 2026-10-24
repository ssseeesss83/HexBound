"""Limited official-source checks; these do not certify engine execution."""
import json
import re

from backend import compendium as c, rules_packages


def norm(text):
    return re.sub(r"\s+", " ", text.replace("\u00ad", "")).strip()


def test_all_reviewed_weapon_values_still_match_official_evidence():
    review = json.loads((c.DATA_DIR / "official/racial-equipment-review.json").read_text(encoding="utf-8"))
    pages = json.loads((c.DATA_DIR / "official/pages.json").read_text(encoding="utf-8"))
    checks = review["weapon_numeric_and_property_checks"]
    assert len(checks) == 203
    assert len({row["record"] for row in checks}) == 37
    for row in checks:
        kind, key = row["record"].split("/")
        assert kind == "equipment"
        value = c.EQUIPMENT[key]
        for part in row["path"]:
            value = value[part]
        if row["path"] == ["properties"]:
            value = sorted(ref["index"] for ref in value if ref["index"] != "monk")
        assert value == row["expected_official_value"], row
        page = pages[row["official_page"] - 1]
        assert norm(row["official_line"]) in norm(page["text"]), row


def test_draconic_line_width_is_reference_only_and_cones_are_unchanged():
    lines = {"black", "blue", "brass", "bronze", "copper"}
    for color in lines | {"gold", "green", "red", "silver", "white"}:
        breath = c.TRAITS[f"draconic-ancestry-{color}"]["trait_specific"]["breath_weapon"]
        if color in lines:
            assert breath["area_of_effect"] == {"size": 30, "type": "line", "width_ft": 5}
            assert breath["geometry_status"] == "reference_pending_execution"
        else:
            assert breath["area_of_effect"] == {"size": 15, "type": "cone"}


def test_range_body_matches_complete_official_heading_interval():
    pages = json.loads((c.DATA_DIR / "official/pages.json").read_text(encoding="utf-8"))
    column = norm(pages[64]["columns"][0])
    source = column.split("Range. ", 1)[1].split("Reach. ", 1)[0].strip()
    record = c.WEAPON_PROPERTIES["range"]
    assert norm(" ".join(record["desc"])) == source
    assert record["source_refs"]["printed_pages"] == [65]
    assert record["status"] == "reference_pending_execution"
    assert record["runtime_verified"] is False
    assert not any(ref["index"] == "range" for item in c.EQUIPMENT.values() for ref in item.get("properties", []))


def test_derived_monk_mapping_and_high_elf_typo_have_no_legacy_mutation():
    assert c.WEAPON_PROPERTIES["monk"]["source_refs"]["printed_pages"] == [26, 27]
    assert c.WEAPON_PROPERTIES["monk"]["source_refs"]["mapping_type"] == "derived_class_weapon_classification"
    assert "choice from the wizard spell list" in c.TRAITS["high-elf-cantrip"]["desc"][0]
    legacy = rules_packages.build_legacy_package()["records"]
    assert "range" not in legacy["weapon-properties"]
    assert "width_ft" not in legacy["traits"]["draconic-ancestry-black"]["trait_specific"]["breath_weapon"]["area_of_effect"]
    assert "choice form the wizard spell list" in legacy["traits"]["high-elf-cantrip"]["desc"][0]
