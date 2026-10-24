"""Waiting preserves settled steps and the playable source across recovery."""
from copy import deepcopy

import pytest

from backend import rules, scene_storage, story_challenges, story_transitions as routes
from test_native_story_checks import table, extend_graph
from test_story_challenges import authored


def route_table():
    book = authored()
    book['edges'][0]['condition'] = dict(op='fact_equals',ref='lens',value=True)
    state = table(book)
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    return state


def test_wait_is_pure_until_requested_and_never_repeats_settled_check(monkeypatch):
    state = table()
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    story_challenges.resolve(state,'p',story_challenges.prepare(state,'p','find-lens'),receipt_id='check-step')
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Wait rolled'))
    plan = routes.prepare(state,'p','follow-courier',prerequisite_receipt_ids=['check-step'])
    assert state == before and plan['destination']['status']=='pending'
    assert routes.request(state,'p',plan,transition_id='wait1')==dict(status='waiting',replayed=False)
    assert state['campaign']['node_id']=='dock' and state['campaign']['visited']==['dock']
    assert state['campaign']['story_state']==before['campaign']['story_state']
    assert state['attempt_ledger']==before['attempt_ledger'] and state['members']==before['members']
    assert routes.status(state,'p')==routes.status(state,'ally')==dict(status='waiting')
    assert routes.request(state,'p',plan,transition_id='wait1')['replayed']


def test_cancel_retains_history_and_old_request_cannot_resurrect_it():
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    routes.request(state,'p',plan,transition_id='wait1')
    assert routes.cancel(state,'p','wait1')==dict(status='cancelled',replayed=False)
    assert routes.cancel(state,'p','wait1')['replayed']
    assert routes.request(state,'p',plan,transition_id='wait1')==dict(status='cancelled',replayed=True)
    assert not state['pending_transition']
    routes.request(state,'p',plan,transition_id='wait2')
    with pytest.raises(ValueError):routes.cancel(state,'p','wait1-new')
    assert state['pending_transition']['id']=='wait2'


def test_duplicate_pending_and_receipt_reuse_reject_atomically():
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    routes.request(state,'p',plan,transition_id='wait1')
    before = deepcopy(state)
    with pytest.raises(ValueError):routes.request(state,'p',plan,transition_id='wait2')
    tampered = deepcopy(plan)
    tampered['edge_id']='different'
    with pytest.raises(ValueError):routes.request(state,'p',tampered,transition_id='wait1')
    assert state == before


def test_late_resolution_requires_fresh_review_and_never_moves_automatically(monkeypatch):
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    routes.request(state,'p',plan,transition_id='wait1')
    branch = extend_graph(state)
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Resolution status rolled'))
    assert routes.status(state,'p')==dict(status='ready_for_review')
    fresh = routes.prepare(state,'p','follow-courier')
    assert fresh['destination']['node_id']==branch['id']
    with pytest.raises(ValueError):routes.request(state,'p',fresh,transition_id='wait2')
    assert state == before and state['campaign']['node_id']=='dock'


def test_related_change_marks_review_without_undoing_settlement():
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    routes.request(state,'p',plan,transition_id='wait1')
    state['campaign']['story_state']['facts']['lens'].update(value=False,revision=2)
    before = deepcopy(state)
    assert routes.status(state,'p')==dict(status='review_required')
    assert routes.request(state,'p',plan,transition_id='wait1')['replayed']
    with pytest.raises(ValueError):routes.request(state,'p',plan,transition_id='wait2')
    assert state == before


def test_wait_keeps_other_checks_available_and_cancellation_works_during_combat():
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    routes.request(state,'p',plan,transition_id='wait1')
    assert story_challenges.prepare(state,'ally','find-lens')
    state['combat']=dict(active=True)
    assert routes.cancel(state,'p','wait1')['status']=='cancelled'


