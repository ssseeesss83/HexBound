"""Independent official headings cannot lose a family or count table captions."""
from copy import deepcopy
import pytest
from backend import compendium,rules_packages
from backend import magic_inventory as inventory


def test_official_inventory_precedes_candidate_matching_and_disposes_subheadings():
    official,dispositions=inventory.expected()
    assert len(official)==240 and len(dispositions)==14
    assert len({inventory.key(row['title']) for row in official})==240
    assert sum(row['title']=='Spell Scroll' for row in official)==1
    assert any(row['title']=='Spell Scroll' and row['disposition']=='item_table' for row in dispositions)
    assert any(row['title']=='Avatar of Death' and row['disposition']=='embedded_stat_block' for row in dispositions)
    amulet=next(row for row in official if row['title']=='Amulet of Proof against Detection and Location')
    assert amulet['page']==207 and amulet['continuation']['title']=='Location'


def test_all_families_and_variants_are_uniquely_linked():
    report=inventory.audit(compendium.COLLECTIONS)
    assert report['official_items']==240 and report['normalized_variants']==126 and report['candidate_records']==366
    assert not report['differences'] and not report['unmapped_base_records'] and not report['malformed_records']
    assert len(report['links'])==126 and len(report['variant_ownership'])==126
    assert all(len(row['parent_ids'])==1 for row in report['variant_ownership'])


@pytest.mark.parametrize('change',['missing_base','missing_child','orphan','two_parents','duplicate_link','child_parent',
 'bad_variant','bad_url','bad_name','unmapped','alias_name','sign','both_names_missing','child_url'])
def test_missing_or_incorrect_inventory_relations_cannot_pass(change):
    records=deepcopy(compendium.COLLECTIONS)
    rows=records['magic-items']
    if change=='missing_base':rows.pop('bag-of-holding')
    elif change=='missing_child':rows.pop('armor-1')
    elif change=='orphan':rows['armor']['variants'].pop(0)
    elif change=='two_parents':rows['shield']['variants'].append(deepcopy(rows['armor']['variants'][0]))
    elif change=='duplicate_link':rows['armor']['variants'].append(deepcopy(rows['armor']['variants'][0]))
    elif change=='child_parent':rows['armor-1']['variants']=[deepcopy(rows['armor']['variants'][1])]
    elif change=='bad_variant':rows['armor-1']['variant']=1
    elif change=='bad_url':rows['armor']['variants'][0]['url']='/api/2014/magic-items/other'
    elif change=='bad_name':rows['armor']['variants'][0]['name']='Other'
    elif change=='unmapped':rows['other']=deepcopy(rows['bag-of-holding']);rows['other']['name']='Other'
    elif change=='alias_name':rows['glamoured-studded-leather-armor']['name']='Other'
    elif change=='both_names_missing':
        rows['armor-1'].pop('name');rows['armor']['variants'][0].pop('name')
    elif change=='child_url':rows['armor-1']['url']='/api/2014/magic-items/other'
    else:rows['armor']['name']=rows['armor']['name'].replace('+1','-1')
    assert inventory.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'magic-items':[]},{'magic-items':{'bag-of-holding':None}}])
def test_bad_shapes_are_reported(bad):
    assert inventory.issues(bad)


def test_candidate_gate_rejects_unmapped_base_entry():
    records=deepcopy(compendium.COLLECTIONS)
    records['magic-items']['bag-of-holding']['name']='Other'
    assert any('Official magic inventory differs' in issue for issue in rules_packages.validate_records(records))
