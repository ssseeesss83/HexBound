"""Whole rule paragraphs, retained general facts and explicit unknown measures."""
from copy import deepcopy
import pytest
from backend import compendium,rules_packages
from backend import equipment_bodies as bodies,equipment_source as measurements


def test_complete_prose_and_references_have_no_candidate_differences():
    report=bodies.audit(compendium.COLLECTIONS)
    assert report['summary']==dict(records=109,differences=0,reference_checks=10,reference_differences=0)
    records,_,_=bodies.expected()
    assert records['crystal']['pages']==[66,67]
    assert records['amulet']['pages']==[67]
    assert records['alchemists-supplies']['pages']==[70]
    assert records['thieves-tools']['pages']==[71]
    assert 'Appendix PH-B' in records['amulet']['body']


@pytest.mark.parametrize('left,right,match',[
    ('A two-foot rope.','A two‐foot rope.',True),
    ('DC 10 Dexterity check.','DC 11 Dexterity check.',False),
    ('Add +2.','Add -2.',False),
    ('It holds 1/2 pint.','It holds 1.2 pint.',False),
    ('Deals 1d4 + 2 damage.','Deals 1d4+2 damage.',True),
    ('Only once per turn.','Once per turn.',False),
])
def test_typography_tolerance_preserves_words_signs_and_numerical_tokens(left,right,match):
    assert bodies.equivalent(left,right) is match


@pytest.mark.parametrize('rid',['healers-kit','amulet','torch','manacles','thieves-tools','barding-ring-mail','burglars-pack'])
def test_deleted_sentence_or_added_effect_is_rejected(rid):
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment'][rid]['desc'].append('The target automatically succeeds.')
    assert any(row['record']==rid for row in bodies.audit(records)['diffs'])


def test_general_rules_and_capacity_are_reference_only_and_complete():
    refs=bodies.references()
    assert all(row['status']=='reference_pending_execution' and row['runtime_verified'] is False for row in refs.values())
    assert len(refs['adventuring-gear']['capacities'])==13
    assert refs['adventuring-gear']['capacities']['pouch']=='1/5 cubic foot/6 pounds of gear'
    assert 'outside of a backpack' in refs['adventuring-gear']['backpack_note']
    assert 'five times its base carrying capacity' in refs['mounts-and-vehicles']['blocks'][0]
    assert 'not tied to a single ability' in refs['tools']['blocks'][0]


def test_reference_fields_cannot_claim_execution_or_replace_false_with_zero():
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment-categories']['tools']['source_rules_reference']['runtime_verified']=0
    assert bodies.audit(records)['reference_diffs']


def test_unknown_source_measurements_remain_null_while_known_prices_survive():
    rows,_=measurements.expected()
    for rid,row in rows.items():
        record=compendium.COLLECTIONS['equipment'][rid]
        for field in ('cost','weight'):
            if row['notes'].get(field+'_status')=='not_stated':assert record.get(field) is None
    assert compendium.COLLECTIONS['equipment']['bell']['cost']==dict(quantity=1,unit='gp')
    assert compendium.COLLECTIONS['equipment']['bell']['weight'] is None
    assert compendium.COLLECTIONS['equipment']['alms-box']['cost'] is None
    assert rules_packages.legacy_records()['equipment']['alms-box']['cost']==dict(quantity=0,unit='cp')


@pytest.mark.parametrize('rid,field,bad',[
    ('alms-box','cost',dict(quantity=0,unit='cp')),('alms-box','weight',0),('bell','weight',0),
])
def test_zero_cannot_replace_a_measurement_absent_from_the_source(rid,field,bad):
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment'][rid][field]=bad
    assert measurements.audit(records)['unspecified_measurement_diffs']
    assert measurements.issues(records)


@pytest.mark.parametrize('bad',[None,{'equipment':None},{'equipment':{'torch':None}}, {'equipment-categories':None}])
def test_bad_shapes_return_prose_or_reference_issues(bad):
    assert bodies.issues(bad)


def test_candidate_install_gate_rejects_missing_prose():
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment']['healers-kit']['desc']=[]
    assert any('Official equipment prose differs: healers-kit' in error for error in rules_packages.validate_records(records))
