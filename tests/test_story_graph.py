"""Sparse graph authoring, malicious conditions and lossless v1 draft migration."""
from copy import deepcopy
import pytest

from backend import story_graph as g
from backend.schemas import parse_card, ScenarioBook
from backend.studio import seed_items
from backend.rules_identity import RULESET_ID, LEGACY_PACKAGE


def sparse():
    return {'id': 'sparse', 'name': 'Sparse', 'schema_version': 2, 'ruleset_id': RULESET_ID,
            'rules_package_version': LEGACY_PACKAGE, 'outline': 'Recover the lens; follow player choices.',
            'entry_node_id': 'dock', 'fact_definitions': [
                {'id': 'lens', 'kind': 'secret', 'value_type': 'boolean', 'initial': False,
                 'mutable': True, 'visibility': 'dm_secret', 'description': 'Lens recovered'}],
            'milestones': [{'id': 'recover', 'description': 'Recover the lens'}],
            'npc_goals': [{'id': 'courier', 'description': 'Avoid arrest'}], 'monster_ids': ['guard'],
            'item_ids': ['lens-item'], 'event_ids': ['heard-courier'],
            'nodes': [
                {'id': 'dock', 'kind': 'key', 'title': 'Dock', 'text': 'A courier departs.',
                 'objective': 'Discover the courier route', 'failure_consequences': 'Courier gains time',
                 'advancement_condition': {'op': 'any', 'children': [
                     {'op': 'fact_equals', 'ref': 'lens', 'value': True},
                     {'op': 'milestone_state', 'ref': 'recover', 'state': 'bypassed'}]}},
                {'id': 'follow', 'kind': 'frontier', 'title': 'Side street', 'continuation': {
                    'summary': 'Players follow the courier', 'confirmed_fact_ids': ['lens'],
                    'unresolved_threads': ['Who hired the courier?'], 'npc_goal_ids': ['courier'],
                    'allowed_monster_ids': ['guard'], 'candidate_milestone_ids': ['recover'],
                    'constraints': ['Preserve confirmed events'], 'fallback_scene_id': 'dock'}}],
            'edges': [{'id': 'follow-courier', 'from': 'dock', 'to': 'follow', 'main_path': True}]}


def test_sparse_outline_can_end_in_continuation_without_prebuilding_branches():
    book = g.parse_book(sparse())
    assert len(book['nodes']) == 2 and book['nodes'][1]['kind'] == 'frontier'
    assert g.graph_issues(book) == []
    assert book['fact_definitions'][0]['mutable'] and book['fact_definitions'][0]['visibility'] == 'dm_secret'
    assert book['nodes'][0]['advancement_condition']['children'][1]['state'] == 'bypassed'
    # This author contract is not silently admitted to the old room compiler.
    with pytest.raises(ValueError):
        ScenarioBook.model_validate(book)


def test_native_author_template_is_valid_sparse_and_defaults_to_frozen_history():
    template = g.sparse_template()
    assert len(template['nodes']) == 2 and len(template['edges']) == 1
    assert template['rules_package_version'] == LEGACY_PACKAGE
    assert template['nodes'][1]['kind'] == 'frontier'
    assert template['nodes'][1]['continuation']['fallback_scene_id'] == 'opening'
    assert g.parse_book(template) == template


@pytest.mark.parametrize('bad', [
    {'op': 'eval', 'code': '__import__("os")'}, {'op': 'all', 'children': []},
    {'op': 'not', 'children': [{'op': 'has_item', 'ref': 'lens-item'}]*2},
    {'op': 'has_item', 'ref': 'lens-item', 'value': True},
    {'op': 'fact_equals', 'ref': 'lens', 'value': 1},
    {'op': 'fact_equals', 'ref': 'lens', 'value': float('nan')},
    {'op': 'fact_equals', 'ref': 'missing', 'value': False},
    {'op': 'event_occurred', 'ref': 'runtime-log-123'},
    {'op': 'milestone_state', 'ref': 'recover', 'state': 'won'},
    {'op': 'has_item', 'ref': 'missing'},
])
def test_untrusted_condition_shapes_types_and_namespaces_reject(bad):
    book = sparse()
    book['edges'][0]['condition'] = bad
    with pytest.raises(ValueError):
        g.parse_book(book)


