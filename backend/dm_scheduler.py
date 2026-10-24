"""Player-priority logical capacity; slow cancelled calls never own that slot.

This internal scheduler does not enqueue plot work, authorize a player action,
publish scenes or send notifications. The application must bind those hooks.
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import sqlite3
import time

from . import story_generation


class DMScheduler:
    def __init__(self,service,provider,*,realtime_capacity=2,orphan_limit=2,clock=time.time):
        if type(realtime_capacity) is not int or not 1<=realtime_capacity<=4:
            raise ValueError('实时容量须为1至4')
        if type(orphan_limit) is not int or not 1<=orphan_limit<=4:
            raise ValueError('迟到调用上限须为1至4')
        self.service,self.provider,self.clock = service,provider,clock
        self._capacity,self._orphan_limit = realtime_capacity,orphan_limit
        self._slots = asyncio.Semaphore(realtime_capacity)
        self._loop = None
        self._wake = asyncio.Event()
        self._pump = None
        self._closed = False
        self._players = self._realtime = self._waiters = 0
        self._running = {}
        self._orphans = set()
        self._metrics = dict(dispatched=0,committed=0,failed=0,preemptions=0,
                             realtime_calls=0,realtime_wait_seconds=0.0,revocation_seconds=0.0,
                             dispatch_errors=0,pump_failures=0)

    def _check(self):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise RuntimeError('同一调度器须在一个服务事件循环中使用')
        if self._closed:
            raise RuntimeError('DM调度器已经关闭')

    def snapshot(self):
        """Internal aggregate diagnostics only; no prompts, actors or job IDs."""
        return dict(self._metrics,players=self._players,realtime_active=self._realtime,
                    realtime_waiting=self._waiters,background_active=len(self._running),
                    late_calls=len(self._orphans),closed=self._closed,
                    pump_running=self._pump is not None and not self._pump.done())

    def _preempt(self):
        for job_id,task in list(self._running.items()):
            # Revoke in a short durable transaction BEFORE cancellation or
            # releasing logical capacity. A provider may swallow cancellation.
            started = time.monotonic()
            self.service.cancel(job_id)
            self._metrics['revocation_seconds'] += time.monotonic()-started
            self._running.pop(job_id)
            if not task.done():
                self._orphans.add(task)
                task.cancel()
                self._metrics['preemptions'] += 1

    @contextmanager
    def player_activity(self):
        """Rule commands preempt background work without waiting for LLM slots."""
        self._check()
        self._players += 1
        try:
            self._preempt()
            yield
        finally:
            self._players -= 1
            self._wake.set()

    @asynccontextmanager
    async def realtime(self):
        """Reserve only realtime model capacity; background has no such permit."""
        with self.player_activity():
            started = time.monotonic()
            self._waiters += 1
            try:
                await self._slots.acquire()
            finally:
                self._waiters -= 1
            self._realtime += 1
            try:
                self._check()
                self._metrics['realtime_calls'] += 1
                self._metrics['realtime_wait_seconds'] += time.monotonic()-started
                yield
            finally:
                self._realtime -= 1
                self._slots.release()

    def _finished(self,job_id,task):
        if self._running.get(job_id) is task:
            self._running.pop(job_id)
        self._orphans.discard(task)
        if not task.cancelled():
            # Consume exceptions without logging provider bodies or prompts.
            error = task.exception()
            if error is None and task.result().get('status')=='committed':
                self._metrics['committed'] += 1
            else:
                self._metrics['failed'] += 1
        self._wake.set()

    async def dispatch(self):
        """At most one shallow worker; foreground admission never awaits it."""
        self._check()
        if self._players or self._running or len(self._orphans)>=self._orphan_limit:
            return []
        if not self.provider.configured:
            return []
        self.service.recover(now=self.clock())
        ready = self.service.ready(limit=16,now=self.clock())
        if not ready:
            return []
        job_id = ready[0]['id']
        task = asyncio.create_task(story_generation.run(self.service,self.provider,job_id,clock=self.clock),
                                   name='hexbound-story-worker')
        self._running[job_id] = task
        task.add_done_callback(lambda completed:self._finished(job_id,completed))
        self._metrics['dispatched'] += 1
        return [job_id]

    def start(self):
        self._check()
        if self._pump is None or self._pump.done():
            if self._pump is not None and not self._pump.cancelled() and self._pump.exception() is not None:
                self._metrics['pump_failures'] += 1
            self._pump = asyncio.create_task(self._serve(),name='hexbound-story-dispatch')

    def wake(self):
        self._check()
        self._wake.set()

    async def _serve(self):
        failures = 0
        while not self._closed:
            self._wake.clear()
            try:
                await self.dispatch()
                failures = 0
            except (sqlite3.Error,OSError,ValueError):
                self._metrics['dispatch_errors'] += 1
                failures += 1
                # Foreground requests keep their own capacity. A wake storm
                # cannot turn a failing DB into an unbounded hot retry loop.
                await asyncio.sleep(min(8,0.5*2**min(failures-1,4)))
                continue
            try:
                await asyncio.wait_for(self._wake.wait(),timeout=0.5)
            except TimeoutError:
                pass

    async def close(self):
        """Durably revoke work; do not await an uncooperative remote provider."""
        if self._closed:
            return
        self._check()
        self._preempt()
        self._closed = True
        self._wake.set()
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except asyncio.CancelledError:
                pass
            except Exception:
                # A completed unexpected pump failure is visible in health
                # counters, but must not prevent revocation/clean shutdown.
                self._metrics['pump_failures'] += 1
