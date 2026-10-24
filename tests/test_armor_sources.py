"""Finite official table comparisons; no armor runtime support is inferred."""
from copy import deepcopy
import json
import shutil

import pytest

from backend import armor_source,compendium as c,rules_packages


def records():
    return {'equipment':{rid:deepcopy(c.EQUIPMENT[rid]) for rid in armor_source.NAMES.values()},
            'equipment-categories':{'armor':deepcopy(c.EQUIPMENT_CATEGORIES['armor'])}}


def test_all_13_armor_rows_and_117_fields_match_pinned_full_width_source():
    report = armor_source.audit(c.COLLECTIONS)
    assert report['summary']['armor_rows']==13 and len(report['checks'])==117
    assert report['inventory_match'] and not report['diffs'] and report['timing_match']
    saved = json.loads((c.DATA_DIR/'official/armor-source-review.json').read_text(encoding='utf-8'))
    assert saved['checks']==report['checks'] and not saved['timing_match']
    assert 'before this invocation' in saved['snapshot_note']
    assert len({(row['record'],tuple(row['path'])) for row in report['checks']})==117


def test_timing_reference_preserves_all_rows_prose_and_unresolved_fractional_actions():
    reference = c.EQUIPMENT_CATEGORIES['armor']['timing_reference']
    assert reference['status']=='reference_pending_execution' and reference['runtime_verified'] is False
    assert reference['categories']=={
        'light':dict(don=dict(amount=1,unit='minutes'),doff=dict(amount=1,unit='minutes')),
        'medium':dict(don=dict(amount=5,unit='minutes'),doff=dict(amount=1,unit='minutes')),
        'heavy':dict(don=dict(amount=10,unit='minutes'),doff=dict(amount=5,unit='minutes')),
        'shield':dict(don=dict(amount=1,unit='action'),doff=dict(amount=1,unit='action')),
    }
    assert reference['armor_ac_requires_full_don'] is True
    assert reference['assistance']['applies_to']=='doff'
    assert reference['assistance']['factor']==dict(numerator=1,denominator=2)
    assert 'fractional_action_timing' in reference['assistance']['interpretation_pending']
    assert reference['source_refs']['printed_pages']==[64]
    assert "benefit from the armor's AC only if you take the full time" in reference['source_text']


@pytest.mark.parametrize('change',['ac','price','strength','stealth_bool','dex_bool','float_weight','medium_cap',
    'missing_cap','null_cap','extra_ac_field','missing_row','extra_row','category','timing','missing_timing'])
def test_any_reviewed_armor_or_timing_drift_fails_candidate_gate(change):
    rows = records()
    if change=='ac':rows['equipment']['padded-armor']['armor_class']['base']=12
    elif change=='price':rows['equipment']['plate-armor']['cost']['quantity']=150
    elif change=='strength':rows['equipment']['chain-mail']['str_minimum']=15
    elif change=='stealth_bool':rows['equipment']['padded-armor']['stealth_disadvantage']=1
    elif change=='dex_bool':rows['equipment']['leather-armor']['armor_class']['dex_bonus']=1
    elif change=='float_weight':rows['equipment']['leather-armor']['weight']=10.0
    elif change=='medium_cap':rows['equipment']['hide-armor']['armor_class']['max_bonus']=3
    elif change=='missing_cap':del rows['equipment']['hide-armor']['armor_class']['max_bonus']
    elif change=='null_cap':rows['equipment']['leather-armor']['armor_class']['max_bonus']=None
    elif change=='extra_ac_field':rows['equipment']['padded-armor']['armor_class']['extra']=0
    elif change=='missing_row':del rows['equipment']['shield']
    elif change=='extra_row':rows['equipment']['invented']=deepcopy(rows['equipment']['shield'])
    elif change=='category':rows['equipment']['ring-mail']['armor_category']='Medium'
    elif change=='timing':rows['equipment-categories']['armor']['timing_reference']['categories']['shield']['don']['unit']='minutes'
    elif change=='missing_timing':del rows['equipment-categories']['armor']['timing_reference']
    assert armor_source.issues(rows)


@pytest.mark.parametrize('name',['SRD_CC_v5.1.pdf','pages.json'])
def test_source_hash_drift_rejects_before_comparing_candidate(tmp_path,name):
    for filename in ['SRD_CC_v5.1.pdf','pages.json']:shutil.copyfile(c.DATA_DIR/'official'/filename,tmp_path/filename)
    with (tmp_path/name).open('ab') as target:target.write(b' ')
    with pytest.raises(ValueError,match='hash mismatch'):armor_source.audit(records(),tmp_path)


def test_legacy_archive_and_candidate_inventory_are_unchanged():
    legacy = rules_packages.build_legacy_package()
    assert 'timing_reference' not in legacy['records']['equipment-categories']['armor']
    assert sum(map(len,c.COLLECTIONS.values()))==2322
    assert rules_packages.LEGACY_PACKAGE==legacy['package_version']
    assert not rules_packages.validate_records(c.COLLECTIONS)


def test_null_armor_record_returns_gate_errors_instead_of_crashing():
    rows = records()
    rows['equipment']['shield']=None
    assert armor_source.issues(rows)
