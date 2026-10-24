"""Independent official spell blocks and header fields from collected columns.

This audits source metadata only. It does not approve damage, saving throws,
targets, higher-level effects or mechanical execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.source_audit import key, TABLE_HEADINGS_IN_SPELLS, OFFICIAL_PDF_SHA


def normalize_header(text):
    # This PDF draws several hyphen glyphs at the same position. Preserve the
    # original extraction separately and collapse that typography for fields.
    return re.sub(r"[-\u2010\u2011]+", "-", text)


def extract():
    root = ROOT / "backend/data/official"
    pages = json.loads((root / "pages.json").read_text(encoding="utf-8"))
    headings = json.loads((root / "headings.json").read_text(encoding="utf-8"))
    headings = [h for h in headings if 114 <= h["page"] <= 194 and 11.8 <= h["size"] <= 12.2
                and h["title"] not in TABLE_HEADINGS_IN_SPELLS]
    lines = []
    for page in pages:
        if not 114 <= page["page"] <= 194:
            continue
        for column, text in enumerate(page["columns"]):
            for line in text.splitlines():
                if "System Reference Document 5.1" in line or not line.strip():
                    continue
                lines.append({"page": page["page"], "column": column, "text": line.strip()})
    starts = []
    for heading in headings:
        matches = [i for i, line in enumerate(lines) if line["page"] == heading["page"] and line["column"] == heading["column"]
                   and key(line["text"]) == key(heading["title"])
                   and i + 1 < len(lines) and re.search(r"cantrip|level", lines[i + 1]["text"], re.I)]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous official spell heading: {heading['title']}: {len(matches)}")
        starts.append((matches[0], heading))
    starts.sort()
    result = []
    for offset, (start, heading) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        block = "\n".join(row["text"] for row in block_lines)
        match = re.search(r"Casting Time:\s*(.*?)\nRange:\s*(.*?)\nComponents?:\s*(.*?)\nDuration:\s*([^\n]+)", block, re.S)
        if match is None:
            raise ValueError("Missing official headers: " + heading["title"])
        casting, range_text, components_text, duration = (normalize_header(re.sub(r"\s+", " ", value).strip()) for value in match.groups())
        component_letters = re.match(r"[VSM,\s]+", components_text)
        components = re.findall(r"[VSM]", component_letters[0])
        material = components_text[components_text.find("(") + 1:components_text.rfind(")")] if "M" in components else None
        subtitle = normalize_header(block_lines[1]["text"])
        level_match = re.search(r"([1-9])(?:st|nd|rd|th)-?level", subtitle, re.I)
        level = int(level_match[1]) if level_match else 0
        concentration = "concentration" in duration.casefold()
        result.append({"official_title": heading["title"], "source_document_sha256": OFFICIAL_PDF_SHA,
                       "printed_pages": sorted({row["page"] for row in block_lines}),
                       "casting_time": casting, "range": range_text, "components": components,
                       "material": material, "duration_header": duration,
                       "duration": re.sub(r"^Concentration,\s*", "", duration, flags=re.I),
                       "concentration": concentration, "ritual": "ritual" in subtitle.casefold(),
                       "level": level, "official_text": block, "audited_fields": ["level", "ritual", "concentration", "components", "material", "casting_time", "range", "duration"]})
    if len(result) != 319:
        raise ValueError("Official spell block count differs")
    return result


if __name__ == "__main__":
    output = ROOT / "backend/data/official/spell-blocks.json"
    rows = extract()
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"official_spell_blocks": len(rows), "output": str(output.relative_to(ROOT)), "mechanical_signoff": False}))
