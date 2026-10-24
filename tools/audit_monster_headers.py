"""Audit all monster movement/defence/skill headers and guarded annotations."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_headers import audit, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args = parser.parse_args()
    report = audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; rerun for current candidate. Differences include source text/ordering and missing evidence, not just numeric errors.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        path = compendium.DATA_DIR/'canonical-overlay.json'
        overlay = json.loads(path.read_text(encoding='utf-8'))
        rows = expected()
        for diff in report['differences']:
            rid = diff['record']
            source = rows[rid]['official_header_reference']
            correction = dict(id='official-monster-header-'+rid+'-'+diff['field'],kind='monsters',records=[rid],
                page=source['page'],heading=source['heading'],operation='set_field',path=[diff['field']],
                expected=diff['actual'],value=diff['expected'])
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction requires review; keep its original guard')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(cards=report['normalized_cards'],checks=len(report['checks']),differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':
    raise SystemExit(main())