@pytest.mark.parametrize('change',['leader','epoch','scene','combat','incapacitated','source','rules','missing_proof'])
def test_changed_scope_or_legality_rejects_without_writes(change):
    state = route_table()
    plan = routes.prepare(state,'p','follow-courier')
    if change=='leader':state['_scene_leader_id']='ally'
    elif change=='epoch':state['member_contexts']={'p':dict(scene_instance_id='scene-main',epoch=2)}
    elif change=='scene':state['member_contexts']={'p':dict(scene_instance_id='other',epoch=1)}
    elif change=='combat':state['combat']=dict(active=True)
    elif change=='incapacitated':
        for member in state['members']:member['character']['conditions']=[dict(id='incapacitated')]
    elif change=='source':state['campaign']['node_id']='follow'
    elif change=='rules':state['rules_package_version']='other'
    elif change=='missing_proof':plan['prerequisite_receipt_ids']=['invented']
    before = deepcopy(state)
    with pytest.raises(ValueError):routes.request(state,'p',plan,transition_id='invalid')
    assert state == before


@pytest.mark.parametrize('visibility',['secret','known'])
def test_hidden_edge_id_guess_cannot_bypass_visibility(visibility):
    book = authored()
    book['edges'][0]['visibility']=visibility
    state = table(book)
    with pytest.raises(ValueError,match='当前路线不可用'):routes.prepare(state,'p','follow-courier')


@pytest.mark.parametrize('result',['direct','success','failure'])
def test_legacy_bridge_is_not_a_new_route_that_bypasses_its_action(result):
    book = authored()
    action = dict(id='old-check',label='Old action')
    if result=='direct':action['next_node_id']='follow'
    else:action.update(skill_id='old-skill',success_node_id='follow',failure_node_id='follow')
    book['skill_ids']=['old-skill'] if result!='direct' else []
    book['nodes'][0]['legacy_actions']=[action]
    book['edges']=[dict(id='legacy-'+outcome,**{'from':'dock'},to='follow',
                        legacy_action_id='old-check',legacy_result=outcome)
                   for outcome in (['direct'] if result=='direct' else ['success','failure'])]
    state = table(book)
    assert not state['campaign']['story_state']['effect_receipts']
    with pytest.raises(ValueError,match='当前路线不可用'):routes.prepare(state,'p','legacy-'+result)


def test_main_path_is_navigation_and_does_not_blanket_gate_failure_exit():
    state = table()
    assert not state['campaign']['story_state']['facts']['lens']['value']
    assert routes.prepare(state,'p','follow-courier')['destination']['status']=='pending'
    state['campaign']['package']['scenario']['edges'][0]['main_path']=False
    # Reinitialize because the author version deliberately changed in this fixture.
    from backend.story_runtime import initialize
    state['campaign'].update(initialize(state['campaign']['package']['scenario']))
    assert routes.prepare(state,'p','follow-courier')['destination']['status']=='pending'


def test_ending_condition_checked_without_publishing_ending_or_entering():
    book = authored()
    book['nodes'].append(dict(id='end',kind='ending',title='Hidden ending',text='ENDING_SECRET',
                             ending_condition=dict(op='fact_equals',ref='lens',value=True)))
    book['edges'].append(dict(id='end-route',**{'from':'dock'},to='end'))
    state = table(book)
    with pytest.raises(ValueError,match='当前路线不可用'):routes.prepare(state,'p','end-route')
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    plan = routes.prepare(state,'p','end-route')
    assert plan['destination']['status']=='ready' and 'facts:lens' in plan['read_set']
    assert not state.get('completed') and state['scene_id']=='dock'


def test_pending_roundtrip_is_scene_local_and_receipts_are_global():
    state = route_table()
    routes.request(state,'p',routes.prepare(state,'p','follow-courier'),transition_id='wait1')
    packed = scene_storage.pack(state)
    assert 'pending_transition' not in packed
    assert packed['scene_instances']['scene-main']['local']['pending_transition']['id']=='wait1'
    assert 'transition_receipts' in packed['campaign']
    recovered = scene_storage.unpack(packed)
    assert routes.status(recovered,'p')==dict(status='waiting')


