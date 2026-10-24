"""Compare all 187 remaining equipment measurements with pinned official rows."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.equipment_source import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Candidate measurements before this invocation; rerun to compare current candidate.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not report['inventory_match'] or report['cross_collection_diffs']:raise ValueError('Resolve inventory/cross-reference mapping before applying corrections')
    if args.apply_corrections:
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        for row in report['diffs']+report['unspecified_measurement_diffs']:
            rid=row['record'].split('/',1)[1]
            correction=dict(id='official-equipment-'+rid+'-'+row['path'][0],kind='equipment',records=[rid],
                page=row['official_page'],heading='Equipment',operation='set_field',path=row['path'],
                expected=row['actual'],value=row['expected'])
            overlay['corrections']=[old for old in overlay['corrections'] if old['id']!=correction['id']]+[correction]
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['summary'],sort_keys=True))
    return int(bool(report['diffs'] or report['unspecified_measurement_diffs']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
