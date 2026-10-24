"""Author challenges declare mechanical intent without executing effects."""
from copy import deepcopy
import json

import pytest

from backend import story_graph as g
from backend.maintenance import backup_database, restore_backup
from backend.store import Store
from backend.studio import ContentService
from test_story_graph import sparse


def authored():
    book = sparse()
    book['fact_definitions'].append(dict(id='weather',kind='state',value_type='integer',initial=0,
        mutable=True,visibility='public',description='Relevant weather evidence'))
    book['nodes'][0]['place_id'] = 'harbor'
    book['nodes'][0]['challenges'] = [dict(id='find-lens', objective_key='lens-location',question_id='discover-route',
        label='辨认路线',skill_ids=['investigation','perception'],dc=12,evidence_fact_ids=['weather'],
        success_text='找到路线。',failure_text='目前无法辨认。',
        success_effects=[dict(op='set_fact',ref='lens',value=True),
                         dict(op='milestone_state',ref='recover',state='achieved'),
                         dict(op='event_occurred',ref='heard-courier')],failure_effects=[])]
    return book


def test_challenge_and_typed_effects_round_trip_without_execution():
    book = authored()
    before = deepcopy(book)
    parsed = g.parse_book(book)
    assert parsed['nodes'][0]['challenges'][0]['executor_ref'] == 'ability_check'
    assert parsed['nodes'][0]['challenges'][0]['repeat_policy'] == 'once_per_evidence'
    assert book == before


@pytest.mark.parametrize('change', ['dc_bool','dc_string','unknown_skill','duplicate_skill','unknown_evidence',
    'self_unlock','unknown_fact','wrong_type','immutable_fact','grant_item','damage','duplicate_effect','reset_milestone'])
def test_invalid_or_unregistered_effects_and_self_unlocking_evidence_are_rejected(change):
    book = authored()
    challenge = book['nodes'][0]['challenges'][0]
    if change == 'dc_bool':challenge['dc'] = True
    elif change == 'dc_string':challenge['dc'] = '12'
    elif change == 'unknown_skill':challenge['skill_ids'] = ['mind-reading']
    elif change == 'duplicate_skill':challenge['skill_ids'] = ['perception','perception']
    elif change == 'unknown_evidence':challenge['evidence_fact_ids'] = ['unregistered']
    elif change == 'self_unlock':challenge['evidence_fact_ids'] = ['lens']
    elif change == 'unknown_fact':challenge['success_effects'][0]['ref'] = 'unregistered'
    elif change == 'wrong_type':challenge['success_effects'][0]['value'] = 1
    elif change == 'immutable_fact':book['fact_definitions'][0].update(mutable=False,kind='premise')
    elif change == 'grant_item':challenge['success_effects'].append(dict(op='grant_item',ref='lens-item'))
    elif change == 'damage':challenge['success_effects'][0]['damage'] = 99
    elif change == 'duplicate_effect':challenge['success_effects'].append(deepcopy(challenge['success_effects'][0]))
    elif change == 'reset_milestone':challenge['success_effects'][1]['state'] = 'pending'
    before = deepcopy(book)
    with pytest.raises(ValueError):g.parse_book(book)
    assert book == before


def aliases():
    book = authored()
    second = deepcopy(book['nodes'][0]['challenges'][0])
    second.update(id='ask-about-lens',label='询问路线')
    book['nodes'].append(dict(id='overlook',kind='scene',place_id='harbor',title='Overlook',text='Another angle.',challenges=[second]))
    book['edges'][0]['to'] = 'overlook'
    book['edges'].append(dict(id='overlook-follow',**{'from':'overlook'},to='follow'))
    return book


def test_same_physical_goal_can_have_aliases_but_not_different_mechanics():
    book = aliases()
    assert g.parse_book(book)
    book['nodes'][2]['challenges'][0]['dc'] = 5
    with pytest.raises(ValueError,match='矛盾规则'):g.parse_book(book)


def test_challenge_ids_are_global_and_frontiers_cannot_carry_actions_or_place():
    book = aliases()
    book['nodes'][2]['challenges'][0]['id'] = 'find-lens'
    with pytest.raises(ValueError,match='挑战 ID 重复'):g.parse_book(book)
    book = authored()
    book['nodes'][1]['challenges'] = deepcopy(book['nodes'][0]['challenges'])
    with pytest.raises(ValueError):g.parse_book(book)
    book = authored()
    book['nodes'][1]['place_id'] = 'harbor'
    with pytest.raises(ValueError):g.parse_book(book)


def test_schema13_preserves_author_challenges_and_blocks_older_reader(tmp_path,monkeypatch):
    from backend import maintenance
    path = tmp_path / 'challenges.sqlite3'
    store = Store(str(path))
    service = ContentService(store)
    book = g.parse_book(authored())
    with store.connect() as db:
        db.execute('INSERT INTO content_items VALUES(?,?,?,?,1,NULL,NULL,0,?)',
                   (book['id'],'scenario',book['name'],json.dumps(book),'2026-10-24'))
        before = service.record(db,book['id'],'create')
        db.execute('PRAGMA user_version=12')
    upgraded = Store(str(path))
    with upgraded.connect() as db:
        assert ContentService(upgraded).get(db,book['id']) == before
    archive = tmp_path / 'challenges.zip'
    backup_database(path,archive)
    restore_backup(archive,tmp_path / 'restored')
    recovered = Store(str(tmp_path / 'restored/database.sqlite3'))
    with recovered.connect() as db:
        assert ContentService(recovered).get(db,book['id']) == before
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',12)
    with pytest.raises(ValueError,match='newer server'):Store(str(path))
