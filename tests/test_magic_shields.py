"""The missing official shield is distinct from armor and the shield spell."""
from copy import deepcopy
import hashlib
import subprocess
import sys
import pytest
from backend import compendium,rules_packages
from backend import magic_shields as shields


def test_one_official_family_three_normalized_variants_and_qualified_ids():
    report=shields.audit(compendium.COLLECTIONS)
    assert report['official_items']==1 and report['normalized_variants']==3 and not report['diffs']
    rows=compendium.COLLECTIONS['magic-items']
    assert [ref['index'] for ref in rows['shield']['variants']]==['shield-1','shield-2','shield-3']
    assert [rows['shield-'+str(n)]['rarity']['name'] for n in (1,2,3)]==['Uncommon','Rare','Very Rare']
    assert compendium.COLLECTIONS['equipment']['shield']['armor_class']['base']==2
    assert compendium.COLLECTIONS['spells']['shield']['index']=='shield'
    assert len(compendium.COLLECTIONS['magic-items'])==366


def test_source_holding_and_additional_ac_are_reference_only():
    rows=shields.expected()
    for n in (1,2,3):
        row=rows['shield-'+str(n)]
        assert row['shield_ac_bonus_reference']==dict(amount=n,requires_holding=True,additional_to_normal_shield=True,
                                                     status='reference_pending_execution',runtime_verified=False)
        assert 'While holding this shield' in row['desc'][1] and 'in addition' in row['desc'][1]
        assert row['source_refs']['printed_pages']==[242] and 'candidate_file' not in row['source_refs']
        assert row['runtime_verified'] is False and 'attunement' not in ' '.join(row['desc'])


@pytest.mark.parametrize('change',['missing','rarity','wearing','overwrite_bonus','bool_bonus','parent','source','runtime'])
def test_wrong_family_or_variant_cannot_enter_candidate(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['shield-1']
    if change=='missing':records['magic-items'].pop('shield-1')
    elif change=='rarity':row['rarity']['name']='Rare'
    elif change=='wearing':row['desc'][1]=row['desc'][1].replace('holding','wearing')
    elif change=='overwrite_bonus':row['shield_ac_bonus_reference']['additional_to_normal_shield']=False
    elif change=='bool_bonus':row['shield_ac_bonus_reference']['amount']=True
    elif change=='parent':records['magic-items']['shield']['variants']=[]
    elif change=='source':row['source_refs']['printed_pages']=[208]
    else:row['runtime_verified']=True
    assert shields.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'magic-items':None},{'magic-items':{'shield':None}}])
def test_bad_shapes_produce_gate_issues(bad):
    assert shields.issues(bad)


def test_candidate_gate_requires_shield_family_and_legacy_is_unchanged():
    records=deepcopy(compendium.COLLECTIONS)
    records['magic-items'].pop('shield')
    assert any('Official magic shield field differs' in issue for issue in rules_packages.validate_records(records))
    assert 'shield' not in rules_packages.legacy_records()['magic-items']


def test_normalizer_is_idempotent_and_keeps_community_archive_unchanged(tmp_path):
    overlay=compendium.DATA_DIR/'canonical-overlay.json'
    raw=compendium.DATA_DIR/'srd2014/5e-SRD-Magic-Items.json'
    before=overlay.read_bytes(),hashlib.sha256(raw.read_bytes()).hexdigest()
    copied=tmp_path/'overlay.json'
    copied.write_bytes(before[0])
    result=subprocess.run([sys.executable,'tools/normalize_magic_shields.py','--overlay',str(copied)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert overlay.read_bytes()==before[0] and hashlib.sha256(raw.read_bytes()).hexdigest()==before[1]
    assert copied.read_bytes()==before[0]
