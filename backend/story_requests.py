"""Atomic scene-wait consumers of bounded jobs; no automatic trigger or entry."""
from copy import deepcopy
import json
import uuid
from typing import Literal

from pydantic import TypeAdapter

from . import generation_jobs,scene_storage,story_patches,story_transitions as routes
from .schemas import Identifier,StrictModel
from .story_challenges import _hash


class RetryPlan(StrictModel):
    schema_version: Literal[1] = 1
    id: story_patches.JobID
    transition_id: Identifier
    job_id: story_patches.JobID
    scope: dict
    route_plan: dict
    authorization_digest: generation_jobs.Digest
    expires_at: float
    budget: generation_jobs.Budget


def _retry_review(db,room_id,actor):
    row = db.execute('SELECT state,version FROM rooms WHERE id=?',(room_id,)).fetchone()
    if row is None:raise ValueError('房间不存在')
    canonical = json.loads(row['state'])
    state = scene_storage.for_actor(canonical,actor)
    scope = routes._guard(state,actor)
    pending = state.get('pending_transition')
    if not pending or not pending.get('generation_job_id'):
        raise ValueError('当前没有可追加预算的路线等待')
    if (pending['plan']['scope']!=scope
            or pending['plan']['source_node_id']!=state.get('campaign',{}).get('node_id')):
        raise ValueError('路线等待范围或来源已经变化，请重新审核')
    job_row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(pending['generation_job_id'],)).fetchone()
    job = generation_jobs._decode(job_row) if job_row else None
    if not job or not _matches(job,state,pending) or job['status']!='terminal_failed':
        raise ValueError('仅耗尽的续写任务可以明确追加一次预算')
    plan = routes.prepare(state,actor,pending['plan']['edge_id'],
                          prerequisite_receipt_ids=pending['plan']['prerequisite_receipt_ids'])
    if plan['destination']['status']!='pending':
        raise ValueError('路线已可审核，不需要追加预算')
    # Bind the complete continuation dependency snapshot, not just the exit's
    # condition. Stable dummy identity/time only make this a pure comparison.
    authorization = story_patches.grant(state,actor,plan['destination']['frontier_id'],
                                        job_id='0'*32,now=0,ttl=1)
    return row,canonical,state,dict(transition_id=pending['id'],job_id=job['id'],scope=scope,route_plan=plan,
                                    authorization_digest=_hash(authorization))


def prepare_retry(service,room_id,actor,*,now=None):
    """Internal read-only review; one explicit confirmation grants one attempt."""
    now = float(story_patches._now(now))
    with service.store.connect() as db:
        db.execute('BEGIN')
        _,_,_,review = _retry_review(db,room_id,actor)
    return RetryPlan(id=uuid.uuid4().hex,**review,expires_at=now+120,
                     budget=generation_jobs.Budget(max_attempts=1)).model_dump(mode='json')


def confirm_retry(service,room_id,actor,plan,*,now=None):
    """Internal confirmed-plan executor; budget, binding and receipt are atomic.

    This never repeats prerequisites, charges character resources or moves the
    party. Ordinary enqueue and automatic recovery cannot invoke this contract.
    """
    plan = RetryPlan.model_validate(plan).model_dump(mode='json')
    now = float(story_patches._now(now))
    if plan['budget']!=generation_jobs.Budget(max_attempts=1).model_dump():
        raise ValueError('本次只允许追加一次默认续写预算')
    digest = _hash(plan)
    with service.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state,version FROM rooms WHERE id=?',(room_id,)).fetchone()
        if row is None:raise ValueError('房间不存在')
        canonical = json.loads(row['state'])
        state = scene_storage.for_actor(canonical,actor)
        scope = routes._guard(state,actor,route=False)
        if scope!=plan['scope']:
            raise ValueError('追加预算的场景或权限已经变化')
        sid = scope['scene_instance_id']
        local = canonical['scene_instances'][sid]['local']
        receipts = local.get('generation_retry_receipts',{})
        prior = receipts.get(plan['id'])
        if prior:
            if prior['digest']!=digest:raise ValueError('同一预算回执不能用于不同请求')
            job_row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(prior['job_id'],)).fetchone()
            if job_row is None:raise ValueError('追加预算任务不存在')
            return dict(job=generation_jobs._decode(job_row),replayed=True)
        if now>=plan['expires_at'] or plan['expires_at']>now+120:
            raise ValueError('追加预算计划已过期或时间无效')
        if len(receipts)>=10000:raise ValueError('当前场景的预算回执已达到上限')
        _,_,state,current = _retry_review(db,room_id,actor)
        if any(plan[key]!=value for key,value in current.items()):
            raise ValueError('任务、等待或路线事实已变化，请重新审核')
        job = service._enqueue_in_transaction(db,state,room_id,actor,
            plan['route_plan']['destination']['frontier_id'],priority=0,budget=plan['budget'],now=now,
            retry_of=plan['job_id'],retry_receipt_id=plan['id'])
        local['pending_transition']['generation_job_id'] = job['id']
        local.setdefault('generation_retry_receipts',{})[plan['id']] = dict(
            digest=digest,job_id=job['id'],previous_job_id=plan['job_id'],budget=deepcopy(plan['budget']))
        canonical['version'] = row['version']+1
        updated = db.execute('UPDATE rooms SET state=?,version=? WHERE id=? AND version=?',
            (json.dumps(canonical,ensure_ascii=False),canonical['version'],room_id,row['version']))
        if updated.rowcount!=1:raise ValueError('房间已变化，请重新审核')
        return dict(job=deepcopy(job),replayed=False)


