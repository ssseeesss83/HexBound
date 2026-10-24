"""Versioned, atomic offline rules installation; never an LLM write surface."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import gzip
import json
import re

from . import compendium
from .source_audit import collection_report, RULESET_ID
from .rules_identity import PACKAGE_VERSION, LEGACY_PACKAGE, ENGINE_PROFILE
SIGNOFF_PATH = compendium.DATA_DIR / "transcription-signoff.json"


def encode(value):
    # JSON object keys are strings. Normalize before sorting so an in-memory
    # integer-keyed level table hashes identically after storage and reload.
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def unreachable_features(records):
    def references(value):
        if isinstance(value, dict):
            url = value.get("url", "")
            if url.startswith("/api/2014/features/"):
                yield url.rsplit("/", 1)[1]
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)
    reached = set()
    pending = list(references(list(records.get("levels", {}).values())))
    while pending:
        fid = pending.pop()
        if fid in reached or fid not in records.get("features", {}):
            continue
        reached.add(fid)
        pending.extend(references(records["features"][fid].get("feature_specific", {})))
    return sorted(set(records.get("features", {})) - reached)


def validate_records(records, *, inventory=None):
    canonical = inventory is None
    inventory = compendium.COLLECTIONS if inventory is None else inventory
    errors = []
    if canonical:
        from .class_growth import growth_issues
        from .armor_source import issues as armor_issues
        from .equipment_source import issues as equipment_issues
        from .equipment_contents import issues as pack_issues
        from .equipment_bodies import issues as equipment_body_issues
        from .magic_shields import issues as magic_shield_issues
        from .magic_inventory import issues as magic_inventory_issues
        from .magic_bodies import issues as magic_body_issues
        from .magic_headers import issues as magic_header_issues
        from .magic_bonus_variants import issues as magic_bonus_issues
        from .magic_consumable_variants import issues as magic_consumable_issues
        from .magic_giant_variants import issues as magic_giant_issues
        from .magic_affinity_variants import issues as magic_affinity_issues
        from .magic_crafting_variants import issues as magic_crafting_issues
        from .magic_bag_variants import issues as magic_bag_issues
        from .magic_scrying_variants import issues as magic_scrying_issues
        from .magic_feather_variants import issues as magic_feather_issues
        from .magic_figurine_ioun_variants import issues as magic_named_issues
        from .monster_inventory import issues as monster_inventory_issues
        from .monster_legendary import issues as monster_legendary_issues
        from .monster_headers import issues as monster_header_issues
        from .monster_bodies import issues as monster_body_issues
        from .monster_action_bodies import issues as monster_action_body_issues
        from .monster_attack_damage import issues as monster_attack_damage_issues
        from .monster_usage import issues as monster_usage_issues
        errors.extend(growth_issues(records))
        errors.extend(armor_issues(records))
        errors.extend(equipment_issues(records))
        errors.extend(pack_issues(records))
        errors.extend(equipment_body_issues(records))
        errors.extend(magic_shield_issues(records))
        errors.extend(magic_inventory_issues(records))
        errors.extend(magic_body_issues(records))
        errors.extend(magic_header_issues(records))
        errors.extend(magic_bonus_issues(records))
        errors.extend(magic_consumable_issues(records))
        errors.extend(magic_giant_issues(records))
        errors.extend(magic_affinity_issues(records))
        errors.extend(magic_crafting_issues(records))
        errors.extend(magic_bag_issues(records))
        errors.extend(magic_scrying_issues(records))
        errors.extend(magic_feather_issues(records))
        errors.extend(magic_named_issues(records))
        errors.extend(monster_inventory_issues(records))
        errors.extend(monster_legendary_issues(records))
        errors.extend(monster_header_issues(records))
        errors.extend(monster_body_issues(records))
        errors.extend(monster_action_body_issues(records))
        errors.extend(monster_attack_damage_issues(records))
        errors.extend(monster_usage_issues(records))
        errors.extend("Feature is unreachable from class grants or choices: " + fid for fid in unreachable_features(records))
    if set(records) != set(inventory):
        errors.append("Rules collection set is incomplete")
    for kind, expected in inventory.items():
        if set(records.get(kind, {})) != set(expected):
            errors.append("Rules record inventory differs: " + kind)
    classes = records.get("classes", {})
    if set(classes) != set(compendium.CLASS_NAMES_ZH):
        errors.append("Core class inventory is incomplete")
    if set(records.get("skills", {})) != set(compendium.SKILL_NAMES_ZH):
        errors.append("Standard skill inventory is incomplete")
    if set(records.get("subclasses", {})) != set(compendium.SUBCLASS_NAMES_ZH):
        errors.append("Selected subclass inventory is incomplete")
    levels = records.get("levels", {})
    for lid, row in levels.items():
        for ref in row.get("features", []):
            feature = records.get("features", {}).get(ref.get("index"), {})
            if feature and (feature.get("class", {}).get("index") != row.get("class", {}).get("index")
                            or feature.get("level") != row.get("level")
                            or (feature.get("subclass") and feature["subclass"]["index"] != row.get("subclass", {}).get("index"))):
                errors.append("Feature grant class/subclass/level mismatch: " + lid + "/" + ref.get("index", ""))
    for class_id in classes:
        for ref in classes[class_id].get("subclasses", []):
            target = records.get("subclasses", {}).get(ref.get("index"), {})
            if target.get("class", {}).get("index") != class_id:
                errors.append("Subclass does not belong to class: " + class_id)
        actual = {row["level"] for row in levels.values() if row.get("class", {}).get("index") == class_id and not row.get("subclass")}
        if actual != set(range(1, 21)):
            errors.append("Incomplete class advancement: " + class_id)
    required_spell_fields = {"name", "level", "range", "components", "ritual", "duration", "concentration", "casting_time", "school", "classes", "desc"}
    for sid, row in records.get("spells", {}).items():
        if required_spell_fields - set(row) or not any(paragraph.strip() for paragraph in row.get("desc", [])):
            errors.append("Incomplete spell fields: " + sid)
        if "M" in row.get("components", []) and not row.get("material"):
            errors.append("Missing spell materials: " + sid)
    for kind, rows in records.items():
        for rid, row in rows.items():
            if row.get("index") != rid or row.get("edition") != "2014":
                errors.append(f"Invalid record identity/version: {kind}/{rid}")
            def walk(value, field=None):
                if isinstance(value, dict):
                    if isinstance(value.get("url"), str) and "index" in value:
                        level_ref = re.fullmatch(r"/api/2014/(?:classes|subclasses)/([^/]+)/levels/(\d+)", value["url"])
                        if level_ref:
                            level_id = level_ref[1] + "-" + level_ref[2]
                            if value["index"] != level_id or level_id not in records.get("levels", {}):
                                errors.append("Invalid level reference: " + value["url"])
                        target = re.fullmatch(r"/api/2014/([^/]+)/([^/]+)", value["url"])
                        if target and target[2] != value["index"]:
                            errors.append("Reference ID/URL mismatch: " + value["url"])
                    for name, child in value.items():
                        walk(child, name)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
                elif isinstance(value, str):
                    if value.startswith("/api/2024/"):
                        errors.append("Cross-edition reference: " + value)
                    match = re.fullmatch(r"/api/2014/([^/]+)/([^/]+)", value)
                    if field in {"url", "reference"} and match and match[1] in records and match[2] not in records[match[1]]:
                        errors.append("Unresolved reference: " + value)
            walk(row)
    return sorted(set(errors))


def build_package():
    from . import abilities
    from .capabilities import audit_registry, FEATURE_BINDINGS
    report = collection_report()
    errors = report["errors"] + compendium.verify_source_integrity()
    if not report["collection_complete"] or errors:
        raise ValueError("Source collection gate failed: " + "; ".join(errors))
    records = deepcopy(compendium.COLLECTIONS)
    errors = validate_records(records) + audit_registry()
    if errors:
        raise ValueError("Rules staging failed: " + "; ".join(errors))
    source_manifest = json.loads((compendium.DATA_DIR / "official/manifest.json").read_text(encoding="utf-8"))
    pages = json.loads((compendium.DATA_DIR / "official/pages.json").read_text(encoding="utf-8"))
    package = {"ruleset_id": RULESET_ID, "package_version": PACKAGE_VERSION,
               "source_manifest": source_manifest, "transcription_manifest": compendium.SOURCE,
               "corrections": deepcopy(compendium.ERRATA), "canonical_corrections": deepcopy(compendium.CANONICAL_OVERLAY), "records": records,
               "feature_bindings": deepcopy(FEATURE_BINDINGS),
               "xp_thresholds": deepcopy(compendium.XP_THRESHOLDS),
               "spell_effects": deepcopy(abilities.SPELL_EFFECTS), "action_features": deepcopy(abilities.FEATURES),
               "documents": [{"page": row["page"], "text": row["text"], "columns": row["columns"]} for row in pages],
               "validation": {"source_collection": "passed", "structural_relations": "passed",
                              "mechanical_completeness": False, "engine_profile": ENGINE_PROFILE}}
    package["digest"] = hashlib.sha256(encode(package).encode()).hexdigest()
    return package


def build_legacy_package():
    """Read the frozen historical runtime, independent of candidate auditing."""
    blob = (compendium.DATA_DIR / "legacy-v06-package.json.gz").read_bytes()
    expected = "4633ce0e49c5119a0d6e459568b874bfad94d5505f30d7f5d9a84575c75daad3"
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError("Frozen historical rules snapshot failed integrity validation")
    return json.loads(gzip.decompress(blob))


def legacy_records():
    return build_legacy_package()["records"]


def validate_admission(package):
    """A caller-recomputed digest is not a source approval signature."""
    if package["package_version"] == LEGACY_PACKAGE:
        expected = build_legacy_package()
        if package["digest"] != expected["digest"]:
            raise ValueError("Historical package does not match its pinned source snapshot")
        return
    # Until the independent per-record official transcription review is complete,
    # P02 candidates are staging data only. No client or test may self-approve.
    signoff_path = SIGNOFF_PATH
    if not signoff_path.is_file():
        raise ValueError("Official structured transcription signoff is pending; staging cannot be activated")
    signoff = json.loads(signoff_path.read_text(encoding="utf-8"))
    if signoff.get("status") != "approved" or signoff.get("package_digest") != package["digest"] or signoff.get("source_document_sha256") != package["source_manifest"]["original"]["sha256"]:
        raise ValueError("Staged package has no matching official transcription signoff")


def install_package(store, package=None):
    """All rows and activation commit together, with version and digest checks.

    A caller may supply a staged package for migration/validation tests. All
    identity, structural and content hash checks still run before any writes.
    """
    package = deepcopy(package) if package is not None else build_package()
    validate_admission(package)
    digest = package.pop("digest", None)
    if hashlib.sha256(encode(package).encode()).hexdigest() != digest:
        raise ValueError("Package digest mismatch")
    if package.get("ruleset_id") != RULESET_ID:
        raise ValueError("Unknown ruleset")
    inventory = build_legacy_package()["records"] if package["package_version"] == LEGACY_PACKAGE else None
    errors = validate_records(package["records"], inventory=inventory)
    if [row["page"] for row in package.get("documents", [])] != list(range(1, 404)):
        errors.append("Official rule documents are incomplete")
    if errors:
        raise ValueError("Invalid staged rules: " + "; ".join(errors))
    rows = [(kind, rid, encode(record)) for kind, entries in package["records"].items() for rid, record in entries.items()]
    metadata = {key: value for key, value in package.items() if key not in {"records", "documents"}}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS rules_packages (version TEXT PRIMARY KEY, ruleset_id TEXT NOT NULL, digest TEXT NOT NULL, metadata TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS rules_records (package_version TEXT NOT NULL REFERENCES rules_packages(version), kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(package_version,kind,id))")
        db.execute("CREATE TABLE IF NOT EXISTS rules_activation (ruleset_id TEXT PRIMARY KEY, package_version TEXT NOT NULL REFERENCES rules_packages(version))")
        db.execute("CREATE TABLE IF NOT EXISTS rules_documents (package_version TEXT NOT NULL REFERENCES rules_packages(version), page INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(package_version,page))")
        previous = db.execute("SELECT digest FROM rules_packages WHERE version=?", (package["package_version"],)).fetchone()
        if previous:
            if previous["digest"] != digest:
                raise ValueError("Rules package versions are immutable")
            count = db.execute("SELECT COUNT(*) FROM rules_records WHERE package_version=?", (package["package_version"],)).fetchone()[0]
            if count != len(rows):
                raise ValueError("Installed rules package is incomplete")
            if db.execute("SELECT COUNT(*) FROM rules_documents WHERE package_version=?", (package["package_version"],)).fetchone()[0] != 403:
                raise ValueError("Installed official documents are incomplete")
            return {"version": package["package_version"], "digest": digest, "replayed": True, "records": len(rows)}
        db.execute("INSERT INTO rules_packages VALUES(?,?,?,?)", (package["package_version"], RULESET_ID, digest, encode(metadata)))
        db.executemany("INSERT INTO rules_records VALUES(?,?,?,?)", [(package["package_version"], *row) for row in rows])
        db.executemany("INSERT INTO rules_documents VALUES(?,?,?)", [(package["package_version"], row["page"], encode(row)) for row in package["documents"]])
        db.execute("INSERT INTO rules_activation VALUES(?,?) ON CONFLICT(ruleset_id) DO UPDATE SET package_version=excluded.package_version", (RULESET_ID, package["package_version"]))
    return {"version": package["package_version"], "digest": digest, "replayed": False, "records": len(rows)}


def lookup_installed(store, version, kind, record_id):
    with store.connect() as db:
        row = db.execute("SELECT payload FROM rules_records WHERE package_version=? AND kind=? AND id=?", (version, kind, record_id)).fetchone()
    if row is None:
        raise ValueError("Pinned rules record does not exist")
    return json.loads(row["payload"])
