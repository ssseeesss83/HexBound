"""Complete source headers retain class/alignment/site attunement conditions."""
from copy import deepcopy
import pytest

from backend import compendium, magic_headers as headers, rules_packages


def test_all_base_header_fields_match_and_are_reference_only():
    rows = headers.expected()
    assert len(rows) == 240
    report = headers.audit(compendium.COLLECTIONS)
    assert len(report['checks']) == 720 and not report['differences']
    assert all(row['official_header_reference']['runtime_verified'] is False for row in rows.values())
    assert 'shield-1' not in rows


def test_rare_and_uncommon_staff_fields_follow_headers():
    rows = headers.expected()
    assert rows['staff-of-swarming-insects']['rarity'] == dict(name='Rare')
    assert rows['staff-of-the-python']['rarity'] == dict(name='Uncommon')
    assert rows['ammunition']['equipment_category']['index'] == 'ammunition'
    assert rows['arrow-of-slaying']['equipment_category']['index'] == 'ammunition'
    assert rows['holy-avenger']['equipment_category']['index'] == 'weapon'


@pytest.mark.parametrize('rid,wording', [
    ('holy-avenger', 'requires attunement by a paladin'),
    ('dwarven-thrower', 'requires attunement by a dwarf'),
    ('ring-of-shooting-stars', 'requires attunement outdoors at night'),
    ('pearl-of-power', 'requires attunement by a spellcaster'),
    ('necklace-of-prayer-beads', 'requires attunement by a cleric, druid, or paladin'),
    ('talisman-of-pure-good', 'requires attunement by a creature of good alignment'),
])
def test_wrapped_attunement_conditions_remain_complete(rid, wording):
    assert headers.expected()[rid]['official_header_reference']['attunement_wording'] == wording


def test_multiple_rarities_and_conditional_types_are_preserved_verbatim():
    rows = headers.expected()
    horn = rows['horn-of-valhalla']['official_header_reference']
    assert horn['stated_rarities'] == ['rare', 'very rare', 'legendary']
    assert '(silver or brass)' in horn['header'] and '(bronze)' in horn['header'] and '(iron)' in horn['header']
    assert rows['figurine-of-wondrous-power']['rarity'] == dict(name='Varies')
    assert rows['shield']['rarity'] == dict(name='Varies')
    assert rows['shield']['official_header_reference']['attunement_wording'] is None
    assert rows['adamantine-armor']['official_header_reference']['item_type'] == 'Armor (medium or heavy, but not hide)'


def test_crystal_ball_typical_item_remains_distinct_from_legendary_family_options():
    row = headers.expected()['crystal-ball']
    assert row['rarity'] == dict(name='Very Rare')
    ref = row['official_header_reference']
    assert ref['rarity_scope'] == 'typical_item'
    assert ref['stated_rarities'] == ['very rare', 'legendary']
    assert ref['rarity_evidence'] == 'The typical crystal ball, a very rare item, is about 6 inches in diameter.'


@pytest.mark.parametrize('text', ['Wondrous item, unknown\nAn item.', 'Weapon, rare\nAn item.',
    'Wondrous item, rarity undisclosed\nAn item.', 'Ring, rare (requires attunement\nAn item.',
    'Ring, rare plus free spell slots\nAn item.'])
def test_unrecognized_or_partial_headers_are_rejected(text):
    with pytest.raises(ValueError):
        headers.parse_header(text)


@pytest.mark.parametrize('change', ['rarity', 'category', 'category_url', 'restriction', 'page', 'verified', 'zero', 'missing'])
def test_drift_is_not_certified(change):
    records = deepcopy(compendium.COLLECTIONS)
    row = records['magic-items']['holy-avenger']
    if change == 'rarity':row['rarity'] = dict(name='Common')
    elif change == 'category':row['equipment_category']['index'] = 'armor'
    elif change == 'category_url':row['equipment_category']['url'] = '/api/2014/equipment-categories/armor'
    elif change == 'restriction':row['official_header_reference']['attunement_wording'] = 'requires attunement'
    elif change == 'page':row['official_header_reference']['printed_page'] = 1
    elif change == 'verified':row['official_header_reference']['runtime_verified'] = True
    elif change == 'zero':row['official_header_reference']['runtime_verified'] = 0
    else:row.pop('official_header_reference')
    assert headers.issues(records)


def test_candidate_gate_rejects_header_field_drift():
    records = deepcopy(compendium.COLLECTIONS)
    records['magic-items']['staff-of-the-python']['rarity']['name'] = 'Very Rare'
    assert any('Official magic item header differs' in issue for issue in rules_packages.validate_records(records))