def test_condition_depth_width_and_total_nodes_are_bounded_before_models():
    leaf = {'op': 'has_item', 'ref': 'lens-item'}
    deep = leaf
    for _ in range(g.MAX_CONDITION_DEPTH):
        deep = {'op': 'not', 'children': [deep]}
    for condition in [deep, {'op': 'all', 'children': [leaf]*33},
                      {'op': 'all', 'children': [{'op': 'all', 'children': [leaf]*32}]*4}]:
        book = sparse()
        book['edges'][0]['condition'] = condition
        with pytest.raises(ValueError):
            g.parse_book(book)


@pytest.mark.parametrize('field,bad', [
    ('confirmed_fact_ids', ['courier']), ('npc_goal_ids', ['lens']),
    ('allowed_monster_ids', ['unfrozen-dragon']), ('candidate_milestone_ids', ['lens']),
    ('fallback_scene_id', 'follow'), ('fallback_scene_id', 'missing'),
    ('summary', ''), ('constraints', []), ('unresolved_threads', [' ']),
])
def test_frontier_requires_complete_typed_references_and_playable_fallback(field, bad):
    book = sparse()
    book['nodes'][1]['continuation'][field] = bad
    with pytest.raises(ValueError):
        g.parse_book(book)


def test_cycles_with_an_exit_are_finite_references_but_closed_cycles_reject():
    book = sparse()
    book['edges'].insert(0, {'id': 'return', 'from': 'dock', 'to': 'dock'})
    parsed = g.parse_book(book)
    rows = g.navigation_rows(parsed)
    assert len(rows) == 3 and any(r['reference'] == 'cycle' for r in rows)
    assert rows[1]['node_id'] == 'follow'  # Primary path is navigation priority only.
    book['edges'] = [book['edges'][0]]
    with pytest.raises(ValueError, match='无法'):
        g.parse_book(book)


def test_shared_ending_is_a_reference_and_terminal_outgoing_edges_are_rejected():
    book = sparse()
    book['nodes'][1] = {'id': 'follow', 'kind': 'ending', 'title': 'End', 'text': 'Dawn.'}
    book['edges'].append({'id': 'another-route', 'from': 'dock', 'to': 'follow'})
    parsed = g.parse_book(book)
    assert [r['reference'] for r in g.navigation_rows(parsed)].count('merge') == 1
    book['edges'].append({'id': 'bad-exit', 'from': 'follow', 'to': 'dock'})
    with pytest.raises(ValueError, match='末端'):
        g.parse_book(book)


def test_duplicate_ids_mutable_premises_and_wrong_initial_types_reject():
    for field, value in [('mutable', True), ('initial', 1)]:
        book = sparse()
        fact = book['fact_definitions'][0]
        fact.update(kind='premise', mutable=False)
        fact[field] = value
        with pytest.raises(ValueError):
            g.parse_book(book)
    for collection in ['nodes', 'edges', 'fact_definitions', 'milestones', 'npc_goals']:
        book = sparse()
        book[collection].append(deepcopy(book[collection][0]))
        with pytest.raises(ValueError, match='重复'):
            g.parse_book(book)


def test_migration_is_deterministic_idempotent_and_does_not_touch_source_or_runtime(monkeypatch):
    from backend import rules, campaign
    def forbidden(*args, **kwargs):
        pytest.fail('Author migration must not execute game rules')
    monkeypatch.setattr(rules, 'roll_dice', forbidden)
    monkeypatch.setattr(campaign, 'start_campaign', forbidden)
    old = next(card for kind, card in seed_items() if kind == 'scenario')
    original = deepcopy(old)
    migrated = g.migrate_legacy(old)
    assert old == original
    assert g.migrate_legacy(old) == migrated == g.migrate_legacy(migrated)
    assert migrated['rules_package_version'] == LEGACY_PACKAGE
    normalized = parse_card('scenario', old)
    assert len(migrated['nodes']) == len(normalized['nodes'])
    for before, after in zip(normalized['nodes'], migrated['nodes']):
        for field in ['id', 'title', 'text', 'objective', 'objects', 'monster_ids']:
            assert before[field] == after[field]
        assert before['actions'] == after['legacy_actions']
        assert before['ending'] == (after['kind'] == 'ending')


