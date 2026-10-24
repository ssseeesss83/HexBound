"""Compare complete equipment rules and preserve source-only general facts."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.equipment_bodies import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; rerun to compare current candidate.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        changes=[]
        for row in report['diffs']:
            rid=row['record']
            changes.append(dict(id='official-equipment-body-'+rid,kind='equipment',records=[rid],
                page=row['official_pages'][0],heading=row['heading'],operation='set_field',path=['desc'],
                expected=compendium.COLLECTIONS['equipment'][rid].get('desc'),value=[row['expected']]))
        for row in report['reference_diffs']:
            changes.append(dict(id='official-equipment-reference-'+row['record'],kind=row['kind'],records=[row['record']],
                page=row['expected'].get('official_page',(row['expected'].get('printed_pages') or [70])[0]),
                heading='Equipment source reference',operation='set_field',path=row['path'],expected=row['actual'],value=row['expected']))
        for correction in changes:
            overlay['corrections']=[old for old in overlay['corrections'] if old['id']!=correction['id']]+[correction]
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['summary'],sort_keys=True))
    return int(bool(report['diffs'] or report['reference_diffs']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
