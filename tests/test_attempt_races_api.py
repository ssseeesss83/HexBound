"""Shared exploration qualification across independently playing real scenes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import uuid

import pytest

from backend import director, rules, scene_storage
from backend.maintenance import backup_database, restore_backup
from backend.store import Store
from test_core_integration import env
from test_scene_groups import setup, split, send


def select(client, rid):
    response = send(client, rid, 'capability_propose', {'action_id':'investigate'})
    assert response.status_code == 200, response.text
    return response.json()['room']['director_proposals'][0]


def test_two_scenes_share_one_roll_and_private_results_never_enter_foreign_projection(env, monkeypatch, tmp_path):
    a, b, store, rid, host, guest = setup(env)
    split(a, rid, guest)
    first, second = select(a, rid), select(b, rid)
    original = rules.roll_dice
    rolls = []
    def counted(*args, **kwargs):
        rolls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(rules, 'roll_dice', counted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda item: send(item[0], rid, 'director_resolve', {'proposal_id':item[1]['id']}), [(a,first),(b,second)]))
    assert sorted(response.status_code for response in responses) == [200, 422]
    assert rolls == ['1d20']
    saved = store.get(rid)
    assert len(saved['attempt_ledger']) == 1
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    loser = (a,b)[1-winner]
    loser_frame = loser.get(f'/api/rooms/{rid}').json()
    assert loser_frame['director_proposals'][0]['stale']
    assert loser_frame['director_proposals'][0]['stale_reason'] == 'challenge_unavailable'
    assert 'attempt_ledger' not in loser_frame
    # Poison the stored internal result to prove every public/model projection excludes it.
    previous = saved['version']
    bucket = next(iter(saved['attempt_ledger'].values()))
    next(iter(bucket['evidence'].values()))['outcome']['private'] = 'PRIVATE_CHALLENGE_RESULT'
    saved['version'] += 1
    store.save(saved, previous)
    loser_id = (host,guest)[1-winner]
    for suffix in ['', '/events']:
        assert 'PRIVATE_CHALLENGE_RESULT' not in loser.get(f'/api/rooms/{rid}' + suffix).text
    view = scene_storage.for_actor(store.get(rid), loser_id)
    assert 'PRIVATE_CHALLENGE_RESULT' not in str(director.build_context(view, loser_id, '我换一种方式观察'))
    # A complete backup carries the same global mechanical lock, without re-rolling.
    archive = tmp_path / 'shared-attempt.zip'
    backup_database(store.path, archive)
    restore_backup(archive, tmp_path / 'restored-attempt')
    restored = Store(str(tmp_path / 'restored-attempt/database.sqlite3'))
    assert restored.get(rid)['attempt_ledger'] == store.get(rid)['attempt_ledger']
    assert rolls == ['1d20']


def test_selection_cancel_and_receipt_replay_never_create_an_attempt(env, monkeypatch):
    a, b, store, rid, host, guest = setup(env)
    before = deepcopy(store.get(rid)['attempt_ledger'])
    def forbidden(*args, **kwargs):
        pytest.fail('Selection or cancellation rolled')
    with monkeypatch.context() as guard:
        guard.setattr(rules, 'roll_dice', forbidden)
        proposal = select(a, rid)
        assert send(a, rid, 'director_cancel', {'proposal_id':proposal['id']}).status_code == 200
    assert store.get(rid)['attempt_ledger'] == before
    proposal = select(a, rid)
    frame = a.get(f'/api/rooms/{rid}').json()
    body = dict(command_id=uuid.uuid4().hex, type='director_resolve', payload={'proposal_id':proposal['id']},
                expected_version=frame['version'], expected_action_revision=frame['action_revision'],
                expected_scene_instance_id=frame['scene_instance_id'], expected_membership_epoch=frame['membership_epoch'])
    response = a.post(f'/api/rooms/{rid}/commands', json=body)
    assert response.status_code == 200, response.text
    settled = deepcopy(store.get(rid))
    with monkeypatch.context() as guard:
        guard.setattr(rules, 'roll_dice', forbidden)
        replay = a.post(f'/api/rooms/{rid}/commands', json=body)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert store.get(rid) == settled
