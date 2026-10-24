"""Offline, source-first extraction of legendary action budgets and bold labels.

No candidate record is consulted. PDF parsing is not a server dependency.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.monster_inventory import expected, HEADINGS_SHA
from backend.armor_source import PDF_SHA
from backend.equipment_source import normalize

ROOT = Path(__file__).resolve().parents[1]/'backend/data/official'


def extract(root=ROOT):
    root = Path(root)
    inventory, _, _ = expected(root)
    headings = json.loads((root/'headings.json').read_text(encoding='utf-8'))
    begin = next(r for r in headings if r['title']=='Legendary Creatures' and r['page']==260)
    end = next(r for r in headings if r['title']=="A Legendary Creature's Lair" and r['page']==260)
    blocks = []
    with pdfplumber.open(root/'SRD_CC_v5.1.pdf') as pdf:
        page = pdf.pages[259]
        general_bbox = [0, begin['top']-2, page.width/2, end['top']-2]
        general = dict(page=260, column=0, bbox=general_bbox,
                       text=page.crop(general_bbox).extract_text())
        for index, monster in enumerate(inventory):
            following = inventory[index+1] if index+1<len(inventory) else dict(page=404,column=0,top=0)
            first = (monster['page']-1)*2+monster['column']
            last = (following['page']-1)*2+following['column']
            segments, labels, active = [], [], False
            for cid in range(first, min(last+1,len(pdf.pages)*2)):
                if cid==last and following['top']==0:
                    continue
                pn, col = cid//2+1, cid%2
                page = pdf.pages[pn-1]
                top = monster['top']-2 if cid==first else 0
                bottom = following['top']-2 if cid==last else page.height-44
                if bottom<=top:
                    continue
                bbox = [col*page.width/2,top,(col+1)*page.width/2,bottom]
                crop = page.crop(bbox)
                words = crop.extract_words(extra_attrs=['fontname','size'])
                bold = [w for w in words if 'Bold' in w['fontname']]
                headers = [w for w in bold if w['text']=='Legendary' and round(w['size'],2)==10.8]
                if headers:
                    if active or len(headers)!=1:
                        raise ValueError('Repeated legendary header: '+monster['title'])
                    header = headers[0]
                    same = [w['text'] for w in bold if abs(w['top']-header['top'])<1]
                    if same!=['Legendary','Actions']:
                        raise ValueError('Unexpected legendary heading')
                    active = True
                    top = header['top']-1
                if not active:
                    continue
                # Family/chapter headings after the block are not legendary text.
                stops = [w['top'] for w in bold if w['top']>top+1 and w['size']>=11.8]
                stop = min(stops)-1 if stops else bottom
                bbox = [bbox[0],top,bbox[2],stop]
                selected = page.crop(bbox)
                text = selected.extract_text() or ''
                if 'System Reference Document' in text:
                    raise ValueError('Footer in legendary block')
                if text.strip():
                    segments.append(dict(page=pn,column=col,bbox=bbox,text=text))
                lines = {}
                for w in selected.extract_words(extra_attrs=['fontname','size']):
                    if 'Bold' in w['fontname'] and 9.7<w['size']<10:
                        lines.setdefault(round(w['top'],1),[]).append(w)
                for y, runs in lines.items():
                    label = normalize(' '.join(w['text'] for w in runs))
                    if not label.endswith('.'):
                        raise ValueError('Incomplete legendary label: '+monster['title']+' / '+label)
                    cost = re.search(r' \(Costs (\d+) Actions\)\.$',label)
                    labels.append(dict(label=label,name=label[:-1],cost=int(cost[1]) if cost else 1,
                        cost_basis='explicit_label' if cost else 'single_action_option_default',
                        page=pn,column=col,top=y))
                if stops:
                    break
            if not active:
                continue
            text = '\n'.join(s['text'] for s in segments)
            prelude = normalize(text.split(labels[0]['label'],1)[0]) if labels else ''
            budget = re.findall(r'can take (\d+) legendary actions',prelude)
            if len(budget)!=1 or not labels or len({r['name'] for r in labels})!=len(labels):
                raise ValueError('Incomplete legendary source: '+monster['title'])
            blocks.append(dict(title=monster['title'],stat_header=monster,segments=segments,
                prelude=prelude,budget=int(budget[0]),options=labels))
    if len(blocks)!=30 or sum(len(b['options']) for b in blocks)!=93:
        raise ValueError('Legendary source inventory changed: '+str((len(blocks),sum(len(b['options']) for b in blocks))))
    return dict(profile='official-monster-legendary-blocks-v1',source_document_sha256=PDF_SHA,
        headings_sha256=HEADINGS_SHA,general_rules=general,blocks=blocks,
        extraction=dict(pdfplumber=pdfplumber.__version__,order='official stat windows; Legendary Actions to next stat/family heading; footer excluded',
            option_labels='Calibri bold 9.84; explicit costs or single-action default; no candidate input'))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,default=ROOT/'monster-legendary-blocks.json')
    args = parser.parse_args()
    report = extract(args.source_dir)
    raw = (json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.output.write_bytes(raw)
    print(json.dumps(dict(blocks=len(report['blocks']),options=sum(len(b['options']) for b in report['blocks']),sha256=hashlib.sha256(raw).hexdigest())))
