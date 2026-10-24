"""Reproduce the offline official corpus. No runtime import or online API use.

Use requirements-data.txt, or the Codex bundled PDF runtime. Raw PDF bytes stay
unchanged; normalized reading text and layout headings are derived separately.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata
import urllib.request

import pdfplumber
import pypdf

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "backend/data/official"
URL = "https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf"
PDF_SHA = "2504d2a0abb0a4d491a939be4f17910a2dde0312570ab8d208080225ccf0a1f0"


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = text.replace("‐‑", "-").replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[\t\r\xa0]+", " ", text)
    return re.sub(r" +", " ", text).strip()


def save(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    (OUTPUT / name).write_bytes(raw)
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main():
    OUTPUT.mkdir(exist_ok=True, parents=True)
    path = OUTPUT / "SRD_CC_v5.1.pdf"
    raw = path.read_bytes() if path.exists() else urllib.request.urlopen(URL, timeout=60).read()
    if hashlib.sha256(raw).hexdigest() != PDF_SHA:
        raise ValueError("Official PDF differs from the reviewed snapshot; do not silently update")
    path.write_bytes(raw)
    pages, headings = [], []
    reader = pypdf.PdfReader(path)
    if len(reader.pages) != 403:
        raise ValueError("Unexpected page count")
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            # Preserve full page reading text, and per-column views for the
            # two-column body. Original PDF remains authoritative for tables.
            raw_text = reader.pages[number - 1].extract_text(extraction_mode="layout")
            left = page.crop((0, 0, page.width / 2, page.height)).extract_text() or ""
            right = page.crop((page.width / 2, 0, page.width, page.height)).extract_text() or ""
            pages.append({"page": number, "raw_text": raw_text, "text": normalize(raw_text),
                          "columns": [normalize(left), normalize(right)]})
            words = page.extract_words(extra_attrs=["size", "fontname"])
            lines = {}
            for word in words:
                if word["size"] < 11.8 or word["top"] > page.height - 36:
                    continue
                column = 0 if word["x0"] < page.width / 2 else 1
                key = (column, round(word["top"], 0), round(word["size"], 1))
                lines.setdefault(key, []).append(word)
            for (column, top, size), line in sorted(lines.items()):
                title = normalize(" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])))
                headings.append({"page": number, "column": column, "top": top, "size": size, "title": title})
            page.close()
    descriptors = [save("pages.json", pages), save("headings.json", headings)]
    manifest = {"ruleset_id": "dnd5e-2014-srd5.1", "source_url": URL,
                "retrieved_at": "2026-10-24", "license": "CC-BY-4.0",
                "original": {"file": path.name, "sha256": PDF_SHA, "bytes": len(raw), "pages": len(pages)},
                "extraction": {"pypdf": pypdf.__version__, "pdfplumber": pdfplumber.__version__,
                               "note": "Derived text is normalized; full PDF preserves all tables and original typography."},
                "derived": descriptors}
    save("manifest.json", manifest)
    print(json.dumps({"pages": len(pages), "headings": len(headings), "source_sha256": PDF_SHA}))


if __name__ == "__main__":
    main()
