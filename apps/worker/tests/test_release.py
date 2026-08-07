"""Public Beta release check tests (OS-040). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migrations applied).
"""

import os
import uuid

import pytest

from scripts.release_check import run, summary


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def test_release_check_runs(engine) -> None:
    checks = run(engine)
    assert checks, "no checks produced"
    names = {c["check"] for c in checks}
    assert "migrations at head" in names
    assert "DEEPSEEK_API_KEY set" in names
    assert "OPEN_SIGNAL_OPS_TOKEN set" in names
    assert "table sources populated" in names
    assert "table audit_events populated" in names


def test_summary_counts(engine) -> None:
    checks = run(engine)
    failed, total = summary(checks)
    assert total == len(checks)
    assert failed <= total


def test_release_check_script_exits(engine) -> None:
    """The script returns exit code 0/1 and prints a summary line."""
    import subprocess
    import sys

    env = dict(os.environ)
    env["OPEN_SIGNAL_DATABASE_URL"] = os.environ["OPEN_SIGNAL_DATABASE_URL"]
    result = subprocess.run(
        [sys.executable, "scripts/release_check.py"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert "checks passed" in result.stdout
    assert result.returncode in (0, 1)
