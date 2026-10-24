"""Add the official missing shield family without modifying community bytes."""
import json
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.magic_shields import expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overlay',type=Path,default=Path(__file__).resolve().parents[1]/'backend/data/canonical-overlay.json')
    args=parser.parse_args()
    path=args.overlay
    overlay=json.loads(path.read_text(encoding='utf-8'))
    rows=expected()
    existing=overlay.get('record_additions',[])
    for addition in existing:
        rid=addition['record']['index']
        if addition['kind']=='magic-items' and rid in rows and addition['record']!=rows[rid]:
            raise ValueError('Existing magic shield addition differs; review it before replacing')
    overlay['record_additions']=[row for row in existing if not (row['kind']=='magic-items' and row['record']['index'] in rows)]
    overlay['record_additions'] += [dict(kind='magic-items',record=row) for row in rows.values()]
    path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(official_items=1,normalized_variants=3,records=4,runtime_verified=False)))


if __name__=='__main__':main()
