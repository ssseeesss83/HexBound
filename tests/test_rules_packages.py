"""P02: real atomic install, pinned data, canonical source and one registry."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from backend import capabilities, characters, compendium as c, rules_packages as p
from backend.store import Store


@pytest.fixture(scope="module")
def package():
    return p.build_legacy_package()


def resign(package):
    package.pop("digest", None)
    package["digest"] = hashlib.sha256(p.encode(package).encode()).hexdigest()
    return package


def test_full_install_is_idempotent_and_frozen_by_version(tmp_path, package):
    store = Store(str(tmp_path / "rules.sqlite3"))
    result = p.install_package(store, package)
    assert result["records"] == 2317 and not result["replayed"]
    assert p.install_package(store, package)["replayed"]
    assert p.lookup_installed(store, p.LEGACY_PACKAGE, "spells", "fireball")["desc"] == c.SPELLS["fireball"]["desc"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM rules_documents").fetchone()[0] == 403
        page = json.loads(db.execute("SELECT payload FROM rules_documents WHERE page=260").fetchone()[0])
        assert "Legendary" in page["text"]
    changed = deepcopy(package)
    changed["records"]["spells"]["fireball"]["desc"] = ["modified"]
    resign(changed)
    with pytest.raises(ValueError, match="snapshot|immutable"):
        p.install_package(store, changed)
    assert p.lookup_installed(store, p.LEGACY_PACKAGE, "spells", "fireball")["desc"] == c.SPELLS["fireball"]["desc"]


def test_partial_database_write_rolls_back_package_and_activation(tmp_path, package):
    store = Store(str(tmp_path / "atomic.sqlite3"))
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_mid_import BEFORE INSERT ON rules_records WHEN NEW.kind='spells' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        p.install_package(store, package)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM rules_packages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rules_records").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rules_activation").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["missing_feature", "missing_level", "dangling", "missing_material", "missing_page", "edition"])
def test_invalid_stage_cannot_activate(tmp_path, package, failure):
    stage = deepcopy(package)
    records = stage["records"]
    if failure == "missing_feature":
        records["features"].pop("rage")
    elif failure == "missing_level":
        records["levels"].pop("wizard-20")
    elif failure == "dangling":
        records["classes"]["fighter"]["subclasses"][0]["url"] = "/api/2014/subclasses/made-up"
    elif failure == "missing_material":
        records["spells"]["fireball"].pop("material")
    elif failure == "missing_page":
        stage["documents"].pop()
    else:
        records["spells"]["fireball"]["edition"] = "2024"
    resign(stage)
    store = Store(str(tmp_path / "invalid.sqlite3"))
    with pytest.raises(ValueError):
        p.install_package(store, stage)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM rules_packages").fetchone()[0] == 0


def test_canonical_wording_preserves_archive_and_cross_references():
    raw = json.loads((c.DATA_DIR / "srd2014/5e-SRD-Features.json").read_text(encoding="utf-8"))
    original = {row["index"]: row for row in raw}
    assert original["divine-domain"]["desc"] != c.FEATURES["divine-domain"]["desc"]
    assert "such as Life" in " ".join(c.FEATURES["divine-domain"]["desc"])
    assert "Great Old One" in c.FEATURES["otherworldly-patron"]["desc"][0]
    assert "Totem Warrior" in " ".join(c.FEATURES["primal-path"]["desc"])
    assert "Rages column" in c.FEATURES["rage"]["desc"][-1]
    assert c.FEATURES["aura-improvements"]["source_text_kind"] == "derived_advancement_alias"
    assert c.verify_source_integrity() == []
    assert all(row["source_refs"]["printed_pages"] for rows in c.COLLECTIONS.values() for row in rows.values())


def test_same_exact_registry_on_sheet_and_catalog():
    assert capabilities.audit_registry() == []
    fighter = characters.add_xp(characters.create_character("fighter"), 300)
    fighter = characters.level_up(fighter, {})
    bard = characters.create_character("bard")
    for character in (fighter, bard):
        sheet = characters.character_sheet(character)
        for feature in sheet["features"]:
            assert feature["automation_status"] == c.lookup("features", feature["id"])["automation_status"]
        for spell in sheet["spell_details"]:
            assert spell["automation_status"] == c.lookup("spells", spell["id"])["automation_status"]
    assert capabilities.FEATURE_BINDINGS["action-surge-1-use"]["handler"] == "action-surge"
    assert capabilities.FEATURE_BINDINGS["bardic-inspiration-d6"]["handler"] == "bardic-inspiration"
    assert capabilities.spell_automation("hex")["status"] == "reference"


def test_new_and_legacy_characters_pin_package_without_healing():
    character = characters.create_character("fighter")
    assert character["rules_package_version"] == p.LEGACY_PACKAGE
    character.pop("rules_package_version")
    character["hp"] = 1
    character["resources"]["second-wind"]["current"] = 0
    migrated = characters.migrate_character(character)
    assert migrated["rules_package_version"] == p.LEGACY_PACKAGE
    assert migrated["hp"] == 1 and migrated["resources"]["second-wind"]["current"] == 0


def test_unsigned_candidate_cannot_activate(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "SIGNOFF_PATH", tmp_path / "absent-signoff.json")
    store = Store(str(tmp_path / "unsigned.sqlite3"))
    with pytest.raises(ValueError, match="signoff is pending"):
        p.install_package(store, p.build_package())
    with store.connect() as db:
        assert not db.execute("SELECT * FROM rules_activation").fetchall()


def test_candidate_metadata_changes_cannot_change_historical_package(tmp_path, package, monkeypatch):
    store = Store(str(tmp_path / "stable-history.sqlite3"))
    p.install_package(store, package)
    monkeypatch.setitem(c.CANONICAL_OVERLAY, "new_candidate_review", "new review")
    assert p.build_legacy_package() == package
    assert p.install_package(store, p.build_legacy_package())["replayed"]


@pytest.mark.parametrize("failure", ["url", "owner", "material", "edition", "level"])
def test_structural_validator_independently_checks_source_relations(package, failure):
    records = deepcopy(package["records"])
    if failure == "url":
        records["classes"]["fighter"]["subclasses"][0]["index"] = "life"
    elif failure == "owner":
        records["subclasses"]["champion"]["class"] = deepcopy(records["subclasses"]["life"]["class"])
    elif failure == "material":
        records["spells"]["fireball"]["material"] = ""
    elif failure == "edition":
        records["spells"]["fireball"]["edition"] = "2024"
    else:
        records["levels"].pop("wizard-20")
    assert p.validate_records(records)


def test_official_spell_header_extraction_is_reproducible_and_matches_canonical():
    from backend.source_audit import key
    from tools.audit_spell_headers import extract
    rows = extract()
    assert rows == json.loads((c.DATA_DIR / "official/spell-blocks.json").read_text(encoding="utf-8"))
    spells = {key(row["name"]): row for row in c.SPELLS.values()}
    for row in rows:
        spell = spells[key(row["official_title"])]
        for field in row["audited_fields"]:
            left, right = spell.get(field), row[field]
            if isinstance(left, str) and isinstance(right, str):
                assert key(left) == key(right), (spell["index"], field)
            else:
                assert left == right, (spell["index"], field)


def test_installed_snapshot_survives_global_data_changes_and_unknown_version_fails(tmp_path, package, monkeypatch):
    from backend.rules_context import active_store, using_version
    store = Store(str(tmp_path / "frozen.sqlite3"))
    p.install_package(store, package)
    monkeypatch.setitem(c.SPELLS["fireball"], "range", "changed global range")
    with active_store(store), using_version(p.LEGACY_PACKAGE) as view:
        assert view.lookup("spells", "fireball")["range"] == "150 feet"
        with pytest.raises(ValueError, match="unavailable"):
            with using_version("missing-package"):
                pass


def test_registry_disabling_handler_blocks_menu_and_execution(tmp_path, package):
    from backend import abilities
    from backend.rules_context import active_store, using_version, RulesView, _VIEW
    store = Store(str(tmp_path / "registry.sqlite3"))
    p.install_package(store, package)
    with active_store(store), using_version(p.LEGACY_PACKAGE) as installed:
        # A test-local view models a different capability profile without
        # mutating either the installed immutable snapshot or production data.
        bindings = deepcopy(installed.FEATURE_BINDINGS)
        bindings["second-wind"]["status"] = "reference"
        metadata = {"feature_bindings": bindings, "xp_thresholds": installed.XP_THRESHOLDS,
                    "spell_effects": installed.SPELL_EFFECTS, "action_features": installed.ACTION_FEATURES}
        view = RulesView(p.LEGACY_PACKAGE, installed.COLLECTIONS, metadata)
        token = _VIEW.set(view)
        try:
            character = characters.create_character("fighter")
            character["hp"] = 1
            state = {"rules_package_version": p.LEGACY_PACKAGE,
                     "members": [{"id": "p", "name": "Hero", "character": character}]}
            action = next(row for row in abilities.capabilities(state, "p") if row["id"] == "feature:second-wind")
            assert action["automation_status"] == "reference" and not action["supported"]
            before = deepcopy(state)
            with pytest.raises(ValueError):
                abilities.apply_action(state, "p", "feature:second-wind", "p")
            assert state == before
        finally:
            _VIEW.reset(token)


def test_new_activation_does_not_rewrite_existing_character_rules(tmp_path, package, monkeypatch):
    from backend.rules_context import active_store, using_version, active_version
    store = Store(str(tmp_path / "versions.sqlite3"))
    p.install_package(store, package)
    candidate = p.build_package()
    candidate["records"]["spells"]["fireball"]["range"] = "test-only second-version range"
    resign(candidate)
    # Test-only approval in a disposable directory; production remains unsigned.
    approval = tmp_path / "test-approval.json"
    approval.write_text(json.dumps({"status": "approved", "package_digest": candidate["digest"],
                                   "source_document_sha256": candidate["source_manifest"]["original"]["sha256"]}), encoding="utf-8")
    monkeypatch.setattr(p, "SIGNOFF_PATH", approval)
    p.install_package(store, candidate)
    with active_store(store):
        assert active_version() == p.PACKAGE_VERSION
        with using_version(p.LEGACY_PACKAGE) as old:
            assert old.lookup("spells", "fireball")["range"] == "150 feet"
            assert characters.create_character("fighter")["rules_package_version"] == p.LEGACY_PACKAGE
        with using_version() as new:
            assert new.lookup("spells", "fireball")["range"] == "test-only second-version range"
            assert characters.create_character("fighter")["rules_package_version"] == p.PACKAGE_VERSION
