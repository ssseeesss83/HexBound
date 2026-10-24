"""Bag tables preserve full action economy and link only source creatures."""
from copy import deepcopy
import pytest

from backend import compendium, magic_bag_variants as variants, rules_packages


def test_three_bags_and_twenty_four_source_monster_identities_match():
    rows=variants.expected()
    assert len(rows)==3
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==48 and report['creature_links']==24 and not report['differences']
    for row in rows.values():
        ref=row['official_variant_reference']
        assert ref['runtime_verified'] is False
        assert [choice['d8_face'] for choice in ref['roll_table']]==list(range(1,9))


def test_colors_have_distinct_complete_source_tables():
    rows=variants.expected()
    for color,first,last in [('gray','weasel','giant-elk'),('rust','rat','brown-bear'),('tan','jackal','tiger')]:
        row=rows['bag-of-tricks-'+color]
        ref=row['official_variant_reference']
        assert ref['color']==color and ref['roll_table'][0]['monster_id']==first and ref['roll_table'][-1]['monster_id']==last
        assert 'made from '+color+' cloth' in ' '.join(row['desc'])


def test_every_bag_retains_actions_friendly_turn_commands_and_daily_limits():
    for row in variants.expected().values():
        text=' '.join(row['desc'])
        for part in ('weighs 1/2 pound','use an action','throw it up to 20 feet','rolling a d8',
                     'vanishes at the next dawn','reduced to 0 hit points','friendly to you and your companions',
                     'acts on your turn','use a bonus action','in the absence of such orders',
                     'Once three fuzzy objects',"can't be used again until the next dawn"):
            assert part.casefold() in text.casefold()


@pytest.mark.parametrize('change',['table_face','table_monster','table_missing','color','charge_limit','command_action',
    'range','vanish','friendly','weight','monster_missing','monster_name','monster_index','monster_url',
    'verified','zero','bad_desc','missing_record'])
def test_bag_or_cross_collection_creature_drift_fails(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['bag-of-tricks-gray']
    if change=='table_face':row['official_variant_reference']['roll_table'][0]['d8_face']=True
    elif change=='table_monster':row['official_variant_reference']['roll_table'][0]['monster_id']='dragon'
    elif change=='table_missing':row['official_variant_reference']['roll_table'].pop()
    elif change=='color':row['official_variant_reference']['color']='tan'
    elif change in {'charge_limit','command_action','range','vanish','friendly','weight'}:
        old,new={'charge_limit':('three fuzzy','thirty fuzzy'),'command_action':('a Bonus Action','a free action'),
            'range':('20 feet','200 feet'),'vanish':('at the next dawn','in a century'),
            'friendly':('friendly to you','hostile to you'),'weight':('1/2 pound','0 pounds')}[change]
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='monster_missing':records['monsters'].pop('weasel')
    elif change=='monster_name':records['monsters']['weasel']['name']='Dragon'
    elif change=='monster_index':records['monsters']['weasel']['index']='dragon'
    elif change=='monster_url':records['monsters']['weasel']['url']='/api/2014/monsters/dragon'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('bag-of-tricks-gray')
    assert variants.issues(records)


def test_candidate_gate_rejects_bag_monster_identity_drift():
    records=deepcopy(compendium.COLLECTIONS)
    records['monsters']['giant-elk']['url']='/api/2014/monsters/other'
    assert any('Official magic bag variant differs' in issue for issue in rules_packages.validate_records(records))
