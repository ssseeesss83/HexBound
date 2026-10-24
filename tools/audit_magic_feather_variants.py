"""Audit six full feather effects and the common single-use rule."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.magic_feather_variants import audit
from backend.magic_bodies import expected as bodies


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args(); report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; rerun for current candidate.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8')); parent=bodies()['feather-token']
        for row in report['differences']:
            rid=row['record']
            correction=dict(id='official-magic-feather-'+rid+'-'+row['field'],kind='magic-items',records=[rid],
                page=parent['printed_pages'][0],heading=parent['title'],operation='set_field',path=[row['field']],
                expected=row['actual'],value=row['expected'])
            overlay['corrections']=[old for old in overlay['corrections'] if old['id']!=correction['id']]+[correction]
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(normalized_variants=6,differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
