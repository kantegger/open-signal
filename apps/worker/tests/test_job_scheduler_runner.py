"""Scale-to-zero Scheduler and per-Job failure-boundary tests (OS-049)."""

from collections import defaultdict
from datetime import UTC, datetime

from open_signal.jobs.queue import ClaimedJob
from open_signal.jobs.runner import QueueWorker
from open_signal.jobs.scheduler import (
    JobScheduler,
    next_schedule_boundary,
    schedule_bucket_start,
)
from open_signal.sources.registry import JobScheduleDefinition, Registry


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self.pending: dict[str, list[ClaimedJob]] = defaultdict(list)
        self.completed: list[str] = []
        self.failed: list[str] = []

    def enqueue(self, job_type, queue_name, payload, **kwargs):
        record = {
            "job_type": job_type,
            "queue_name": queue_name,
            "payload": payload,
            **kwargs,
        }
        self.enqueued.append(record)
        return f"job-{len(self.enqueued)}"

    def claim(self, queue_name):
        return self.pending[queue_name].pop(0) if self.pending[queue_name] else None

    def complete(self, job_id):
        self.completed.append(job_id)

    def fail(self, job_id, error):
        del error
        self.failed.append(job_id)
        return False

    def heartbeat(self, job_id):
        raise AssertionError(f"unexpected heartbeat for short Job {job_id}")


def _schedule(**overrides) -> JobScheduleDefinition:
    values = {
        "id": "expectations-source",
        "job_type": "source.discover",
        "queue_name": "source",
        "cadence_seconds": 900,
        "phase_offset_seconds": 0,
        "priority": 10,
        "maximum_attempts": 3,
        "payload": {"section_id": "expectations-moved"},
    }
    values.update(overrides)
    return JobScheduleDefinition.model_validate(values)


def test_schedule_bucket_and_key_are_deterministic() -> None:
    queue = FakeQueue()
    schedule = _schedule()
    scheduler = JobScheduler(queue, [schedule], version="1.0.0")
    now = datetime(2026, 8, 8, 12, 7, tzinfo=UTC)

    first = scheduler.enqueue_due(now)
    second = scheduler.enqueue_due(now)

    assert schedule_bucket_start(schedule, now) == datetime(
        2026, 8, 8, 12, 0, tzinfo=UTC
    )
    assert first[0].idempotency_key == second[0].idempotency_key
    assert queue.enqueued[0]["payload"]["_scheduled_for"].endswith("12:00:00+00:00")
    assert scheduler.next_due_at(now) == datetime(2026, 8, 8, 12, 15, tzinfo=UTC)


def test_phase_boundary_leaves_neon_quiet_window() -> None:
    registry = Registry.load()
    schedules = registry.job_schedules()
    # Immediately after the :16 observation phase that follows the :15 source
    # refresh, the next launch boundary is :30: over thirteen quiet minutes.
    now = datetime(2026, 8, 8, 12, 16, 1, tzinfo=UTC)
    next_due = min(next_schedule_boundary(schedule, now) for schedule in schedules)
    assert (next_due - now).total_seconds() > 5 * 60


def test_worker_failure_does_not_block_next_job() -> None:
    queue = FakeQueue()
    queue.pending["analysis"] = [
        ClaimedJob("failed", "section.fail", "analysis", {}, 1, 3),
        ClaimedJob("healthy", "section.ok", "analysis", {}, 1, 3),
    ]
    handled: list[str] = []

    def fail(job):
        del job
        raise RuntimeError("section-local failure")

    def succeed(job):
        handled.append(job.id)

    worker = QueueWorker(
        queue,
        {"section.fail": fail, "section.ok": succeed},
        queue_names=("analysis",),
        heartbeat_interval=0,
    )
    result = worker.drain()

    assert result.processed == 2
    assert result.retried == 1
    assert result.succeeded == 1
    assert queue.failed == ["failed"]
    assert queue.completed == ["healthy"]
    assert handled == ["healthy"]
