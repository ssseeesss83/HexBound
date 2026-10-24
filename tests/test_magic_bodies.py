"""Item source blocks must retain embedded rules and precise boundaries."""
from copy import deepcopy
import pytest

from backend import compendium, magic_bodies as bodies, rules_packages


def test_complete_base_text_is_independent_and_candidate_matches():
    rows = bodies.expected()
    assert len(rows) == 240
    assert set(rows) == {rid for rid, row in compendium.MAGIC_ITEMS.items() if row['variant'] is False}
    report = bodies.audit(compendium.COLLECTIONS)
    assert len(report['checks']) == 480 and not report['differences']
    assert all('System Reference Document' not in row['text'] for row in rows.values())


def test_cross_page_embedded_creatures_and_tables_survive():
    rows = bodies.expected()
    deck = rows['deck-of-many-things']
    assert deck['printed_pages'] == [216, 217, 218]
    for text in ('Avatar of Death', 'Armor Class 20', 'Reaping Scythe.', 'The Void.', 'Playing Card Card'):
        assert text in deck['text']
    assert 'Giant Fly' in rows['figurine-of-wondrous-power']['text']
    assert rows['figurine-of-wondrous-power']['printed_pages'] == [221, 222, 223]
    assert 'Apparatus of the Crab Levers' in rows['apparatus-of-the-crab']['text']
    assert 'Spell Scroll' in rows['spell-scroll']['text']


def test_general_rules_do_not_pollute_last_alphabetical_item_or_artifact():
    rows = bodies.expected()
    assert 'Sentient Magic Items' not in rows['wings-of-flying']['text']
    assert 'Creating Sentient Magic Items' not in rows['wings-of-flying']['text']
    assert 'Conflict' not in rows['orb-of-dragonkind']['text']
    assert 'Destroying an Orb.' in rows['orb-of-dragonkind']['text']
    assert rows['orb-of-dragonkind']['printed_pages'] == [252, 253]
    assert rows['orb-of-dragonkind']['text'].endswith('weapon is sufficient to destroy an orb, however.')


@pytest.mark.parametrize('change', ['drop_statblock', 'drop_table', 'wrong_number', 'wrong_sign', 'extra_rule',
                                     'bad_desc', 'missing_record', 'false_verified', 'zero_verified',
                                     'wrong_page', 'wrong_source', 'missing_reference', 'drop_footnotes', 'drop_multiplication'])
def test_missing_or_mutated_text_and_reference_fail_acceptance(change):
    records = deepcopy(compendium.COLLECTIONS)
    row = records['magic-items']['deck-of-many-things']
    if change == 'drop_statblock':
        row['desc'] = [part.split('Avatar of Death')[0] for part in row['desc']]
    elif change == 'drop_table':
        row['desc'] = [part.replace('Ace of diamonds Vizier*', '') for part in row['desc']]
    elif change == 'wrong_number':
        row['desc'] = [part.replace('Armor Class 20', 'Armor Class 21') for part in row['desc']]
    elif change == 'wrong_sign':
        row['desc'] = [part.replace('−2 penalty', '+2 penalty') for part in row['desc']]
    elif change == 'extra_rule':
        row['desc'].append('Gain one free spell slot.')
    elif change == 'bad_desc':
        row['desc'] = [None]
    elif change == 'missing_record':
        records['magic-items'].pop('deck-of-many-things')
    elif change == 'false_verified':
        row['official_item_reference']['runtime_verified'] = True
    elif change == 'zero_verified':
        row['official_item_reference']['runtime_verified'] = 0
    elif change == 'wrong_page':
        row['official_item_reference']['printed_pages'] = [216]
    elif change == 'wrong_source':
        row['official_item_reference']['source_blocks_sha256'] = '0'*64
    elif change == 'drop_footnotes':
        row['desc'] = [part.replace('*', '') for part in row['desc']]
    elif change == 'drop_multiplication':
        row = records['magic-items']['staff-of-power']
        row['desc'] = [part.replace('×', '') for part in row['desc']]
    else:
        row.pop('official_item_reference')
    assert bodies.issues(records)


@pytest.mark.parametrize('left,right', [('2 × 10', '2 10'), ('Vizier*', 'Vizier'), ('1½', '1'), ('+2', '-2'), ('1/2', '1.2')])
def test_rule_bearing_symbols_cannot_be_ignored(left, right):
    assert not bodies.equivalent(left, right)


@pytest.mark.parametrize('bad', [None, [], {'magic-items': []}, {'magic-items': {'deck-of-many-things': None}}])
def test_malformed_collection_is_reported(bad):
    assert bodies.issues(bad)


def test_candidate_gate_checks_full_body_and_does_not_certify_variants():
    records = deepcopy(compendium.COLLECTIONS)
    records['magic-items']['deck-of-many-things']['desc'] = ['Wondrous item, legendary']
    assert any('Official magic item body differs' in error for error in rules_packages.validate_records(records))
    assert 'armor-1' not in bodies.expected()
    assert all(row['official_item_reference']['runtime_verified'] is False
               for row in compendium.MAGIC_ITEMS.values() if row['variant'] is False)
