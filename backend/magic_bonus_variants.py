"""Fifteen +1/+2/+3 item variants derived from five explicit source headers.

Only reference transcription is audited. No equipment or attack effects execute.
"""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA
from .magic_headers import parse_header
from .magic_shields import expected as shields

FAMILIES = ('ammunition', 'armor', 'shield', 'wand-of-the-war-mage', 'weapon')
REMOVED_RARITY_SENTENCE = {
    'ammunition': 'The bonus is determined by the rarity of the ammunition.',
    'armor': 'The bonus is determined by its rarity.',
    'weapon': "The bonus is determined by the weapon's rarity.",
}


def expected(source_dir=None):
    source = bodies(source_dir)
    shield_rows = shields(source_dir)
    records = {}
    for parent in FAMILIES:
        block = source[parent]
        parsed = parse_header(block['text'])
        choices = re.findall(r'\b(very rare|uncommon|common|rare|legendary) \(\+(\d)\)', parsed['header'])
        if [int(n) for _,n in choices] != [1,2,3]:
            raise ValueError('Official bonus rarity mapping incomplete: '+parent)
        body = normalize(block['text'])[len(parsed['header']):].strip()
        if not body or 'a bonus' not in body:
            raise ValueError('Official bonus body changed: '+parent)
        for rarity, number in choices:
            rid = parent+'-'+number
            if parent == 'shield':
                desc = shield_rows[rid]['desc']
            else:
                derived = body.replace('a bonus', 'a +'+number+' bonus', 1)
                if parent in REMOVED_RARITY_SENTENCE:
                    sentence = REMOVED_RARITY_SENTENCE[parent]
                    if derived.count(sentence) != 1:
                        raise ValueError('Official rarity sentence changed: '+parent)
                    derived = normalize(derived.replace(sentence, ''))
                elif parent == 'wand-of-the-war-mage':
                    suffix = " determined by the wand's rarity"
                    if derived.count(suffix) != 1:
                        raise ValueError('Official wand rarity clause changed')
                    derived = derived.replace(suffix, '')
                header = parsed['item_type']+', '+rarity
                if parsed['attunement_wording']:
                    header += ' ('+parsed['attunement_wording']+')'
                desc = [header, derived]
            records[rid] = dict(name=block['title'].split(',',1)[0]+', +'+number,
                equipment_category=parsed['category'], rarity=dict(name=rarity.title()), variant=True, desc=desc,
                derived_from='magic-items/'+parent, source_text_kind='derived_numeric_variant',
                official_variant_reference=dict(parent_id=parent, numeric_bonus=int(number), selected_rarity=rarity,
                    selection_header=parsed['header'], complete_parent_text=block['text'],
                    printed_pages=block['printed_pages'], source_document_sha256=PDF_SHA, source_blocks_sha256=BLOCKS_SHA,
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
            if field == 'desc':
                match = isinstance(got, list) and bool(got) and all(isinstance(s, str) for s in got) and equivalent(' '.join(got), ' '.join(want))
            else:
                try:
                    match = json.dumps(got, sort_keys=True, allow_nan=False) == json.dumps(want, sort_keys=True, allow_nan=False)
                except (TypeError, ValueError):
                    match = False
            checks.append(dict(record=rid, field=field, expected=want, actual=got, match=match))
    return dict(profile='official-magic-bonus-variants-v1', official_families=len(FAMILIES), normalized_variants=len(official),
                checks=checks, differences=[row for row in checks if not row['match']],
                limitations=['Only five source bonus families are transcribed here; remaining variants, equipped AC, ammunition consumption and attack/spell modifiers are not certified.'])


def issues(records):
    return ['Official magic bonus variant differs: '+row['record']+'/'+row['field']
            for row in audit(records)['differences']]
