"""Job queue — 512MB par ek waqt me ek hi bhaari kaam.

Kyun: do RMBG inference saath chalein to RAM double, OOM.
Queue se user ko position dikhti hai aur crash nahi hota.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Any

from . import config as C
from . import engine

log = logging.getLogger("queue")


@dataclass
class Job:
    uid: int
    kind: str
    fn: Callable[[], Any]
    created: float = field(default_factory=time.time)
    fut: asyncio.Future = None


class JobQueue:
    def __init__(self, workers: int = 1):
        self.q: asyncio.Queue[Job] = asyncio.Queue(maxsize=C.QUEUE_MAX)
        self.workers = workers
        self._tasks = []
        self.active = 0
        self.done = 0
        self.failed = 0
        self._t0 = time.time()

    async def start(self):
        for i in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(i)))
        self._tasks.append(asyncio.create_task(self._janitor()))
        log.info("queue started (%d worker)", self.workers)

    async def stop(self):
        for t in self._tasks:
            t.cancel()

    @property
    def waiting(self) -> int:
        return self.q.qsize()

    async def submit(self, uid: int, kind: str, fn) -> Any:
        """Blocking submit — result ya exception wapas."""
        loop = asyncio.get_running_loop()
        job = Job(uid=uid, kind=kind, fn=fn, fut=loop.create_future())
        try:
            self.q.put_nowait(job)
        except asyncio.QueueFull:
            raise RuntimeError("Server abhi bahut busy hai, thodi der baad try karo")
        return await asyncio.wait_for(job.fut, timeout=C.JOB_TIMEOUT + 30)

    async def _worker(self, n: int):
        loop = asyncio.get_running_loop()
        while True:
            job = await self.q.get()
            self.active += 1
            try:
                # CPU-bound kaam thread me — event loop block na ho
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, job.fn), timeout=C.JOB_TIMEOUT
                )
                if not job.fut.done():
                    job.fut.set_result(res)
                self.done += 1
            except asyncio.TimeoutError:
                self.failed += 1
                if not job.fut.done():
                    job.fut.set_exception(
                        RuntimeError("Bahut time lag gaya — chhoti image try karo")
                    )
            except Exception as e:
                self.failed += 1
                log.exception("job fail")
                if not job.fut.done():
                    job.fut.set_exception(e)
            finally:
                self.active -= 1
                self.q.task_done()

    async def _janitor(self):
        """Idle par model unload + RAM report."""
        while True:
            await asyncio.sleep(30)
            if self.active == 0 and self.q.empty():
                engine.maybe_unload()
            r = engine.ram_mb()
            if r > C.MAX_RAM_MB * 0.88:
                log.warning("RAM high: %.0f MB — unloading", r)
                engine._last_used = 0
                engine.maybe_unload()

    def stats(self) -> dict:
        up = time.time() - self._t0
        return {
            "waiting": self.waiting,
            "active": self.active,
            "done": self.done,
            "failed": self.failed,
            "ram_mb": round(engine.ram_mb()),
            "uptime_min": round(up / 60, 1),
        }


queue = JobQueue(workers=C.MAX_CONCURRENT_JOBS)
