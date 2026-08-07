"""Job queue tests (OS-004). Requires a real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from open_signal.jobs.queue import (
    DEAD,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    JobNotFound,
    JobQueue,
)
from sqlalchemy import text


@pytest.fixture()
def queue() -> JobQueue:
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    os.environ.setdefault("OPEN_SIGNAL_DATABASE_URL", url)
    return JobQueue(worker_id=f"test-{uuid.uuid4().hex[:8]}")


@pytest.fixture()
def job_ids(queue: JobQueue) -> list[str]:
    ids: list[str] = []
    yield ids
    with queue.engine.begin() as conn:
        if ids:
            conn.execute(
                text("DELETE FROM jobs WHERE id = ANY(:ids)"),
                {"ids": [uuid.UUID(i) for i in ids]},
            )
        conn.execute(
            text("DELETE FROM jobs WHERE idempotency_key LIKE 'osq-test-%'")
        )


def enqueue(queue: JobQueue, job_ids: list[str], key: str, **kw) -> str:
    jid = queue.enqueue(
        "osq-test.task",
        "default",
        {"n": 1},
        idempotency_key=f"osq-test-{key}",
        **kw,
    )
    job_ids.append(jid)
    return jid


# ---------------------------------------------------------------- tests


def test_enqueue_is_idempotent(queue: JobQueue, job_ids: list[str]) -> None:
    jid1 = enqueue(queue, job_ids, "idem")
    jid2 = enqueue(queue, job_ids, "idem")
    assert jid1 == jid2
    with queue.engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM jobs WHERE idempotency_key = :k"),
            {"k": "osq-test-idem"},
        ).scalar_one()
    assert count == 1


def test_claim_returns_single_job_and_locks(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "claim1")
    job = queue.claim("default")
    assert job is not None
    assert job.id == jid
    assert job.job_type == "osq-test.task"
    with queue.engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, locked_by FROM jobs WHERE id = :id"),
            {"id": jid},
        ).fetchone()
    assert row[0] == RUNNING
    assert row[1] == queue.worker_id
    assert queue.claim("default") is None  # already running


def test_two_workers_do_not_claim_the_same_job(
    queue: JobQueue, job_ids: list[str]
) -> None:
    n = 6
    for i in range(n):
        enqueue(queue, job_ids, f"concurrent-{i}")

    worker_a = JobQueue(worker_id="worker-a")
    worker_b = JobQueue(worker_id="worker-b")

    def drain(w: JobQueue, limit: int = 10) -> list[str]:
        got: list[str] = []
        while len(got) < limit:
            job = w.claim("default")
            if job is None:
                break
            got.append(job.id)
        return got

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(drain, worker_a), pool.submit(drain, worker_b)]]

    all_claimed = results[0] + results[1]
    assert len(all_claimed) == n, f"expected {n} jobs, got {len(all_claimed)}"
    assert len(set(all_claimed)) == n, "a job was claimed by two workers"


def test_failure_requeues_and_increments_attempts(
    queue: JobQueue, job_ids: list[str]
) -> None:
    jid = enqueue(queue, job_ids, "retry", maximum_attempts=3)
    queue.claim("default")
    dead = queue.fail(jid, ValueError("boom"))
    assert dead is False
    with queue.engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, attempts, run_after, payload FROM jobs WHERE id = :id"),
            {"id": jid},
        ).fetchone()
    assert row[0] == QUEUED
    assert row[1] == 1  # incremented on claim
    assert "_last_error" in row[3]
    assert row[2] is not None  # backoff applied


def test_max_attempts_moves_to_dead(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "dead", maximum_attempts=2)
    for attempt in range(2):
        # 模拟退避到期（fail 会把 run_after 推迟 30s）
        with queue.engine.begin() as conn:
            conn.execute(
                text("UPDATE jobs SET run_after = now() - interval '1 minute' WHERE id = :id"),
                {"id": jid},
            )
        queue.claim("default")
        queue.fail(jid, RuntimeError("nope"))
    with queue.engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, attempts FROM jobs WHERE id = :id"), {"id": jid}
        ).fetchone()
    assert row[0] == DEAD
    assert row[1] == 2
    dead = queue.dead_letters()
    assert any(d["id"] == jid for d in dead)


def test_complete_succeeds(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "complete")
    queue.claim("default")
    queue.complete(jid)
    with queue.engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, completed_at FROM jobs WHERE id = :id"), {"id": jid}
        ).fetchone()
    assert row[0] == SUCCEEDED
    assert row[1] is not None


def test_complete_by_wrong_worker_raises(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "owner")
    queue.claim("default")  # locked by queue.worker_id
    other = JobQueue(worker_id="other-worker")
    with pytest.raises(JobNotFound):
        other.complete(jid)


def test_heartbeat_renews_lock(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "hb")
    queue.claim("default")
    queue.heartbeat(jid)
    with queue.engine.connect() as conn:
        locked_at = conn.execute(
            text("SELECT locked_at FROM jobs WHERE id = :id"), {"id": jid}
        ).fetchone()[0]
    assert locked_at is not None


def test_stale_running_job_is_reclaimed(queue: JobQueue, job_ids: list[str]) -> None:
    jid = enqueue(queue, job_ids, "stale")
    queue.claim("default")
    with queue.engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET locked_at = now() - interval '10 minutes' WHERE id = :id"),
            {"id": jid},
        )
    job = queue.claim("default", stale_interval=timedelta(minutes=5))
    assert job is not None
    assert job.id == jid
    assert job.attempts == 2  # re-claimed as a new attempt
