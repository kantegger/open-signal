"""Job execution modes with per-Job failure isolation (OS-049).

``scheduled`` drains work and then sleeps without touching PostgreSQL until a
known schedule/retry boundary.  ``poll`` is intentionally a separate opt-in
mode because empty-queue polling prevents managed PostgreSQL scale-to-zero.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from open_signal.jobs.queue import RETRY_BACKOFF, ClaimedJob, JobError, JobQueue
from open_signal.jobs.scheduler import JobScheduler

logger = logging.getLogger(__name__)

DEFAULT_QUEUES = ("source", "analysis", "agent", "publication")


@dataclass
class DrainResult:
    processed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead: int = 0
    unhandled: int = 0

    @property
    def retry_pending(self) -> bool:
        return self.retried > 0


class QueueWorker:
    def __init__(
        self,
        queue: JobQueue,
        handlers: Mapping[str, Any],
        *,
        queue_names: tuple[str, ...] = DEFAULT_QUEUES,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self.queue = queue
        self.handlers = handlers
        self.queue_names = queue_names
        self.heartbeat_interval = heartbeat_interval

    def execute(self, job: ClaimedJob, result: DrainResult) -> None:
        result.processed += 1
        handler = self.handlers.get(job.job_type)
        if handler is None:
            result.unhandled += 1
            dead = self.queue.fail(
                job.id,
                JobError(f"no handler registered for {job.job_type}"),
            )
            result.dead += int(dead)
            result.retried += int(not dead)
            return

        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job.id, heartbeat_stop),
            name=f"job-heartbeat-{job.id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            output = handler(job)
            self.queue.complete(job.id)
            result.succeeded += 1
            logger.info(
                "job succeeded",
                extra={
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "queue_name": job.queue_name,
                    "job_output": output,
                },
            )
        except Exception as exc:
            dead = self.queue.fail(job.id, exc)
            result.dead += int(dead)
            result.retried += int(not dead)
            logger.exception(
                "job failed",
                extra={
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "queue_name": job.queue_name,
                    "dead": dead,
                },
            )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_interval + 1.0))

    def _heartbeat(self, job_id: str, stop: threading.Event) -> None:
        if self.heartbeat_interval <= 0:
            return
        while not stop.wait(self.heartbeat_interval):
            try:
                self.queue.heartbeat(job_id)
            except Exception:
                logger.exception("job heartbeat failed", extra={"job_id": job_id})

    def drain(self, *, maximum_jobs: int = 1000) -> DrainResult:
        """Drain each configured stage completely before advancing.

        Queue order is the batch dependency order: source data must be present
        before analysis, analysis before Agents, and all editorial work before
        publication. A later-stage failure remains isolated to its own Job.
        """
        result = DrainResult()
        for queue_name in self.queue_names:
            while result.processed < maximum_jobs:
                job = self.queue.claim(queue_name)
                if job is None:
                    break
                self.execute(job, result)
            if result.processed >= maximum_jobs:
                break
        return result


class ScheduledWorkerService:
    """Coordinate Scheduler and Worker without idle database polling."""

    def __init__(
        self,
        scheduler: JobScheduler,
        worker: QueueWorker,
        *,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.worker = worker
        self.stop_event = stop_event or threading.Event()

    def run_cycle(self, now: datetime | None = None) -> DrainResult:
        now = now or datetime.now(timezone.utc)
        self.scheduler.enqueue_due(now)
        return self.worker.drain()

    def run(self) -> None:
        while not self.stop_event.is_set():
            started_at = datetime.now(timezone.utc)
            result = self.run_cycle(started_at)
            next_due = self.scheduler.next_due_at(datetime.now(timezone.utc))
            if result.retry_pending:
                retry_due = datetime.now(timezone.utc) + RETRY_BACKOFF
                next_due = min(next_due, retry_due)
            delay = max(
                0.0,
                (next_due - datetime.now(timezone.utc)).total_seconds(),
            )
            logger.info(
                "worker sleeping without database polling",
                extra={
                    "sleep_seconds": delay,
                    "next_due_at": next_due.isoformat(),
                    "processed": result.processed,
                },
            )
            self.stop_event.wait(delay)

    def run_polling(self, poll_interval: float = 1.0) -> None:
        """Always-on mode; callers explicitly accept loss of scale-to-zero."""
        while not self.stop_event.is_set():
            result = self.worker.drain()
            if result.processed == 0:
                self.stop_event.wait(poll_interval)


def retry_wake_at(now: datetime | None = None) -> datetime:
    """Small public helper used by deterministic runner tests."""
    return (now or datetime.now(timezone.utc)) + timedelta(
        seconds=RETRY_BACKOFF.total_seconds()
    )
