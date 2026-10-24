"""Source reconciliation must preserve variants and unpriced narrative items."""
from copy import deepcopy
import json
import re
import pytest

from backend import compendium as c
from backend.rules_packages import build_package, build_legacy_package, validate_records


def words(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def test_character_source_passages_match_official_pages():
    report = json.loads((c.DATA_DIR / 'official/character-source-review.json').read_text(encoding='utf-8'))
    pages = json.loads((c.DATA_DIR / 'official/pages.json').read_text(encoding='utf-8'))
    for row in report['records']:
        source = words(' '.join(' '.join(pages[p-1]['columns']) for p in row['printed_pages']))
        for field, value in row['fields'].items():
            assert c.COLLECTIONS[row['kind']][row['id']][field] == value
            for text in value if isinstance(value, list) else [value]:
                if isinstance(text, str):
                    assert words(text) in source, (row['id'], field)


def test_background_missing_items_are_distinct_and_do_not_invent_price_or_weight():
    background = c.BACKGROUNDS['acolyte']
    equipment = background['starting_equipment']
    assert [e['equipment']['index'] for e in equipment] == ['clothes-common', 'pouch', 'vestments']
    prayer, incense = background['narrative_grants']
    assert prayer['choose'] == 1
    assert {r['id'] for r in prayer['options']} == {'prayer-book', 'prayer-wheel'}
    assert incense['quantity'] == 5 and incense['unit'] == 'stick'
    assert all(g['status'] == 'reference_pending_execution' for g in background['narrative_grants'])
    for item in [*prayer['options'], incense]:
        assert not {'cost', 'weight', 'equipment', 'url'} & item.keys()
    assert c.RACES['dwarf']['heavy_armor_speed_reduction_exception'] is True
    assert c.RACES['dwarf']['speed_rule_status'] == 'reference_pending_execution'
    broken = deepcopy(c.COLLECTIONS)
    broken['backgrounds']['acolyte']['starting_equipment'][-1]['equipment']['index'] = 'missing'
    assert validate_records(broken)


@pytest.mark.parametrize('metal,page', [('bronze',294), ('gold',300), ('silver',302)])
def test_adult_dragons_have_exact_official_change_shape_without_new_execution(metal, page):
    dragon = c.MONSTERS[f'adult-{metal}-dragon']
    action = next(a for a in dragon['actions'] if a['name'] == 'Change Shape')
    text = json.loads((c.DATA_DIR / 'official/pages.json').read_text(encoding='utf-8'))[page-1]['columns']
    assert words(action['desc']) in words(' '.join(text))
    assert 'class features' in action['desc'] and 'legendary actions' in action['desc']
    for unaffected in ['adult-brass-dragon', 'adult-copper-dragon']:
        assert not any(a['name'] == 'Change Shape' for a in c.MONSTERS[unaffected]['actions'])


def test_variant_size_and_lich_target_and_half_damage_are_preserved():
    assert c.MONSTERS['wererat-rat']['size'] == 'Small'
    assert c.MONSTERS['weretiger-tiger']['size'] == 'Large'
    assert c.MONSTERS['weretiger-hybrid']['size'] == 'Medium'
    disrupt = next(a for a in c.MONSTERS['lich']['legendary_actions'] if a['name'].startswith('Disrupt Life'))
    assert 'non-undead creature' in disrupt['desc']
    assert disrupt['dc']['success_type'] == 'half'


def test_quarantine_removes_only_unverified_night_hag_items():
    hag = c.MONSTERS['night-hag']
    assert not any(a['name'] == 'Night Hag Items' for a in hag['special_abilities'])
    ethereal = next(a for a in hag['actions'] if a['name'] == 'Etherealness')
    nightmare = next(a for a in hag['actions'] if a['name'].startswith('Nightmare Haunting'))
    assert 'heartstone' in ethereal['desc'] and 'soul bag' in nightmare['desc']
    report = json.loads((c.DATA_DIR / 'official/monster-source-review.json').read_text(encoding='utf-8'))
    correction = next(r for r in report['corrections'] if r['records'] == ['night-hag'])
    assert any(a['name'] == 'Night Hag Items' for a in correction['expected'])
    assert correction['value'] == hag['special_abilities']


def test_candidate_contains_corrections_and_frozen_history_keeps_originals():
    current = build_package()
    legacy = build_legacy_package()
    assert current['validation']['mechanical_completeness'] is False
    assert 'narrative_grants' in current['records']['backgrounds']['acolyte']
    assert 'narrative_grants' not in legacy['records']['backgrounds']['acolyte']
    assert legacy['records']['monsters']['wererat-rat']['size'] == 'Medium'
    assert any(a['name'] == 'Night Hag Items' for a in legacy['records']['monsters']['night-hag']['special_abilities'])
