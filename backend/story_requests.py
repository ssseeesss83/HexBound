"""Atomic scene-wait consumers of bounded jobs; no automatic trigger or entry."""
from copy import deepcopy
import json

from pydantic import TypeAdapter

from . import generation_jobs,scene_storage,story_patches,story_transitions as routes
from .schemas import Identifier


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
