"""Reproduce complete official item blocks using PDF column coordinates.

Offline data tooling only (requirements-data.txt); no game-server PDF dependency.
The item inventory is resolved from official headings before candidate matching.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.magic_inventory import expected, HEADINGS_SHA, key
from backend.armor_source import PDF_SHA

ROOT = Path(__file__).resolve().parents[1] / 'backend/data/official'


def extract(source_dir=ROOT):
    source_dir = Path(source_dir)
    items, _ = expected(source_dir)
    # General sentient-item rules separate the alphabetic list from one artifact.
    headings = json.loads((source_dir / 'headings.json').read_text(encoding='utf-8'))
    stops = [r for r in headings if r['title'] == 'Sentient Magic Items' and r['page'] == 251]
    if len(stops) != 1 or stops[0]['column'] != 0 or stops[0]['top'] != 380:
        raise ValueError('Official alphabetical item endpoint changed')
    rows = []
    with pdfplumber.open(source_dir / 'SRD_CC_v5.1.pdf') as pdf:
        for index, item in enumerate(items):
            if item['title'] == 'Wings of Flying':
                end = stops[0]
            elif item['title'] == 'Orb of Dragonkind':
                end = dict(page=253, column=1, top=0)
            else:
                end = items[index+1]
            start_column = (item['page']-1)*2 + item['column']
            end_column = (end['page']-1)*2 + end['column']
            segments = []
            for column_id in range(start_column, end_column+1):
                page_number, column = column_id//2+1, column_id % 2
                page = pdf.pages[page_number-1]
                if column_id == end_column and end['top'] == 0:
                    continue
                top = item['top']-2 if column_id == start_column else 0
                bottom = end['top']-2 if column_id == end_column else page.height-44
                if bottom <= top:
                    raise ValueError('Invalid official item crop')
                bbox = (column*page.width/2, top, (column+1)*page.width/2, bottom)
                text = page.crop(bbox).extract_text() or ''
                if 'System Reference Document' in text:
                    raise ValueError('Footer leaked into official item block')
                if text.strip():
                    segments.append(dict(page=page_number, column=column, bbox=list(bbox), text=text))
            lines = '\n'.join(segment['text'] for segment in segments).splitlines()
            title_lines = 2 if item.get('continuation') else 1
            if key(' '.join(lines[:title_lines])) != key(item['title']):
                raise ValueError('Official item crop lost heading: '+item['title'])
            body = '\n'.join(lines[title_lines:]).strip()
            if not body:
                raise ValueError('Empty official item body')
            rows.append(dict(title=item['title'], printed_pages=sorted({r['page'] for r in segments}),
                             segments=segments, text=body))
    return dict(profile='official-magic-item-blocks-v1', source_document_sha256=PDF_SHA,
                headings_sha256=HEADINGS_SHA, extraction=dict(pdfplumber=pdfplumber.__version__,
                    order='page, column, y; heading to next heading; footer excluded',
                    alphabetical_endpoint=stops[0], artifact_endpoint=dict(page=253, column=1, top=0)), items=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT/'magic-item-blocks.json')
    args = parser.parse_args()
    report = extract(args.source_dir)
    raw = (json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    args.output.write_bytes(raw)
    print(json.dumps(dict(items=len(report['items']), sha256=hashlib.sha256(raw).hexdigest())))


if __name__ == '__main__':
    main()
