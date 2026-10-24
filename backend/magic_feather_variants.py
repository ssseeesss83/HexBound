"""Six feather tokens, preserving the shared single-use condition."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize, identifier
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_consumable_variants import replaced
from .magic_crafting_variants import _display, _range
from .magic_scrying_variants import sections

HEADINGS = ['Anchor','Bird','Fan','Swan Boat','Tree','Whip']


def display(text):
    return re.sub(r'-\s+(?=\w)','-',_display(text))


def expected(source_dir=None):
    block = bodies(source_dir)['feather-token']; parsed = parse_header(block['text'])
    before,rest = block['text'].split('\nd100 Feather Token d100 Feather Token\n')
    table,tail = rest.split('\nAnchor. ',1)
    common = display(before)[len(parsed['header']):].strip()
    common = replaced(common,'The GM chooses the kind of token or determines it randomly.','')
    if 'each with a different single-use effect.' not in common:
        raise ValueError('Official feather token single-use condition missing')
    prefix, selected = sections(display('Anchor. '+tail),HEADINGS)
    if prefix:raise ValueError('Unconsumed feather section prefix')
    choices = {}; covered = set()
    for line in table.splitlines():
        match = re.fullmatch(r'(\d+)[–-](\d+) (Anchor|Bird|Fan|Swan boat|Tree|Whip) (\d+)[–-](\d+) (Anchor|Bird|Fan|Swan boat|Tree|Whip)',normalize(line))
        if not match:raise ValueError('Unconsumed official feather table row')
        for low,high,title in ((match[1],match[2],match[3]),(match[4],match[5],match[6])):
            interval = _range(low,high,d100=True)
            numbers = set(range(interval[0],interval[1]+1))
            title = title.title()
            if title in choices or covered & numbers:raise ValueError('Duplicate feather choice')
            covered.update(numbers); choices[title] = (interval,normalize(line))
    if set(choices) != set(HEADINGS) or covered != set(range(1,101)):
        raise ValueError('Official feather table incomplete')
    records = {}
    for title in HEADINGS:
        interval,line = choices[title]
        records['feather-token-'+identifier(title)] = dict(name=title+' Feather Token',equipment_category=parsed['category'],
            rarity=parsed['rarity'],variant=True,desc=[parsed['header'],common,selected[title]],
            derived_from='magic-items/feather-token',source_text_kind='derived_named_section',
            official_variant_reference=dict(parent_id='feather-token',selected_heading=title,selection_row=line,
                selection=dict(d100_range=interval,single_use=True),complete_parent_text=block['text'],
                printed_pages=block['printed_pages'],source_document_sha256=PDF_SHA,source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution',runtime_verified=False))
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
    return dict(profile='official-magic-feather-variants-v1',official_families=1,normalized_variants=6,checks=checks,
        differences=[row for row in checks if not row['match']],
        limitations=['Complete source prose and single-use reference only; item use, flight, boats, terrain and whip attacks are not executed.'])


def issues(records):
    return ['Official magic feather variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
