"""Numeric source variants retain conditions and cannot silently gain effects."""
from copy import deepcopy
import pytest

from backend import compendium, magic_bonus_variants as variants, rules_packages


def test_fifteen_variants_have_complete_source_based_numeric_bindings():
    rows = variants.expected()
    assert len(rows) == 15
    report = variants.audit(compendium.COLLECTIONS)
    assert report['official_families'] == 5 and len(report['checks']) == 120
    assert not report['differences']
    for rid, row in rows.items():
        ref = row['official_variant_reference']
        assert row['variant'] is True and ref['runtime_verified'] is False
        assert ref['numeric_bonus'] == int(rid[-1])
        assert row['derived_from'] == 'magic-items/'+ref['parent_id']


def test_armor_rarity_mapping_is_different_from_shield_weapon_and_ammunition():
    rows = variants.expected()
    assert [rows['armor-'+str(n)]['rarity']['name'] for n in (1,2,3)] == ['Rare','Very Rare','Legendary']
    for family in ('shield','weapon','ammunition','wand-of-the-war-mage'):
        assert [rows[family+'-'+str(n)]['rarity']['name'] for n in (1,2,3)] == ['Uncommon','Rare','Very Rare']


def test_numeric_derivation_retains_all_use_restrictions():
    rows = variants.expected()
    assert 'while wearing this armor' in ' '.join(rows['armor-1']['desc'])
    assert 'While holding this shield' in ' '.join(rows['shield-1']['desc'])
    assert "in addition to the shield's normal bonus" in ' '.join(rows['shield-1']['desc'])
    assert 'Once it hits a target, the ammunition is no longer magical.' in ' '.join(rows['ammunition-1']['desc'])
    wand = ' '.join(rows['wand-of-the-war-mage-3']['desc'])
    assert 'requires attunement by a spellcaster' in wand
    assert '+3 bonus to spell attack rolls' in wand and 'ignore half cover' in wand


@pytest.mark.parametrize('change', ['bonus','rarity','name','category','body_sign','body_consumption','wand_cover',
    'wand_attunement','armor_wearing','shield_holding','shield_extra_ac','variant_bool','wrong_parent','wrong_kind',
    'verified','zero','missing_reference','missing_record'])
def test_variant_semantic_or_numeric_drift_fails_gate(change):
    records = deepcopy(compendium.COLLECTIONS)
    row = records['magic-items']['ammunition-1']
    if change == 'bonus':row['official_variant_reference']['numeric_bonus'] = 2
    elif change == 'rarity':row['rarity']['name'] = 'Legendary'
    elif change == 'name':row['name'] = 'Ammunition, +2'
    elif change == 'category':row['equipment_category']['index'] = 'weapon'
    elif change == 'body_sign':row['desc'] = [s.replace('+1','-1') for s in row['desc']]
    elif change == 'body_consumption':row['desc'] = [s.replace('Once it hits a target, the ammunition is no longer magical.','') for s in row['desc']]
    elif change in {'wand_cover','wand_attunement'}:
        row = records['magic-items']['wand-of-the-war-mage-1']
        row['desc'] = [s.replace('half cover','full cover') if change=='wand_cover' else s.replace('by a spellcaster','') for s in row['desc']]
    elif change == 'armor_wearing':
        row = records['magic-items']['armor-1']; row['desc'] = [s.replace('wearing','holding') for s in row['desc']]
    elif change in {'shield_holding','shield_extra_ac'}:
        row = records['magic-items']['shield-1']
        row['desc'] = [s.replace('holding','wearing') if change=='shield_holding' else s.replace('in addition','instead') for s in row['desc']]
    elif change == 'variant_bool':row['variant'] = 1
    elif change == 'wrong_parent':row['derived_from'] = 'magic-items/armor'
    elif change == 'wrong_kind':row['source_text_kind'] = 'official_heading'
    elif change == 'verified':row['official_variant_reference']['runtime_verified'] = True
    elif change == 'zero':row['official_variant_reference']['runtime_verified'] = 0
    elif change == 'missing_reference':row.pop('official_variant_reference')
    else:records['magic-items'].pop('ammunition-1')
    assert variants.issues(records)


def test_source_gate_checks_numeric_variants_and_leaves_other_families_for_later():
    records = deepcopy(compendium.COLLECTIONS)
    records['magic-items']['wand-of-the-war-mage-2']['desc'] = ['You gain +2 to all spell save DCs.']
    assert any('Official magic bonus variant differs' in issue for issue in rules_packages.validate_records(records))
    assert 'ioun-stone-of-protection' not in variants.expected()
