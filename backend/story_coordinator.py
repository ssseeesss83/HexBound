"""Bounded server triggers, recoverable wait binding and safe snapshot notices."""
import asyncio
import json
import sqlite3

from . import scene_storage,story_requests,story_runtime,story_transitions as routes


def nearby_frontiers(state):
    """At most one public frontier within two author edges; no recursive fanout."""
    view,facts,source = routes._source(state)
    nodes = {row['id']:row for row in view['book']['nodes']}
    current,seen = [source['id']],{source['id']}
    for _ in range(2):
        following = []
        for node_id in current:
            edges = sorted((edge for edge in view['book']['edges'] if edge['from']==node_id),
                           key=lambda edge:(-edge['priority'],not edge['main_path'],edge['id']))
            for edge in edges:
                if edge['visibility']!='public' or not story_runtime.evaluate(edge['condition'],view,facts)['value']:
                    continue
                target = nodes[edge['to']]
                if target['id'] in seen:
                    continue
                seen.add(target['id'])
                if target['kind']=='frontier':
                    if target['id'] not in view['frontier_resolutions']:
                        return [target['id']]
                    # A generated attachment is NOT another speculative step.
                    # Only a later confirmed player action may plan its exits.
                    continue
                if target['kind'] in {'scene','key'}:
                    following.append(target['id'])
        current = following
    return []