def test_local_action_ids_long_ids_and_equal_check_targets_keep_all_routes():
    old = next(card for kind, card in seed_items() if kind == 'scenario')
    for node in old['nodes']:
        for i, action in enumerate(node.get('actions', [])):
            action['id'] = ('a'*63 + str(i))
            if action.get('skill_id'):
                action['failure_node_id'] = action['success_node_id']
    # Ensure formerly failure-only nodes remain structurally reachable.
    old['nodes'][0]['actions'].append({'id': 'detour', 'label': 'Detour', 'next_node_id': 'stairs'})
    old['nodes'][0]['actions'].append({'id': 'alley-detour', 'label': 'Alley', 'next_node_id': 'alley'})
    migrated = g.migrate_legacy(old)
    assert len({e['id'] for e in migrated['edges']}) == len(migrated['edges'])
    for node in migrated['nodes']:
        for action in node['legacy_actions']:
            edges = [e for e in migrated['edges'] if e['from'] == node['id'] and e['legacy_action_id'] == action['id']]
            assert len(edges) == (2 if action['skill_id'] else 1)
    broken = deepcopy(migrated)
    broken['edges'][0]['to'] = 'quiet-dawn'
    with pytest.raises(ValueError, match='旧行动'):
        g.parse_book(broken)


def test_unknown_schema_huge_document_and_recursive_input_are_rejected():
    book = sparse()
    book['schema_version'] = 99
    with pytest.raises(ValueError):
        g.migrate_legacy(book)
    book = sparse()
    book['outline'] = 'x' * g.MAX_BYTES
    with pytest.raises(ValueError, match='大小'):
        g.parse_book(book)
    recursive = {}
    recursive['self'] = recursive
    with pytest.raises(ValueError, match='嵌套'):
        g.parse_book(recursive)


def test_legacy_ending_objects_are_preserved_and_duplicate_local_actions_reject():
    old = next(card for kind, card in seed_items() if kind == 'scenario')
    end = next(n for n in old['nodes'] if n.get('ending'))
    end['objects'] = [{'id': 'lantern', 'name': 'Lantern'}]
    normalized = parse_card('scenario', old)
    migrated = g.migrate_legacy(old)
    assert next(n for n in migrated['nodes'] if n['id'] == end['id'])['objects'] == next(
        n for n in normalized['nodes'] if n['id'] == end['id'])['objects']
    node = migrated['nodes'][0]
    direct = {'id': 'same', 'label': 'Go', 'next_node_id': 'dawn'}
    check = {'id': 'same', 'label': 'Try', 'skill_id': migrated['skill_ids'][0],
             'success_node_id': 'dawn', 'failure_node_id': 'dawn'}
    node['legacy_actions'] = [direct, check]
    with pytest.raises(ValueError, match='旧行动 ID'):
        g.parse_book(migrated)


def test_migration_bounds_raw_input_before_copying_or_recursive_validation():
    expr = {'op': 'has_item', 'ref': 'lens-item'}
    for _ in range(1500):
        expr = {'op': 'not', 'children': [expr]}
    for version in [1, 2]:
        book = sparse()
        book['schema_version'] = version
        book['edges'][0]['condition'] = expr
        with pytest.raises(ValueError, match='嵌套'):
            g.migrate_legacy(book)


def test_valid_v1_maximum_route_count_is_not_rejected_by_v2_budget():
    nodes = []
    for index in range(49):
        nodes.append({'id': f'n{index}', 'title': 'Scene', 'text': 'Room', 'actions': [
            {'id': f'try-{action}', 'label': 'Try', 'skill_id': 'check',
             'success_node_id': f'n{index+1}', 'failure_node_id': 'n49'} for action in range(12)]})
    nodes.append({'id': 'n49', 'title': 'End', 'text': 'Dawn', 'ending': True})
    old = {'id': 'max-book', 'name': 'Maximum valid v1', 'entry_node_id': 'n0', 'nodes': nodes,
           'skill_ids': ['check'], 'monster_ids': []}
    migrated = g.migrate_legacy(old)
    assert len(migrated['edges']) == 49*12*2
    assert g.migrate_legacy(migrated) == migrated
