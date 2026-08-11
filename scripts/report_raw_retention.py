"""Print the raw payload retention plan without mutating PostgreSQL or R2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from open_signal.retention import RawRetentionPlanner


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only report for raw payload cold-storage eligibility"
    )
    parser.add_argument(
        "--as-of",
        help="timezone-aware ISO-8601 timestamp; defaults to now",
    )
    args = parser.parse_args()
    database_url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not database_url:
        raise SystemExit("OPEN_SIGNAL_DATABASE_URL is required")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        report = RawRetentionPlanner(engine).plan(as_of=as_of)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
