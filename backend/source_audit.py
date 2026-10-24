"""Offline official-source collection gates, separate from mechanical support.

The community archive remains a candidate transcription. Preserving an entire
official page closes a collection gap; it does not certify every parsed field.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).parent / "data"
RULESET_ID = "dnd5e-2014-srd5.1"
OFFICIAL_PDF_SHA = "2504d2a0abb0a4d491a939be4f17910a2dde0312570ab8d208080225ccf0a1f0"

# Printed-page ranges reviewed against the official 5.1 document. Ranges
# overlap where a section starts in the second column of a page.
SECTIONS = [
    ("legal", 1, 2), ("races", 3, 7),
    ("barbarian", 8, 10), ("bard", 11, 14), ("cleric", 15, 18),
    ("druid", 19, 23), ("fighter", 24, 25), ("monk", 26, 29),
    ("paladin", 30, 34), ("ranger", 35, 38), ("rogue", 39, 41),
    ("sorcerer", 42, 45), ("warlock", 46, 51), ("wizard", 52, 55),
    ("advancement-multiclassing", 56, 58), ("alignment-languages-inspiration", 58, 60),
    ("backgrounds", 60, 61), ("equipment", 62, 74), ("feats", 75, 75),
    ("abilities-skills-saves", 76, 83), ("adventuring", 84, 89), ("combat", 90, 99),
    ("spellcasting", 100, 104), ("spell-lists", 105, 113), ("spell-descriptions", 114, 194),
    ("traps", 195, 198), ("diseases", 199, 200), ("madness", 201, 202),
    ("objects", 203, 203), ("poisons", 204, 205), ("magic-items", 206, 253),
    ("monster-rules", 254, 260), ("monster-statblocks", 261, 357),
    ("conditions", 358, 359), ("pantheons", 360, 362), ("planes", 363, 365),
    ("miscellaneous-creatures", 366, 394), ("npc-statblocks", 395, 403),
]
TABLE_HEADINGS_IN_SPELLS = {"Animated Object Statistics", "Precipitation", "Temperature", "Wind"}
SUBCLASS_TITLES = {
    "berserker": "Path of the Berserker", "lore": "College of Lore", "life": "Life Domain",
    "land": "Circle of the Land", "champion": "Champion", "open-hand": "Way of the Open Hand",
    "devotion": "Oath of Devotion", "hunter": "Hunter", "thief": "Thief",
    "draconic": "Draconic Bloodline", "fiend": "The Fiend", "evocation": "School of Evocation",
}


def key(text):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).casefold())


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _collection_report(root):
    official = Path(root) / "official"
    errors = []
    try:
        manifest = _load(official / "manifest.json")
        descriptors = [manifest["original"], *manifest["derived"]]
        for entry in descriptors:
            path = (official / entry["file"]).resolve()
            if not path.is_relative_to(official.resolve()) or not path.is_file():
                errors.append("Missing source: " + entry["file"])
                continue
            raw = path.read_bytes()
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                errors.append("Source bytes changed: " + entry["file"])
        if manifest["original"]["sha256"] != OFFICIAL_PDF_SHA or manifest["ruleset_id"] != RULESET_ID:
            errors.append("Wrong official source version")
        pages, headings = _load(official / "pages.json"), _load(official / "headings.json")
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"ruleset_id": RULESET_ID, "collection_complete": False, "errors": [f"Invalid corpus: {type(exc).__name__}"]}
    if [row["page"] for row in pages] != list(range(1, 404)):
        errors.append("Official pages must be exactly 1..403")
    for row in pages:
        if row["page"] != 2 and (not row.get("text") or not row.get("raw_text")):
            errors.append(f"Missing reading text on page {row['page']}")
    covered = set()
    chapters = []
    for name, lo, hi in SECTIONS:
        numbers = list(range(lo, hi + 1))
        covered.update(numbers)
        chapters.append({"id": name, "printed_pages": numbers, "source_status": "collected",
                         "raw_records": [f"official-page:{page}" for page in numbers],
                         "mapping_type": "full_official_text", "structure_status": "pending_P02"})
    if covered != set(range(1, 404)):
        errors.append("Official chapter map leaves page gaps")
    # Candidate collection must remain complete relative to its pinned archive.
    # Transcription accuracy is a separate P02 gate, not inferred from hashes.
    upstream = _load(Path(root) / "source-manifest.json")
    candidate_records = []
    for descriptor in upstream["files"]:
        path = Path(root) / descriptor["file"]
        if not path.is_file():
            errors.append("Missing candidate archive: " + descriptor["file"])
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"] or len(raw) != descriptor["bytes"]:
            errors.append("Candidate archive changed: " + descriptor["file"])
        try:
            rows = json.loads(raw)
            if len(rows) != descriptor["records"]:
                errors.append("Candidate record count changed: " + descriptor["file"])
            for row in rows:
                candidate_records.append({"local_record_id": row["index"], "name": row.get("name", row["index"]),
                                          "raw_file": descriptor["file"], "source_status": "collected_candidate",
                                          "structure_status": "pending_P02", "class_id": row.get("class", {}).get("index")})
        except (ValueError, KeyError, TypeError):
            errors.append("Invalid candidate records: " + descriptor["file"])
    if errors:
        return {"ruleset_id": RULESET_ID, "collection_complete": False, "errors": errors}
    classes = _load(Path(root) / "srd2014/5e-SRD-Classes.json")
    class_inventory = []
    for row in classes:
        matching = [h for h in headings if h["size"] > 25 and key(h["title"]) == key(row["name"])]
        if len(matching) != 1:
            errors.append("Missing or duplicate official class: " + row["index"])
        class_inventory.append({"local_record_id": row["index"], "official_locations": matching})
    subclass_inventory = []
    for rid, title in SUBCLASS_TITLES.items():
        matching = [h for h in headings if 8 <= h["page"] <= 55 and key(h["title"]) == key(title)]
        if len(matching) != 1:
            errors.append("Missing or duplicate official subclass: " + rid)
        subclass_inventory.append({"local_record_id": rid, "official_title": title, "official_locations": matching})
    skills = _load(Path(root) / "srd2014/5e-SRD-Skills.json")
    skill_inventory = []
    for row in skills:
        locations = [p["page"] for p in pages if 76 <= p["page"] <= 83 and key(row["name"]) in key(p["text"])]
        if not locations:
            errors.append("Missing official skill: " + row["index"])
        skill_inventory.append({"local_record_id": row["index"], "printed_pages": locations})
    # The inventory is independently read from official typography, before
    # comparison with community IDs. Four spell tables are explicit exceptions.
    spell_headings = [h for h in headings if 114 <= h["page"] <= 194 and 11.8 <= h["size"] <= 12.2
                      and h["title"] not in TABLE_HEADINGS_IN_SPELLS]
    spell_names = [key(h["title"]) for h in spell_headings]
    if len(spell_names) != len(set(spell_names)):
        errors.append("Duplicate official spell headings")
    upstream_spells = _load(Path(root) / "srd2014/5e-SRD-Spells.json")
    local_spells = {key(row["name"]): row["index"] for row in upstream_spells}
    if set(spell_names) != set(local_spells):
        errors.append("Official/community spell inventory differs")
    official_entries = []
    for i, heading in enumerate(headings):
        official_entries.append({"official_entry_key": f"heading:{i + 1}", **heading,
                                 "source_document_sha256": OFFICIAL_PDF_SHA,
                                 "raw_record": f"official-page:{heading['page']}",
                                 "source_status": "collected",
                                 "structure_status": "pending_P02"})
    return {"ruleset_id": RULESET_ID, "collection_complete": not errors, "errors": errors,
            "official_pages": len(pages), "chapters": chapters, "official_entries": official_entries,
            "candidate_records": candidate_records, "class_inventory": class_inventory,
            "subclass_inventory": subclass_inventory, "skill_inventory": skill_inventory,
            "official_spell_inventory": [{"name": h["title"], "printed_page": h["page"],
                                           "local_record_id": local_spells.get(key(h["title"]))}
                                          for h in spell_headings],
            "scope": {"included": "Complete official SRD 5.1 PDF, including appendices",
                      "excluded": ["PHB 2014 material outside SRD 5.1", "commercial supplements", "2024 / SRD 5.2"],
                      "basic_rules_note": "Basic Rules is a separate publication; only text actually in this pinned SRD is included."},
            "transcription_status": "candidate_only_not_signed_off",
            "mechanical_support": "not_evaluated_by_collection_gate"}


def collection_report(root=ROOT):
    try:
        return _collection_report(root)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"ruleset_id": RULESET_ID, "collection_complete": False,
                "errors": [f"Invalid corpus: {type(exc).__name__}"]}


def main():
    report = collection_report()
    print(json.dumps({key: value for key, value in report.items() if key not in {"chapters", "official_entries", "official_spell_inventory", "candidate_records", "class_inventory", "subclass_inventory", "skill_inventory"}}, ensure_ascii=False, indent=2))
    raise SystemExit(not report["collection_complete"])


if __name__ == "__main__":
    main()
