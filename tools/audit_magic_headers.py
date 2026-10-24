"""Audit official base-item header fields and preserve exact attunement wording."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.magic_headers import audit, expected
from backend.magic_bodies import expected as bodies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--apply-corrections', action='store_true')
    args = parser.parse_args()
    report = audit(compendium.COLLECTIONS)
    if args.output:
        report['snapshot_note'] = 'Before this invocation; rerun for current candidate.'
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.apply_corrections:
        path = compendium.DATA_DIR/'canonical-overlay.json'
        overlay = json.loads(path.read_text(encoding='utf-8'))
        source = expected()
        titles = {rid:row['title'] for rid,row in bodies().items()}
        for row in report['differences']:
            rid = row['record']
            ref = source[rid]['official_header_reference']
            correction = dict(id='official-magic-header-'+rid+'-'+row['field'], kind='magic-items', records=[rid],
                page=ref['printed_page'], heading=titles[rid], operation='set_field',
                path=[row['field']], expected=row['actual'], value=row['expected'])
            overlay['corrections'] = [old for old in overlay['corrections'] if old['id'] != correction['id']] + [correction]
        path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(official_items=report['official_items'], differences=len(report['differences']))))
    return int(bool(report['differences']) and not args.apply_corrections)


if __name__ == '__main__':
    raise SystemExit(main())
