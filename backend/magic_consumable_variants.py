"""Four healing potions and ten scrolls, with complete shared source rules."""
import json
import re

from .armor_source import PDF_SHA
from .equipment_source import normalize
from .magic_bodies import expected as bodies, equivalent, BLOCKS_SHA

HEALING_NAMES = {'Healing':'common', 'Greater healing':'greater', 'Superior healing':'superior', 'Supreme healing':'supreme'}
HEALING_ROW = re.compile(r'^(Healing|Greater healing|Superior healing|Supreme healing) (Common|Uncommon|Rare|Very rare) (\d+d\d+) \+ (\d+)$')
SCROLL_ROW = re.compile(r'^(Cantrip|[1-9](?:st|nd|rd|th)) (Common|Uncommon|Rare|Very rare|Legendary) (\d+) \+(\d+)$')


def replaced(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Official consumable derivation clause changed')
    return normalize(text.replace(old, new))


def _reference(parent, block, row, values):
    return dict(parent_id=parent, selection_row=row, selection=values, complete_parent_text=block['text'],
                printed_pages=block['printed_pages'], source_document_sha256=PDF_SHA, source_blocks_sha256=BLOCKS_SHA,
                status='reference_pending_execution', runtime_verified=False)


def expected(source_dir=None):
    source = bodies(source_dir)
    records = {}
    parent = 'potion-of-healing'
    block = source[parent]
    before, table = block['text'].split('\nPotions of Healing\n')
    lines = table.splitlines()
    if normalize(lines[0]) != 'Potion of … Rarity HP Regained':
        raise ValueError('Official healing table header changed')
    shared = normalize(before).removeprefix('Potion, rarity varies ').strip()
    shared = replaced(shared, 'The number of hit points depends on the potion\'s rarity, as shown in the Potions of Healing table.', '')
    shared = replaced(shared, 'Whatever its potency, the potion', 'The potion')
    labels = []
    for line in lines[1:]:
        match = HEALING_ROW.fullmatch(normalize(line))
        if not match:
            raise ValueError('Unconsumed official healing table row')
        label, rarity, dice, bonus = match.groups()
        labels.append(label)
        rid = parent+'-'+HEALING_NAMES[label]
        text = replaced(shared, 'You regain hit points', 'You regain '+dice+' + '+bonus+' hit points')
        records[rid] = dict(name='Potion of '+label.title(),
            equipment_category=dict(index='potion',name='Potion',url='/api/2014/equipment-categories/potion'),
            rarity=dict(name=rarity.title()),variant=True,desc=['Potion, '+rarity.lower(),text],
            derived_from='magic-items/'+parent,source_text_kind='derived_table_variant',
            official_variant_reference=_reference(parent,block,normalize(line),dict(healing_dice=dice,healing_bonus=int(bonus))))
    if labels != list(HEALING_NAMES):
        raise ValueError('Official healing table inventory changed')

    parent = 'spell-scroll'
    block = source[parent]
    before, rest = block['text'].split('\nSpell Scroll\n')
    lines = rest.splitlines()
    if normalize(lines[0]) != 'Spell Level Rarity Save DC Attack Bonus':
        raise ValueError('Official scroll table header changed')
    matches = []
    for index in range(1,11):
        match = SCROLL_ROW.fullmatch(normalize(lines[index]))
        if not match:
            raise ValueError('Unconsumed official scroll table row')
        matches.append((match,normalize(lines[index])))
    if [m[0][1] for m in matches] != ['Cantrip','1st','2nd','3rd','4th','5th','6th','7th','8th','9th']:
        raise ValueError('Official scroll level inventory changed')
    after = normalize(' '.join(lines[11:]))
    if not after.startswith('A wizard spell on a spell scroll can be copied') or not after.endswith('the spell scroll is destroyed.'):
        raise ValueError('Official wizard copying rule missing')
    shared = normalize(before).removeprefix('Scroll, varies ').strip()
    generic = "The level of the spell on the scroll determines the spell's saving throw DC and attack bonus, as well as the scroll's rarity, as shown in the Spell Scroll table."
    for level, (match, line) in enumerate(matches):
        label, rarity, dc, attack = match.groups()
        rid = parent+'-'+label.lower()
        selection = 'a cantrip' if level == 0 else ('an ' if level == 8 else 'a ')+label+'-level spell'
        explicit = "This scroll contains "+selection+". The spell's saving throw DC is "+dc+' and its attack bonus is +'+attack+'.'
        text = replaced(shared,generic,explicit)+' '+after
        records[rid] = dict(name='Spell Scroll ('+label+')',
            equipment_category=dict(index='scroll',name='Scroll',url='/api/2014/equipment-categories/scroll'),
            rarity=dict(name=rarity.title()),variant=True,desc=['Scroll, '+rarity.lower(),text],
            derived_from='magic-items/'+parent,source_text_kind='derived_table_variant',
            official_variant_reference=_reference(parent,block,line,dict(spell_level=level,save_dc=int(dc),attack_bonus=int(attack))))
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
                match = isinstance(got, list) and bool(got) and all(isinstance(s,str) for s in got) and equivalent(' '.join(got),' '.join(want))
            else:
                try:
                    match = json.dumps(got,sort_keys=True,allow_nan=False) == json.dumps(want,sort_keys=True,allow_nan=False)
                except (TypeError,ValueError):
                    match = False
            checks.append(dict(record=rid,field=field,expected=want,actual=got,match=match))
    return dict(profile='official-magic-consumable-variants-v1',official_families=2,normalized_variants=len(official),checks=checks,
                differences=[row for row in checks if not row['match']],
                limitations=['Four healing potions and ten scrolls only; casting eligibility, interrupted casting, copying, healing and item destruction are reference rules pending execution.'])


def issues(records):
    return ['Official magic consumable variant differs: '+row['record']+'/'+row['field'] for row in audit(records)['differences']]
