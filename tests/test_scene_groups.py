"""Public split/merge plans, permissions, privacy, retries and SQL rollback."""
from copy import deepcopy
import json
import sqlite3
import uuid
import pytest
from backend import scene_storage as scenes, world_environment
from test_core_integration import env, room, cmd


def setup(env):
    a,b,store,_ = env
    created=room(a).json()
    rid=created['room']['id']
    joined=b.post('/api/rooms/join',json={'invite_code':created['invite_code'],'player_name':'Other','character_id':'fighter'}).json()
    assert cmd(a,rid,'start')[0].status_code==200
    return a,b,store,rid,created['member_id'],joined['member_id']


def scope(frame):
    return {key:frame[key] for key in ('scene_instance_id','membership_epoch','action_revision')}


def prepare(client,rid,operation,**kwargs):
    frame=client.get(f'/api/rooms/{rid}').json()
    return client.post(f'/api/rooms/{rid}/groups/prepare',json={'operation':operation,'expected_scope':scope(frame),**kwargs})


def commit(client,rid,plan,command=None):
    return client.post(f'/api/rooms/{rid}/groups/commit',json={'plan_id':plan,'command_id':command or uuid.uuid4().hex})


def send(client,rid,kind,payload):
    frame=client.get(f'/api/rooms/{rid}').json()
    return client.post(f'/api/rooms/{rid}/commands',json={'command_id':uuid.uuid4().hex,'type':kind,'payload':payload,'expected_version':frame['version'],
        'expected_scene_instance_id':frame['scene_instance_id'],'expected_membership_epoch':frame['membership_epoch'],'expected_action_revision':frame['action_revision']})


def split(a,rid,member):
    preview=prepare(a,rid,'split',members=[member])
    assert preview.status_code==200,preview.text
    result=commit(a,rid,preview.json()['plan_id'])
    assert result.status_code==200,result.text
    return result.json()


def test_split_and_merge_keep_chat_scoped_and_revoke_old_history(env):
    a,b,store,rid,host,guest=setup(env)
    old_cursor=b.get(f'/api/rooms/{rid}/events').json()['cursor']
    before=store.get(rid)['version']
    preview=prepare(a,rid,'split',members=[guest])
    assert preview.status_code==200,preview.text
    assert store.get(rid)['version']==before
    assert not {'proof','action_revision','entity_versions'} & preview.json().keys()
    assert send(a,rid,'chat',{'text':'Discussion does not invalidate this plan.'}).status_code==200
    command=uuid.uuid4().hex
    result=commit(a,rid,preview.json()['plan_id'],command)
    assert result.status_code==200,result.text
    replay=commit(a,rid,preview.json()['plan_id'],command)
    assert replay.status_code==200 and replay.json()['group_change']['replayed']
    assert a.get(f'/api/rooms/{rid}').json()['party'][0]['id']==host
    side=b.get(f'/api/rooms/{rid}').json()
    assert side['party'][0]['id']==guest and side['scene_leader_id']==guest
    assert b.get(f'/api/rooms/{rid}/events',params={'cursor':old_cursor}).status_code==409
    assert send(b,rid,'chat',{'text':'SIDE_PRIVATE'}).status_code==200
    assert send(a,rid,'chat',{'text':'MAIN_PRIVATE'}).status_code==200
    assert 'SIDE_PRIVATE' not in a.get(f'/api/rooms/{rid}/events').text
    assert 'MAIN_PRIVATE' not in b.get(f'/api/rooms/{rid}/events').text
    groups=a.get(f'/api/rooms/{rid}/groups').json()['groups']
    assert all(set(group)=={'id','members'} for group in groups)
    main=a.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    preview=prepare(a,rid,'merge',source=side['scene_instance_id'],target=main)
    assert preview.status_code==200,preview.text
    result=commit(a,rid,preview.json()['plan_id'])
    assert result.status_code==200,result.text
    assert len(result.json()['room']['party'])==2
    assert 'SIDE_PRIVATE' not in a.get(f'/api/rooms/{rid}/events').text
    assert 'MAIN_PRIVATE' not in b.get(f'/api/rooms/{rid}/events').text
    assert send(b,rid,'chat',{'text':'TOGETHER_AGAIN'}).status_code==200
    assert 'TOGETHER_AGAIN' in a.get(f'/api/rooms/{rid}/events').text


def test_stale_plan_rejected_and_all_members_cannot_leave(env):
    a,b,store,rid,host,guest=setup(env)
    assert prepare(a,rid,'split',members=[host,guest]).status_code==409
    preview=prepare(a,rid,'split',members=[guest]).json()
    assert send(a,rid,'action',{'action_id':'investigate'}).status_code==200
    result=commit(a,rid,preview['plan_id'])
    assert result.status_code==409 and len(store.get(rid)['scene_instances'])==1


