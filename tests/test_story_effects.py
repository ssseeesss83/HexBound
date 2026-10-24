"""Fact changes are atomic, typed, relevant-read checked and replayable."""
from copy import deepcopy

import pytest

from backend import story_effects as effects, story_runtime as runtime
from test_story_challenges import authored


def setup():
    book = authored()
    saved = runtime.initialize(book)
    view = runtime.effective_book(book)
    outcome = view['book']['nodes'][0]['challenges'][0]['success_effects']
    return view,saved['story_state'],outcome


def apply(view,state,outcome,**options):
    params=dict(receipt_id='effect1',source_ref='find-lens',success=True,expected_reads=effects.snapshot(view,state,outcome))
    params.update(options)
    return effects.apply(view,state,outcome,**params)


def test_registered_effects_commit_once_and_replay_without_advancing_revisions():
    view,state,outcome = setup()
    before = deepcopy(state)
    planned = effects.snapshot(view,state,outcome)
    result = apply(view,state,outcome)
    assert state == before and result['replayed'] is False
    settled = result['state']
    assert settled['facts']['lens'] == dict(value=True,revision=1)
    assert settled['milestones']['recover'] == dict(value='achieved',revision=1)
    assert settled['events']['heard-courier'] == dict(value=True,revision=1)
    assert settled['items']['lens-item'] == dict(value=False,revision=0)
    assert len(result['changes']) == 3 and settled['revision'] == 1
    replay = apply(view,settled,outcome,expected_reads=planned)
    assert replay == dict(state=settled,replayed=True,changes=[])
    with pytest.raises(ValueError):
        apply(view,settled,[],expected_reads={})
    with pytest.raises(ValueError,match='不同结果'):
        apply(view,settled,[],success=False,expected_reads={})


def test_stale_dependency_or_missing_written_target_rejects_atomically():
    view,state,outcome = setup()
    reads = effects.snapshot(view,state,outcome)
    for damage in ['missing','stale','bool_revision','wrong_type','extra_shape']:
        bad = deepcopy(reads)
        if damage=='missing':bad.pop('facts:lens')
        elif damage=='stale':bad['facts:lens']['revision']=99
        elif damage=='bool_revision':bad['facts:lens']['revision']=False
        elif damage=='wrong_type':bad['facts:lens']['value']=0
        elif damage=='extra_shape':bad['facts:lens']['extra']='ignored?'
        before = deepcopy(state)
        with pytest.raises(ValueError):apply(view,state,outcome,expected_reads=bad)
        assert state == before


def test_all_effects_abort_when_last_milestone_cannot_be_rewritten():
    view,state,outcome = setup()
    state['milestones']['recover'] = dict(value='failed',revision=1)
    before = deepcopy(state)
    with pytest.raises(ValueError,match='里程碑'):
        apply(view,state,outcome)
    assert state == before and not state['facts']['lens']['value'] and not state['effect_receipts']


@pytest.mark.parametrize('options', [{'source_ref':'unregistered'}, {'success':1}, {'success':False}])
def test_frozen_effects_must_match_the_registered_source_and_settled_branch(options):
    view,state,outcome = setup()
    before = deepcopy(state)
    with pytest.raises(ValueError):apply(view,state,outcome,**options)
    assert state == before


def test_noop_assignments_do_not_fabricate_new_evidence_revisions():
    outcome = [dict(op='set_fact',ref='lens',value=False)]
    book = authored()
    book['nodes'][0]['challenges'][0]['failure_effects'] = outcome
    state = runtime.initialize(book)['story_state']
    view = runtime.effective_book(book)
    result = apply(view,state,outcome,success=False)
    assert result['changes'] == []
    assert result['state']['facts']['lens'] == dict(value=False,revision=0)
    assert result['state']['revision'] == 1 and result['state']['effect_receipts']


@pytest.mark.parametrize('outcome', [
    [dict(op='set_fact',ref='lens',value=1)], [dict(op='set_fact',ref='missing',value=True)],
    [dict(op='grant_item',ref='lens-item')], [dict(op='milestone_state',ref='recover',state='pending')],
    [dict(op='event_occurred',ref='unknown')], [dict(op='set_fact',ref='lens',value=True,damage=9)],
])
def test_unknown_and_mistyped_operations_never_produce_partial_state(outcome):
    view,state,_ = setup()
    before = deepcopy(state)
    with pytest.raises(ValueError):apply(view,state,outcome)
    assert state == before
