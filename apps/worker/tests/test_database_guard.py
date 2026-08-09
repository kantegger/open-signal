"""Regression tests for the destructive-test database safety boundary."""

import os

import conftest as database_guard
import pytest


def test_guard_refuses_application_database_without_test_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(database_guard.TEST_DATABASE_ENV, raising=False)
    monkeypatch.setenv(
        database_guard.APP_DATABASE_ENV,
        "postgresql://user:password@db.example.com/app",
    )
    with pytest.raises(pytest.UsageError, match="Refusing destructive database tests"):
        database_guard.pytest_configure(None)


def test_guard_refuses_same_endpoint_with_pooler_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        database_guard.TEST_DATABASE_ENV,
        "postgresql://user:password@ep-safe-pooler.example.com/app",
    )
    monkeypatch.setenv(
        database_guard.APP_DATABASE_ENV,
        "postgresql://user:password@ep-safe.example.com/app",
    )
    with pytest.raises(pytest.UsageError, match="resolve to the same database"):
        database_guard.pytest_configure(None)


def test_guard_requires_expected_branch_for_neon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        database_guard.TEST_DATABASE_ENV,
        "postgresql://user:password@ep-test.example.neon.tech/app",
    )
    monkeypatch.delenv(database_guard.APP_DATABASE_ENV, raising=False)
    monkeypatch.delenv(database_guard.TEST_BRANCH_ENV, raising=False)
    with pytest.raises(pytest.UsageError, match=database_guard.TEST_BRANCH_ENV):
        database_guard.pytest_configure(None)


def test_guard_maps_isolated_test_url_for_application_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_url = "postgresql://user:password@test.example.com/open_signal_test"
    monkeypatch.setenv(database_guard.TEST_DATABASE_ENV, test_url)
    monkeypatch.setenv(
        database_guard.APP_DATABASE_ENV,
        "postgresql://user:password@dev.example.com/open_signal",
    )
    database_guard.pytest_configure(None)
    assert os.environ[database_guard.APP_DATABASE_ENV] == test_url
