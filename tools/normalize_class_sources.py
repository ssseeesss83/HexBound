"""Reproduce reviewed class source corrections, preserving the raw archive."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "backend/data"


def normalize(text):
    text = re.sub(r"System Reference Document 5.1 \d+", "", text)
    return re.sub(r"[-\u2010\u2011]+", "-", re.sub(r"\s+", " ", text)).strip()


def corrections():
    pages = json.loads((ROOT / "official/pages.json").read_text(encoding="utf-8"))
    raw = {}
    for kind, filename in (("classes", "Classes"), ("subclasses", "Subclasses"), ("proficiencies", "Proficiencies")):
        raw[kind] = {row["index"]: row for row in json.loads((ROOT / f"srd2014/5e-SRD-{filename}.json").read_text(encoding="utf-8"))}
    result = []
    def field(kind, rid, path, value, page, heading):
        old = raw[kind][rid]
        for part in path:
            old = old.get(part) if isinstance(old, dict) else old[part]
        result.append({"id": "official-source-" + rid + "-" + str(path[-1]), "kind": kind,
                       "records": [rid], "page": page, "heading": heading, "operation": "set_field",
                       "path": path, "expected": old, "value": value})
    info = raw["classes"]["wizard"]["spellcasting"]["info"][:]
    page53 = "\n".join(pages[52]["columns"])
    body = page53.split("Learning Spells of 1st Level and Higher\n")[1].split("\nArcane Recovery")[0]
    info.append({"name": "Learning Spells of 1st Level and Higher", "desc": [normalize(body)], "source_pages": [53]})
    book = pages[53]["columns"][1].split("Your Spellbook\n")[1] + "\n" + pages[54]["columns"][0]
    info.append({"name": "Your Spellbook", "desc": [normalize(book)], "source_pages": [54, 55],
                 "learning_parameters": {"external_spell_min_level": 1, "external_spell_must_be_preparable": True,
                     "external_copy_hours_per_spell_level": 2, "external_copy_gp_per_spell_level": 50,
                     "own_book_copy_hours_per_spell_level": 1, "own_book_copy_gp_per_spell_level": 10,
                     "lost_book_recovery_source": "currently_prepared_spells", "remaining_lost_spells_require_rediscovery": True}})
    field("classes", "wizard", ["spellcasting", "info"], info, 53, "Learning Spells and Your Spellbook (53-55)")
    field("classes", "druid", ["spellcasting", "info", 4, "desc"],
          ['You can use a druidic focus (see “Equipment”) as a spellcasting focus for your druid spells.'], 20, "Spellcasting Focus")
    life = pages[16]["columns"][0].split("Life Domain\n")[1] + " " + pages[16]["columns"][1].split("\nLife Domain Spells")[0]
    field("subclasses", "life", ["desc"], [normalize(life)], 17, "Life Domain")
    for rid in ("disguise-kit", "forgery-kit"):
        field("proficiencies", rid, ["type"], "Other", 70, "Tools")
    for rid, mode, page in (("life", "always_prepared", 17), ("land", "always_prepared_selected_terrain", 21),
                             ("devotion", "always_prepared", 33), ("fiend", "expanded_spell_list", 50)):
        field("subclasses", rid, ["spell_grant_mode"], mode, page, "Subclass spell grant mode")
    fiend = "\n".join(pages[49]["columns"]).split("Expanded Spell List\n")[1].split("\nFiend Expanded Spells")[0]
    field("subclasses", "fiend", ["spell_grant_description"], normalize(fiend), 50, "Expanded Spell List")
    return result


if __name__ == "__main__":
    path = ROOT / "canonical-overlay.json"
    overlay = json.loads(path.read_text(encoding="utf-8"))
    new = corrections()
    ids = {row["id"] for row in new}
    overlay["corrections"] = [row for row in overlay["corrections"] if row["id"] not in ids] + new
    path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reviewed_source_corrections": len(new), "complete_signoff": False}))
