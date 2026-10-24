"""Independent pinned rows protect bundle units and derived barding prices."""
from copy import deepcopy
import pytest
from backend import compendium,rules_packages
from backend import equipment_source as equipment


def test_all_187_records_have_official_measurements_or_explicit_absence():
    report=equipment.audit(compendium.COLLECTIONS)
    assert report['inventory_match'] and not report['diffs']
    assert report['summary']==dict(records=187,measurement_fields=346,differences=0)
    assert report['cross_collection_rows'][0]['mapped_record']=='magic-items/potion-of-healing-common'
    assert not report['cross_collection_diffs']
    assert report['unspecified_measurements']['alms-box']==dict(cost_status='not_stated',weight_status='not_stated')
    assert report['unspecified_measurements']['waterskin']['weight_condition']=='full'


@pytest.mark.parametrize('text,want',[('11⁄2',1.5),('21⁄2',2.5),('1/2',0.5),('1/4',0.25),('1,320',1320)])
def test_official_mixed_and_fractional_units(text,want):
    assert equipment.number(text)==want


def test_bundle_costs_and_amounts_are_not_mixed_with_single_item_weight():
    rows,_=equipment.expected()
    for rid,quantity in (('arrow',20),('blowgun-needle',50),('crossbow-bolt',20),('sling-bullet',20),('caltrops',20),('spike-iron',10)):
        assert rows[rid]['value']['quantity']==quantity
    assert rows['caltrops']['value']['cost']==dict(quantity=1,unit='gp')
    assert rows['spike-iron']['value']['weight']==5
    assert rows['barding-ring-mail']['value']['cost']==dict(quantity=120,unit='gp')
    assert rows['saddle-exotic']['value']['weight']==40


@pytest.mark.parametrize('rid,field,bad',[
    ('arrow','quantity',1),('caltrops','cost',dict(quantity=5,unit='cp')),
    ('saddle-exotic','weight',50),('barding-ring-mail','cost',dict(quantity=12,unit='gp')),
    ('rowboat','speed',dict(quantity=11.5,unit='mph')),('elephant','capacity','1320 lb.'),
    ('backpack','weight',True),('backpack','cost',dict(quantity='2',unit='gp')),
])
def test_candidate_measurement_drift_cannot_pass(rid,field,bad):
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment'][rid][field]=bad
    report=equipment.audit(records)
    assert any(row['record']=='equipment/'+rid and row['path']==[field] for row in report['diffs'])
    assert equipment.issues(records)


def test_missing_record_and_unexpected_equipment_are_not_accepted():
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment']['invented']=records['equipment'].pop('backpack')
    report=equipment.audit(records)
    assert report['missing_records']==['backpack'] and report['unexpected_records']==['invented']
    assert not report['inventory_match']


@pytest.mark.parametrize('change',['missing','rarity','parent','bad_shape'])
def test_healing_table_does_not_price_all_potion_variants(change):
    records=deepcopy(compendium.COLLECTIONS)
    if change=='missing':records['magic-items'].pop('potion-of-healing-common')
    elif change=='rarity':records['magic-items']['potion-of-healing-common']['rarity']['name']='Varies'
    elif change=='parent':records['magic-items']['potion-of-healing']['variants']=[]
    else:records['magic-items']['potion-of-healing-common']=None
    assert equipment.audit(records)['cross_collection_diffs']
    assert equipment.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'equipment':[]},{'equipment':{'backpack':None}}])
def test_bad_candidate_shapes_are_reported_as_issues(bad):
    assert equipment.issues(bad)


def test_pinned_sources_are_required_and_reject_tampered_pages(tmp_path):
    root=compendium.DATA_DIR/'official'
    (tmp_path/'SRD_CC_v5.1.pdf').write_bytes((root/'SRD_CC_v5.1.pdf').read_bytes())
    (tmp_path/'pages.json').write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError,match='hash mismatch'):equipment.expected(tmp_path)


def test_candidate_admission_rejects_drift_without_changing_frozen_legacy():
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment']['saddle-exotic']['weight']=50
    assert any('equipment/saddle-exotic/weight' in issue for issue in rules_packages.validate_records(records))
    assert rules_packages.legacy_records()['equipment']['saddle-exotic']['weight']==50
