"""Public Beta release check tests (OS-040). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migrations applied).
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import pytest
from scripts.release_check import ops_token_meets_minimum_length, run, summary


def test_ops_token_minimum_length_check() -> None:
    assert ops_token_meets_minimum_length("a" * 32) is True
    assert ops_token_meets_minimum_length("a" * 31) is False
    assert ops_token_meets_minimum_length("") is False
    assert ops_token_meets_minimum_length(None) is False


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
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
    env = dict(os.environ)
    env["OPEN_SIGNAL_TEST_DATABASE_URL"] = os.environ["OPEN_SIGNAL_TEST_DATABASE_URL"]
    result = subprocess.run(
        [sys.executable, "scripts/release_check.py"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert "checks passed" in result.stdout
    assert result.returncode in (0, 1)
