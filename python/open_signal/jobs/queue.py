"""PostgreSQL-backed job queue (spec §120–§124, OS-004).

Core operations: enqueue (idempotent), claim with ``FOR UPDATE SKIP LOCKED``,
complete, fail (retry or dead-letter), heartbeat.

The ``jobs`` table is defined in ``open_signal.db.models`` (appendix C.12).
Stale ``running`` jobs (locked_at older than ``STALE_LOCK_TIMEOUT``) are
treated as crashed workers and re-claimed.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

#: Statuses per spec §120.
QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
DEAD = "dead"

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_PRIORITY = 100
STALE_LOCK_TIMEOUT = timedelta(minutes=5)
RETRY_BACKOFF = timedelta(seconds=30)


class JobError(Exception):
    """Raised by a job handler to mark the job as failed."""


class JobNotFound(Exception):
    """Raised when operating on a job that does not exist."""


@dataclass
class ClaimedJob:
    """A job handed to a worker for execution."""

    id: str
    job_type: str
    queue_name: str
    payload: Mapping[str, Any]
    attempts: int
    maximum_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "queue_name": self.queue_name,
            "payload": self.payload,
            "attempts": self.attempts,
            "maximum_attempts": self.maximum_attempts,
        }


_CLAIM_SQL = text(
    """
    WITH claimed AS (
      SELECT id
      FROM jobs
      WHERE queue_name = :queue_name
        AND status IN ('queued', 'running')
        AND run_after <= now()
        AND (
          status = 'queued'
          OR locked_at IS NULL
          OR locked_at < now() - :stale_interval
        )
      ORDER BY priority ASC, created_at ASC
      LIMIT 1
      FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs
    SET status = 'running',
        locked_by = :worker_id,
        locked_at = now(),
        attempts = attempts + 1
    WHERE id IN (SELECT id FROM claimed)
    RETURNING id, job_type, queue_name, payload, attempts, maximum_attempts
    """
)


class JobQueue:
    """Thin wrapper around the PostgreSQL-backed queue."""

    def __init__(
        self,
        engine: Engine | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.engine = engine or self._default_engine()
        self.worker_id = worker_id or os.environ.get(
            "OPEN_SIGNAL_WORKER_ID", f"worker-{os.getpid()}"
        )

    @staticmethod
    def _default_engine() -> Engine:
        url = os.environ["OPEN_SIGNAL_DATABASE_URL"]
        return create_engine(url)

    # ------------------------------------------------------------------ enqueue
    def enqueue(
        self,
        job_type: str,
        queue_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str,
        priority: int = DEFAULT_PRIORITY,
        run_after: datetime | None = None,
        maximum_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> str:
        """Insert a job. Idempotent: duplicate ``idempotency_key`` is a no-op.

        Returns the job id (existing one if the key already exists).
        """
        run_after = run_after or datetime.now(timezone.utc)
        stmt = text(
            """
            INSERT INTO jobs
              (job_type, queue_name, payload, priority, run_after, status,
               maximum_attempts, idempotency_key)
            VALUES
              (:job_type, :queue_name, :payload, :priority, :run_after, 'queued',
               :maximum_attempts, :idempotency_key)
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        )
        with self.engine.begin() as conn:
            conn.execute(
                stmt,
                {
                    "job_type": job_type,
                    "queue_name": queue_name,
                    "payload": json.dumps(payload or {}),
                    "priority": priority,
                    "run_after": run_after,
                    "maximum_attempts": maximum_attempts,
                    "idempotency_key": idempotency_key,
                },
            )
            row = conn.execute(
                text("SELECT id FROM jobs WHERE idempotency_key = :k"),
                {"k": idempotency_key},
            ).fetchone()
        return str(row[0])

    # -------------------------------------------------------------------- claim
    def claim(self, queue_name: str, stale_interval: timedelta | None = None) -> ClaimedJob | None:
        """Claim one job with ``FOR UPDATE SKIP LOCKED``; None if queue empty."""
        stale = stale_interval or STALE_LOCK_TIMEOUT
        with self.engine.begin() as conn:
            row = conn.execute(
                _CLAIM_SQL,
                {
                    "queue_name": queue_name,
                    "stale_interval": stale,
                    "worker_id": self.worker_id,
                },
            ).fetchone()
        if row is None:
            return None
        return ClaimedJob(
            id=str(row[0]),
            job_type=row[1],
            queue_name=row[2],
            payload=row[3],
            attempts=row[4],
            maximum_attempts=row[5],
        )

    def claim_many(self, queue_name: str, limit: int, stale_interval: timedelta | None = None) -> list[ClaimedJob]:
        jobs: list[ClaimedJob] = []
        for _ in range(limit):
            job = self.claim(queue_name, stale_interval)
            if job is None:
                break
            jobs.append(job)
        return jobs

    # ---------------------------------------------------------------- complete
    def complete(self, job_id: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE jobs SET status = 'succeeded', completed_at = now(), "
                    "locked_by = NULL, locked_at = NULL "
                    "WHERE id = :id AND locked_by = :worker"
                ),
                {"id": job_id, "worker": self.worker_id},
            )
            if result.rowcount == 0:
                raise JobNotFound(f"job {job_id} not owned by {self.worker_id}")

    # ---------------------------------------------------------------------- fail
    def fail(self, job_id: str, error: Exception | None = None) -> bool:
        """Mark a job failed; dead-letter when maximum_attempts reached.

        Returns True if the job went to ``dead``, False if it is retried.
        """
        error_text = f"{type(error).__name__}: {error}" if error else "unknown error"
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT attempts, maximum_attempts, payload "
                    "FROM jobs WHERE id = :id AND locked_by = :worker"
                ),
                {"id": job_id, "worker": self.worker_id},
            ).fetchone()
            if row is None:
                raise JobNotFound(f"job {job_id} not owned by {self.worker_id}")

            attempts, maximum_attempts, payload = row
            dead = attempts >= maximum_attempts
            if dead:
                conn.execute(
                    text(
                        "UPDATE jobs SET status = 'dead', locked_by = NULL, "
                        "locked_at = NULL, completed_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": job_id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE jobs SET status = 'queued', locked_by = NULL, "
                        "locked_at = NULL, run_after = now() + :backoff "
                        "WHERE id = :id"
                    ),
                    {"id": job_id, "backoff": RETRY_BACKOFF},
                )
            # Record the last error on the payload for observability.
            updated_payload = dict(payload or {})
            updated_payload["_last_error"] = error_text
            updated_payload["_failed_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text("UPDATE jobs SET payload = :payload WHERE id = :id"),
                {"payload": json.dumps(updated_payload), "id": job_id},
            )
        return dead

    # ------------------------------------------------------------------ heartbeat
    def heartbeat(self, job_id: str) -> None:
        """Renew the lock so the job is not reclaimed as stale."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE jobs SET locked_at = now() "
                    "WHERE id = :id AND locked_by = :worker AND status = 'running'"
                ),
                {"id": job_id, "worker": self.worker_id},
            )

    # ------------------------------------------------------------------ inspect
    def stats(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, count(*) FROM jobs GROUP BY status"
                )
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, job_type, queue_name, payload, attempts, "
                    "maximum_attempts, created_at, completed_at "
                    "FROM jobs WHERE status = 'dead' "
                    "ORDER BY completed_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "id": str(r[0]),
                "job_type": r[1],
                "queue_name": r[2],
                "payload": r[3],
                "attempts": r[4],
                "maximum_attempts": r[5],
                "created_at": r[6],
                "completed_at": r[7],
            }
            for r in rows
        ]


Handler = Callable[[ClaimedJob], None]


def run_worker_poll(
    queue: JobQueue,
    handlers: Mapping[str, Handler],
    *,
    poll_interval: float = 1.0,
    max_jobs_per_poll: int = 5,
    stop_event: Any = None,
) -> None:
    """Blocking worker loop (polling)."""
    import threading

    def _guard(stop_event: Any) -> None:
        if stop_event is None:
            return
        while not stop_event.is_set():
            stop_event.wait(0.1)

    _t = threading.Thread(target=_guard, daemon=True)
    _t.start()

    while stop_event is None or not stop_event.is_set():
        claimed = queue.claim_many("default", max_jobs_per_poll)
        for job in claimed:
            handler = handlers.get(job.job_type)
            if handler is None:
                queue.fail(job.id, JobError(f"no handler for {job.job_type}"))
                continue
            try:
                handler(job)
                queue.complete(job.id)
            except Exception as exc:  # noqa: BLE001
                queue.fail(job.id, exc)
        if not claimed:
            time.sleep(poll_interval)
