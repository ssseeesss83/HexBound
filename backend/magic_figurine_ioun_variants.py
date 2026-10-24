"""Twenty-three named sections, including complete nested stat/ability blocks."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import identifier
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_feather_variants import display
from .magic_scrying_variants import sections

HEADINGS = {
    'figurine-of-wondrous-power': ['Bronze Griffon (Rare)','Ebony Fly (Rare)','Golden Lions (Rare)',
        'Ivory Goats (Rare)','Marble Elephant (Rare)','Obsidian Steed (Very Rare)','Onyx Dog (Rare)',
        'Serpentine Owl (Rare)','Silver Raven (Uncommon)'],
    'ioun-stone': ['Absorption (Very Rare)','Agility (Very Rare)','Awareness (Rare)','Fortitude (Very Rare)',
        'Greater Absorption (Legendary)','Insight (Very Rare)','Intellect (Very Rare)','Leadership (Very Rare)',
        'Mastery (Legendary)','Protection (Rare)','Regeneration (Legendary)','Reserve (Rare)',
        'Strength (Very Rare)','Sustenance (Rare)'],
}


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}
    for parent,headings in HEADINGS.items():
        block = source[parent]; parsed = parse_header(block['text'])
        text = display(block['text'])[len(parsed['header']):].strip()
        shared, selected = sections(text,headings)
        for heading in headings:
            match = re.fullmatch(r'(.+) \((Rare|Very Rare|Legendary|Uncommon)\)',heading)
            if not match:raise ValueError('Official named section rarity missing')
            title, rarity = match.groups()
            if parent == 'ioun-stone':
                rid = parent+'-of-'+identifier(title)
                name = 'Ioun Stone of '+title
            else:
                rid = parent+'-'+identifier(title)
                name = title+' Figurine of Wondrous Power'
            header = parsed['item_type']+', '+rarity.lower()
            if parsed['attunement_wording']:header += ' ('+parsed['attunement_wording']+')'
            records[rid] = dict(name=name,equipment_category=parsed['category'],rarity=dict(name=rarity),variant=True,
                desc=[header,shared,title+'. '+selected[heading]],derived_from='magic-items/'+parent,
                source_text_kind='derived_named_section',official_variant_reference=dict(parent_id=parent,selected_heading=heading,
                    complete_parent_text=block['text'],printed_pages=block['printed_pages'],source_document_sha256=PDF_SHA,
                    source_blocks_sha256=BLOCKS_SHA,status='reference_pending_execution',runtime_verified=False))
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
    return dict(profile='official-magic-figurine-ioun-variants-v1',official_families=2,normalized_variants=len(official),checks=checks,
        differences=[row for row in checks if not row['match']],
        limitations=['Complete selected prose only; embedded creature stats, transformations, stored spells, reactions, ability changes and regeneration remain pending execution.'])


def issues(records):
    return ['Official magic figurine/Ioun variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