def _matches(job,state,pending):
    plan = pending['plan']
    auth = job['authorization']
    return (job['room_id']==state['id']
            and auth['scope']['scene_instance_id']==plan['scope']['scene_instance_id']
            and auth['source_node_id']==plan['source_node_id']
            and auth['frontier_id']==plan['destination']['frontier_id'])


def bind(service,room_id,actor,transition_id,*,now=None):
    """Recheck the same wait, enqueue/promote and bind in ONE write transaction.

    Repeated calls keep an existing binding, including failed/stale/cancelled
    jobs. They cannot reset its budget or silently reauthorize its dependencies.
    """
    transition_id = TypeAdapter(Identifier).validate_python(transition_id,strict=True)
    now = float(story_patches._now(now))
    with service.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state,version FROM rooms WHERE id=?',(room_id,)).fetchone()
        if row is None:raise ValueError('房间不存在')
        canonical = json.loads(row['state'])
        state = scene_storage.for_actor(canonical,actor)
        scope = routes._guard(state,actor,route=False)
        pending = state.get('pending_transition')
        if (not pending or pending['id']!=transition_id or pending['plan']['scope']!=scope
                or pending['plan']['source_node_id']!=state.get('campaign',{}).get('node_id')):
            raise ValueError('路线等待身份或范围已经变化')
        generation_jobs._prune_room(db,room_id,now)
        existing = pending.get('generation_job_id')
        if existing is not None:
            job_row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(existing,)).fetchone()
            if job_row is None:raise ValueError('等待任务不存在，请重新审核路线')
            job = generation_jobs._decode(job_row)
            if not _matches(job,state,pending):
                raise ValueError('等待与任务的场景或出口不匹配')
            return dict(job=deepcopy(job),replayed=True)
        if routes.status(state,actor)!={'status':'waiting'}:
            raise ValueError('请重新审核当前路线后再请求续写')
        job = service._enqueue_in_transaction(db,state,room_id,actor,
            pending['plan']['destination']['frontier_id'],priority=0,
            budget=generation_jobs.Budget().model_dump(),now=now)
        sid = scope['scene_instance_id']
        saved = canonical['scene_instances'][sid]['local'].get('pending_transition')
        if saved!=pending:
            raise ValueError('路线等待已经变化')
        saved['generation_job_id'] = job['id']
        canonical['version'] = row['version']+1
        updated = db.execute('UPDATE rooms SET state=?,version=? WHERE id=? AND version=?',
            (json.dumps(canonical,ensure_ascii=False),canonical['version'],room_id,row['version']))
        if updated.rowcount!=1:raise ValueError('房间已变化，请重新审核路线')
        return dict(job=deepcopy(job),replayed=False)


def public_status(service,state,actor,*,now=None):
    """Only scene-local readiness codes; never job IDs, reports or grants."""
    route = routes.status(state,actor)
    if route is None or route['status']!='waiting':
        return route
    pending = state['pending_transition']
    job_id = pending.get('generation_job_id')
    if job_id is None:
        return route
    try:
        job = service.get(job_id)
        if job is None or not _matches(job,state,pending):
            raise ValueError('等待任务身份无效')
        story_patches._check_grant(state,job['authorization'],story_patches._now(now))
        if job['status']=='stale':
            return dict(status='review_required')
        if job['status'] in {'terminal_failed','cancelled'}:
            return dict(status='failed')
        if job['status']=='retryable_failed':
            return dict(status='retrying')
        if job['status']=='committed':
            return dict(status='review_required')
        return route
    except (ValueError,KeyError):
        return dict(status='review_required')
