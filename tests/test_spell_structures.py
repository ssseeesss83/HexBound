"""Source stages retain exceptional timing without claiming runtime handlers."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend import compendium as c
from backend.spell_structures import load_structures, REVIEWED_IDS
from backend.rules_packages import build_package, build_legacy_package


def stages(sid):return {row['id']:row for row in c.SPELLS[sid]['effect_structure']['stages']}


def test_delayed_damage_and_retaliation_choices_keep_distinct_semantics():
    acid=stages('acid-arrow')
    assert acid['initial']['resolution']['on_miss']['schedule_delayed'] is False
    assert acid['initial']['resolution']['on_hit']['damage_at_slot_level']['9']=='11d4'
    assert acid['delayed']['resolution']['damage_at_slot_level']['9']=='9d4'
    assert acid['delayed']['requires']['initial_attack']=='hit'
    assert acid['delayed']['trigger']['event']=='target_next_turn_end'
    assert acid['delayed']['persists_after_instantaneous_cast']
    shield=c.SPELLS['fire-shield']['effect_structure']
    assert shield['choices'][0]['choose']==1
    assert shield['choices'][0]['change_rule']=='not_provided_by_spell_text'
    assert shield['choices'][0]['options']=={'warm':{'resistance':'cold'},'chill':{'resistance':'fire'}}
    for stage in shield['stages']:
        assert stage['action_cost']=='none' and stage['frequency']=='every_qualifying_hit'
        assert stage['targets']['distance_to_caster_lte_ft']==5
        assert stage['targets']['attacker_kind']=='creature'
    assert stages('fire-shield')['chill-retaliation']['resolution']['damage_type']=='cold'


def test_walls_keep_secondary_saves_types_and_first_entry_identity():
    ice=stages('wall-of-ice')
    assert ice['appearance']['resolution']['saving_throw']['ability']=='dex'
    assert ice['appearance']['resolution']['damage_at_slot_level']['9']=='16d6'
    assert ice['frigid-air']['resolution']['saving_throw']['ability']=='con'
    assert ice['frigid-air']['resolution']['damage_at_slot_level']['9']=='8d6'
    assert ice['frigid-air']['frequency']=='first_passage_per_any_turn'
    panels=c.SPELLS['wall-of-ice']['effect_structure']['barrier']['shapes']['panels']
    assert panels['declared_panel_count']==10 and 'max_count' not in panels
    thorns=stages('wall-of-thorns')
    assert thorns['appearance']['resolution']['damage_type']=='piercing'
    assert thorns['entry']['resolution']['damage_type']=='slashing'
    assert thorns['entry']['frequency']=='first_entry_per_any_turn'
    assert thorns['turn-end']['trigger']['event']=='creature_ends_own_turn_in_wall'
    assert c.SPELLS['wall-of-thorns']['effect_structure']['barrier']['movement_cost_ft_per_foot']==4


def test_storm_rounds_and_guardians_do_not_invent_trigger_or_target_rules():
    storm=stages('storm-of-vengeance')
    assert storm['round-2']['targets']['selector']=='each_creature_and_object_under_cloud'
    assert storm['round-3']['resolution']['object_resolution']=='pending_general_object_rules'
    assert storm['round-3']['trigger']['event']=='caster_turn_in_spell_round'
    assert storm['round-4']['spell_rounds']==[4]
    assert storm['round-5-to-10']['spell_rounds']==[5,6,7,8,9,10]
    assert storm['appearance']['resolution']['on_failed_save_condition']['independent_of_spell_duration']
    guards=stages('spirit-guardians')
    assert guards['exclusions']['targets']['selector']=='any_number_of_creatures_visible_to_caster_at_cast'
    assert not guards['speed']['resolution']['creates_difficult_terrain']
    assert guards['entry']['frequency']=='first_entry_per_any_turn'
    assert guards['turn-start']['trigger']['event']=='creature_starts_own_turn_in_aura'
    assert 'damage_at_slot_level' not in guards['exclusions']['resolution']
    assert c.SPELLS['spirit-guardians']['effect_structure']['damage_type_by_alignment']=={'good':'radiant','neutral':'radiant','evil':'necrotic'}


def test_stage_references_enter_candidate_only_without_claiming_execution():
    candidate=build_package()
    legacy=build_legacy_package()
    for sid in REVIEWED_IDS:
        spec=candidate['records']['spells'][sid]['effect_structure']
        assert not spec['runtime_verified'] and spec['status']=='reference_pending_execution'
        assert spec['interpretation_pending']
        assert 'effect_structure' not in legacy['records']['spells'][sid]
    assert not candidate['validation']['mechanical_completeness']


@pytest.mark.parametrize('mutation', ['source','slot','save','coverage','missing'])
def test_malformed_reference_never_partially_attaches(tmp_path,mutation):
    payload=json.loads((c.DATA_DIR/'spell-effect-structures.json').read_text(encoding='utf-8'))
    record=payload['records']['acid-arrow']
    if mutation=='source':record['source']['spell_block_sha256']='0'*64
    elif mutation=='slot':record['stages'][0]['resolution']['on_hit']['damage_at_slot_level'].pop('9')
    elif mutation=='save':payload['records']['wall-of-ice']['stages'][0]['resolution']['saving_throw']['ability']='unknown'
    elif mutation=='coverage':record['runtime_verified']=True
    else:payload['records'].pop('acid-arrow')
    path=tmp_path/'bad.json';path.write_text(json.dumps(payload),encoding='utf-8')
    before=deepcopy(c.COLLECTIONS)
    with pytest.raises(ValueError):load_structures(c.COLLECTIONS,path=path)
    assert c.COLLECTIONS==before
