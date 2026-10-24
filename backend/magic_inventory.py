"""Independent official item headings and complete normalized family links."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from .armor_source import source,PDF_SHA
from .equipment_source import normalize

HEADINGS_SHA='896c018bd844f0dc5e8f1759c9c8dd27d74856047d938c41ff132c7a110deb02'
# These are retained within their enclosing item/general-rule blocks. They
# are table captions, embedded stat blocks or sentient-item subsections.
EXCLUSIONS={
 (208,'Apparatus of the Crab Levers'):'item_table',
 (210,'Gray Bag of Tricks'):'variant_table',
 (211,'Rust Bag of Tricks'):'variant_table',
 (211,'Tan Bag of Tricks'):'variant_table',
 (215,'Cube of Force Faces'):'item_table',
 (218,'Avatar of Death'):'embedded_stat_block',
 (222,'Giant Fly'):'embedded_stat_block',
 (234,'Potions of Healing'):'variant_table',
 (251,'Abilities'):'sentient_item_general_rule',
 (251,'Communication'):'sentient_item_general_rule',
 (251,'Senses'):'sentient_item_general_rule',
 (251,'Alignment'):'sentient_item_general_rule',
 (251,'Special Purpose'):'sentient_item_general_rule',
}
ALIASES={'Glamoured Studded Leather':('glamoured-studded-leather-armor','Glamoured Studded Leather Armor')}


def key(text):
    text=normalize(text).casefold().replace('−','-')
    return tuple(re.findall(r'[+-]?\d+|[a-z]+',text))


def expected(source_dir=None):
    source(source_dir) # Pin original PDF and extracted pages as well.
    root=Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    raw=(root/'headings.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=HEADINGS_SHA:raise ValueError('Official magic item headings hash mismatch')
    headings=[row for row in json.loads(raw) if 207<=row['page']<=253 and row['size']==12]
    if len(headings)!=255:raise ValueError('Official magic heading inventory changed')
    items,dispositions=[],[]
    excluded=set()
    for row in headings:
        disposition=EXCLUSIONS.get((row['page'],row['title']))
        if row['page']==242 and row['column']==1 and row['title']=='Spell Scroll':disposition='item_table'
        if disposition:
            dispositions.append(dict(**row,disposition=disposition))
            excluded.add((row['page'],row['title']))
            continue
        if row['title']=='Location':
            if (not items or items[-1]['title']!='Amulet of Proof against Detection and'
                    or items[-1]['page']!=row['page'] or items[-1]['column']!=row['column']
                    or row['top']-items[-1]['top']!=14):
                raise ValueError('Official wrapped item heading changed')
            items[-1]['title']+=' Location'
            items[-1]['continuation']=dict(row)
            continue
        items.append(dict(row))
    if (len(items)!=240 or len(dispositions)!=14 or not set(EXCLUSIONS)<=excluded
            or len({key(row['title']) for row in items})!=240):
        raise ValueError('Official magic item title dispositions incomplete')
    return items,dispositions


def audit(records,source_dir=None):
    official,dispositions=expected(source_dir)
    records=records if isinstance(records,dict) else {}
    magic=records.get('magic-items',{})
    magic=magic if isinstance(magic,dict) else {}
    base={rid:row for rid,row in magic.items() if isinstance(row,dict) and row.get('variant') is False}
    variants={rid:row for rid,row in magic.items() if isinstance(row,dict) and row.get('variant') is True}
    names=defaultdict(list)
    for rid,row in base.items():
        if isinstance(row.get('name'),str):names[key(row['name'])].append(rid)
    mappings=[]
    consumed=set()
    for entry in official:
        alias=ALIASES.get(entry['title'])
        found=([alias[0]] if alias[0] in base and base[alias[0]].get('name')==alias[1] else []) if alias else names[key(entry['title'])]
        match=len(found)==1
        if match:consumed.add(found[0])
        mappings.append(dict(official_title=entry['title'],official_page=entry['page'],column=entry['column'],top=entry['top'],
                             record_ids=found,match=match,mapping_type='explicit_title_alias' if alias else 'official_title'))
    links=[]
    parents=defaultdict(list)
    shape_errors=[]
    for rid,row in magic.items():
        if not isinstance(row,dict) or type(row.get('variant')) is not bool:
            shape_errors.append(rid);continue
        refs=row.get('variants')
        if not isinstance(refs,list) or (row['variant'] and refs):shape_errors.append(rid);continue
        seen=set()
        for ref in refs:
            target=ref.get('index') if isinstance(ref,dict) else None
            child=variants.get(target,{}) if isinstance(target,str) else {}
            match=(bool(child) and target not in seen and isinstance(ref.get('name'),str) and bool(ref['name'].strip())
                   and isinstance(child.get('name'),str) and bool(child['name'].strip())
                   and ref['name']==child['name'] and ref.get('url')=='/api/2014/magic-items/'+target
                   and child.get('url')=='/api/2014/magic-items/'+target and child.get('index')==target)
            if isinstance(target,str):
                seen.add(target)
                parents[target].append(rid)
            links.append(dict(parent_id=rid,variant_id=target,match=match))
    ownership=[dict(variant_id=rid,parent_ids=parents[rid],match=len(parents[rid])==1) for rid in variants]
    return dict(profile='official-magic-inventory-v1',source_document_sha256=PDF_SHA,headings_sha256=HEADINGS_SHA,
        official_items=len(official),normalized_variants=len(variants),candidate_records=len(magic),
        mappings=mappings,heading_dispositions=dispositions,unmapped_base_records=sorted(set(base)-consumed),
        malformed_records=sorted(set(shape_errors)),links=links,variant_ownership=ownership,
        differences=[dict(check='official_title',**row) for row in mappings if not row['match']]
            +[dict(check='family_link',**row) for row in links if not row['match']]
            +[dict(check='variant_owner',**row) for row in ownership if not row['match']],
        limitations=['Title and family-reference coverage only; does not certify item prose, rarity/category fields, derived variant effects or execution.',
                     'Embedded stat blocks and tables remain required source within enclosing entries; their exclusion is only from independent item titles.'])


def issues(records):
    report=audit(records)
    errors=['Official magic inventory differs: '+row['check'] for row in report['differences']]
    errors.extend('Unmapped magic item base record: '+rid for rid in report['unmapped_base_records'])
    errors.extend('Malformed magic item record: '+rid for rid in report['malformed_records'])
    return errors
