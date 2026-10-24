"""Audit all monster trait/action prose without changing numeric parameters."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_action_bodies import audit
from backend.monster_bodies import expected as complete_sources
from backend.equipment_source import identifier


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--apply-corrections',action='store_true')
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note']='Before this invocation; prose differences include source units/formatting, not only semantic errors. Nested parameters are not changed.'
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.apply_corrections:
        if any(r['field']=='names' for r in report['differences']):
            raise ValueError('Action identity mismatch requires review; no action is added, deleted or renamed')
        path=compendium.DATA_DIR/'canonical-overlay.json'
        overlay=json.loads(path.read_text(encoding='utf-8'))
        sources=complete_sources()
        for diff in report['differences']:
            rid=diff['record']; source=sources[rid]
            if diff['position'] is None:raise ValueError('Missing unique action binding')
            correction=dict(id='official-monster-action-prose-'+rid+'-'+diff['section']+'-'+identifier(diff['action'])+'-'+diff['field'],
                kind='monsters',records=[rid],operation='set_field',path=[diff['section'],diff['position'],diff['field']],
                expected=diff['actual'],value=diff['expected'],
                # Keep the creature anchor stable; per-action printed pages
                # remain in the source reference rather than overriding it.
                page=source['printed_pages'][0],heading=source['heading'])
            if any(old['id']==correction['id'] for old in overlay['corrections']):
                raise ValueError('Existing correction requires review; original guard cannot be replaced')
            overlay['corrections'].append(correction)
        path.write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(entries=report['normalized_entries'],checks=len(report['checks']),differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__=='__main__':raise SystemExit(main())
