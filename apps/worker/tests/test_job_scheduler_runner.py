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
from open_signal.research.candidates import CANDIDATE_VERSION
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
        "cadence_seconds": 3600,
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
    scheduler = JobScheduler(queue, [schedule], version="2.0.0")
    now = datetime(2026, 8, 8, 12, 7, tzinfo=UTC)

    first = scheduler.enqueue_due(now)
    second = scheduler.enqueue_due(now)

    assert schedule_bucket_start(schedule, now) == datetime(
        2026, 8, 8, 12, 0, tzinfo=UTC
    )
    assert first[0].idempotency_key == second[0].idempotency_key
    assert queue.enqueued[0]["payload"]["_scheduled_for"].endswith("12:00:00+00:00")
    assert scheduler.next_due_at(now) == datetime(2026, 8, 8, 13, 0, tzinfo=UTC)


def test_schedule_revision_replays_only_the_changed_contract() -> None:
    queue = FakeQueue()
    schedule = _schedule(
        revision="os-021.2",
        payload={"candidate_version": "os-021.2"},
    )
    scheduler = JobScheduler(queue, [schedule], version="2.0.0")
    now = datetime(2026, 8, 8, 12, 7, tzinfo=UTC)

    scheduled = scheduler.enqueue_due(now)[0]

    assert scheduled.idempotency_key == (
        "schedule:2.0.0:expectations-source:os-021.2:1786190400"
    )
    assert queue.enqueued[0]["payload"]["_schedule_revision"] == "os-021.2"
    assert queue.enqueued[0]["payload"]["candidate_version"] == "os-021.2"


def test_twelve_hour_boundary_leaves_neon_quiet_window() -> None:
    registry = Registry.load()
    schedules = registry.job_schedules()
    # Internal offsets must not cause immediate retry polling. Actual one-shot
    # launches are limited to twice daily by the outer Cloudflare Cron.
    now = datetime(2026, 8, 8, 12, 0, 1, tzinfo=UTC)
    next_due = min(next_schedule_boundary(schedule, now) for schedule in schedules)
    assert (next_due - now).total_seconds() > 5 * 60


def test_reference_cadence_has_two_fast_buckets_and_one_research_bucket_daily() -> None:
    scheduler = JobScheduler(FakeQueue())
    occurrences = defaultdict(set)
    for hour in (0, 12):
        for job in scheduler.enqueue_due(datetime(2026, 9, 4, hour, tzinfo=UTC)):
            occurrences[job.schedule_id].add(job.idempotency_key)
    assert len(occurrences["expectations-source-refresh"]) == 2
    assert len(occurrences["research-clinicaltrials-refresh"]) == 1
    assert len(occurrences["research-openalex-refresh"]) == 1
    # A delayed launch schedules one current occurrence, not missed batches.
    delayed = scheduler.enqueue_due(datetime(2026, 9, 6, 12, tzinfo=UTC))
    assert len(delayed) == len(scheduler.schedules)


def test_research_schedule_revision_matches_candidate_contract() -> None:
    schedule = next(
        item
        for item in Registry.load().job_schedules()
        if item.id == "research-candidate-refresh"
    )

    assert schedule.revision == CANDIDATE_VERSION
    assert schedule.payload["candidate_version"] == CANDIDATE_VERSION


def test_retention_schedules_report_then_run_bounded_purge() -> None:
    report = next(
        item
        for item in Registry.load().job_schedules()
        if item.id == "raw-retention-report"
    )
    purge = next(
        item
        for item in Registry.load().job_schedules()
        if item.id == "raw-retention-purge"
    )

    assert report.job_type == "retention.report_raw"
    assert report.cadence_seconds == 86400
    assert report.payload == {
        "mode": "report_only",
        "policy_version": "2.0.0",
    }
    assert purge.job_type == "retention.purge_raw"
    assert purge.cadence_seconds == 43200
    assert purge.phase_offset_seconds > report.phase_offset_seconds
    assert purge.payload == {
        "mode": "active",
        "policy_version": "2.0.0",
    }


def test_worker_drains_dependency_stages_in_order() -> None:
    queue = FakeQueue()
    queue.pending["source"] = [
        ClaimedJob("source-1", "stage.source", "source", {}, 1, 3),
        ClaimedJob("source-2", "stage.source", "source", {}, 1, 3),
    ]
    queue.pending["analysis"] = [
        ClaimedJob("analysis-1", "stage.analysis", "analysis", {}, 1, 3)
    ]
    queue.pending["publication"] = [
        ClaimedJob("publish-1", "stage.publish", "publication", {}, 1, 3)
    ]
    handled: list[str] = []

    def handle(job):
        handled.append(job.id)

    worker = QueueWorker(
        queue,
        {
            "stage.source": handle,
            "stage.analysis": handle,
            "stage.publish": handle,
        },
        heartbeat_interval=0,
    )

    result = worker.drain()

    assert result.succeeded == 4
    assert handled == ["source-1", "source-2", "analysis-1", "publish-1"]


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
