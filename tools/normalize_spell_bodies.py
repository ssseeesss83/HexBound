"""Reproduce the reviewed official spell-body overlays without changing archives.

The review inventory deliberately excludes ambiguous source and table layouts.
Whitespace/hyphen normalization only; never correct rule wording from memory.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend/data"


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"[-\u2010\u2011]+", "-", text)).strip()


def body_fields(block):
    body = re.split(r"Duration:[^\n]*\n", block["official_text"], maxsplit=1)[1]
    parts = re.split(r"At Higher Levels\.", body, maxsplit=1, flags=re.I)
    return {"desc": [clean(parts[0])], "higher_level": [clean(parts[1])] if len(parts) == 2 else []}


def corrections():
    review = json.loads((ROOT / "official/spell-body-review.json").read_text(encoding="utf-8"))
    blocks = json.loads((ROOT / "official/spell-blocks.json").read_text(encoding="utf-8"))
    blocks = {row["official_title"]: row for row in blocks}
    result = []
    for row in review["differences"]:
        if row["status"] != "ready_for_source_text_overlay":
            continue
        fields = body_fields(blocks[row["official_title"]])
        if fields != row["recommended_canonical_fields"]:
            raise ValueError(f"Reviewed source changed: {row['id']}")
        for field, value in fields.items():
            old = row["expected_canonical_fields"][field]
            if old == value:
                continue
            result.append({"id": f"official-body-{row['id']}-{field}", "kind": "spells",
                           "records": [row["id"]], "page": row["printed_pages"][0],
                           "heading": row["official_title"], "operation": "set_field", "path": [field],
                           "expected": old, "value": value})
    return result


if __name__ == "__main__":
    path = ROOT / "canonical-overlay.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    additions = corrections()
    data["corrections"] = [r for r in data["corrections"] if not r["id"].startswith("official-body-")] + additions
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reviewed_body_fields": len(additions), "complete_signoff": False}))
