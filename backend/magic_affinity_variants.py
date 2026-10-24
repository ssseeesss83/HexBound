"""Thirty-four damage/element choices from four complete official tables."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced

DAMAGE_TYPES = {'Acid','Cold','Fire','Force','Lightning','Necrotic','Poison','Psychic','Radiant','Thunder'}
DRAGONS = {'Black','Blue','Brass','Bronze','Copper','Gold','Green','Red','Silver','White'}


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}

    def prepare(parent, marker):
        block = source[parent]
        before,table = block['text'].split(marker)
        parsed = parse_header(block['text'])
        return block,parsed,normalize(before)[len(parsed['header']):].strip(),table.splitlines()

    def add(parent, key, name, text, values, line, block, parsed):
        rid = parent+'-'+key
        if rid in records:
            raise ValueError('Duplicate official affinity variant')
        records[rid] = dict(name=name,equipment_category=parsed['category'],rarity=parsed['rarity'],variant=True,
            desc=[parsed['header'],text],derived_from='magic-items/'+parent,source_text_kind='derived_table_variant',
            official_variant_reference=dict(parent_id=parent,selection_row=normalize(line),selection=values,
                complete_parent_text=block['text'],printed_pages=block['printed_pages'],
                source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution',runtime_verified=False))

    parent = 'potion-of-resistance'
    block,parsed,body,lines = prepare(parent,'\nd10 Damage Type d10 Damage Type\n')
    body = replaced(body,'The GM chooses the type or determines it randomly from the options below.','')
    duration = re.search(r'for (\d+ hours?)\.',body)
    if not duration or len(lines) != 5:
        raise ValueError('Official potion resistance table/duration changed')
    faces,damage_types = set(),set()
    for line in lines:
        match = re.fullmatch(r'(\d+) (\w+) (\d+) (\w+)',normalize(line))
        if not match:
            raise ValueError('Unconsumed potion resistance table row')
        for face,damage in ((match[1],match[2]),(match[3],match[4])):
            if int(face) in faces or damage in damage_types:
                raise ValueError('Duplicate potion resistance table choice')
            faces.add(int(face));damage_types.add(damage)
            text = replaced(body,'one type of damage',damage.lower()+' damage')
            add(parent,damage.lower(),'Potion of '+damage+' Resistance',text,
                dict(damage_type=damage.lower(),d10_face=int(face),duration_wording=duration[1]),line,block,parsed)
    if faces != set(range(1,11)) or damage_types != DAMAGE_TYPES:
        raise ValueError('Official potion resistance table incomplete')

    parent = 'ring-of-resistance'
    block,parsed,body,lines = prepare(parent,'\nd10 Damage Type Gem\n')
    body = replaced(body,'The gem in the ring indicates the type, which the GM chooses or determines randomly.','')
    faces,damage_types = set(),set()
    if len(lines) != 10:
        raise ValueError('Official resistance ring table row count changed')
    for line in lines:
        match = re.fullmatch(r'(\d+) (\w+) (\w+)',normalize(line))
        if not match:
            raise ValueError('Unconsumed resistance ring table row')
        face,damage,gem = match.groups()
        if int(face) in faces or damage in damage_types:
            raise ValueError('Duplicate resistance ring choice')
        faces.add(int(face));damage_types.add(damage)
        text = replaced(body,'one damage type',damage.lower()+' damage')
        text = replaced(text,'this ring','this '+gem.lower()+' ring')
        add(parent,damage.lower(),'Ring of '+damage+' Resistance',text,
            dict(damage_type=damage.lower(),d10_face=int(face),gem=gem),line,block,parsed)
    if faces != set(range(1,11)) or damage_types != DAMAGE_TYPES:
        raise ValueError('Official resistance ring table incomplete')

    parent = 'dragon-scale-mail'
    block,parsed,body,lines = prepare(parent,'\nDragon Resistance Dragon Resistance\n')
    kinds = set()
    if len(lines) != 5:
        raise ValueError('Official dragon scale table row count changed')
    for line in lines:
        match = re.fullmatch(r'(\w+) (\w+) (\w+) (\w+)',normalize(line))
        if not match:
            raise ValueError('Unconsumed dragon scale table row')
        for dragon,damage in ((match[1],match[2]),(match[3],match[4])):
            if dragon in kinds or damage not in DAMAGE_TYPES:
                raise ValueError('Invalid/duplicate dragon scale choice')
            kinds.add(dragon)
            text = replaced(body,'one kind of dragon','a '+dragon.lower()+' dragon')
            text = replaced(text,'one damage type that is determined by the kind of dragon that provided the scales (see the table)',damage.lower()+' damage')
            text = replaced(text,'the closest dragon within 30 miles of you that is of the same type as the armor','the closest '+dragon.lower()+' dragon within 30 miles of you')
            add(parent,dragon.lower(),dragon+' Dragon Scale Mail',text,
                dict(dragon_type=dragon.lower(),damage_type=damage.lower()),line,block,parsed)
    if kinds != DRAGONS:
        raise ValueError('Official dragon scale type inventory incomplete')

    parent = 'elemental-gem'
    block,parsed,body,lines = prepare(parent,'\nGem Summoned Elemental\n')
    body = replaced(body,'The type of gem determines the elemental summoned by the spell.','')
    elements = set()
    if len(lines) != 4:
        raise ValueError('Official elemental gem row count changed')
    for line in lines:
        match = re.fullmatch(r'(Blue sapphire|Yellow diamond|Red corundum|Emerald) (Air|Earth|Fire|Water) elemental',normalize(line))
        if not match or match[2] in elements:
            raise ValueError('Invalid/duplicate elemental gem table row')
        gem,element = match.groups(); elements.add(element)
        text = replaced(body,'This gem','This '+gem.lower())
        text = replaced(text,'an elemental',('an ' if element in {'Air','Earth'} else 'a ')+element.lower()+' elemental')
        add(parent,element.lower(),element+' Elemental Gem',text,
            dict(gem=gem,elemental_type=element.lower()),line,block,parsed)
    if elements != {'Air','Earth','Fire','Water'}:
        raise ValueError('Official elemental gem inventory incomplete')
    return records


def audit(records, source_dir=None):
    official = expected(source_dir)
    magic = records.get('magic-items',{}) if isinstance(records,dict) else {}
    magic = magic if isinstance(magic,dict) else {}
    checks = []
    for rid, fields in official.items():
        row = magic.get(rid,{})
        row = row if isinstance(row,dict) else {}
        for field,want in fields.items():
            got = row.get(field)
            if field == 'desc':
                match = isinstance(got,list) and bool(got) and all(isinstance(s,str) for s in got) and equivalent(' '.join(got),' '.join(want))
            else:
                try:match = json.dumps(got,sort_keys=True,allow_nan=False) == json.dumps(want,sort_keys=True,allow_nan=False)
                except (TypeError,ValueError):match = False
            checks.append(dict(record=rid,field=field,expected=want,actual=got,match=match))
    return dict(profile='official-magic-affinity-variants-v1',official_families=4,normalized_variants=len(official),checks=checks,
                differences=[row for row in checks if not row['match']],
                limitations=['Source choices only; resistance, AC, dragon sensing, summoning and item consumption are not executed here.'])


def issues(records):
    return ['Official magic affinity variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
