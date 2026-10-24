"""Native checks share menu, intent, immutable plans and confirmation."""
import asyncio
from copy import deepcopy

import pytest

from backend import action_menu, action_plans, director, rules
from test_native_story_checks import table, extend_graph


class LocalDM:
    configured = False


def test_menu_and_two_entries_share_native_plan_without_exposing_internal_facts(monkeypatch):
    state = table()
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Preview rolled'))
    menu = action_menu.available(state,'p')
    assert next(row for row in menu if row['id']=='story-check:find-lens')['skill_ids']==['investigation','perception']
    selected = director.propose_selected(state,'p','story-check:find-lens',options={'skill_id':'perception'})['proposal']
    described = asyncio.run(director.propose(LocalDM(),state,'p','我尝试辨认路线',skill_id='perception'))['proposal']
    for key in ['executor','action_id','options','resources','story_plan']:
        assert selected['plan'][key]==described['plan'][key]
    public = director.public_proposal(selected,state)
    assert public['plan']['options']=={'skill_id':'perception'} and not public['stale']
    assert not {'story_plan','read_set','actor_digest','author_digest','fingerprint'} & public['plan'].keys()
    assert 'success_effects' not in str(public) and 'facts:weather' not in str(director.build_context(state,'p','辨认路线'))
    assert state == before


def test_confirm_records_effect_and_attempt_once_and_removes_menu_entry(monkeypatch):
    state = table()
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    proposal = director.propose_selected(state,'p','story-check:find-lens')['proposal']
    events = director.resolve(state,'p',proposal)
    assert events[0]['roll']['success']
    assert proposal['id'] in state['campaign']['story_state']['effect_receipts']
    assert len(state['attempt_ledger'])==1
    assert all(row['id']!='story-check:find-lens' for row in action_menu.available(state,'p'))
    with pytest.raises(ValueError):director.resolve(state,'p',proposal)


def test_related_fact_change_marks_public_stale_and_rejects_before_rng(monkeypatch):
    state = table()
    proposal = director.propose_selected(state,'p','story-check:find-lens')['proposal']
    state['campaign']['story_state']['facts']['weather'].update(value=1,revision=1)
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Stale plan rolled'))
    assert director.public_proposal(proposal,state)['stale']
    with pytest.raises(ValueError):director.resolve(state,'p',proposal)
    assert state == before


def test_unrelated_extension_keeps_outer_confirmation_plan_valid():
    state = table()
    proposal = director.propose_selected(state,'p','story-check:find-lens')['proposal']
    extend_graph(state)
    assert not director.public_proposal(proposal,state)['stale']
    assert action_plans.revalidate(state,'p',proposal['plan'])==proposal['plan']


@pytest.mark.parametrize('options,target',[
    ({'slot_level':1},None),({'resource_amount':1},None),({'target_ids':['p']},None),
    ({},'p'),({'skill_id':'deception'},None),
])
def test_invalid_targets_or_options_never_create_native_plan(options,target):
    state = table()
    before = deepcopy(state)
    with pytest.raises(ValueError):
        director.propose_selected(state,'p','story-check:find-lens',target,options)
    assert state == before


def test_skill_option_cannot_be_smuggled_into_non_native_actions():
    with pytest.raises(ValueError):action_plans.prepare(table(),'p','attack',options={'skill_id':'perception'})


def test_unregistered_method_declares_dialogue_without_execution():
    state = table()
    proposal = asyncio.run(director.propose(LocalDM(),state,'p','我尝试辨认路线',skill_id='deception'))['proposal']
    assert proposal['decision']['kind']=='dialogue'


def test_inspiration_cost_uses_public_resource_description():
    state = table()
    state['members'][0]['character']['inspiration_die']='1d6'
    proposal = director.propose_selected(state,'p','story-check:find-lens')['proposal']
    assert '1d6' in director.public_proposal(proposal,state)['plan']['cost_label']
