"""One official omitted magic shield family, three normalized variants.

Reference data only: these records do not implement shield equipment or AC.
"""
from copy import deepcopy
import json
import re
from .armor_source import source,PDF_SHA
from .equipment_source import normalize
from .source_audit import RULESET_ID


def expected(source_dir=None):
    pages=source(source_dir)
    text=normalize(pages[241]['columns'][0])
    title='Shield, +1, +2, or +3'
    if not text.startswith(title+' '):raise ValueError('Official magic shield heading changed')
    block=text[len(title)+1:].split('Shield of Missile Attraction',1)[0].strip()
    header,body=block.split(' While holding this shield,',1)
    body='While holding this shield,'+body
    rarities=re.findall(r'(uncommon|rare|very rare) \(\+(\d)\)',header)
    if rarities!=[('uncommon','1'),('rare','2'),('very rare','3')]:raise ValueError('Official magic shield rarity mapping changed')
    if header!='Armor (shield), uncommon (+1), rare (+2), or very rare (+3)':raise ValueError('Official magic shield type changed')
    if body!="While holding this shield, you have a bonus to AC determined by the shield's rarity. This bonus is in addition to the shield's normal bonus to AC.":
        raise ValueError('Official magic shield body changed')
    def record(rid,name,rarity,variant,desc):
        return dict(index=rid,id=rid,name=name,display_name=name,edition='2014',srd_version='5.1',ruleset_id=RULESET_ID,
            url='/api/2014/magic-items/'+rid,equipment_category=dict(index='armor',name='Armor',url='/api/2014/equipment-categories/armor'),
            rarity=dict(name=rarity),variant=variant,variants=[],desc=desc,status='reference_pending_execution',runtime_verified=False,
            source_refs=dict(official_document='official/SRD_CC_v5.1.pdf',printed_pages=[242],canonical_page=242,
                canonical_heading=title,source_document_sha256=PDF_SHA,
                mapping_type='official_normalized_variant' if variant else 'official_heading'))
    rows={'shield':record('shield',title,'Varies',False,[header,body])}
    for rarity,bonus in rarities:
        rid='shield-'+bonus
        row=record(rid,'Shield, +'+bonus,rarity.title(),True,['Armor (shield), '+rarity+' (+'+bonus+')',body])
        row.update(derived_from='magic-items/shield',source_text_kind='derived_numeric_variant',
            shield_ac_bonus_reference=dict(amount=int(bonus),requires_holding=True,additional_to_normal_shield=True,
                                            status='reference_pending_execution',runtime_verified=False))
        rows[rid]=row
        rows['shield']['variants'].append(dict(index=rid,name=row['name'],url=row['url']))
    return rows


def audit(records,source_dir=None):
    rows=expected(source_dir)
    records=records if isinstance(records,dict) else {}
    magic=records.get('magic-items',{})
    magic=magic if isinstance(magic,dict) else {}
    checks=[]
    for rid,want in rows.items():
        row=magic.get(rid,{})
        row=row if isinstance(row,dict) else {}
        for field,value in want.items():
            got=row.get(field)
            try:matched=json.dumps(got,sort_keys=True,allow_nan=False)==json.dumps(value,sort_keys=True,allow_nan=False)
            except (TypeError,ValueError):matched=False
            checks.append(dict(record='magic-items/'+rid,field=field,expected=deepcopy(value),actual=deepcopy(got),match=matched))
    return dict(profile='official-magic-shields-v1',official_items=1,normalized_variants=3,records=4,official_page=242,
                checks=checks,diffs=[row for row in checks if not row['match']],
                limitations=['Reference transcription only; does not certify equipped AC, attunement, magic item execution or the full magic-item corpus.'])


def issues(records):
    report=audit(records)
    return ['Official magic shield field differs: '+row['record']+'/'+row['field'] for row in report['diffs']]
