"""Durable server-owned generation requests with revocable worker leases.

No provider calls or graph writes. Callers own scheduling and permission-safe
notifications. Never expose this payload or grant through player projections.
"""
from copy import deepcopy
import json
import uuid
from typing import Literal

from pydantic import Field, model_validator

from . import scene_storage, story_patches
from .schemas import StrictModel
from .story_challenges import _hash
from .story_runtime import Digest

ACTIVE = ('queued','running','validated','retryable_failed')


class Budget(StrictModel):
    max_attempts: int = Field(default=3,ge=1,le=3)
    timeout_seconds: int = Field(default=90,ge=1,le=120)
    max_tokens: int = Field(default=4000,ge=500,le=6000)


class Dispatches(StrictModel):
    generation: int = Field(default=0,ge=0,le=3)
    semantic: int = Field(default=0,ge=0,le=3)


class Job(StrictModel):
    id: story_patches.JobID
    room_id: str
    dedup_key: Digest
    status: Literal['queued','running','validated','committed','cancelled','stale','retryable_failed','terminal_failed']
    priority: int = Field(ge=0,le=3)
    authorization: dict
    budget: Budget
    attempts: int = Field(default=0,ge=0,le=3)
    # None means historical counts were not collected, never zero usage.
    dispatches: Dispatches | None = None
    attempt_stage: Literal['claimed','generation','semantic'] | None = None
    created_at: float
    next_run_at: float
    lease_token: story_patches.JobID | None = None
    lease_until: float | None = None
    error_code: Literal['lease_expired','dependency_changed','provider_failed','preempted'] | None = None
    output: dict | None = None
    commit_receipt: dict | None = None

    @model_validator(mode='after')
    def lease_shape(self):
        leased = self.status in {'running','validated'}
        if leased != (self.lease_token is not None and self.lease_until is not None):
            raise ValueError('任务状态与租约不一致')
        if not leased and (self.lease_token is not None or self.lease_until is not None):
            raise ValueError('已撤销任务不能保留租约')
        if self.attempts>self.budget.max_attempts or (leased and self.attempts==0):
            raise ValueError('任务尝试次数无效')
        if not leased and self.attempt_stage is not None:
            raise ValueError('已撤销任务不能保留当前调用阶段')
        if self.dispatches and not self.dispatches.semantic<=self.dispatches.generation<=self.attempts:
            raise ValueError('任务调用计数无效')
        return self


def _decode(row):
    job = Job.model_validate_json(row['payload']).model_dump(mode='json')
    for key in ['id','room_id','dedup_key','status','priority','lease_until']:
        if job[key]!=row[key]:
            raise ValueError('剧情任务索引与内容不一致')
    return job


def _save(db,job):
    job = Job.model_validate(job).model_dump(mode='json')
    db.execute('UPDATE generation_jobs SET status=?,priority=?,lease_until=?,payload=? WHERE id=?',
               (job['status'],job['priority'],job['lease_until'],json.dumps(job,ensure_ascii=False),job['id']))


def _view(db,job):
    room = db.execute('SELECT state FROM rooms WHERE id=?',(job['room_id'],)).fetchone()
    if room is None:
        raise ValueError('剧情任务房间不存在')
    return scene_storage.for_actor(json.loads(room['state']),job['authorization']['scope']['actor_id'])


def _check_current(db,job,now):
    story_patches._check_grant(_view(db,job),job['authorization'],now)


def _end_attempt(job,now,error):
    job.update(status='terminal_failed' if job['attempts']>=job['budget']['max_attempts'] else 'retryable_failed',
               error_code=error,lease_token=None,lease_until=None,output=None,attempt_stage=None,
               next_run_at=now+min(30,2**job['attempts']))


