"""Audit outer limited-use labels and source recovery without executing them."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_usage import audit
from backend.monster_bodies import expected as complete_sources
from backend.equipment_source import identifier


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; outer ability labels and general recovery only, not nested casting or resource execution.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        sources=complete_sources()
        for row in report['differences']:
            if row['position'] is None:raise ValueError('Missing unique source action binding')
            rid=row['record']; source=sources[rid]
            correction=dict(id='official-monster-usage-'+rid+'-'+row['section']+'-'+identifier(row['action'])+'-'+row['field'],
                kind='monsters',records=[rid],page=source['printed_pages'][0],heading=source['heading'],operation='set_field',
                path=[row['section'],row['position'],row['field']],expected=row['actual'],value=row['expected'])
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction requires review; keep original guard')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(labels=report['limited_use_labels'],pool_templates=report['source_ability_pool_templates'],
        checks=len(report['checks']),differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