class StoryCoordinator:
    def __init__(self,jobs,scheduler,publish):
        self.jobs,self.scheduler,self.publish = jobs,scheduler,publish
        scheduler.on_result = self.completed
        self._notifications = set()
        self._notify_retry = {}
        self._inflight = set()
        self._wake = asyncio.Event()
        self._task = None
        self._closed = False
        self._cursor = ''
        self._partial = None
        self._metrics = dict(wait_bindings=0,prefetch_requests=0,refresh_errors=0,
                             notifications=0,notify_errors=0,notify_drops=0,recovery_errors=0,pump_failures=0)

    def snapshot(self):
        return dict(self._metrics,pending_notifications=len(self._notifications),closed=self._closed,
                    pump_running=self._task is not None and not self._task.done())

    def _state(self,room_id,actor):
        with self.jobs.store.connect() as db:
            row = db.execute('SELECT state FROM rooms WHERE id=?',(room_id,)).fetchone()
        if row is None:raise ValueError('房间不存在')
        return scene_storage.for_actor(json.loads(row['state']),actor)

    def refresh(self,room_id,actor):
        """Call only after a committed player action, never chat or a draft."""
        if self._closed:return None
        try:
            state = self._state(room_id,actor)
            if (state.get('status')!='playing' or state.get('completed')
                    or (state.get('campaign') or {}).get('package',{}).get('scenario',{}).get('schema_version')!=2):
                return None
            pending = state.get('pending_transition')
            if pending:
                result = story_requests.bind(self.jobs,room_id,actor,pending['id'],now=self.scheduler.clock())
                if not result['replayed']:
                    self._metrics['wait_bindings'] += 1
                self.scheduler.wake()
                self.completed(result['job']['id'])
                return result['job']
            if not self.scheduler.provider.configured or (state.get('combat') or {}).get('active'):
                return None
            candidates = nearby_frontiers(state)
            if candidates:
                job = self.jobs.enqueue(room_id,actor,candidates[0],priority=2,now=self.scheduler.clock())
                self._metrics['prefetch_requests'] += 1
                self.scheduler.wake()
                return job
        except (ValueError,KeyError,OSError,sqlite3.Error):
            # A post-commit binding failure must not undo/replay a paid action.
            # The recovery sweep can attach its still-unbound explicit wait.
            self._metrics['refresh_errors'] += 1
        return None

    def status(self,state,actor):
        result = story_requests.public_status(self.jobs,state,actor,now=self.scheduler.clock())
        if result and result['status'] in {'waiting','retrying'} and not self.scheduler.provider.configured:
            return dict(status='unavailable')
        return result

    def can_retry(self,state,actor):
        pending=state.get('pending_transition')
        if not pending or not pending.get('generation_job_id'):return False
        job=self.jobs.get(pending['generation_job_id'])
        if not job or job['status']!='terminal_failed':return False
        try:story_requests.prepare_retry(self.jobs,state['id'],actor,now=self.scheduler.clock())
        except (ValueError,KeyError):return False
        return True

    def completed(self,job_id):
        """Coalesce safe current snapshots; no private task text becomes an event."""
        if self._closed:return
        job = self.jobs.get(job_id)
        if job is None:return
        room_id = job['room_id']
        if len(self._notifications | self._inflight)>=128 and room_id not in self._notifications | self._inflight:
            self._metrics['notify_drops'] += 1
            return
        self._notifications.add(room_id)
        self._wake.set()

    def recover_waits(self):
        """Incremental restart sweep; only explicit unbound waits, never prefetch."""
        with self.jobs.store.connect() as db:
            rows = db.execute("SELECT id,state FROM rooms WHERE id>? AND json_extract(state,'$.status')='playing' ORDER BY id LIMIT 8",(self._cursor,)).fetchall()
        if not rows:
            self._cursor = ''
            self._partial = None
            return
        remaining = 4
        for row in rows:
            room = json.loads(row['state'])
            if self._partial and self._partial[0]!=row['id']:
                self._partial = None
            for scene_id,instance in sorted(room.get('scene_instances',{}).items()):
                if self._partial and scene_id<=self._partial[1]:
                    continue
                pending = instance['local'].get('pending_transition')
                if not pending or pending.get('generation_job_id'):
                    continue
                try:
                    result = story_requests.bind(self.jobs,row['id'],pending['plan']['scope']['actor_id'],
                        pending['id'],now=self.scheduler.clock())
                    if not result['replayed']:
                        self._metrics['wait_bindings'] += 1
                    self.scheduler.wake()
                    self.completed(result['job']['id'])
                except (ValueError,KeyError,OSError,sqlite3.Error):
                    self._metrics['recovery_errors'] += 1
                remaining -= 1
                self._partial = (row['id'],scene_id)
                if remaining==0:return
            self._cursor = row['id']
            self._partial = None

    async def _send(self,room_id):
        try:
            async with asyncio.timeout(4):
                await self.publish(room_id)
            self._metrics['notifications'] += 1
            self._notify_retry.pop(room_id,None)
        except Exception:
            self._metrics['notify_errors'] += 1
            failures = min(self._notify_retry.get(room_id,(0,0))[0]+1,7)
            self._notify_retry[room_id] = (failures,asyncio.get_running_loop().time()+min(0.5*2**(failures-1),30))
            self._notifications.add(room_id)

    async def _serve(self):
        while not self._closed:
            self._wake.clear()
            try:self.recover_waits()
            except (ValueError,KeyError,OSError,sqlite3.Error):self._metrics['recovery_errors'] += 1
            now = asyncio.get_running_loop().time()
            batch = [room for room in sorted(self._notifications)
                     if self._notify_retry.get(room,(0,0))[1]<=now][:8]
            self._notifications.difference_update(batch)
            self._inflight.update(batch)
            await asyncio.gather(*(self._send(room_id) for room_id in batch))
            self._inflight.difference_update(batch)
            try:await asyncio.wait_for(self._wake.wait(),timeout=0.5)
            except TimeoutError:pass

    def start(self):
        if self._closed:raise RuntimeError('剧情协调器已经关闭')
        if self._task is None or self._task.done():
            if self._task is not None and not self._task.cancelled() and self._task.exception() is not None:
                self._metrics['pump_failures'] += 1
            self._task = asyncio.create_task(self._serve(),name='hexbound-story-notifications')

    async def close(self):
        if self._closed:return
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:await self._task
            except asyncio.CancelledError:pass
            except Exception:self._metrics['pump_failures'] += 1
