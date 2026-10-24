"""Reconcile direct bonuses and numeric damage summaries, preserving gaps."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_attack_damage import audit
from backend.monster_bodies import expected as complete_sources
from backend.equipment_source import identifier


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation. Existing damage numeric/type summaries are checked, not their complete conditional semantics; unprojected literal components remain visible model work.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        if any(r['path']==['damage_field_paths'] for r in report['differences']):
            raise ValueError('Damage field identity/shape needs review; cannot invent or delete summary components')
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        sources=complete_sources()
        for row in report['differences']:
            if row['position'] is None:raise ValueError('Action identity is not unique')
            rid=row['record']; source=sources[rid]
            correction=dict(id='official-monster-attack-damage-'+rid+'-'+row['section']+'-'+identifier(row['action'])+'-'+'-'.join(map(str,row['path'])),
                kind='monsters',records=[rid],operation='set_field',path=[row['section'],row['position'],*row['path']],
                expected=row['actual'],value=row['expected'],page=source['printed_pages'][0],heading=source['heading'])
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction needs review; original guard cannot be replaced')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(source_inventory=report['source_inventory'],checks=len(report['checks']),differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
