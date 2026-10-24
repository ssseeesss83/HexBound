"""All source list clauses are consumed, with correct packaged-unit amounts."""
from copy import deepcopy
import pytest
from backend import compendium,rules_packages
from backend import equipment_contents as packs


def test_complete_seven_pack_lists_match_without_changing_candidates():
    before=deepcopy(compendium.COLLECTIONS)
    report=packs.audit(compendium.COLLECTIONS)
    assert report['inventory_match'] and not report['diffs']
    assert report['summary']==dict(packs=7,relations=66,checks=73,differences=0)
    assert compendium.COLLECTIONS==before
    burglar={row['item_id']:row for row in report['source_packs']['burglars-pack']['contents']}
    assert burglar['rope-hempen-50-feet']['quantity']==1 and burglar['rope-hempen-50-feet']['source_amount']==50
    assert burglar['string-10-feet']['quantity']==1 and burglar['string-10-feet']['source_amount']==10
    assert burglar['piton']['quantity']==10


@pytest.mark.parametrize('change',['missing','extra','duplicate','quantity','bool','url','name','target','shape','category'])
def test_malformed_or_incorrect_relations_cannot_pass(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['equipment']['burglars-pack']
    if change=='missing':row['contents'].pop()
    elif change=='extra':row['contents'].append(deepcopy(records['equipment']['scholars-pack']['contents'][-1]))
    elif change=='duplicate':row['contents'].append(deepcopy(row['contents'][0]))
    elif change=='quantity':row['contents'][0]['quantity']=2
    elif change=='bool':row['contents'][0]['quantity']=True
    elif change=='url':row['contents'][0]['item']['url']='/api/2014/equipment/other'
    elif change=='name':row['contents'][0]['item']['name']='Other'
    elif change=='target':records['equipment'].pop('backpack')
    elif change=='shape':row['contents']=[None]
    else:row['gear_category']=None
    assert packs.issues(records)


@pytest.mark.parametrize('body',[
    'Pack. Includes a previously unknown item.',
    'Pack. Includes 7 feet of string.',
    'Pack. Includes 0 candles.',
    'Pack. Includes a backpack, a backpack.',
    'Pack. Includes a backpack. The pack also has 50 feet of hempen rope plus a bonus.',
])
def test_source_parser_never_ignores_unmapped_clauses(body):
    with pytest.raises(ValueError):packs.parse_pack(body)


@pytest.mark.parametrize('bad',[None,[],{'equipment':None},{'equipment':{'burglars-pack':None}}])
def test_bad_record_shapes_return_issues(bad):
    assert packs.issues(bad)


def test_candidate_gate_checks_all_pack_relations():
    records=deepcopy(compendium.COLLECTIONS)
    records['equipment']['priests-pack']['contents'][-1]['quantity']=2
    assert any('Official equipment pack relation differs' in error for error in rules_packages.validate_records(records))
