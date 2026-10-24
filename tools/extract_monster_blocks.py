"""Offline source-first full stat blocks and typographic action/trait boundaries.

The events preserve nested headings in source order; they are not automatically
flattened into game actions or treated as form permission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pdfplumber

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.monster_inventory import expected, HEADINGS_SHA
from backend.armor_source import PDF_SHA
from backend.equipment_source import normalize

ROOT = Path(__file__).resolve().parents[1]/'backend/data/official'
SECTIONS = {'Actions':'actions','Reactions':'reactions','Legendary Actions':'legendary_actions'}


def extract(root=ROOT):
    root = Path(root)
    inventory,_,variants = expected(root)
    blocks = []
    with pdfplumber.open(root/'SRD_CC_v5.1.pdf') as pdf:
        for index,stat in enumerate(inventory):
            following = inventory[index+1] if index+1<len(inventory) else dict(page=404,column=0,top=0)
            first = (stat['page']-1)*2+stat['column']
            last = (following['page']-1)*2+following['column']
            segments,events,body,section = [],[],False,'special_abilities'
            narrative=False
            for cid in range(first,min(last+1,len(pdf.pages)*2)):
                if cid==last and following['top']==0:continue
                pn,col = cid//2+1,cid%2
                page = pdf.pages[pn-1]
                top = stat['top']-2 if cid==first else 0
                bottom = following['top']-2 if cid==last else page.height-44
                if bottom<=top:continue
                bbox = [col*page.width/2,top,(col+1)*page.width/2,bottom]
                words = page.crop(bbox).extract_words(extra_attrs=['fontname','size'])
                # Family/chapter introductions between two stat blocks belong
                # to the complete document, not to the preceding creature.
                stops = [w['top'] for w in words if 'Bold' in w['fontname'] and w['size']>=11.8
                         and (cid!=first or w['top']>stat['top']+2)]
                # A printed sidebar can follow a different creature (the
                # insect variants follow Swarm of Ravens). Preserve it under
                # the explicit inventory binding, never the nearest stat card.
                stops += [w['top'] for w in words if 'Bold' in w['fontname'] and w['text']=='Variant:'
                          and round(w['size'],2)==10.8]
                if stops:bottom=min(stops)-1
                if bottom<=top:break
                bbox[3] = bottom
                crop = page.crop(bbox)
                text = crop.extract_text() or ''
                if not text.strip():
                    if stops:break
                    continue
                if 'System Reference Document' in text:raise ValueError('Footer leaked into stat block')
                segments.append(dict(page=pn,column=col,bbox=bbox,text=text))
                words = crop.extract_words(extra_attrs=['fontname','size'])
                lines = {}
                for w in words:lines.setdefault(round(w['top'],1),[]).append(w)
                line_rows = list(lines.items())
                i = 0
                while i<len(line_rows):
                    y,runs = line_rows[i]
                    if runs[0]['text']=='Challenge' and 'Bold' in runs[0]['fontname']:
                        body=True
                        i+=1
                        continue
                    if not body:
                        i+=1
                        continue
                    if 'Cambria' in runs[0]['fontname']:
                        if not narrative:
                            events.append(dict(kind='narrative',section='narrative',label='Source narrative',page=pn,column=col,top=y,
                                boundary_basis='first Cambria paragraph after Calibri stat rules',font=runs[0]['fontname']))
                            narrative=True
                        i+=1
                        continue
                    if narrative:
                        raise ValueError('Rules resume after narrative: '+stat['title'])
                    if 'Bold' in runs[0]['fontname'] and round(runs[0]['size'],2)==10.8:
                        label = normalize(' '.join(w['text'] for w in runs))
                        if label not in SECTIONS:raise ValueError('Unknown stat section: '+stat['title']+' / '+label)
                        section=SECTIONS[label]
                        events.append(dict(kind='section',section=section,label=label,page=pn,column=col,top=y))
                        i+=1
                        continue
                    font = 'Bold'
                    if (font in runs[0]['fontname'] and round(runs[0]['size'],2)==9.84
                            and abs(runs[0]['x0']-(57.6 if col==0 else 328.56))<1):
                        label_words=[]
                        j=i
                        while j<len(line_rows):
                            row=line_rows[j][1]
                            prefix=[]
                            for w in row:
                                if font not in w['fontname'] or round(w['size'],2)!=9.84:
                                    # Some official labels put the terminating
                                    # full stop in the regular face.
                                    if w['text']=='.' and prefix:prefix[-1]+='.'
                                    break
                                prefix.append(w['text'])
                            label_words.extend(prefix)
                            if len(prefix)!=len(row):break
                            # Complete all-bold labels may end at the line end.
                            if normalize(' '.join(label_words)).endswith('.'):break
                            j+=1
                        label=normalize(' '.join(label_words).replace('\u00ad',''))
                        if not label.endswith('.'):
                            events.append(dict(kind='unclassified_bold_prefix',section=section,label=label,page=pn,column=col,top=y,font=runs[0]['fontname']))
                        else:
                            events.append(dict(kind='label',section=section,label=label,name=label[:-1],page=pn,column=col,top=y,font=runs[0]['fontname']))
                        i=j+1
                        continue
                    i+=1
                if stops:break
            if not body or not segments:raise ValueError('Truncated stat header: '+stat['title'])
            if normalize(segments[0]['text'].splitlines()[0].replace('\u00ad',''))!=normalize(stat['title']):
                raise ValueError('Stat crop lost title: '+stat['title']+' / '+segments[0]['text'].splitlines()[0])
            for event_index,event in enumerate(events):
                end = events[event_index+1] if event_index+1<len(events) else None
                start_cid = (event['page']-1)*2+event['column']
                end_cid = (end['page']-1)*2+end['column'] if end else None
                parts=[]
                for segment in segments:
                    cid = (segment['page']-1)*2+segment['column']
                    if cid<start_cid or end_cid is not None and cid>end_cid:continue
                    bounds=segment['bbox'][:]
                    if cid==start_cid:bounds[1]=max(bounds[1],event['top']-0.1)
                    if cid==end_cid:bounds[3]=min(bounds[3],end['top']-0.1)
                    if bounds[3]<=bounds[1]:continue
                    value=pdf.pages[segment['page']-1].crop(bounds).extract_text() or ''
                    if value.strip():parts.append(dict(page=segment['page'],column=segment['column'],bbox=bounds,text=value))
                if not parts:raise ValueError('Empty typographic span')
                event['segments']=parts
                event['text']='\n'.join(part['text'] for part in parts)
            blocks.append(dict(title=stat['title'],stat_header=stat,printed_pages=sorted({s['page'] for s in segments}),
                text='\n'.join(s['text'] for s in segments),segments=segments,events=events))
    if len(blocks)!=317:raise ValueError('Incomplete full stat-block inventory')
    return dict(profile='official-monster-blocks-v1',source_document_sha256=PDF_SHA,headings_sha256=HEADINGS_SHA,
        blocks=blocks,source_variants=[dict(**v,owner='Giant Rat' if v['heading']=='Variant: Diseased Giant Rats' else 'Swarm of Insects') for v in variants],
        extraction=dict(pdfplumber=pdfplumber.__version__,
            order='official stat heading to next stat/family/chapter heading; footer and empty segments excluded',
            labels='post-Challenge bold labels (including bold italic); nested boundaries preserved, not flattened; explicitly bound variant sidebars kept separately'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,default=ROOT/'monster-blocks.json')
    args=parser.parse_args()
    report=extract(args.source_dir)
    raw=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.output.write_bytes(raw)
    print(json.dumps(dict(blocks=len(report['blocks']),events=sum(len(b['events']) for b in report['blocks']),sha256=hashlib.sha256(raw).hexdigest())))
