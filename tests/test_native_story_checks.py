"""Native checks freeze server facts and settle effects plus global attempts once."""
from copy import deepcopy

import pytest

from backend import attempts, rules, story_challenges as checks, story_effects, story_runtime
from test_scenario_plans import room
from test_story_challenges import authored, aliases


def table(book=None):
    state = room()
    book = authored() if book is None else book
    initial = story_runtime.initialize(book)
    state['campaign'] = dict(package=dict(scenario=book,skills={},monsters={}),node_id='dock',
        visited=['dock'],spent={},cleared=[],**initial)
    state['scene_id'] = 'dock'
    state['scene'] = deepcopy(book['nodes'][0])
    return state


def test_preview_is_pure_and_collects_condition_evidence_and_both_outcome_dependencies(monkeypatch):
    state = table()
    before = deepcopy(state)
    def forbidden(*args,**kwargs):pytest.fail('Preview cannot execute')
    monkeypatch.setattr(rules,'roll_dice',forbidden)
    monkeypatch.setattr(story_effects,'apply',forbidden)
    plan = checks.prepare(state,'p','find-lens','perception')
    assert set(plan['read_set']) == {'facts:weather','facts:lens','milestones:recover','events:heard-courier'}
    assert plan['skill_id']=='perception' and plan['dc']==12
    assert 'success_effects' not in plan and 'failure_effects' not in plan
    assert state == before


def test_success_updates_facts_and_ledger_without_movement_rewards_or_source_mutation(monkeypatch):
    state = table()
    original = deepcopy(state['campaign']['package'])
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    plan = checks.prepare(state,'p','find-lens')
    events = checks.resolve(state,'p',plan,receipt_id='native-result')
    assert events[0]['roll']['success'] and events[0]['text']=='找到路线。'
    assert state['campaign']['story_state']['facts']['lens']['value'] is True
    assert state['campaign']['story_state']['milestones']['recover']['value']=='achieved'
    assert state['campaign']['node_id']=='dock' and not state.get('reward_ledger')
    assert state['campaign']['package'] == original
    assert state['campaign']['story_state']['items']['lens-item']['value'] is False
    spec = attempts.lookup(state,'story-check:find-lens')
    result = attempts.inspect(state,spec,'ally')
    assert result['status']=='resolved' and result['previous']['effect_receipt']==events[0]['attempt_receipt']
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Replay rolled'))
    with pytest.raises(ValueError):checks.resolve(state,'p',plan,receipt_id='native-result')
    assert state == before


def test_failure_cannot_retry_with_new_method_member_alias_or_unrelated_state(monkeypatch):
    state = table(aliases())
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='failed1')
    state.update(rest_used=True,version=99)
    state['members'][0]['character']['hp'] -= 1
    for actor,skill in [('p','perception'),('ally','investigation')]:
        with pytest.raises(ValueError):checks.prepare(state,actor,'find-lens',skill)
    state['campaign']['node_id']='overlook'
    state['scene_id']='overlook'
    state['scene']=deepcopy(state['campaign']['package']['scenario']['nodes'][2])
    assert not attempts.available(state,'ally','story-check:ask-about-lens')
    with pytest.raises(ValueError):checks.prepare(state,'ally','ask-about-lens')


def test_only_changed_registered_evidence_grants_new_attempt_and_returning_value_stays_consumed(monkeypatch):
    state = table()
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='failed1')
    fact = state['campaign']['story_state']['facts']['weather']
    fact.update(value=1,revision=1)  # Trusted fixture: another registered action changes this fact.
    assert checks.prepare(state,'p','find-lens')
    fact.update(value=0,revision=2)
    with pytest.raises(ValueError):checks.prepare(state,'p','find-lens')
    fact.update(value=1,revision=3)
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='succeeded2')
    fact = state['campaign']['story_state']['facts']['weather']
    fact.update(value=2,revision=4)
    with pytest.raises(ValueError):checks.prepare(state,'p','find-lens')


def test_individual_attempt_owner_is_persistent_hero_not_recreated_seat(monkeypatch):
    book = authored()
    book['nodes'][0]['challenges'][0]['attempt_scope']='individual'
    state = table(book)
    state['members'][0]['hero_id']='persistent-hero'
    state['members'][1]['hero_id']='other-hero'
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='failed1')
    assert checks.prepare(state,'ally','find-lens')
    state['members'].append(dict(id='new-seat',name='Rejoin',hero_id='persistent-hero',
                                character=deepcopy(state['members'][0]['character'])))
    with pytest.raises(ValueError):checks.prepare(state,'new-seat','find-lens')


def test_both_outcomes_are_preflighted_before_any_roll(monkeypatch):
    state = table()
    state['campaign']['story_state']['milestones']['recover'].update(value='failed',revision=1)
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Invalid outcome rolled'))
    with pytest.raises(ValueError,match='里程碑'):checks.prepare(state,'p','find-lens')
    assert state == before


