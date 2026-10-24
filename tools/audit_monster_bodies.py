"""Audit complete bounded monster source; add guarded references if requested."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_bodies import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; complete-source references only, not existing action-description acceptance.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        for row in report['differences']:
            want=row['expected']
            correction=dict(id='official-monster-full-source-'+row['record'],kind='monsters',records=[row['record']],
                page=want['printed_pages'][0],heading=want['heading'],operation='set_field',
                path=['official_stat_block_reference'],expected=row['actual'],value=want)
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction needs review; original guard cannot be replaced')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(blocks=report['official_stat_blocks'],cards=report['normalized_cards'],differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
