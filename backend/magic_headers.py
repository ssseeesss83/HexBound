"""Source-only item categories, rarity ranges and attunement wording.

The exact restrictions are retained as references; no attunement executor here.
"""
import json
import re

from .magic_bodies import expected as bodies, BLOCKS_SHA
from .armor_source import PDF_SHA
from .equipment_source import normalize

CATEGORIES = {
    'Wondrous item': ('wondrous-items', 'Wondrous Items'), 'Armor': ('armor', 'Armor'),
    'Weapon': ('weapon', 'Weapon'), 'Ring': ('ring', 'Ring'), 'Potion': ('potion', 'Potion'),
    'Wand': ('wand', 'Wand'), 'Staff': ('staff', 'Staff'), 'Rod': ('rod', 'Rod'), 'Scroll': ('scroll', 'Scroll'),
}
RARITY = r'(?:very rare|uncommon|common|rare|legendary|artifact)(?: \((?!requires attunement)[^)]{1,100}\))?'
HEADER = re.compile(r'(?P<type>Wondrous item|Armor \([^)]{1,100}\)|Weapon \([^)]{1,100}\)|Ring|Potion|Wand|Staff|Rod|Scroll), '
    r'(?P<rarity>rarity by figurine|rarity varies|varies|'+RARITY+r'(?:(?:, (?:or )?| or )'+RARITY+r')*)'
    r'(?: \((?P<attunement>requires attunement[^)]*)\))?(?=\s|$)')


def parse_header(text):
    flat = normalize(text)
    match = HEADER.match(flat)
    if not match:
        raise ValueError('Unrecognized official magic item header')
    # The header must consume whole physical lines, not a partial line which
    # merely happens to match a known rarity prefix.
    lines = text.splitlines()
    count = 0
    while count < len(lines) and len(normalize(' '.join(lines[:count]))) < len(match[0]):
        count += 1
    if normalize(' '.join(lines[:count])) != match[0]:
        raise ValueError('Official magic item header ended within a line')
    item_type = match['type']
    base_type = item_type.split(' (', 1)[0]
    category_id, category_name = CATEGORIES[base_type]
    if item_type in {'Weapon (any ammunition)', 'Weapon (arrow)'}:
        category_id, category_name = 'ammunition', 'Ammunition'
    rarity = match['rarity']
    names = re.findall(r'\b(very rare|uncommon|common|rare|legendary|artifact)\b', rarity)
    if not names and rarity not in {'varies', 'rarity varies', 'rarity by figurine'}:
        raise ValueError('Official magic item rarity missing')
    return dict(header=match[0], item_type=item_type,
                category=dict(index=category_id, name=category_name, url='/api/2014/equipment-categories/'+category_id),
                rarity=dict(name=names[0].title() if len(set(names)) == 1 else 'Varies'),
                stated_rarities=list(dict.fromkeys(names)), attunement_wording=match['attunement'])


def expected(source_dir=None):
    records = {}
    for rid, body in bodies(source_dir).items():
        parsed = parse_header(body['text'])
        scope = 'header'
        evidence = parsed['header']
        if rid == 'crystal-ball':
            # This record is both the typical usable item and family entry.
            # The full family header must not override its explicit base rarity.
            evidence = 'The typical crystal ball, a very rare item, is about 6 inches in diameter.'
            if evidence not in normalize(body['text']):
                raise ValueError('Official typical crystal ball rarity evidence changed')
            parsed['rarity'] = dict(name='Very Rare')
            scope = 'typical_item'
        records[rid] = dict(equipment_category=parsed['category'], rarity=parsed['rarity'],
            official_header_reference=dict(header=parsed['header'], item_type=parsed['item_type'],
                stated_rarities=parsed['stated_rarities'], attunement_wording=parsed['attunement_wording'],
                rarity_scope=scope, rarity_evidence=evidence,
                printed_page=body['printed_pages'][0], source_document_sha256=PDF_SHA, source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution', runtime_verified=False))
    return records


def audit(records, source_dir=None):
    official = expected(source_dir)
    magic = records.get('magic-items', {}) if isinstance(records, dict) else {}
    magic = magic if isinstance(magic, dict) else {}
    checks = []
    for rid, fields in official.items():
        row = magic.get(rid, {})
        row = row if isinstance(row, dict) else {}
        for field, want in fields.items():
            got = row.get(field)
            try:
                match = json.dumps(got, sort_keys=True, allow_nan=False) == json.dumps(want, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError):
                match = False
            checks.append(dict(record=rid, field=field, expected=want, actual=got, match=match))
    return dict(profile='official-magic-base-headers-v1', official_items=len(official), checks=checks,
                differences=[row for row in checks if not row['match']],
                limitations=['Base item header fields only; a Varies family does not assign rarity or attunement to individual variants. No item execution is certified.'])


def issues(records):
    return ['Official magic item header differs: '+row['record']+'/'+row['field']
            for row in audit(records)['differences']]
