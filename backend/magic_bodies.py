"""Complete official base-item text, including tables and embedded creatures.

Normalized variants and mechanical execution require separate acceptance.
"""
import hashlib
import json
from pathlib import Path
import re

from .armor_source import source, PDF_SHA
from .equipment_source import identifier, normalize
from .magic_inventory import expected as inventory, HEADINGS_SHA

BLOCKS_SHA = 'adf5571f35d1f0c3d3d66006aa5bbf2bb748f107cc7b4f739dbaa67eb9f1a0da'
IDS = {
    'Ammunition, +1, +2, or +3': 'ammunition',
    'Armor, +1, +2, or +3': 'armor',
    'Glamoured Studded Leather': 'glamoured-studded-leather-armor',
    'Shield, +1, +2, or +3': 'shield',
    'Wand of the War Mage, +1, +2, or +3': 'wand-of-the-war-mage',
    'Weapon, +1, +2, or +3': 'weapon',
}


def equivalent(left, right):
    def tokens(text):
        text = normalize(text).casefold().replace('−', '-').replace('–', '-')
        text = re.sub(r'([+-])\s+(?=\d)', r'\1', text)
        # Footnote stars identify 22-card-only entries in the Deck table.
        # Multiplication and vulgar fractions must not disappear as typography.
        return re.findall(r'[+-]?\d+(?:[./⁄]\d+)*|[^\W\d_]+\d*|[×÷%=<>*¼½¾⅐-⅞]', text)
    return tokens(left) == tokens(right)


def expected(source_dir=None):
    source(source_dir)
    root = Path(source_dir) if source_dir else Path(__file__).parent/'data/official'
    raw = (root/'magic-item-blocks.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BLOCKS_SHA:
        raise ValueError('Official magic item blocks hash mismatch')
    document = json.loads(raw)
    official, _ = inventory(source_dir)
    if (document['source_document_sha256'] != PDF_SHA or document['headings_sha256'] != HEADINGS_SHA
            or [row['title'] for row in document['items']] != [row['title'] for row in official]):
        raise ValueError('Official magic item blocks inventory mismatch')
    return {IDS.get(row['title'], identifier(row['title'])): row for row in document['items']}


def reference(row):
    return dict(heading=row['title'], printed_pages=row['printed_pages'], text=row['text'],
                source_document_sha256=PDF_SHA, source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution', runtime_verified=False)


def audit(records, source_dir=None):
    rows = expected(source_dir)
    magic = records.get('magic-items', {}) if isinstance(records, dict) else {}
    magic = magic if isinstance(magic, dict) else {}
    checks = []
    for rid, official in rows.items():
        row = magic.get(rid, {})
        row = row if isinstance(row, dict) else {}
        desc = row.get('desc')
        match = (isinstance(desc, list) and bool(desc) and all(isinstance(s, str) for s in desc)
                 and equivalent(' '.join(desc), official['text']))
        checks.append(dict(record=rid, field='desc', expected=[official['text']], actual=desc, match=match))
        want, got = reference(official), row.get('official_item_reference')
        try:
            match = json.dumps(got, sort_keys=True, allow_nan=False) == json.dumps(want, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            match = False
        checks.append(dict(record=rid, field='official_item_reference', expected=want, actual=got, match=match))
    return dict(profile='official-magic-base-bodies-v1', official_items=len(rows), checks=checks,
                differences=[row for row in checks if not row['match']],
                limitations=['Full base-item source text only; normalized variant text, rarity/category fields, general magic-item rules and execution remain separate.'])


def issues(records):
    return ['Official magic item body differs: '+row['record']+'/'+row['field']
            for row in audit(records)['differences']]
