"""Audit legendary budgets/costs; optionally add guarded source annotations."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_legendary import audit, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args = parser.parse_args()
    report = audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; rerun for current candidate.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        if any(r['path']==['legendary_actions','names'] for r in report['differences']):
            raise ValueError('Action identity requires separate review; no action is created or rewritten')
        path = compendium.DATA_DIR/'canonical-overlay.json'
        overlay = json.loads(path.read_text(encoding='utf-8'))
        rows = expected()
        for diff in report['differences']:
            rid = diff['record']
            block = rows[rid]['block']
            correction = dict(id='official-monster-legendary-'+rid+'-'+'-'.join(map(str,diff['path'])),
                kind='monsters',records=[rid],page=block['stat_header']['page'],heading=block['title'],
                operation='set_field',path=diff['path'],expected=diff['actual'],value=diff['expected'])
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction needs review, not replacement of its original guard')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(blocks=report['official_blocks'],cards=report['normalized_cards'],options=report['normalized_options'],differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':
    raise SystemExit(main())
