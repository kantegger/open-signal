"""Open Signal production Worker command."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
from pathlib import Path

from open_signal.jobs.queue import JobQueue
from open_signal.jobs.runner import DEFAULT_QUEUES, QueueWorker, ScheduledWorkerService
from open_signal.jobs.scheduler import JobScheduler
from open_signal.orchestration.handlers import ProductionHandlers
from open_signal.sources.registry import Registry
from sqlalchemy import create_engine

ROLE_QUEUES = {
    "all": DEFAULT_QUEUES,
    "source": ("source",),
    "analysis": ("analysis",),
    "agent": ("agent",),
    "publication": ("publication",),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Signal registry-driven production Worker"
    )
    parser.add_argument(
        "--mode",
        choices=("scheduled", "once", "poll"),
        default="scheduled",
        help="scheduled is scale-to-zero friendly; poll is explicitly always-on",
    )
    parser.add_argument(
        "--role",
        choices=tuple(ROLE_QUEUES),
        default="all",
        help="limit this process to one queue role",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="read recorded source fixtures instead of live public APIs",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        help="override the repository fixtures directory",
    )
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database_url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not database_url:
        raise SystemExit("OPEN_SIGNAL_DATABASE_URL is required")

    worker_id = os.environ.get(
        "OPEN_SIGNAL_WORKER_ID",
        f"{socket.gethostname()}-{os.getpid()}",
    )
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=240,
    )
    queue = JobQueue(engine=engine, worker_id=worker_id)
    queue_names = ROLE_QUEUES[args.role]
    handlers = ProductionHandlers(
        engine,
        offline=args.offline,
        fixture_root=args.fixture_root,
    ).registry()
    worker = QueueWorker(
        queue,
        handlers,
        queue_names=queue_names,
    )
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    registry = Registry.load()
    schedules = [
        schedule
        for schedule in registry.job_schedules()
        if schedule.queue_name in queue_names
    ]
    scheduler = JobScheduler(
        queue,
        schedules,
        version=registry.job_schedule_version,
    )
    service = ScheduledWorkerService(
        scheduler,
        worker,
        stop_event=stop_event,
    )
    try:
        if args.mode == "once":
            result = service.run_cycle()
            logging.getLogger(__name__).info(
                "one-shot cycle complete: processed=%s succeeded=%s retried=%s dead=%s",
                result.processed,
                result.succeeded,
                result.retried,
                result.dead,
            )
        elif args.mode == "poll":
            logging.getLogger(__name__).warning(
                "poll mode is always-on and prevents database scale-to-zero"
            )
            service.run_polling(args.poll_interval)
        else:
            service.run()
    finally:
        engine.dispose()
    return 0
