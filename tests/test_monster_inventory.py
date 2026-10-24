"""Official base headers precede canonical forms and optional source variants."""
from collections import Counter
from copy import deepcopy
import pytest

from backend import compendium, monster_inventory as inventory, rules_packages


def test_official_inventory_excludes_only_ten_dragon_family_titles():
    items,dispositions,variants=inventory.expected()
    assert len(items)==317 and len({r['title'] for r in items})==317
    assert len(dispositions)==10 and {r['title'] for r in dispositions}==inventory.FAMILY_TITLES
    assert all(r['disposition']=='dragon_family_title_not_statblock' for r in dispositions)
    assert {r['heading'] for r in variants}=={'Variant: Diseased Giant Rats','Variant: Insect Swarms'}
    assert all(r['size_type_alignment_line'].split()[0] in {'Tiny','Small','Medium','Large','Huge','Gargantuan'} for r in items)


def test_317_official_headers_cover_334_unique_normalized_cards():
    report=inventory.audit(compendium.COLLECTIONS)
    assert report['official_stat_headers']==317 and report['normalized_records']==report['candidate_records']==334
    assert not report['differences'] and not report['unmapped_records'] and not report['duplicate_mappings']
    assert Counter(row['mapping_type'] for row in report['mappings'])=={
        'official_stat_header':309,'explicit_title_alias':2,'derived_monster_form':18,'explicit_source_variant':5}


def test_shapechanger_forms_do_not_become_independent_official_statblocks():
    items,_,_=inventory.expected()
    for title,forms in inventory.FORMS.items():
        row=next(r for r in items if r['title']==title)
        assert len(row['bindings'])==3
        assert {r['name'] for r in row['bindings']}=={title+', '+form+' Form' for form in forms}
    rat=next(r for r in items if r['title']=='Giant Rat')
    assert {r['record_id'] for r in rat['bindings']}=={'giant-rat','giant-rat-diseased'}
    swarm=next(r for r in items if r['title']=='Swarm of Insects')
    assert len(swarm['bindings'])==5


@pytest.mark.parametrize('change',['missing_base','missing_form','missing_optional','unknown','wrong_name','wrong_index',
    'wrong_url','alias_name','hyphen_title','bad_record'])
def test_missing_or_unmapped_identity_cannot_pass(change):
    records=deepcopy(compendium.COLLECTIONS)
    rows=records['monsters']
    if change=='missing_base':rows.pop('aboleth')
    elif change=='missing_form':rows.pop('vampire-mist')
    elif change=='missing_optional':rows.pop('giant-rat-diseased')
    elif change=='unknown':rows['unknown']=deepcopy(rows['aboleth'])
    elif change=='wrong_name':rows['aboleth']['name']='Dragon'
    elif change=='wrong_index':rows['aboleth']['index']='dragon'
    elif change=='wrong_url':rows['aboleth']['url']='/api/2014/monsters/dragon'
    elif change=='alias_name':rows['drow']['name']='Another Elf'
    elif change=='hyphen_title':rows['half-red-dragon-veteran']['name']='Half Blue Dragon Veteran'
    else:rows['aboleth']=None
    assert inventory.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_invalid_collection_shape_returns_inventory_errors(bad):
    assert inventory.issues(bad)


def test_candidate_gate_rejects_unmapped_monster_identity():
    records=deepcopy(compendium.COLLECTIONS)
    records['monsters']['aboleth']['name']='Invented'
    assert any('Official monster identity differs' in issue for issue in rules_packages.validate_records(records))
