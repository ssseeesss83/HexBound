"""Selected consumable rows cannot lose shared casting/copying restrictions."""
from copy import deepcopy
import pytest

from backend import compendium, magic_consumable_variants as variants, rules_packages


def test_complete_table_coverage_and_current_candidate_agree():
    rows=variants.expected()
    assert len(rows)==14
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==112 and not report['differences']
    assert all(row['official_variant_reference']['runtime_verified'] is False for row in rows.values())


def test_all_four_healing_doses_are_independent_table_values():
    rows=variants.expected()
    for suffix,rarity,dice,bonus in [('common','Common','2d4',2),('greater','Uncommon','4d4',4),
                                   ('superior','Rare','8d4',8),('supreme','Very Rare','10d4',20)]:
        row=rows['potion-of-healing-'+suffix]
        assert row['rarity']==dict(name=rarity)
        assert row['official_variant_reference']['selection']==dict(healing_dice=dice,healing_bonus=bonus)
        assert 'when you drink this potion' in ' '.join(row['desc'])
        assert 'glimmers when agitated' in ' '.join(row['desc'])


def test_all_scroll_levels_and_stats_are_read_from_source_rows():
    rows=variants.expected()
    ids=['cantrip','1st','2nd','3rd','4th','5th','6th','7th','8th','9th']
    stats=[(13,5),(13,5),(13,5),(15,7),(15,7),(17,9),(17,9),(18,10),(18,10),(19,11)]
    rarities=['Common','Common','Uncommon','Uncommon','Rare','Rare','Very Rare','Very Rare','Very Rare','Legendary']
    for level,(suffix,(dc,bonus),rarity) in enumerate(zip(ids,stats,rarities)):
        row=rows['spell-scroll-'+suffix]
        assert row['rarity']==dict(name=rarity)
        assert row['official_variant_reference']['selection']==dict(spell_level=level,save_dc=dc,attack_bonus=bonus)


def test_every_scroll_preserves_casting_and_wizard_copying_rules():
    for rid,row in variants.expected().items():
        if not rid.startswith('spell-scroll-'):continue
        text=' '.join(row['desc'])
        for phrase in ("If the spell is on your class's spell list",'without providing any material components',
                       "requires the spell's normal casting time",'Once the spell is cast',
                       'If the casting is interrupted, the scroll is not lost.',
                       'On a failed check, the spell disappears from the scroll with no other effect.',
                       'A wizard spell on a spell scroll can be copied',
                       'Intelligence (Arcana) check',
                       'Whether the check succeeds or fails, the spell scroll is destroyed.'):
            assert phrase in text
        assert 'uninterrupted' not in text


@pytest.mark.parametrize('change',['casting_typo','lose_copying','copy_success_keeps_scroll','normal_time','material',
    'class_list','dc_and_reference','attack_sign','false_level','rarity','healing_dice','healing_bonus',
    'wrong_parent','wrong_source_row','verified','zero','bad_desc','missing_record'])
def test_incomplete_or_forged_consumable_derivation_fails(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['spell-scroll-cantrip']
    if change=='casting_typo':row['desc']=[s.replace('is interrupted','is uninterrupted') for s in row['desc']]
    elif change=='lose_copying':row['desc']=[s.split('A wizard spell on a spell scroll')[0] for s in row['desc']]
    elif change=='copy_success_keeps_scroll':row['desc']=[s.replace('Whether the check succeeds or fails','If the check fails') for s in row['desc']]
    elif change=='normal_time':row['desc']=[s.replace("the spell's normal casting time",'one bonus action') for s in row['desc']]
    elif change=='material':row['desc']=[s.replace('without providing any material components','without providing any components') for s in row['desc']]
    elif change=='class_list':row['desc']=[s.replace("If the spell is on your class's spell list",'If you can read any spell') for s in row['desc']]
    elif change=='dc_and_reference':
        row['desc']=[s.replace('DC is 13','DC is 99') for s in row['desc']]
        row['official_variant_reference']['selection']['save_dc']=99
    elif change=='attack_sign':row['desc']=[s.replace('bonus is +5','bonus is -5') for s in row['desc']]
    elif change=='false_level':row['official_variant_reference']['selection']['spell_level']=False
    elif change=='rarity':row['rarity']['name']='Legendary'
    elif change in {'healing_dice','healing_bonus'}:
        row=records['magic-items']['potion-of-healing-common']
        row['official_variant_reference']['selection'][change]='9d9' if change=='healing_dice' else 99
    elif change=='wrong_parent':row['derived_from']='magic-items/potion-of-healing'
    elif change=='wrong_source_row':row['official_variant_reference']['selection_row']='9th Legendary 19 +11'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('spell-scroll-cantrip')
    assert variants.issues(records)


def test_candidate_gate_cannot_reintroduce_scroll_casting_typo():
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['spell-scroll-9th']
    row['desc']=[s.replace('is interrupted','is uninterrupted') for s in row['desc']]
    assert any('Official magic consumable variant differs' in issue for issue in rules_packages.validate_records(records))
