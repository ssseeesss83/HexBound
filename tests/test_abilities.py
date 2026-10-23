"""Combat acceptance tests: costs, ownership and persisted effects, not catalog labels."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from backend import abilities as a, characters, content, rules


def battle(cls='wizard', level=1):
    c = characters.create_character(cls, 'Hero')
    c['level'] = level
    s = content.initialize_state()
    s['members'] = [{'id': 'p', 'name': 'Hero', 'character': c}, {'id': 'ally', 'name': 'Ally', 'character': characters.create_character('fighter')}]
    s['combat'] = {'active': True, 'round': 1, 'turn_actor_id': 'p', 'action_used': False, 'bonus_action_used': False, 'dodging': [], 'enemies': [{'id': 'e', 'name': 'Enemy', 'hp': 1000, 'max_hp': 1000, 'ac': 10, 'abilities': {'dex': 10, 'con': 10, 'wis': 10}}]}
    return s


def hero(s):
    return s['members'][0]['character']


def castable(s, sid):
    c = hero(s)
    if sid not in c['prepared_spells']:
        c['prepared_spells'].append(sid)
    if sid not in c['known_spells']:
        c['known_spells'].append(sid)


def test_ownership_unsupported_and_invalid_target_are_atomic():
    s = battle()
    original = deepcopy(s)
    for action, target in [('cast:fireball', 'e'), ('cast:magic-missile', 'ally')]:
        with pytest.raises(ValueError):
            a.apply_action(s, 'p', action, target)
        assert s == original
    castable(s, 'wish')
    original = deepcopy(s)
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'cast:wish', 'e')
    assert s == original
    assert a.spell_automation('wish')['status'] == 'reference'


@patch('backend.rules.secrets.randbelow', return_value=0)
def test_magic_missile_consumes_one_slot_and_action(mock):
    s = battle()
    before = hero(s)['spell_slots']['1']['current']
    events = a.apply_action(s, 'p', 'cast:magic-missile', 'e')
    assert len(events) == 3
    assert s['combat']['enemies'][0]['hp'] == 994
    assert hero(s)['spell_slots']['1']['current'] == before - 1
    assert s['combat']['action_used']
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'cast:magic-missile', 'e')


@patch('backend.rules.secrets.randbelow', return_value=0)
def test_bonus_spell_allows_cantrip_but_not_leveled_action(mock):
    s = battle('cleric')
    castable(s, 'healing-word')
    s['members'][1]['character']['hp'] = 0
    a.apply_action(s, 'p', 'cast:healing-word', 'ally')
    assert s['members'][1]['character']['hp'] > 0
    assert s['combat']['bonus_action_used'] and not s['combat']['action_used']
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'cast:bless', 'p')
    a.apply_action(s, 'p', 'cast:sacred-flame', 'e')
    assert s['combat']['action_used']


def test_concentration_ends_on_failed_damage_save_and_buff_stops():
    s = battle('cleric')
    castable(s, 'shield-of-faith')
    a.apply_action(s, 'p', 'cast:shield-of-faith', 'ally')
    ally = s['members'][1]['character']
    assert a.armor_class(s, ally) == ally['ac'] + 2
    with patch('backend.rules.secrets.randbelow', return_value=0):
        result = rules.damage_character(hero(s), 1, state=s)
    assert result['concentration']['success'] is False
    assert hero(s)['concentration'] is None
    assert a.armor_class(s, ally) == ally['ac']


@patch('backend.rules.secrets.randbelow', return_value=0)
def test_extra_attack_and_action_surge_budget(mock):
    s = battle('fighter', 5)
    hero(s)['resources']['action-surge'] = {'current': 1, 'max': 1}
    a.weapon_attack(s, 'p', 'e')
    assert s['combat']['attacks_remaining'] == 1
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'feature:action-surge')
    a.weapon_attack(s, 'p', 'e')
    with pytest.raises(ValueError):
        a.weapon_attack(s, 'p', 'e')
    a.apply_action(s, 'p', 'feature:action-surge')
    a.weapon_attack(s, 'p', 'e')
    a.weapon_attack(s, 'p', 'e')
    assert hero(s)['resources']['action-surge']['current'] == 0


@patch('backend.rules.secrets.randbelow', return_value=0)
def test_flurry_uses_bonus_and_ki_after_attack(mock):
    s = battle('monk', 2)
    hero(s)['resources']['ki'] = {'current': 2, 'max': 2}
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'feature:flurry-of-blows', 'e')
    a.weapon_attack(s, 'p', 'e')
    events = a.apply_action(s, 'p', 'feature:flurry-of-blows', 'e')
    assert len(events) == 2
    assert hero(s)['resources']['ki']['current'] == 1
    assert s['combat']['bonus_action_used']


def test_rage_resistance_and_slotless_smite_miss():
    s = battle('barbarian')
    a.apply_action(s, 'p', 'feature:rage')
    hp = hero(s)['hp']
    rules.damage_character(hero(s), 5, damage_type='slashing')
    assert hero(s)['hp'] == hp - 2
    p = battle('paladin', 2)
    hero(p)['spell_slots'] = {'1': {'current': 2, 'max': 2}}
    with patch('backend.rules.secrets.randbelow', return_value=0):
        a.apply_action(p, 'p', 'feature:divine-smite', 'e')
    assert hero(p)['spell_slots']['1']['current'] == 2


def test_downed_cannot_cast_and_invalid_multitarget_never_spends():
    s = battle('cleric')
    before = deepcopy(s)
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'cast:bless', options={'target_ids': ['p', 'p']})
    assert s == before
    hero(s)['hp'] = 0
    with pytest.raises(ValueError):
        a.apply_action(s, 'p', 'cast:bless', 'ally')


@patch('backend.rules.secrets.randbelow', return_value=0)
def test_extra_director_encounter_does_not_complete_main_scene(mock):
    s = battle()
    s['combat']['director_encounter'] = True
    s['combat']['enemies'][0]['hp'] = 1
    before = deepcopy(s['flags'])
    a.apply_action(s, 'p', 'cast:magic-missile', 'e')
    assert not s['combat']['active']
    assert s['flags'] == before


def test_aoe_rolls_damage_once_then_saves_for_each_target():
    s = battle()
    castable(s, 'burning-hands')
    s['combat']['enemies'].append({**deepcopy(s['combat']['enemies'][0]), 'id': 'e2'})
    with patch('backend.rules.roll_dice', return_value={'dice': [3, 3, 3], 'total': 9}) as dice, patch('backend.rules.check', return_value={'success': False, 'dice': [1]}):
        a.apply_action(s, 'p', 'cast:burning-hands', options={'target_ids': ['e', 'e2']})
    assert dice.call_count == 1
    assert [x['hp'] for x in s['combat']['enemies']] == [991, 991]


def test_legacy_full_party_rest_cannot_bypass_modern_rests():
    s = battle('fighter')
    s['combat'] = None
    s['host_member_id'] = 'p'
    hero(s)['hp'] -= 1
    original = deepcopy(s)
    with pytest.raises(ValueError, match='短休或长休'):
        rules.apply_action(s, 'p', 'rest')
    assert s == original


@pytest.mark.parametrize('expertise,expected', [(False, 2), (True, 4)])
@patch('backend.rules.secrets.randbelow', return_value=9)
def test_classic_scene_explicit_skill_training(mock, expertise, expected):
    s = battle('rogue')
    s['combat'] = None
    s['scene_index'] = 2
    hero(s)['skills'] = ['investigation']
    hero(s)['expertise'] = ['investigation'] if expertise else []
    r = rules.apply_action(s, 'p', 'investigate')[0]['roll']
    assert r['skill_id'] == 'investigation'
    assert r['proficiency_bonus'] == expected
    assert r['total'] == 10 + rules.modifier(hero(s)['abilities']['int']) + expected


@patch('backend.rules.secrets.randbelow', return_value=9)
def test_untyped_and_generated_checks_do_not_infer_skill_from_ability(mock):
    s = battle('rogue')
    s['combat'] = None
    s['scene_index'] = 3
    hero(s)['skills'] = hero(s)['expertise'] = ['investigation']
    r = rules.apply_action(s, 'p', 'repair')[0]['roll']
    assert r['skill_id'] is None and r['proficiency_bonus'] == 0
    s = battle('rogue')
    s['combat'] = None
    s['mode'] = 'free'
    hero(s)['skills'] = hero(s)['expertise'] = ['survival']
    r = rules.apply_action(s, 'p', 'investigate')[0]['roll']
    assert r['skill_id'] is None and r['proficiency_bonus'] == 0


@pytest.mark.parametrize('expertise,expected', [(False, 2), (True, 4)])
@patch('backend.rules.secrets.randbelow', return_value=9)
def test_campaign_explicit_proficiency_skill(mock, expertise, expected):
    from backend import campaign
    s = battle('rogue')
    hero(s)['skills'] = ['investigation']
    hero(s)['expertise'] = ['investigation'] if expertise else []
    card = {'id': 'test', 'name': '调查', 'ability': 'int', 'bonus': 1, 'dc': 12, 'proficiency_skill': 'investigation', 'uses': None}
    with patch('backend.campaign._spend'):
        r = campaign._effect_check(s, 'p', card, None)['roll']
    assert r['proficiency_bonus'] == expected
    assert r['total'] == 10 + rules.modifier(hero(s)['abilities']['int']) + expected + 1
    legacy = content.new_character('scholar')
    s['members'][0]['character'] = legacy
    with patch('backend.campaign._spend'):
        r = campaign._effect_check(s, 'p', card, None)['roll']
    assert r['proficiency_bonus'] == 0
