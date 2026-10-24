"""Giant table types and upper-bound suppression remain explicit references."""
from copy import deepcopy
import pytest

from backend import compendium, magic_giant_variants as variants, rules_packages


def test_both_giant_tables_are_complete_and_candidate_matches():
    rows=variants.expected()
    assert len(rows)==12
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==96 and not report['differences']
    for parent in variants.FAMILIES:
        assert {rid.removeprefix(parent+'-') for rid in rows if rid.startswith(parent+'-')} == variants.TYPES


def test_each_type_has_independent_table_score_rarity_and_duration():
    rows=variants.expected()
    for kind,score,belt_rarity,potion_rarity in [
        ('hill',21,'Rare','Uncommon'),('stone',23,'Very Rare','Rare'),('frost',23,'Very Rare','Rare'),
        ('fire',25,'Very Rare','Rare'),('cloud',27,'Legendary','Very Rare'),('storm',29,'Legendary','Legendary')]:
        for parent,rarity in [('belt-of-giant-strength',belt_rarity),('potion-of-giant-strength',potion_rarity)]:
            row=rows[parent+'-'+kind]
            assert row['rarity']==dict(name=rarity)
            assert row['official_variant_reference']['selection']==dict(giant_type=kind,strength_score=score,
                duration_wording=None if parent.startswith('belt') else '1 hour')
            assert row['official_variant_reference']['runtime_verified'] is False


def test_wearing_attunement_drinking_and_no_downgrade_conditions_remain_complete():
    for rid,row in variants.expected().items():
        text=' '.join(row['desc'])
        if rid.startswith('belt'):
            assert 'requires attunement' in text and 'While wearing this belt' in text
            assert "already equal to or greater than the belt's score" in text
            assert 'the item has no effect on you' in text
        else:
            assert 'When you drink this potion' in text and 'for 1 hour' in text
            assert 'no effect on you if your Strength is equal to or greater than that score' in text
            assert 'sliver of fingernail' in text
            assert 'requires attunement' not in text


def test_shared_stone_frost_rows_expand_without_losing_source_identity():
    rows=variants.expected()
    for parent in variants.FAMILIES:
        stone=rows[parent+'-stone']['official_variant_reference']
        frost=rows[parent+'-frost']['official_variant_reference']
        assert stone['selection_row']==frost['selection_row']
        assert stone['selection']['giant_type'] != frost['selection']['giant_type']
        assert 'same effect' in stone['complete_parent_text']


@pytest.mark.parametrize('change',['score','duration','rarity','kind','body_score','body_duration','wearing',
    'attunement','equal_suppression','greater_suppression','potion_use','verified','zero','bad_desc','missing_record'])
def test_strength_variant_drift_fails_gate(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['belt-of-giant-strength-hill']
    if change=='score':row['official_variant_reference']['selection']['strength_score']=99
    elif change=='duration':row['official_variant_reference']['selection']['duration_wording']='1 hour'
    elif change=='rarity':row['rarity']['name']='Uncommon'
    elif change=='kind':row['official_variant_reference']['selection']['giant_type']='storm'
    elif change=='body_score':row['desc']=[s.replace('changes to 21','changes to 99') for s in row['desc']]
    elif change=='body_duration':
        row=records['magic-items']['potion-of-giant-strength-hill']; row['desc']=[s.replace('1 hour','8 hours') for s in row['desc']]
    elif change=='wearing':row['desc']=[s.replace('wearing','holding') for s in row['desc']]
    elif change=='attunement':row['desc']=[s.replace('(requires attunement)','') for s in row['desc']]
    elif change=='equal_suppression':row['desc']=[s.replace('equal to or greater than','greater than') for s in row['desc']]
    elif change=='greater_suppression':row['desc']=[s.replace('equal to or greater than','equal to') for s in row['desc']]
    elif change=='potion_use':
        row=records['magic-items']['potion-of-giant-strength-hill']; row['desc']=[s.replace('drink','hold') for s in row['desc']]
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('belt-of-giant-strength-hill')
    assert variants.issues(records)


def test_candidate_gate_rejects_wrong_source_strength():
    records=deepcopy(compendium.COLLECTIONS)
    records['magic-items']['belt-of-giant-strength-storm']['official_variant_reference']['selection']['strength_score']=30
    assert any('Official magic giant variant differs' in issue for issue in rules_packages.validate_records(records))
