"""Three bags of tricks: complete shared rules and 24 source creature links."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize, identifier
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced


def expected(source_dir=None):
    block = bodies(source_dir)['bag-of-tricks']
    parsed = parse_header(block['text'])
    parts = re.split(r'\n(Gray|Rust|Tan) Bag of Tricks\n',block['text'])
    if len(parts) != 7 or parts[1::2] != ['Gray','Rust','Tan']:
        raise ValueError('Official bag subtype headings changed')
    shared = normalize(parts[0])[len(parsed['header']):].strip()
    records = {}
    for position in (1,3,5):
        color,table = parts[position:position+2]
        lines = table.splitlines()
        if normalize(lines[0]) != 'd8 Creature' or len(lines) != 9:
            raise ValueError('Official bag creature table incomplete')
        choices = []
        for face,line in enumerate(lines[1:],1):
            match = re.fullmatch(r'([1-8]) (.+)',normalize(line))
            if not match or int(match[1]) != face:
                raise ValueError('Unconsumed official bag creature row')
            choices.append(dict(d8_face=face,creature_name=match[2],monster_id=identifier(match[2]),source_row=normalize(line)))
        desc = [parsed['header'],replaced(shared,'gray, rust, or tan cloth',color.lower()+' cloth'),
                color+' Bag:','| d8 | Creature |','|---|---|']
        desc += ['| '+str(row['d8_face']).zfill(2)+' | '+row['creature_name'].title()+' |' for row in choices]
        records['bag-of-tricks-'+color.lower()] = dict(name=color+' Bag of Tricks',equipment_category=parsed['category'],
            rarity=parsed['rarity'],variant=True,desc=desc,derived_from='magic-items/bag-of-tricks',source_text_kind='derived_table_variant',
            official_variant_reference=dict(parent_id='bag-of-tricks',color=color.lower(),roll_table=choices,
                complete_parent_text=block['text'],printed_pages=block['printed_pages'],source_document_sha256=PDF_SHA,
                source_blocks_sha256=BLOCKS_SHA,status='reference_pending_execution',runtime_verified=False))
    return records


def audit(records,source_dir=None):
    official = expected(source_dir)
    records = records if isinstance(records,dict) else {}
    magic = records.get('magic-items',{})
    magic = magic if isinstance(magic,dict) else {}
    monsters = records.get('monsters',{})
    monsters = monsters if isinstance(monsters,dict) else {}
    checks = []
    for rid,fields in official.items():
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
        for choice in fields['official_variant_reference']['roll_table']:
            mid = choice['monster_id']
            monster = monsters.get(mid,{})
            monster = monster if isinstance(monster,dict) else {}
            want = dict(index=mid,name=choice['creature_name'],url='/api/2014/monsters/'+mid)
            got = {field:monster.get(field) for field in want}
            match = (got['index']==want['index'] and isinstance(got['name'],str)
                     and got['name'].casefold()==want['name'].casefold() and got['url']==want['url'])
            checks.append(dict(record=rid,field='monster_reference.'+str(choice['d8_face']),expected=want,actual=got,match=match))
    return dict(profile='official-magic-bag-variants-v1',official_families=1,normalized_variants=3,creature_links=24,checks=checks,
        differences=[row for row in checks if not row['match']],
        limitations=['Creature identity links and source rules only; spawning, commands, initiative, daily charges and creature-stat execution are not certified.'])


def issues(records):
    return ['Official magic bag variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
