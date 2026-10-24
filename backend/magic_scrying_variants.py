"""Seven crystal/ring variants retain every selected section and shared rule."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize, identifier
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced


def sections(text, headings):
    pattern = re.compile(r'(?<!\w)('+'|'.join(re.escape(h) for h in headings)+r')\.\s+')
    matches = list(pattern.finditer(text))
    if [m[1] for m in matches] != headings:
        raise ValueError('Official named item section headings changed')
    return text[:matches[0].start()].strip(), {match[1]:text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
                                             for i,match in enumerate(matches)}


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}

    def add(parent,heading,desc,parsed,block,rarity):
        rid = identifier(heading) if parent == 'crystal-ball' else parent+'-'+heading.split()[2].lower()
        records[rid] = dict(name=heading,equipment_category=parsed['category'],rarity=dict(name=rarity),variant=True,desc=desc,
            derived_from='magic-items/'+parent,source_text_kind='derived_named_section',
            official_variant_reference=dict(parent_id=parent,selected_heading=heading,complete_parent_text=block['text'],
                printed_pages=block['printed_pages'],source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution',runtime_verified=False))

    parent = 'crystal-ball'
    block = source[parent]; parsed = parse_header(block['text'])
    text = normalize(block['text'])[len(parsed['header']):].strip()
    headings = ['Crystal Ball of Mind Reading','Crystal Ball of Telepathy','Crystal Ball of True Seeing']
    shared, selected = sections(text,headings)
    shared = replaced(shared,'The following crystal ball variants are legendary items and have additional properties.','')
    shared = replaced(shared,'The typical crystal ball, a very rare item','The crystal ball')
    if parsed['attunement_wording'] != 'requires attunement':raise ValueError('Official crystal attunement changed')
    for heading in headings:
        add(parent,heading,['Wondrous item, legendary (requires attunement)',shared,heading+'. '+selected[heading]],parsed,block,'Legendary')

    parent = 'ring-of-elemental-command'
    block = source[parent]; parsed = parse_header(block['text'])
    text = normalize(block['text'])[len(parsed['header']):].strip()
    headings = ['Ring of '+element+' Elemental Command' for element in ('Air','Earth','Fire','Water')]
    shared, selected = sections(text,headings)
    shared = replaced(shared,'The GM chooses or randomly determines the linked plane.','')
    for heading in headings:
        element = heading.split()[2]
        base = replaced(shared,'one of the four Elemental Planes','the Elemental Plane of '+element)
        # Origin in the linked plane is the source's criterion. Substituting
        # "air elementals" could be read as the one homonymous monster card.
        add(parent,heading,[parsed['header'],base,selected[heading]],parsed,block,parsed['rarity']['name'])
    return records


def audit(records,source_dir=None):
    official = expected(source_dir)
    magic = records.get('magic-items',{}) if isinstance(records,dict) else {}
    magic = magic if isinstance(magic,dict) else {}
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
    return dict(profile='official-magic-scrying-variants-v1',official_families=2,normalized_variants=len(official),checks=checks,
        differences=[row for row in checks if not row['match']],
        limitations=['Source prose only; scrying, concentration exceptions, charges, prerequisites and elemental powers remain pending execution.'])


def issues(records):
    return ['Official magic scrying variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
