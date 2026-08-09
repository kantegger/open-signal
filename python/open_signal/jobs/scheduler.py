"""Deterministic, registry-driven Job scheduler (spec §210.3, OS-049).

The scheduler has no task handlers.  It only maps the current wall-clock
bucket to an idempotent PostgreSQL Job.  Restarts therefore replay safely and
never require a mutable in-process "last run" cursor.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from open_signal.jobs.queue import JobQueue
from open_signal.sources.registry import JobScheduleDefinition, Registry


@dataclass(frozen=True)
class ScheduledJob:
    schedule_id: str
    job_id: str
    bucket_started_at: datetime
    idempotency_key: str


def schedule_bucket_start(
    schedule: JobScheduleDefinition, now: datetime
) -> datetime:
    """Return the occurrence bucket containing ``now``."""
    if now.tzinfo is None:
        raise ValueError("scheduler timestamps must be timezone-aware")
    timestamp = int(now.timestamp())
    shifted = timestamp - schedule.phase_offset_seconds
    bucket = (shifted // schedule.cadence_seconds) * schedule.cadence_seconds
    return datetime.fromtimestamp(
        bucket + schedule.phase_offset_seconds,
        tz=timezone.utc,
    )


def next_schedule_boundary(
    schedule: JobScheduleDefinition, now: datetime
) -> datetime:
    """Return the first schedule boundary strictly after ``now``."""
    current = schedule_bucket_start(schedule, now)
    return datetime.fromtimestamp(
        int(current.timestamp()) + schedule.cadence_seconds,
        tz=timezone.utc,
    )


class JobScheduler:
    def __init__(
        self,
        queue: JobQueue,
        schedules: Iterable[JobScheduleDefinition] | None = None,
        *,
        version: str | None = None,
    ) -> None:
        if schedules is None:
            registry = Registry.load()
            schedules = registry.job_schedules()
            version = version or registry.job_schedule_version
        self.queue = queue
        self.schedules = tuple(schedule for schedule in schedules if schedule.enabled)
        self.version = version or "unversioned"
        if not self.schedules:
            raise ValueError("at least one enabled Job schedule is required")

    def enqueue_due(self, now: datetime | None = None) -> list[ScheduledJob]:
        """Enqueue the current occurrence for every enabled schedule."""
        now = now or datetime.now(timezone.utc)
        enqueued: list[ScheduledJob] = []
        for schedule in self.schedules:
            bucket = schedule_bucket_start(schedule, now)
            bucket_key = int(bucket.timestamp())
            revision_key = f":{schedule.revision}" if schedule.revision else ""
            idempotency_key = (
                f"schedule:{self.version}:{schedule.id}{revision_key}:{bucket_key}"
            )
            payload: dict[str, Any] = {
                **schedule.payload,
                "_schedule_id": schedule.id,
                "_schedule_version": self.version,
                "_scheduled_for": bucket.isoformat(),
            }
            if schedule.revision:
                payload["_schedule_revision"] = schedule.revision
            job_id = self.queue.enqueue(
                schedule.job_type,
                schedule.queue_name,
                payload,
                idempotency_key=idempotency_key,
                priority=schedule.priority,
                run_after=bucket,
                maximum_attempts=schedule.maximum_attempts,
            )
            enqueued.append(
                ScheduledJob(
                    schedule_id=schedule.id,
                    job_id=job_id,
                    bucket_started_at=bucket,
                    idempotency_key=idempotency_key,
                )
            )
        return enqueued

    def next_due_at(self, now: datetime | None = None) -> datetime:
        """Earliest future boundary, used for database-silent sleeping."""
        now = now or datetime.now(timezone.utc)
        return min(next_schedule_boundary(schedule, now) for schedule in self.schedules)
