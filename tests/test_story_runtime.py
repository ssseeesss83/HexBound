"""Sparse effective reads are pure and never turn a frontier into a scene."""
from copy import deepcopy

import pytest

from backend import campaign, rules, story_runtime as runtime
from test_story_graph import sparse
from test_campaign import package


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Reading a graph cannot execute a game action')
    monkeypatch.setattr(rules, 'roll_dice', forbidden)
    monkeypatch.setattr(campaign, '_enter', forbidden)


def extension():
    book = sparse()
    saved = runtime.initialize(book)
    graph = saved['runtime_graph']
    graph.update(graph_revision=1, frontier_resolutions={'follow':'branch'}, commits=[dict(
        job_id='job1', revision=1, patch_digest='a'*64, frontier_id='follow', entry_node_id='branch')])
    graph['nodes'] = [dict(id='branch',kind='scene',title='Branch',text='A quiet lane.'),
        dict(id='next',kind='frontier',title='Next',continuation=deepcopy(book['nodes'][1]['continuation']))]
    graph['edges'] = [dict(id='branch-next', **{'from':'branch'}, to='next')]
    return book, saved


def test_sparse_initialization_is_pure_and_declarations_do_not_grant_items_or_events():
    book = sparse()
    before = deepcopy(book)
    saved = runtime.initialize(book)
    assert book == before
    assert not saved['runtime_graph']['nodes'] and saved['runtime_graph']['graph_revision'] == 0
    assert saved['story_state']['items']['lens-item'] == dict(value=False, revision=0)
    assert saved['story_state']['events']['heard-courier'] == dict(value=False, revision=0)
    view = runtime.effective_book(book, saved['runtime_graph'])
    assert runtime.destination(view, 'follow') == dict(status='pending', frontier_id='follow', node_id=None)
    assert runtime.destination(view, 'dock')['node_id'] == 'dock'


def test_resolved_view_preserves_frozen_frontier_and_reaches_next_sparse_exit():
    book, saved = extension()
    before = deepcopy((book, saved))
    view = runtime.effective_book(book, saved['runtime_graph'])
    assert next(row for row in view['book']['nodes'] if row['id']=='follow')['kind'] == 'frontier'
    assert runtime.destination(view,'follow') == dict(status='ready', frontier_id='follow', node_id='branch')
    assert runtime.destination(view,'next')['status'] == 'pending'
    assert (book,saved) == before


@pytest.mark.parametrize('damage', ['author','duplicate_node','unknown_target','frontier_edge','unreachable','missing_commit','bad_revision','no_exit'])
def test_corrupt_or_unbounded_extension_fails_closed(damage):
    book, saved = extension()
    graph = saved['runtime_graph']
    if damage == 'author':
        graph['author_digest'] = '0'*64
    elif damage == 'duplicate_node':
        graph['nodes'][0]['id'] = 'dock'
    elif damage == 'unknown_target':
        graph['frontier_resolutions']['follow'] = 'missing'
    elif damage == 'frontier_edge':
        graph['edges'].append(dict(id='illegal', **{'from':'follow'}, to='branch'))
    elif damage == 'unreachable':
        graph['nodes'].append(dict(id='orphan',kind='scene',title='Orphan',text='Unreachable.'))
    elif damage == 'missing_commit':
        graph['commits'] = []
    elif damage == 'bad_revision':
        graph['commits'][0]['revision'] = 2
    elif damage == 'no_exit':
        graph['edges'][0]['to'] = 'dock'
        graph['nodes'].pop()
    before = deepcopy((book,graph))
    with pytest.raises(ValueError):
        runtime.effective_book(book, graph)
    assert (book,graph) == before


def test_boolean_operators_record_all_dependencies_and_never_execute_text():
    book = sparse()
    saved = runtime.initialize(book)
    view = runtime.effective_book(book,saved['runtime_graph'])
    expression = dict(op='all', children=[dict(op='not',children=[dict(op='fact_equals',ref='lens',value=True)]),
        dict(op='any',children=[dict(op='milestone_state',ref='recover',state='pending'),
                               dict(op='event_occurred',ref='heard-courier')])])
    before = deepcopy(saved)
    evaluated = runtime.evaluate(expression,view,saved['story_state'])
    assert evaluated['value'] is True
    assert set(evaluated['read_set']) == {'facts:lens','milestones:recover','events:heard-courier'}
    assert saved == before
    assert runtime.evaluate(dict(op='has_item',ref='lens-item'),view,saved['story_state'])['value'] is False
    assert runtime.evaluate(None,view,saved['story_state']) == dict(value=True,read_set={})


@pytest.mark.parametrize('expression', [dict(op='eval',ref='__import__'),dict(op='fact_equals',ref='lens',value=0),
    dict(op='fact_equals',ref='missing',value=True),dict(op='not',children=[]),dict(op='has_item',ref='made-up')])
def test_unregistered_or_mistyped_conditions_are_rejected(expression):
    book = sparse()
    saved = runtime.initialize(book)
    with pytest.raises(ValueError):
        runtime.evaluate(expression,runtime.effective_book(book),saved['story_state'])


def test_corrupt_authoritative_values_and_changed_immutable_premise_are_rejected():
    book = sparse()
    book['fact_definitions'][0].update(kind='premise', mutable=False)
    saved = runtime.initialize(book)
    view = runtime.effective_book(book)
    for value in [True, 0]:
        saved['story_state']['facts']['lens']['value'] = value
        with pytest.raises(ValueError):
            runtime.evaluate(None,view,saved['story_state'])


def test_v1_node_gateway_never_enters_or_rewrites_an_old_room():
    state = dict(campaign=dict(package=package(),node_id='gate'))
    before = deepcopy(state)
    found = campaign._node(state)
    assert found == before['campaign']['package']['scenario']['nodes'][0]
    found['text'] = 'Local mutation'
    assert state == before


@pytest.mark.parametrize('version', [True, 1.0, '1', 2])
def test_runtime_schema_is_a_strict_supported_integer(version):
    saved = runtime.initialize(sparse())
    saved['runtime_graph']['schema_version'] = version
    with pytest.raises(ValueError):
        runtime.effective_book(sparse(),saved['runtime_graph'])
    saved['story_state']['schema_version'] = version
    with pytest.raises(ValueError):
        runtime.evaluate(None,runtime.effective_book(sparse()),saved['story_state'])
