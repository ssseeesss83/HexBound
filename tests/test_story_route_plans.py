"""Native route capability confirmation never enters an unresolved frontier."""
from copy import deepcopy
import pytest
from backend import action_menu, action_plans, campaign, director, rules, story_runtime
from backend import story_transitions as routes
from test_native_story_checks import table, extend_graph
from test_story_challenges import authored


def book_with_labels():
    book = authored()
    book['edges'][0]['label'] = '跟随信使'
    book['edges'][0]['outcome'] = 'HIDDEN_FUTURE_CONSEQUENCE'
    return book


def proposal(state, actor='p', action='story-route:follow-courier'):
    return director.validate_proposal(dict(kind='capability',action_id=action,label='选择',text='请求审核'),state,actor)


def test_both_entry_plans_wait_then_cancel_without_roll_or_movement(monkeypatch):
    state = table(book_with_labels())
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Route rolled'))
    before = deepcopy(state)
    selected = proposal(state)
    described = director._capability_fallback(state,'p','我选择跟随信使')
    second = director.validate_proposal(described,state,'p')
    assert selected['plan']['route_plan']==second['plan']['route_plan']
    assert state==before
    public = director.public_proposal(selected,state)
    assert 'route_plan' not in public['plan']
    assert 'HIDDEN_FUTURE_CONSEQUENCE' not in str(public)
    director.resolve(state,'p',selected)
    assert state['campaign']['node_id']=='dock' and state['campaign']['visited']==['dock']
    assert state['campaign']['story_state']==before['campaign']['story_state']
    assert state['members']==before['members'] and not state.get('attempt_ledger')
    assert routes.status(state,'ally')==dict(status='waiting')
    actions = action_menu.available(state,'p')
    assert 'story-cancel' in {row['id'] for row in actions}
    assert 'story-route:follow-courier' not in {row['id'] for row in actions}
    # Other legal checks remain available, and cancel is a fresh plan.
    assert 'story-check:find-lens' in {row['id'] for row in actions}
    cancellation = proposal(state,action='story-cancel')
    director.resolve(state,'p',cancellation)
    assert state['pending_transition'] is None
    assert state['campaign']['transition_receipts'][selected['id']]['status']=='cancelled'