def extend_graph(state, alias=False):
    book = state['campaign']['package']['scenario']
    branch = dict(id='runtime-branch',kind='scene',place_id='harbor',title='Branch',text='Another angle.')
    if alias:
        challenge = deepcopy(book['nodes'][0]['challenges'][0])
        challenge.update(id='runtime-alias',label='Another method')
        branch['challenges'] = [challenge]
    graph = state['campaign']['runtime_graph']
    graph.update(graph_revision=1,frontier_resolutions={'follow':'runtime-branch'},
        commits=[dict(job_id='job1',revision=1,patch_digest='a'*64,
                      frontier_id='follow',entry_node_id='runtime-branch')],
        nodes=[branch,dict(id='runtime-next',kind='frontier',title='Continue',
                          continuation=deepcopy(book['nodes'][1]['continuation']))],
        edges=[dict(id='branch-next',**{'from':'runtime-branch'},to='runtime-next')])
    story_runtime.effective_book(book,graph)
    return branch


def test_generated_alias_cannot_reset_failed_attempt_at_same_place(monkeypatch):
    state = table()
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='failed')
    branch = extend_graph(state,alias=True)
    state['campaign']['node_id'] = state['scene_id'] = branch['id']
    state['scene'] = deepcopy(branch)
    assert checks.definition(state,'runtime-alias').place_id == 'harbor'
    with pytest.raises(ValueError,match='已经结算'):
        checks.prepare(state,'ally','runtime-alias','perception')


def test_unrelated_background_extension_does_not_invalidate_plan():
    state = table()
    plan = checks.prepare(state,'p','find-lens')
    extend_graph(state)
    assert checks.prepare(state,'p','find-lens') == plan


@pytest.mark.parametrize('condition,skill,values,success',[
    ('poisoned','perception',[19,0],False),
    ('rage','athletics',[0,19],True),
])
def test_native_checks_apply_state_advantage_rules(monkeypatch,condition,skill,values,success):
    book = authored()
    book['nodes'][0]['challenges'][0]['skill_ids'] = [skill]
    state = table(book)
    character = state['members'][0]['character']
    if condition=='rage':character['rage']=True
    else:character['conditions']=[dict(id=condition)]
    rolls = iter(values)
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:next(rolls))
    event = checks.resolve(state,'p',checks.prepare(state,'p','find-lens'),receipt_id='state-roll')[0]
    assert event['roll']['success'] is success
    assert event['roll']['selected'] == (1 if condition=='poisoned' else 20)


def test_inspiration_is_previewed_and_only_consumed_on_confirmation(monkeypatch):
    state = table()
    state['members'][0]['character']['inspiration_die'] = '1d6'
    plan = checks.prepare(state,'p','find-lens')
    assert plan['resources']==[dict(type='inspiration_die',dice='1d6',amount=1)]
    assert state['members'][0]['character']['inspiration_die']=='1d6'
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    event = checks.resolve(state,'p',plan,receipt_id='inspired')[0]
    assert event['roll']['inspiration_bonus']==6
    assert not state['members'][0]['character'].get('inspiration_die')
    with pytest.raises(ValueError):checks.resolve(state,'p',plan,receipt_id='inspired-again')


def test_reliable_talent_applies_after_poisoned_dice_selection(monkeypatch):
    from backend.characters import create_character
    state = table()
    character = create_character('rogue')
    character.update(level=11,skills=['perception'],conditions=[dict(id='poisoned')])
    state['members'][0]['character'] = character
    rolls = iter([19,0])
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:next(rolls))
    event = checks.resolve(state,'p',checks.prepare(state,'p','find-lens','perception'),receipt_id='talent')[0]
    assert event['roll']['reliable_talent'] and event['roll']['selected']==10


@pytest.mark.parametrize('change',['paused','dead','combat','condition','skill','scope','bool_read','used_receipt'])
def test_changed_legality_or_plan_tampering_rejects_without_rng_or_writes(monkeypatch,change):
    state = table()
    plan = checks.prepare(state,'p','find-lens')
    if change=='paused':state['status']='paused'
    elif change=='dead':state['members'][0]['character']['hp']=0
    elif change=='combat':state['combat']=dict(active=True)
    elif change=='condition':state['members'][0]['character']['conditions']=[dict(id='incapacitated')]
    elif change=='skill':plan['skill_id']='deception'
    elif change=='scope':plan['scope']['membership_epoch']=9
    elif change=='bool_read':plan['read_set']['facts:lens']['value']=0
    elif change=='used_receipt':state['campaign']['story_state']['effect_receipts']['planned']='0'*64
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Invalid plan rolled'))
    with pytest.raises(ValueError):checks.resolve(state,'p',plan,receipt_id='planned')
    assert state == before
