"""Authority adapter admission tests before runtime hooks are enabled."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend import scene_storage as scenes, world_environment as environment, world_combat as combat, world_state as world


def legacy():
    return json.loads((Path(__file__).parent / 'fixtures/legacy_room_v06.json').read_text(encoding='utf-8'))


def canonical():
    from backend.session_scope import initialize
    return environment.migrate(scenes.pack(initialize(legacy())))


def view(canonical):
    return combat.materialize(scenes.for_actor(canonical, 'p0'))


def test_migrate_initiative_and_resources_unchanged_without_rule_execution(monkeypatch):
    from backend import campaign, rules
    def forbidden(*args, **kwargs):
        pytest.fail('migration cannot run rules')
    monkeypatch.setattr(campaign, '_enter', forbidden)
    monkeypatch.setattr(campaign, '_start_combat', forbidden)
    monkeypatch.setattr(rules, 'check', forbidden)
    original = canonical()
    before = deepcopy(original)
    result = combat.migrate(original)
    assert original == before
    local = result['scene_instances'][scenes.MAIN_SCENE]['local']['combat']
    assert 'enemies' not in local
    original_combat = legacy()['combat']
    projected = view(result)['combat']
    for key, value in original_combat.items():
        if key != 'enemies':
            assert projected[key] == value
    for old, new in zip(original_combat['enemies'], projected['enemies']):
        assert {key:value for key,value in new.items() if key not in combat.META} == old
    assert combat.migrate(result) == result


def test_alias_is_one_object_and_mismatch_aborts_migration():
    source = canonical()
    c = source['scene_instances'][scenes.MAIN_SCENE]['local']['combat']
    c['enemy'] = deepcopy(c['enemies'][0])
    projected = view(combat.migrate(source))
    assert projected['combat']['enemy'] is projected['combat']['enemies'][0]
    projected['combat']['enemy']['hp'] = 2
    assert projected['combat']['enemies'][0]['hp'] == 2
    c['enemy']['hp'] = 999
    before = deepcopy(source)
    with pytest.raises(world.WorldConflict, match='状态冲突'):
        combat.migrate(source)
    assert source == before


def test_same_template_different_slots_and_death_release_are_authoritative():
    source = canonical()
    c = source['scene_instances'][scenes.MAIN_SCENE]['local']['combat']
    second = deepcopy(c['enemies'][0])
    second['id'] = 'enemy:1:salt-warden'
    c['enemies'].append(second)
    result = combat.migrate(source)
    projected = view(result)
    enemies = projected['combat']['enemies']
    assert enemies[0]['entity_id'] != enemies[1]['entity_id']
    enemies[0]['hp'] = 0
    combat.commit_view(projected)
    assert projected['world_entities'][enemies[0]['entity_id']]['state']['hp'] == 0
    assert projected['world_entities'][enemies[1]['entity_id']]['state']['hp'] > 0
    enemies[1]['hp'] = 0
    projected['combat']['active'] = False
    combat.commit_view(projected)
    combat.commit_view(projected)  # release is not repeated
    place = projected['world_places'][projected['scene_instances'][scenes.MAIN_SCENE]['place_id']]
    assert place['active_encounter_id'] is None
    frozen = combat.freeze(deepcopy(projected))
    restored = view(scenes.pack(frozen))
    assert [enemy['hp'] for enemy in restored['combat']['enemies']] == [0,0]


def test_stale_read_set_rejected_before_any_effect():
    result = combat.migrate(canonical())
    first = view(result)
    stale = view(result)
    first['combat']['enemies'][0]['hp'] = 1
    combat.commit_view(first)
    stale['world_entities'] = deepcopy(first['world_entities'])
    before = deepcopy(stale)
    with pytest.raises(world.WorldConflict, match='版本'):
        combat.validate_read_set(stale)
    assert stale == before
    with pytest.raises(world.WorldConflict, match='版本'):
        combat.commit_view(stale)
    assert stale == before


def test_two_scenes_cannot_own_same_spawn_encounter():
    source = canonical()
    main = source['scene_instances'][scenes.MAIN_SCENE]
    source['scene_instances']['side'] = deepcopy(main)
    source['scene_instances']['side']['id'] = 'side'
    source['members'].append({'id':'side-player'})
    source['member_contexts']['side-player'] = {'scene_instance_id':'side','epoch':1}
    before = deepcopy(source)
    with pytest.raises(world.WorldConflict, match='遭遇'):
        combat.migrate(source)
    assert source == before


def test_serialization_rejects_removed_cards_or_unreleased_encounter():
    projected = view(combat.migrate(canonical()))
    missing = deepcopy(projected)
    missing['combat']['enemies'] = []
    with pytest.raises(world.WorldConflict, match='清单'):
        combat.freeze(missing)
    ended = deepcopy(projected)
    ended['combat']['active'] = False
    with pytest.raises(world.WorldConflict, match='遭遇锁'):
        combat.freeze(ended)
    combat.commit_view(ended)
    assert combat.freeze(ended)['combat']['active'] is False


def test_begin_reserves_before_initiative_and_dead_spawn_never_returns(monkeypatch):
    from backend import rules
    monkeypatch.setattr(rules, 'check', lambda *args, **kwargs: pytest.fail('adapter must not roll'))
    projected = view(combat.migrate(canonical()))
    old = deepcopy(projected['combat']['enemies'][0])
    projected['combat']['enemies'][0]['hp'] = 0
    projected['combat']['active'] = False
    combat.commit_view(projected)
    projected['combat'] = None
    # Same authored slot is dead even if the caller supplies a full-health card.
    old['hp'] = old['max_hp']
    cards, encounter = combat.begin(projected, [old])
    assert cards == [] and encounter is None
    newcomer = {**old, 'id':'enemy:1:salt-warden'}
    cards, encounter = combat.begin(projected, [newcomer])
    assert len(cards) == 1 and encounter
    pid = projected['scene_instances'][scenes.MAIN_SCENE]['place_id']
    assert projected['world_places'][pid]['active_encounter_id'] == encounter
    projected['combat'] = {'active':True,'enemies':cards}
    combat.bind(projected, encounter)
    combat.validate_read_set(projected)
    with pytest.raises(world.WorldConflict, match='活动遭遇'):
        combat.begin(projected, [newcomer])


def test_destination_foreign_encounter_rejected_on_copy_before_changes():
    projected = view(combat.migrate(canonical()))
    projected['combat']['active'] = False
    combat.commit_view(projected)
    pid = environment.place_id(projected, 'blocked')
    world.add_place(projected, pid)
    projected['world_places'][pid].update(active_encounter_id='foreign', encounter_owner_scene_id='other')
    before = deepcopy(projected)
    with pytest.raises(world.WorldConflict, match='另一队'):
        combat.preflight_place(projected, 'blocked')
    assert projected == before
