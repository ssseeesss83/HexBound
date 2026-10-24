from copy import deepcopy
import json
import pytest
from backend import scene_storage as scenes, world_environment as env, world_state as world
from backend.free_actions import advance_environment
from backend.store import Store


def room():
    raw = {'id':'r', 'invite_code':'INV', 'version':1, 'status':'playing',
           'members':[{'id':'a'}, {'id':'b'}], 'progression':{'world_minutes':0},
           'scene_id':'hall', 'scene':{'id':'hall','objects':[{'id':'crate','hp':12,'tags':['flammable']}]},
           'environment':{'hall':{'objects':{'crate':{'hp':8,'burning':True}},'tick':2,'elapsed_seconds':12}}}
    canonical = scenes.pack(raw)
    canonical['scene_instances']['side'] = deepcopy(canonical['scene_instances'][scenes.MAIN_SCENE])
    canonical['scene_instances']['side']['id'] = 'side'
    canonical['member_contexts']['b']['scene_instance_id'] = 'side'
    return canonical


def test_migration_retains_damage_and_has_one_authoritative_copy():
    original = room()
    before = deepcopy(original)
    migrated = env.migrate(original)
    assert original == before
    assert len(migrated['world_entities']) == 1
    for instance in migrated['scene_instances'].values():
        assert 'objects' not in instance['local']['environment']['hall']
    view = scenes.for_actor(migrated, 'a')
    assert view['environment']['hall']['objects']['crate']['hp'] == 8
    assert env.migrate(migrated) == migrated


def test_conflicting_old_copies_abort_and_schema_does_not_advance(tmp_path):
    original = room()
    original['scene_instances']['side']['local']['environment']['hall']['objects']['crate']['hp'] = 1
    before = deepcopy(original)
    with pytest.raises(world.WorldConflict, match='冲突'):
        env.migrate(original)
    assert original == before
    path = str(tmp_path / 'conflict.sqlite3')
    store = Store(path)
    with store.connect() as db:
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)', ('r','INV',1,json.dumps(original)))
        db.execute('PRAGMA user_version=6')
    with pytest.raises(world.WorldConflict, match='冲突'):
        Store(path)
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 6
        assert json.loads(db.execute('SELECT state FROM rooms').fetchone()[0]) == original


def test_explicit_read_set_and_serialization_guard():
    migrated = env.migrate(room())
    first = scenes.for_actor(migrated, 'a')
    stale = scenes.for_actor(migrated, 'b')
    first['environment']['hall']['objects']['crate']['hp'] = 3
    with pytest.raises(world.WorldConflict, match='尚未'):
        scenes.pack(first)
    env.commit_view(first)
    env.commit_view(first)  # idempotent writeback
    canonical = scenes.pack(first)
    observed = scenes.for_actor(canonical, 'b')
    assert observed['environment']['hall']['objects']['crate']['hp'] == 3
    stale['world_entities'] = deepcopy(canonical['world_entities'])
    stale['environment']['hall']['objects']['crate']['hp'] = 0
    with pytest.raises(world.WorldConflict, match='版本'):
        env.commit_view(stale)
    assert next(iter(stale['world_entities'].values()))['state']['hp'] == 3


def test_shared_time_beat_burns_once_and_reads_do_not_tick():
    canonical = env.migrate(room())
    first = scenes.for_actor(canonical, 'a')
    advance_environment(first)
    env.commit_view(first)
    canonical = scenes.pack(first)
    second = scenes.for_actor(canonical, 'b')
    before = deepcopy(second['world_entities'])
    assert scenes.for_actor(canonical, 'a')['world_entities'] == before
    advance_environment(second)  # same logical timestamp 18s
    env.commit_view(second)
    assert second['world_entities'] == before
    assert second['environment']['hall']['objects']['crate']['hp'] == 6
    advance_environment(second)  # next beat 24s
    env.commit_view(second)
    assert second['environment']['hall']['objects']['crate']['hp'] == 4


def test_leave_and_revisit_retains_authority():
    view = scenes.for_actor(env.migrate(room()), 'a')
    view['environment']['hall']['objects']['crate']['hp'] = 0
    view['environment']['hall']['objects']['crate']['destroyed'] = True
    view.update(scene_id='yard', scene={'id':'yard','objects':[]})
    env.prepare_save(view)
    view = scenes.for_actor(scenes.pack(view), 'a')
    view.update(scene_id='hall', scene={'id':'hall','objects':[{'id':'crate','hp':12,'tags':['flammable']}]})
    env.prepare_save(view)
    obj = view['environment']['hall']['objects']['crate']
    assert obj['hp'] == 0 and obj['destroyed']
