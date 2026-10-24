from itertools import product

from backend.homeward import book
from backend.story_graph import graph_issues
from backend import story_runtime


def test_book_has_complete_offline_routes_for_every_check_outcome():
    author = book()
    assert graph_issues(author) == []
    checks = [n['id'] for n in author['nodes'] if n['challenges']]
    assert len(checks) == 10
    endings = {n['id'] for n in author['nodes'] if n['kind']=='ending'}
    # Every combination, including all failures: the author path terminates.
    for values in product([1,2], repeat=len(checks)):
        current = story_runtime.initialize(author)
        for id, value in zip(checks, values):
            current['story_state']['facts'][id]['value'] = value
        view = story_runtime.effective_book(author, current['runtime_graph'])
        reachable, pending = set(), ['dock']
        while pending:
            id = pending.pop()
            if id in reachable: continue
            reachable.add(id)
            pending.extend(e['to'] for e in author['edges'] if e['from']==id
                           and e['to']!='courier-frontier'
                           and story_runtime.evaluate(e['condition'], view, current['story_state'])['value'])
        assert 'evacuation' in reachable
        assert {'dawn','vigil'} & reachable
        for node in author['nodes']:
            if node['challenges']:
                assert any(e['from']==node['id'] and story_runtime.evaluate(e['condition'],view,current['story_state'])['value']
                           for e in author['edges'])


def test_no_required_generated_branch_or_unimplemented_item_grant():
    author = book()
    assert not author['item_ids']
    assert len([n for n in author['nodes'] if n['kind']=='frontier']) == 1
    assert next(n for n in author['nodes'] if n['kind']=='frontier')['continuation']['fallback_scene_id']=='customs'
    assert all(len(n['text']) >= 100 for n in author['nodes'] if n['kind']!='frontier')