def test_ready_requires_fresh_plan_and_commits_one_entry_with_old_wait_receipt(monkeypatch):
    state = table(book_with_labels())
    old = proposal(state)
    director.resolve(state,'p',old)
    branch = extend_graph(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Non-combat route rolled'))
    before = deepcopy(state)
    assert routes.status(state,'p')==dict(status='ready_for_review')
    with pytest.raises(ValueError):director.resolve(state,'p',old)
    assert state==before
    fresh = proposal(state)
    assert fresh['plan']['route_plan']['pending_transition_id']==old['id']
    assert not director.public_proposal(fresh,state)['stale']
    director.resolve(state,'p',fresh)
    assert state['scene_id']==state['campaign']['node_id']==branch['id']
    assert state['campaign']['visited']==['dock',branch['id']]
    assert state['pending_transition'] is None
    assert all(row['status']=='entered' for row in state['campaign']['transition_receipts'].values())
    settled = deepcopy(state)
    with pytest.raises(ValueError):director.resolve(state,'p',fresh)
    assert state==settled


def test_cancel_replacement_invalidates_review_without_fingerprint_change():
    state = table(book_with_labels())
    first = proposal(state)
    director.resolve(state,'p',first)
    cancellation = proposal(state,action='story-cancel')
    routes.cancel(state,'p',first['id'])
    second = proposal(state)
    director.resolve(state,'p',second)
    before = deepcopy(state)
    assert director.public_proposal(cancellation,state)['stale']
    with pytest.raises(ValueError):director.resolve(state,'p',cancellation)
    assert state==before and state['pending_transition']['id']==second['id']


@pytest.mark.parametrize('change',['fact','epoch','leader','combat','destination_lock'])
def test_ready_route_rechecks_dependencies_and_authority_atomically(change):
    from backend import scene_storage, session_scope, world_combat, world_environment, world_state
    state = table(book_with_labels())
    state['campaign']['package']['scenario']['edges'][0]['condition'] = dict(op='fact_equals',ref='lens',value=False)
    state['campaign'].update(story_runtime.initialize(state['campaign']['package']['scenario']))
    extend_graph(state)
    if change=='destination_lock':
        state['campaign']['runtime_graph']['nodes'][0]['place_id']='warehouse'
        session_scope.initialize(state)
        state = scene_storage.unpack(world_combat.migrate(world_environment.migrate(scene_storage.pack(state))))
    selected = proposal(state)
    if change=='fact':state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    elif change=='epoch':state['member_contexts']={'p':dict(scene_instance_id='scene-main',epoch=2)}
    elif change=='leader':state['_scene_leader_id']='ally'
    elif change=='combat':state['combat']=dict(active=True)
    else:
        world_state.add_place(state,'warehouse')
        state['world_places']['warehouse'].update(active_encounter_id='foreign',encounter_owner_scene_id='other')
    before = deepcopy(state)
    assert director.public_proposal(selected,state)['stale']
    with pytest.raises(ValueError):director.resolve(state,'p',selected)
    assert state==before


@pytest.mark.parametrize('options',[dict(skill_id='perception'),dict(slot_level=1),dict(resource_amount=1),dict(target_ids=['p'])])
def test_route_rejects_mechanical_parameters(options):
    state = table(book_with_labels())
    before = deepcopy(state)
    with pytest.raises(ValueError):action_plans.prepare(state,'p','story-route:follow-courier',options=options)
    with pytest.raises(ValueError):action_plans.prepare(state,'p','story-route:follow-courier',target_id='p')
    assert state==before


def test_route_menu_and_guessed_ids_obey_leader_visibility_and_legacy_bridge():
    state = table(book_with_labels())
    assert not routes.menu(state,'ally')
    with pytest.raises(ValueError):proposal(state,actor='ally')
    for changes in [dict(visibility='secret'),dict(legacy_action_id='old-direct',legacy_result='direct')]:
        book = book_with_labels()
        book['edges'][0].update(changes)
        if 'legacy_action_id' in changes:
            book['nodes'][0]['legacy_actions'] = [dict(id='old-direct',label='Old',next_node_id='follow')]
        state = table(book)
        assert not routes.menu(state,'p')
        with pytest.raises(ValueError):proposal(state)


def test_entry_guard_rejects_frontier_and_false_ending_before_touching_world():
    state = table(book_with_labels())
    before = deepcopy(state)
    with pytest.raises(ValueError):campaign._enter(state,'follow',[])
    assert state==before
    book = book_with_labels()
    book['nodes'].append(dict(id='finish',kind='ending',title='Ending',text='DONE',
                             ending_condition=dict(op='fact_equals',ref='lens',value=True)))
    book['edges'].append(dict(id='finish-route',label='结束旅程',**{'from':'dock'},to='finish'))
    state = table(book)
    before = deepcopy(state)
    with pytest.raises(ValueError):campaign._enter(state,'finish',[])
    assert state==before
    assert 'story-route:finish-route' not in {row['id'] for row in routes.menu(state,'p')}
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    selected = proposal(state,action='story-route:finish-route')
    events = director.resolve(state,'p',selected)
    assert state['completed'] and state['ending']=='DONE' and events[0]['kind']=='ending'


def test_entry_failure_rolls_back_wait_cursor_and_visits(monkeypatch):
    state = table(book_with_labels())
    waiting = proposal(state)
    director.resolve(state,'p',waiting)
    extend_graph(state)
    selected = proposal(state)
    before = deepcopy(state)
    def fail(work,*args):
        work['campaign']['visited'].append('CORRUPT')
        raise ValueError('entry fault')
    monkeypatch.setattr(campaign,'_enter',fail)
    with pytest.raises(ValueError):director.resolve(state,'p',selected)
    assert state==before


def test_cancel_during_combat_leaves_turn_and_resources_untouched():
    state = table(book_with_labels())
    selected = proposal(state)
    director.resolve(state,'p',selected)
    state['combat']=dict(active=True,turn_actor_id='ally')
    before = deepcopy(state['combat'])
    cancellation = proposal(state,action='story-cancel')
    director.resolve(state,'p',cancellation)
    assert state['combat']==before and not state['pending_transition']


def test_foreign_world_lock_does_not_block_cancel_or_authorize_other_actions():
    from backend import scene_storage, session_scope, world_combat, world_environment
    state = table(book_with_labels())
    session_scope.initialize(state)
    state = scene_storage.unpack(world_combat.migrate(world_environment.migrate(scene_storage.pack(state))))
    selected = proposal(state)
    director.resolve(state,'p',selected)
    sid = state.get('_scene_execution_view','scene-main')
    place = state['world_places'][state['scene_instances'][sid]['place_id']]
    place.update(active_encounter_id='foreign',encounter_owner_scene_id='other')
    before = deepcopy(state)
    assert 'story-cancel' in {row['id'] for row in routes.menu(state,'p')}
    with pytest.raises(ValueError):action_plans.prepare(state,'p','story-check:find-lens')
    cancellation = proposal(state,action='story-cancel')
    director.resolve(state,'p',cancellation)
    assert not state['pending_transition']
    assert state['world_places']==before['world_places']
    assert state['world_entities']==before['world_entities']
    assert state['members']==before['members']