def test_two_scene_waits_cancel_independently_and_survive_packing():
    from backend import session_scope
    state = route_table()
    session_scope.initialize(state)
    canonical = scene_storage.pack(state)
    side = deepcopy(canonical['scene_instances']['scene-main'])
    side.update(id='side',channel_id='side',leader_id='ally')
    canonical['scene_instances']['side'] = side
    canonical['member_contexts']['ally'] = dict(scene_instance_id='side',epoch=2)
    canonical['text_scope']['channels']['side'] = dict(id='side',name='Other')
    canonical['text_scope']['members']['ally'].update(channel='side',epoch=2)
    main = scene_storage.for_actor(canonical,'p')
    routes.request(main,'p',routes.prepare(main,'p','follow-courier'),transition_id='main-wait')
    canonical = scene_storage.pack(main)
    other = scene_storage.for_actor(canonical,'ally')
    assert routes.status(other,'ally') is None
    routes.request(other,'ally',routes.prepare(other,'ally','follow-courier'),transition_id='side-wait')
    with pytest.raises(ValueError):routes.cancel(other,'ally','main-wait')
    routes.cancel(other,'ally','side-wait')
    canonical = scene_storage.pack(other)
    assert routes.status(scene_storage.for_actor(canonical,'p'),'p')==dict(status='waiting')
    assert routes.status(scene_storage.for_actor(canonical,'ally'),'ally') is None


def test_new_leader_must_review_but_can_explicitly_cancel_old_wait():
    state = route_table()
    routes.request(state,'p',routes.prepare(state,'p','follow-courier'),transition_id='wait1')
    state['_scene_leader_id']='ally'
    assert routes.status(state,'ally')==dict(status='review_required')
    with pytest.raises(ValueError):routes.cancel(state,'p','wait1')
    assert routes.cancel(state,'ally','wait1')['status']=='cancelled'


def test_resolved_wait_rechecks_authoritative_destination_encounter_lock():
    from backend import session_scope, world_combat, world_environment, world_state
    state = route_table()
    session_scope.initialize(state)
    state = scene_storage.unpack(world_combat.migrate(world_environment.migrate(scene_storage.pack(state))))
    routes.request(state,'p',routes.prepare(state,'p','follow-courier'),transition_id='wait1')
    # Make the continuation a different physical destination.
    extend_graph(state)
    state['campaign']['runtime_graph']['nodes'][0]['place_id']='warehouse'
    world_state.add_place(state,'warehouse')
    state['world_places']['warehouse'].update(active_encounter_id='foreign-battle',encounter_owner_scene_id='other')
    before = deepcopy(state)
    assert routes.status(state,'p')==dict(status='review_required')
    with pytest.raises(ValueError):routes.prepare(state,'p','follow-courier')
    assert state == before
    state['world_places']['warehouse'].update(active_encounter_id=None,encounter_owner_scene_id=None)
    assert routes.status(state,'p')==dict(status='ready_for_review')
    assert state['pending_transition']['id']=='wait1' and state['campaign']['node_id']=='dock'


def test_schema14_upgrade_backup_and_wait_recovery_preserve_room(tmp_path,monkeypatch):
    import json
    from backend import maintenance, session_scope
    from backend.maintenance import backup_database, restore_backup
    from backend.store import Store
    state = route_table()
    state.update(invite_code='WAITFIXTURE',version=1,action_revision=0)
    session_scope.initialize(state)
    path = tmp_path/'wait.sqlite3'
    store = Store(str(path))
    with store.connect() as db:
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)',
                   (state['id'],state['invite_code'],state['version'],json.dumps(scene_storage.pack(state))))
        db.execute('PRAGMA user_version=13')
    upgraded = Store(str(path))
    assert list((tmp_path/'backups').glob('pre-schema-14-*.zip'))
    recovered = upgraded.get(state['id'])
    before = deepcopy(recovered)
    routes.request(recovered,'p',routes.prepare(recovered,'p','follow-courier'),transition_id='persisted-wait')
    previous = recovered['version']
    recovered['version'] += 1
    upgraded.save(recovered,previous)
    archive = tmp_path/'wait.zip'
    backup_database(path,archive)
    restore_backup(archive,tmp_path/'restored')
    restored = Store(str(tmp_path/'restored/database.sqlite3'))
    restored_state = restored.get(state['id'])
    assert restored_state['pending_transition']==recovered['pending_transition']
    assert restored_state['campaign']['transition_receipts']==recovered['campaign']['transition_receipts']
    assert restored_state['campaign']['story_state']==before['campaign']['story_state']
    assert routes.status(restored_state,'p')==dict(status='waiting')
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',13)
    with pytest.raises(ValueError,match='newer server'):Store(str(path))
