"""Audit fixed official armor rows; optionally add the source-only timing field."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.armor_source import audit,expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-reference',action='store_true')
    args = parser.parse_args()
    report = audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Candidate snapshot before this invocation; rerun to compare the current candidate.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_reference:
        _,reference = expected()
        path = compendium.DATA_DIR/'canonical-overlay.json'
        overlay = json.loads(path.read_text(encoding='utf-8'))
        cid = 'official-armor-don-doff-reference'
        correction = dict(id=cid,kind='equipment-categories',records=['armor'],page=64,
            heading='Getting Into and Out of Armor',operation='set_field',path=['timing_reference'],
            expected=None,value=reference)
        overlay['corrections']=[row for row in overlay['corrections'] if row['id']!=cid]+[correction]
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['summary'],sort_keys=True))
    return int(bool(report['diffs'] or not report['inventory_match'] or (not report['timing_match'] and not args.apply_reference)))


if __name__=='__main__':raise SystemExit(main())