def _prune_room(db,room_id,now):
    """At most 16 active records per room; stale queues cannot consume capacity."""
    rows = db.execute("SELECT * FROM generation_jobs WHERE room_id=? AND status IN ('queued','running','validated','retryable_failed')",(room_id,)).fetchall()
    changed = []
    for row in rows:
        job = _decode(row)
        try:_check_current(db,job,now)
        except (ValueError,KeyError):
            job.update(status='stale',error_code='dependency_changed',lease_token=None,lease_until=None,output=None,attempt_stage=None)
        else:
            if job['status'] not in {'running','validated'} or now<job['lease_until']:
                continue
            _end_attempt(job,now,'lease_expired')
        _save(db,job)
        changed.append(job['id'])
    return changed


class GenerationJobs:
    def __init__(self,store):
        self.store = store

    def get(self,job_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            return _decode(row) if row else None

    def ready(self,*,limit=16,now=None):
        """Bounded internal dispatch candidates, not a public task projection."""
        now = float(story_patches._now(now))
        if type(limit) is not int or not 1<=limit<=100:
            raise ValueError('任务读取上限无效')
        with self.store.connect() as db:
            rows = db.execute("""SELECT * FROM generation_jobs
                WHERE status IN ('queued','retryable_failed')
                  AND json_extract(payload,'$.next_run_at')<=?
                ORDER BY priority,json_extract(payload,'$.created_at'),id LIMIT ?""",(now,limit)).fetchall()
            return [_decode(row) for row in rows]

    def enqueue(self,room_id,actor,frontier_id,*,priority=2,budget=None,now=None):
        now = float(story_patches._now(now))
        if type(priority) is not int or not 0<=priority<=3:
            raise ValueError('剧情任务优先级无效')
        budget = Budget.model_validate({} if budget is None else budget).model_dump()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE id=?',(room_id,)).fetchone()
            if row is None:raise ValueError('房间不存在')
            state = scene_storage.for_actor(json.loads(row['state']),actor)
            return self._enqueue_in_transaction(db,state,room_id,actor,frontier_id,priority=priority,budget=budget,now=now)

    def _enqueue_in_transaction(self,db,state,room_id,actor,frontier_id,*,priority,budget,now):
        if not db.in_transaction:
            raise RuntimeError('入队须在调用方持有的事务内完成')
        sid = uuid.uuid4().hex
        auth = story_patches.grant(state,actor,frontier_id,job_id=sid,now=now,ttl=600)
        _prune_room(db,room_id,now)
        dedup_input = {key:value for key,value in auth.items() if key not in {'job_id','namespace','expires_at'}}
        dedup_input['scope'] = {key:value for key,value in auth['scope'].items() if key not in {'actor_id','membership_epoch'}}
        dedup = _hash(dedup_input)
        old = db.execute("SELECT * FROM generation_jobs WHERE room_id=? AND dedup_key=? AND status IN ('queued','running','validated','retryable_failed')",(room_id,dedup)).fetchone()
        if old:
            existing = _decode(old)
            # A required request can promote queued work without replacing
            # its identity, budget, lease or original authority snapshot.
            if now<existing['authorization']['expires_at']:
                existing['priority']=min(priority,existing['priority'])
                _save(db,existing)
                return deepcopy(existing)
            existing.update(status='stale',error_code='dependency_changed',lease_token=None,lease_until=None,output=None,attempt_stage=None)
            _save(db,existing)
        exhausted = db.execute("SELECT * FROM generation_jobs WHERE room_id=? AND dedup_key=? AND status='terminal_failed' ORDER BY rowid DESC LIMIT 1",(room_id,dedup)).fetchone()
        if exhausted:
            # Repeated automatic triggers are not fresh generation budget.
            # An explicit additional-budget/retry contract belongs to the
            # logical waiting request, not to ordinary enqueue calls.
            return deepcopy(_decode(exhausted))
        count = db.execute("SELECT COUNT(*) FROM generation_jobs WHERE room_id=? AND status IN ('queued','running','validated','retryable_failed')",(room_id,)).fetchone()[0]
        if count>=16:raise ValueError('当前冒险的续写队列已满')
        job = Job(id=sid,room_id=room_id,dedup_key=dedup,status='queued',priority=priority,
                  authorization=auth,budget=budget,dispatches=Dispatches(),created_at=now,next_run_at=now).model_dump(mode='json')
        db.execute('INSERT INTO generation_jobs VALUES(?,?,?,?,?,?,?)',
                   (sid,room_id,dedup,'queued',priority,None,json.dumps(job,ensure_ascii=False)))
        return deepcopy(job)

    def claim(self,job_id,*,now=None):
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:return None
            job = _decode(row)
            if job['status'] not in {'queued','retryable_failed'} or now<job['next_run_at']:
                return None
            try:_check_current(db,job,now)
            except (ValueError,KeyError):
                job.update(status='stale',error_code='dependency_changed',lease_token=None,lease_until=None,output=None,attempt_stage=None)
                _save(db,job)
                return None
            if job['attempts']>=job['budget']['max_attempts']:
                job['status']='terminal_failed'
                _save(db,job)
                return None
            job.update(status='running',attempts=job['attempts']+1,lease_token=uuid.uuid4().hex,
                       lease_until=min(now+job['budget']['timeout_seconds'],job['authorization']['expires_at']),error_code=None,
                       attempt_stage='claimed')
            _save(db,job)
            return deepcopy(job)

    def require_lease(self,job_id,lease_token,*,now=None):
        """Read-only worker check; writers must repeat it inside their transaction."""
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise ValueError('剧情任务不存在')
            job = _decode(row)
            self._lease(db,job,lease_token,now)
            return deepcopy(job)

    def mark_dispatch(self,job_id,lease_token,stage,*,now=None):
        """Reserve one actual provider dispatch immediately before its await.

        Dispatch does not imply the supplier received/charged the request, and
        is not a token-usage measurement. Uncertain sent calls are not refunded.
        """
        if stage not in {'generation','semantic'}:
            raise ValueError('续写调用阶段无效')
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise ValueError('剧情任务不存在')
            job = _decode(row)
            self._lease(db,job,lease_token,now)
            if job['status']!='running' or job['attempt_stage']!=('claimed' if stage=='generation' else 'generation'):
                raise ValueError('同一尝试不能重复或跳过调用阶段')
            if job['dispatches'] is not None:
                job['dispatches'][stage] += 1
            job['attempt_stage'] = stage
            _save(db,job)
            return deepcopy(job)

    def preempt(self,job_id,lease_token,*,now=None):
        """Revoke only this worker and resume the SAME bounded logical job."""
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:return None
            job = _decode(row)
            if job['status'] not in {'running','validated'} or job['lease_token']!=lease_token:
                return deepcopy(job)
            try:_check_current(db,job,now)
            except (ValueError,KeyError):
                job.update(status='stale',error_code='dependency_changed',lease_token=None,lease_until=None,output=None,attempt_stage=None)
            else:
                # A claimed worker interrupted BEFORE any remote dispatch did
                # not consume an outbound attempt. Legacy unknown stages are
                # charged conservatively, and dispatched work is never free.
                if job['attempt_stage']=='claimed':
                    job['attempts'] -= 1
                job.update(status='terminal_failed' if job['attempts']>=job['budget']['max_attempts'] else 'retryable_failed',
                           error_code='preempted',lease_token=None,lease_until=None,output=None,attempt_stage=None,next_run_at=now)
            _save(db,job)
            return deepcopy(job)

    @staticmethod
    def _lease(db,job,token,now):
        if job['status'] not in {'running','validated'} or job['lease_token']!=token or now>=job['lease_until']:
            raise ValueError('剧情任务租约已失效')
        _check_current(db,job,now)

    def fail(self,job_id,lease_token,*,now=None):
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise ValueError('剧情任务不存在')
            job = _decode(row)
            self._lease(db,job,lease_token,now)
            _end_attempt(job,now,'provider_failed')
            _save(db,job)
            return deepcopy(job)

    def cancel(self,job_id,*,lease_token=None):
        """Server scheduler revocation, separate from cancelling a scene wait."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:return None
            job = _decode(row)
            if lease_token is not None and job['lease_token']!=lease_token:
                return deepcopy(job)
            if job['status'] in ACTIVE:
                job.update(status='cancelled',lease_token=None,lease_until=None,output=None,attempt_stage=None)
                _save(db,job)
            return deepcopy(job)

    def recover(self,*,now=None):
        """Bounded restart sweep; expired old callbacks lose their lease first."""
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT * FROM generation_jobs WHERE status IN ('running','validated') AND lease_until<=? ORDER BY lease_until,id LIMIT 100",(now,)).fetchall()
            result = []
            for row in rows:
                job = _decode(row)
                _end_attempt(job,now,'lease_expired')
                _save(db,job)
                result.append(job['id'])
            return result

    def prune_room(self,room_id,*,now=None):
        """Scheduler/foreground-trigger cleanup including queued and retryable."""
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return _prune_room(db,room_id,now)

    def validate_output(self,job_id,lease_token,candidate,approval,*,now=None):
        """Store reviewed output after fresh checks; no graph write yet."""
        from .story_semantics import NarrativeApproval
        now = float(story_patches._now(now))
        if not isinstance(candidate,story_patches.ReviewedPatch) or not isinstance(approval,NarrativeApproval):
            raise ValueError('剧情结果须先完成结构和独立语义复审')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise ValueError('剧情任务不存在')
            job = _decode(row)
            self._lease(db,job,lease_token,now)
            fresh = story_patches.review(_view(db,job),job['authorization'],json.loads(candidate.payload_json),now=now)
            if candidate.job_id!=job_id or candidate.patch_digest!=fresh.patch_digest or candidate.compiled_digest!=fresh.compiled_digest:
                raise ValueError('剧情候选与任务不一致')
            approval.verify(job['authorization'],fresh)
            output = dict(patch=json.loads(fresh.payload_json),approval=approval.model_dump(mode='json'))
            if job['status']=='validated' and job['output']!=output:
                raise ValueError('同一租约不能替换已经验证的补丁')
            job.update(status='validated',output=output)
            _save(db,job)
            return deepcopy(job)

    def commit(self,job_id,lease_token,*,now=None):
        """Atomically attach a reviewed graph and complete its job, never entry."""
        from .story_semantics import NarrativeApproval
        now = float(story_patches._now(now))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise ValueError('剧情任务不存在')
            job = _decode(row)
            if job['status']=='committed':
                receipt = job['commit_receipt']
                if not receipt or receipt['worker_digest']!=_hash(lease_token):
                    raise ValueError('剧情完成回执不属于该worker')
                return dict(receipt=deepcopy(receipt),replayed=True)
            self._lease(db,job,lease_token,now)
            if job['status']!='validated' or not job['output']:
                raise ValueError('剧情结果尚未完成验证')
            # Recompute on the latest room, so unrelated facts changed during
            # remote review survive. Never copy an earlier full-state snapshot.
            fresh = story_patches.review(_view(db,job),job['authorization'],job['output']['patch'],now=now)
            NarrativeApproval.model_validate(job['output']['approval']).verify(job['authorization'],fresh)
            room = db.execute('SELECT state,version FROM rooms WHERE id=?',(job['room_id'],)).fetchone()
            canonical = json.loads(room['state'])
            canonical['campaign']['runtime_graph'] = json.loads(fresh.graph_json)
            canonical['campaign']['story_state'] = json.loads(fresh.state_json)
            canonical['version'] = room['version']+1
            receipt = dict(job_id=job_id,patch_digest=fresh.patch_digest,
                compiled_digest=fresh.compiled_digest,
                graph_revision=canonical['campaign']['runtime_graph']['graph_revision'],
                room_version=canonical['version'],worker_digest=_hash(lease_token))
            updated = db.execute('UPDATE rooms SET state=?,version=? WHERE id=? AND version=?',
                (json.dumps(canonical,ensure_ascii=False),canonical['version'],job['room_id'],room['version']))
            if updated.rowcount!=1:raise ValueError('剧情房间已变化')
            job.update(status='committed',lease_token=None,lease_until=None,commit_receipt=receipt,attempt_stage=None)
            _save(db,job)
            return dict(receipt=deepcopy(receipt),replayed=False)
