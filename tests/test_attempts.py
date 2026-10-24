"""Qualification is about server objectives and evidence, never prose or counters."""
from copy import deepcopy
import hashlib
import json

import pytest

from backend import attempts, content, scene_storage, world_environment
from test_scenario_plans import room


def challenge(**changes):
    return attempts.Challenge(**dict(place_id='place:gate', challenge_id='read-inscription',
                                     question='identify-author', evidence={'inscription_version': 0}, **changes))


def settled(state, spec, actor='hero', success=False):
    return attempts.record(state, spec, actor, success=success, outcome={'roll': {'total': 7}},
                           effect_receipt='command:once', audience=[actor])


def test_qualification_is_pure_and_party_identity_ignores_prose_skill_and_membership():
    state, spec = {}, challenge()
    assert attempts.inspect(state, spec, 'hero')['status'] == 'eligible' and state == {}
    settled(state, spec)
    before = deepcopy(state)
    for actor in ['hero', 'companion', 'new-seat']:
        assert attempts.inspect(state, spec, actor)['status'] == 'exhausted'
    assert state == before
    state.update(version=999, events=[{'kind':'chat', 'text':'try another wording'}],
                 rest_used=True, members=[{'id':'hero','character':{'hp':99}}])
    assert attempts.inspect(state, spec, 'hero')['status'] == 'exhausted'


def test_evidence_changes_only_with_registered_read_set_and_previous_versions_remain_consumed():
    state, spec = {}, challenge()
    settled(state, spec)
    changed = spec.model_copy(update={'evidence': {'inscription_version': 1}})
    assert attempts.inspect(state, changed, 'hero')['status'] == 'eligible'
    settled(state, changed)
    assert attempts.inspect(state, spec, 'hero')['status'] == 'exhausted'
    altered_keys = spec.model_copy(update={'evidence': {'unrelated_hp': 1}})
    with pytest.raises(ValueError, match='definition'):
        attempts.inspect(state, altered_keys, 'hero')


def test_success_is_internal_reusable_result_and_never_becomes_eligible_after_fact_change():
    state, spec = {}, challenge()
    settled(state, spec, success=True)
    changed = spec.model_copy(update={'evidence': {'inscription_version': 1}})
    result = attempts.inspect(state, changed, 'other-party-member')
    assert result['status'] == 'resolved'
    assert result['previous']['audience'] == ['hero']  # This is not an information grant.
    result['previous']['outcome']['roll']['total'] = 999
    assert attempts.inspect(state, spec, 'hero')['previous']['outcome']['roll']['total'] == 7
    before = deepcopy(state)
    with pytest.raises(ValueError):
        settled(state, changed, success=True)
    assert state == before


def test_retry_requires_positive_rule_cost_and_success_ends_retries():
    spec = challenge(repeat_policy='repeat_with_cost', retry_cost={'tool-charge': 1})
    state = {}
    settled(state, spec)
    status = attempts.inspect(state, spec, 'hero')
    assert status['status'] == 'eligible_with_cost' and status['required_cost'] == {'tool-charge': 1}
    result = settled(state, spec, success=True)
    assert result['attempt_count'] == 2
    assert attempts.inspect(state, spec, 'hero')['status'] == 'resolved'


@pytest.mark.parametrize('fields', [
    {'repeat_policy':'repeat_with_cost'}, {'retry_cost':{'action':1}},
    {'repeat_policy':'repeat_with_cost','retry_cost':{'charge':0}},
    {'repeat_policy':'repeat_with_cost','retry_cost':{'charge':True}},
    {'evidence':{}}, {'evidence':{'key':[]}}, {'evidence':{'key':1.2}},
])
def test_invalid_definition_is_rejected(fields):
    data = dict(place_id='p', challenge_id='c', question='q', evidence={'key':0})
    data.update(fields)
    with pytest.raises(ValueError):
        attempts.Challenge(**data)


def test_individual_attempts_are_separate_and_failed_records_cannot_be_overwritten():
    state, spec = {}, challenge(attempt_scope='individual')
    settled(state, spec)
    assert attempts.inspect(state, spec, 'other-character')['status'] == 'eligible'
    with pytest.raises(ValueError):
        settled(state, spec, success=True)
    assert attempts.inspect(state, spec, 'hero')['previous']['success'] is False


def test_invalid_result_fails_before_any_mutation():
    state, spec = {}, challenge()
    for extra in [{'success':1}, {'outcome':{'number':float('nan')}}, {'audience':[]}, {'effect_receipt':''}]:
        kwargs = dict(success=False, outcome={}, effect_receipt='command:x', audience=['hero'])
        kwargs.update(extra)
        with pytest.raises(ValueError):
            attempts.record(state, spec, 'hero', **kwargs)
        assert state == {}


def test_registered_lookup_has_no_model_defined_identity_and_ledger_stays_global():
    state = room()
    spec = attempts.lookup(state, 'investigate')
    assert spec.challenge_id == 'authored:dock:investigate'
    assert attempts.lookup(state, 'invent-a-different-name') is None
    assert attempts.lookup(state, 'attack') is None
    state['scene']['objects'] = [dict(id='crate', tags=['searchable'], hp=10)]
    search = attempts.lookup(state, 'search', object_id='crate')
    settled(state, search, actor='p')
    state['scene']['objects'][0].update(hp=1, burning=True, activated=True)
    assert attempts.lookup(state, 'search', object_id='crate') == search
    before = deepcopy(state['attempt_ledger'])
    packed = scene_storage.pack(state)
    assert packed['attempt_ledger'] == before
    assert 'attempt_ledger' not in packed['scene_instances']['scene-main']['local']
    restored = scene_storage.unpack(packed)
    assert restored['attempt_ledger'] == before
    canonical = world_environment.migrate(packed)
    migrated = scene_storage.unpack(canonical)
    assert attempts.lookup(migrated, 'search', object_id='crate') == search
    assert attempts.inspect(migrated, search, 'new-seat')['status'] == 'exhausted'


def test_optional_native_definition_binding_keeps_existing_legacy_digest():
    spec = challenge()
    old_definition = spec.model_dump(exclude={'evidence','definition_ref'})
    old_definition['evidence_keys'] = sorted(spec.evidence)
    old_digest = hashlib.sha256(json.dumps(old_definition,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    state = {}
    settled(state,spec)
    assert next(iter(state['attempt_ledger'].values()))['definition_digest'] == old_digest
    assert attempts.inspect(state,spec,'hero')['status']=='exhausted'
