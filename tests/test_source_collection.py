"""P01: official pages are collected, candidate transcription is NOT certified."""
import json
import shutil

import pytest

from backend import source_audit as audit


def test_official_full_corpus_and_independent_core_inventories():
    report = audit.collection_report()
    assert report["errors"] == [] and report["collection_complete"]
    assert report["official_pages"] == 403
    assert len(report["class_inventory"]) == len(report["subclass_inventory"]) == 12
    assert len(report["skill_inventory"]) == 18
    assert len(report["official_spell_inventory"]) == 319
    assert all(row["local_record_id"] for row in report["official_spell_inventory"])
    assert len(report["candidate_records"]) == 2317
    assert report["transcription_status"] == "candidate_only_not_signed_off"
    assert report["mechanical_support"] == "not_evaluated_by_collection_gate"
    coverage = json.loads((audit.ROOT / "official/source-coverage.json").read_text(encoding="utf-8"))
    assert coverage == report


@pytest.mark.parametrize("name", ["official/SRD_CC_v5.1.pdf", "official/pages.json", "official/headings.json",
                                  "srd2014/5e-SRD-Features.json", "srd2014/5e-SRD-Spells.json"])
def test_corrupt_or_truncated_material_prevents_collection_signoff(tmp_path, name):
    root = tmp_path / "data"
    shutil.copytree(audit.ROOT, root)
    path = root / name
    if name.endswith(".pdf"):
        path.write_bytes(path.read_bytes()[:-1])
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(rows[1:]), encoding="utf-8")
    report = audit.collection_report(root)
    assert report["errors"] and not report["collection_complete"]


def test_every_official_section_and_heading_retains_unabridged_source():
    report = audit.collection_report()
    chapters = {chapter["id"]: chapter for chapter in report["chapters"]}
    assert chapters["advancement-multiclassing"]["printed_pages"] == [56, 57, 58]
    assert chapters["monster-rules"]["printed_pages"] == list(range(254, 261))
    assert all(entry["raw_record"] and entry["source_document_sha256"] == audit.OFFICIAL_PDF_SHA
               for entry in report["official_entries"])
    assert all(entry["structure_status"] == "pending_P02" for entry in report["official_entries"])