def test_scope_and_table_authorization(env):
    a,b,store,rid,host,guest=setup(env)
    assert b.get(f'/api/rooms/{rid}/groups').status_code==403
    assert prepare(b,rid,'split',members=[guest]).status_code==403
    preview=prepare(a,rid,'split',members=[guest]).json()
    assert commit(b,rid,preview['plan_id']).status_code==403
    old=a.get(f'/api/rooms/{rid}').json()
    split(a,rid,host)  # host may lead the new group without reading the old one
    assert len(a.get(f'/api/rooms/{rid}').json()['party'])==1
    bad=a.post(f'/api/rooms/{rid}/groups/prepare',json={'operation':'split','members':[guest],'expected_scope':scope(old)})
    assert bad.status_code==409


def test_merge_rejects_different_clocks_and_battle(env):
    a,b,store,rid,host,guest=setup(env)
    split(a,rid,guest)
    main=a.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    side=b.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    state=scenes.for_actor(store.get(rid),guest)
    previous=state['version']
    state['progression']['world_minutes']+=1
    state['version']+=1
    store.save(state,previous)
    assert prepare(a,rid,'merge',source=side,target=main).status_code==409
    from backend import rules
    state=scenes.for_actor(store.get(rid),host)
    previous=state['version']
    rules.start_combat(state)
    state['version']+=1
    store.save(state,previous)
    assert prepare(a,rid,'split',members=[host]).status_code==409


def test_receipt_failure_rolls_back_membership_and_preserves_plan(env):
    a,b,store,rid,host,guest=setup(env)
    preview=prepare(a,rid,'split',members=[guest]).json()
    before=deepcopy(store.get(rid))
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_group_receipt BEFORE INSERT ON commands BEGIN SELECT RAISE(FAIL,'test receipt failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.commit_group_change(rid,host,preview['plan_id'],'atomic-group-test')
    assert store.get(rid)==before
    with store.connect() as db:
        assert db.execute('SELECT 1 FROM group_plans WHERE id=?',(preview['plan_id'],)).fetchone()
        db.execute('DROP TRIGGER fail_group_receipt')
    assert commit(a,rid,preview['plan_id'],'atomic-group-test').status_code==200


def test_non_host_scene_leader_can_advance_own_group(env):
    a,b,store,rid,host,guest=setup(env)
    split(a,rid,guest)
    assert send(b,rid,'action',{'action_id':'investigate'}).status_code==200
    before=a.get(f'/api/rooms/{rid}').json()
    next_step=send(b,rid,'action',{'action_id':'advance'})
    assert next_step.status_code==200,next_step.text
    assert next_step.json()['room']['scene']['id'] != before['scene']['id']
    assert a.get(f'/api/rooms/{rid}').json()['scene']==before['scene']


def test_empty_merged_source_does_not_prevent_room_completion(env):
    a,b,store,rid,host,guest=setup(env)
    split(a,rid,guest)
    main=a.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    side=b.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    plan=prepare(a,rid,'merge',source=side,target=main).json()
    assert commit(a,rid,plan['plan_id']).status_code==200
    state=scenes.for_actor(store.get(rid),host)
    previous=state['version']
    state.update(status='finished',completed=True,ending='Done')
    state['version']+=1
    store.save(state,previous)
    assert store.get(rid)['status']=='finished'
    assert a.get(f'/api/rooms/{rid}').json()['status']=='finished'
    assert b.get(f'/api/rooms/{rid}').json()['status']=='finished'
    with a.websocket_connect(f'/api/rooms/{rid}/ws') as ws:
        ws.send_json({})
        assert ws.receive_json()['room']['status']=='finished'


def test_merge_also_checks_subminute_environment_clock(env):
    a,b,store,rid,host,guest=setup(env)
    split(a,rid,guest)
    main=a.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    side=b.get(f'/api/rooms/{rid}').json()['scene_instance_id']
    state=scenes.for_actor(store.get(rid),guest)
    previous=state['version']
    state.setdefault('environment',{}).setdefault(state['scene_id'],{})['elapsed_seconds']=6
    state['version']+=1
    store.save(state,previous)
    assert prepare(a,rid,'merge',source=side,target=main).status_code==409


def test_non_leader_cannot_advance_current_group(env):
    a,b,store,rid,host,guest=setup(env)
    assert send(a,rid,'action',{'action_id':'investigate'}).status_code==200
    before=deepcopy(store.get(rid))
    assert send(b,rid,'action',{'action_id':'advance'}).status_code==422
    assert store.get(rid)==before
