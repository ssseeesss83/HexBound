"""Bounded sources preserve rules, supporting prose, nested choices and sidebars."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re

import pytest

from backend import compendium, monster_bodies as bodies, monster_legendary, rules_packages
from backend.equipment_source import normalize
from backend.magic_bodies import equivalent


def test_source_inventory_and_all_post_challenge_spans_are_lossless():
    data=bodies.document()
    assert len(data['blocks'])==317
    kinds=Counter(e['kind'] for b in data['blocks'] for e in b['events'])
    assert kinds=={'label':1472,'section':356,'narrative':47}
    for block in data['blocks']:
        assert all(s['text'].strip() for s in block['segments'])
        assert 'System Reference Document' not in block['text']
        text=normalize(block['text'])
        match=re.search(r'Challenge [\d/]+ \([\d,]+ XP\)',text)
        assert match
        assert equivalent(text[match.end():],' '.join(e['text'] for e in block['events'])),block['title']


def test_43_plain_bold_subheadings_are_preserved_within_parent_ranges():
    data=bodies.document()
    nested=[]
    for block in data['blocks']:
        parent=None
        for event in block['events']:
            if event['kind']=='label' and event['section']=='actions':
                if event['font'].endswith('+Calibri-Bold'):
                    nested.append((block['title'],parent,event['name']))
                else:parent=event['name']
    assert len(nested)==43
    assert Counter(p.split(' (',1)[0] for _,p,_ in nested)=={'Breath Weapons':40,'Roar':3}
    assert len({title for title,_,_ in nested})==21


def test_every_legendary_tail_matches_the_previously_verified_full_block():
    rows=monster_legendary.expected()
    official={row['block']['title']:row['block'] for row in rows.values()}
    checked=0
    for block in bodies.document()['blocks']:
        if block['title'] not in official:continue
        texts=[e['text'] for e in block['events'] if e['section']=='legendary_actions']
        assert equivalent(' '.join(texts),' '.join(s['text'] for s in official[block['title']]['segments']))
        checked+=1
    assert checked==30


def test_narrative_starts_at_full_paragraph_and_is_not_appended_to_last_action():
    by_title={b['title']:b for b in bodies.document()['blocks']}
    for title,start in [('Reef Shark','Smaller than giant sharks'),('Bandit Captain','It takes a strong personality'),
        ('Noble','Nobles wield great authority')]:
        block=by_title[title]
        prose=[e for e in block['events'] if e['kind']=='narrative']
        assert len(prose)==1 and normalize(prose[0]['text']).startswith(start)
        assert start not in [e for e in block['events'] if e['kind']=='label'][-1]['text']
    assert 'courtiers' in by_title['Noble']['events'][-1]['text']


def test_supporting_prose_includes_rule_bearing_text():
    rows=bodies.expected()
    frog=rows['frog']['supporting_prose'][0]['text']
    beetle=normalize(rows['giant-fire-beetle']['supporting_prose'][0]['text'])
    assert 'no effective attacks' in frog
    assert '1d6 days after the beetle dies' in beetle
    assert 'additional 10 feet' in rows['giant-fire-beetle']['text']
    assert 'may contain rules' in rows['frog']['limitation']


def test_variant_sidebars_have_explicit_owner_and_do_not_contaminate_neighbors():
    rows=bodies.expected()
    assert not rows['swarm-of-ravens']['source_variants']
    assert 'Variant: Insect Swarms' not in rows['swarm-of-ravens']['text']
    for rid in ['swarm-of-insects','swarm-of-spiders','swarm-of-wasps']:
        variant=rows[rid]['source_variants'][0]
        assert variant['owner']=='Swarm of Insects' and 'Web Walker.' in variant['text']
    assert not rows['spider']['source_variants']
    assert rows['giant-rat-diseased']['source_variants'][0]['owner']=='Giant Rat'


def test_all_candidate_refs_are_complete_and_only_reference_fields_are_added():
    report=bodies.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==334 and not report['differences']
    corrections=[r for r in compendium.CANONICAL_OVERLAY['corrections'] if r['id'].startswith('official-monster-full-source-')]
    assert len(corrections)==334
    assert all(r['expected'] is None and r['path']==['official_stat_block_reference'] for r in corrections)
    for row in bodies.expected().values():
        assert row['status']=='reference_pending_execution' and row['runtime_verified'] is False
        assert row['derived_form_eligibility_verified'] is False


@pytest.mark.parametrize('change',['missing','truncate','wrong_source','runtime','form_permission','sidebar_owner','drop_prose'])
def test_incomplete_or_promoted_source_reference_is_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['monsters']['aboleth']
    if change=='missing':row.pop('official_stat_block_reference')
    elif change=='truncate':row['official_stat_block_reference']['text']='Aboleth'
    elif change=='wrong_source':row['official_stat_block_reference']['source_blocks_sha256']='0'*64
    elif change=='runtime':row['official_stat_block_reference']['runtime_verified']=True
    elif change=='form_permission':row['official_stat_block_reference']['derived_form_eligibility_verified']=True
    elif change=='sidebar_owner':records['monsters']['swarm-of-spiders']['official_stat_block_reference']['source_variants'][0]['owner']='Spider'
    else:records['monsters']['frog']['official_stat_block_reference']['supporting_prose']=[]
    assert bodies.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_invalid_collections_return_errors(bad):
    assert bodies.issues(bad)


def test_source_hash_mismatch_fails_before_interpreting_blocks(tmp_path,monkeypatch):
    root=Path(bodies.__file__).parent/'data/official'
    (tmp_path/'monster-blocks.json').write_bytes((root/'monster-blocks.json').read_bytes()+b' ')
    monkeypatch.setattr(bodies,'source',lambda _:None)
    with pytest.raises(ValueError,match='hash mismatch'):bodies.document(tmp_path)


def test_package_gate_rejects_source_truncation():
    records=deepcopy(compendium.COLLECTIONS)
    records['monsters']['basilisk']['official_stat_block_reference']['text']='Petrifying Gaze'
    assert any('Official monster complete source differs' in e for e in rules_packages.validate_records(records))
