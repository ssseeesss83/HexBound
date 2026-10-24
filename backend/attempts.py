"""Server-defined challenge identity and relevant-evidence attempt qualification.

No model text, selected skill, room revision or unrelated character state is an
identity. Callers must resolve the definition and facts from authoritative data.
This module is internal; its stored outcomes are never a public projection.
"""
from copy import deepcopy
import hashlib
import json
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=240)]
Fact = StrictBool | StrictInt | StrictStr | None


class Challenge(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    place_id: Identifier
    challenge_id: Identifier
    question: Identifier
    attempt_scope: Literal['party', 'individual'] = 'party'
    repeat_policy: Literal['once_per_evidence', 'repeat_with_cost'] = 'once_per_evidence'
    evidence: dict[Identifier, Fact] = Field(min_length=1, max_length=32)
    # Positive, authoritative costs must be enforced by the caller's executor.
    retry_cost: dict[Identifier, Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=dict, max_length=8)

    @model_validator(mode='after')
    def validate_cost_policy(self):
        if (self.repeat_policy == 'repeat_with_cost') != bool(self.retry_cost):
            raise ValueError('Repeated attempts require an explicit rule cost')
        if any(isinstance(value, str) and len(value) > 2000 for value in self.evidence.values()):
            raise ValueError('Evidence value is too long')
        return self


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _keys(challenge, actor):
    if not isinstance(actor, str) or not actor:
        raise ValueError('Attempt needs a server actor identity')
    definition = challenge.model_dump(exclude={'evidence'})
    definition['evidence_keys'] = sorted(challenge.evidence)
    owner = actor if challenge.attempt_scope == 'individual' else 'party'
    identity = _digest([challenge.place_id, challenge.challenge_id, challenge.question, owner])
    return identity, _digest(challenge.evidence), _digest(definition)


def inspect(state, challenge, actor):
    """Pure qualification. A previous result is internal, with no knowledge grant."""
    if not isinstance(challenge, Challenge):
        raise ValueError('Only a validated server challenge can qualify attempts')
    identity, evidence, definition = _keys(challenge, actor)
    bucket = state.get('attempt_ledger', {}).get(identity)
    if bucket and bucket['definition_digest'] != definition:
        raise ValueError('Challenge definition changed without a new identity')
    previous = (bucket.get('completed') or bucket.get('evidence', {}).get(evidence)) if bucket else None
    if bucket and bucket.get('legacy_consumed_unknown'):
        status = 'legacy_consumed_unknown'
    elif previous is None:
        status = 'eligible'
    elif previous['success']:
        status = 'resolved'
    elif challenge.repeat_policy == 'repeat_with_cost':
        status = 'eligible_with_cost'
    else:
        status = 'exhausted'
    return dict(status=status, identity=identity, evidence_digest=evidence,
                definition_digest=definition, previous=deepcopy(previous),
                required_cost=deepcopy(challenge.retry_cost))


def record(state, challenge, actor, *, success, outcome, effect_receipt, audience):
    """Record only after authoritative settlement, in the same room transaction.

Callers discard the transaction on any error and apply required costs first.
Both failures and successes persist; replay is handled before settlement by the
command receipt. This function cannot spend resources or roll dice.
"""
    if type(success) is not bool or not isinstance(outcome, dict):
        raise ValueError('Attempt result must be a settled typed outcome')
    if not isinstance(effect_receipt, str) or not 1 <= len(effect_receipt) <= 240:
        raise ValueError('Attempt needs an authoritative effect receipt')
    if not isinstance(audience, list) or not audience or any(not isinstance(sid, str) or not sid for sid in audience) or len(set(audience)) != len(audience):
        raise ValueError('Attempt outcome needs its original knowledge audience')
    qualified = inspect(state, challenge, actor)
    if qualified['status'] not in {'eligible', 'eligible_with_cost'}:
        raise ValueError('Challenge already attempted with the current evidence')
    # Check serialization before any mutation, including non-finite numbers.
    _digest(outcome)
    previous = qualified['previous']
    result = dict(success=success, outcome=deepcopy(outcome), actor_id=actor,
                  attempt_count=(previous['attempt_count'] if previous else 0) + 1,
                  evidence=deepcopy(challenge.evidence), effect_receipt=effect_receipt,
                  audience=sorted(audience))
    ledger = state.setdefault('attempt_ledger', {})
    bucket = ledger.setdefault(qualified['identity'], dict(
        definition_digest=qualified['definition_digest'],
        definition=challenge.model_dump(exclude={'evidence'}), evidence={}))
    bucket['evidence'][qualified['evidence_digest']] = result
    if success:
        bucket['completed'] = deepcopy(result)
    return deepcopy(result)


def lookup(state, action_id, *, object_id=None):
    """Resolve existing frozen challenges, never a free-form model-defined ID.

    New generated challenges need a separately validated graph registration.
    The initial once-per-evidence policy grants no retries for damage, rest,
    room revision, changing skills or changing party membership.
    """
    from . import campaign, content, free_actions, world_environment
    node_id = state.get('scene_id') or content.scene_for(state)['id']
    place = world_environment.place_id(state, node_id)
    if action_id == 'search':
        obj = free_actions._objects(state).get(object_id)
        if not obj or 'searchable' not in obj.get('tags', []):
            raise ValueError('Search needs an existing registered searchable object')
        identity = obj.get('entity_id') or world_environment._entity_id(place, object_id)
        return Challenge(place_id=place, challenge_id='search:' + identity,
                         question='discover_existing_contents', evidence={'registered_contents': 0})
    if object_id is not None:
        raise ValueError('Authored challenges do not accept object overrides')
    if state.get('campaign'):
        action = next((row for row in campaign._node(state).get('actions', [])
                       if 'node:' + row['id'] == action_id and row.get('skill_id')), None)
        if not action or campaign._skill(state, action['skill_id'])['effect'] != 'check':
            return None
    else:
        action = next((row for row in content.scene_for(state).get('actions', [])
                       if row['id'] == action_id and row.get('ability')), None)
        if not action:
            return None
    return Challenge(place_id=place, challenge_id='authored:' + node_id + ':' + action_id,
                     question='resolve_authored_outcome', evidence={'frozen_definition': 0})


def available(state, actor, action_id, *, object_id=None):
    spec = lookup(state, action_id, object_id=object_id)
    return spec is None or inspect(state, spec, actor)['status'] in {'eligible', 'eligible_with_cost'}


def require(state, actor, action_id, *, object_id=None):
    spec = lookup(state, action_id, object_id=object_id)
    if spec and inspect(state, spec, actor)['status'] not in {'eligible', 'eligible_with_cost'}:
        raise ValueError('同一挑战在当前证据下已经尝试；请依据已确认事实行动，不能重新掷骰')
    return spec


def proposal_available(state, actor, decision):
    """Public stale status may expose qualification, never an old private result."""
    kind = decision.get('kind')
    action = decision.get('anchor_action_id') if kind == 'check' else decision.get('action_id')
    if kind == 'check' and not action:
        return False
    if kind not in {'check', 'capability'} and not (kind == 'free_action' and action == 'search'):
        return True
    try:
        return available(state, actor, action, object_id=decision.get('object_id') if action == 'search' else None)
    except (ValueError, KeyError):
        return False


def record_roll(state, spec, actor, roll, event):
    """Bind a settled mechanical result to an effect event, with no narration."""
    if spec is None:
        return
    channel = state.get('_text_channel', 'party-main')
    members = state.get('text_scope', {}).get('members')
    audience = [row['id'] for row in state['members']
                if members is None or members.get(row['id'], {}).get('channel') == channel]
    receipt = uuid.uuid4().hex
    record(state, spec, actor, success=roll['success'], outcome={'roll':deepcopy(roll)},
           effect_receipt=receipt, audience=audience)
    event['attempt_receipt'] = receipt


def migrate(canonical):
    """Pure migration of explicit legacy consumed markers; never invent rolls."""
    from . import content, world_environment
    result = deepcopy(canonical)
    if result.get('attempt_ledger_version') == 1:
        return result
    if result.get('attempt_ledger_version') is not None:
        raise ValueError('Unknown attempt ledger version')
    result.setdefault('attempt_ledger', {})

    def consumed(spec, source):
        identity, _, definition = _keys(spec, 'legacy-party')
        bucket = result['attempt_ledger'].setdefault(identity, dict(
            definition_digest=definition, definition=spec.model_dump(exclude={'evidence'}), evidence={}))
        bucket['legacy_consumed_unknown'] = True
        bucket.setdefault('legacy_sources', []).append(source)

    # Old counters contain no objective identity and cannot become challenge rows.
    for sid, instance in result.get('scene_instances', {}).items():
        local = instance['local']
        if result.get('campaign'):
            continue  # A spent card alone cannot identify which node was attempted.
        definitions = result.get('scenes') or content.SCENES
        for key, value in local.get('flags', {}).get('attempted', {}).items():
            if value is not True:
                continue
            index, separator, action_id = key.partition(':')
            if not separator or not index.isdecimal() or int(index) >= len(definitions):
                continue
            scene = definitions[int(index)]
            view = {**result, **local, 'scene':scene, 'scene_id':scene['id'], 'scene_index':int(index)}
            spec = lookup(view, action_id)
            if spec:
                consumed(spec, 'flags:' + sid + ':' + key)
    for entity in result.get('world_entities', {}).values():
        if entity['kind'] == 'object' and entity['state'].get('searched') is True:
            spec = Challenge(place_id=entity['place_id'], challenge_id='search:' + entity['id'],
                             question='discover_existing_contents', evidence={'registered_contents':0})
            consumed(spec, 'searched:' + entity['id'])
    result['attempt_ledger_version'] = 1
    return result
