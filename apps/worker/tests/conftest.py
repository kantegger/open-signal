"""Database safety boundary for the Open Signal test suite.

The suite contains destructive cleanup (including ``TRUNCATE ... CASCADE``),
so application/database URLs are never accepted as an implicit test target.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_ENV = "OPEN_SIGNAL_TEST_DATABASE_URL"
APP_DATABASE_ENV = "OPEN_SIGNAL_DATABASE_URL"
TEST_BRANCH_ENV = "OPEN_SIGNAL_TEST_BRANCH_ID"
_CONFIGURED_TEST_URL: str | None = None


def _normalized_target(raw_url: str) -> tuple[str, int, str]:
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise pytest.UsageError(f"{TEST_DATABASE_ENV} is not a valid database URL") from exc

    host = (url.host or "").casefold()
    if not host or not url.database:
        raise pytest.UsageError(
            f"{TEST_DATABASE_ENV} must include a database host and name"
        )
    labels = host.split(".", maxsplit=1)
    labels[0] = labels[0].removesuffix("-pooler")
    normalized_host = ".".join(labels)
    return normalized_host, url.port or 5432, url.database


def _is_neon(raw_url: str) -> bool:
    return _normalized_target(raw_url)[0].endswith(".neon.tech")


def _neon_branch_id(raw_url: str) -> str | None:
    engine = create_engine(raw_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT current_setting('neon.branch_id', true)")
            ).scalar_one_or_none()
    except Exception as exc:
        raise pytest.UsageError(
            f"Unable to verify the Neon branch configured by {TEST_DATABASE_ENV}"
        ) from exc
    finally:
        engine.dispose()


def _configure_test_database() -> None:
    """Map the explicit test URL only after proving it is an isolated target."""
    global _CONFIGURED_TEST_URL
    test_url = os.environ.get(TEST_DATABASE_ENV)
    app_url = os.environ.get(APP_DATABASE_ENV)

    if test_url == _CONFIGURED_TEST_URL and app_url == test_url:
        return

    if not test_url:
        if app_url:
            raise pytest.UsageError(
                f"Refusing destructive database tests: {APP_DATABASE_ENV} is set but "
                f"{TEST_DATABASE_ENV} is not. Configure an isolated test database."
            )
        return  # database-backed tests retain their existing skip behavior

    test_target = _normalized_target(test_url)
    if app_url and _normalized_target(app_url) == test_target:
        raise pytest.UsageError(
            f"{TEST_DATABASE_ENV} and {APP_DATABASE_ENV} resolve to the same database"
        )

    if _is_neon(test_url):
        expected_branch = os.environ.get(TEST_BRANCH_ENV)
        if not expected_branch:
            raise pytest.UsageError(
                f"{TEST_BRANCH_ENV} is required when the test database is hosted on Neon"
            )
        actual_branch = _neon_branch_id(test_url)
        if actual_branch != expected_branch:
            raise pytest.UsageError(
                "Refusing destructive database tests: the Neon test URL resolves to "
                f"branch {actual_branch!r}, expected {expected_branch!r}"
            )

    # Application code still reads OPEN_SIGNAL_DATABASE_URL. Shadow it only
    # inside the pytest process after the isolation checks above have passed.
    os.environ[APP_DATABASE_ENV] = test_url
    _CONFIGURED_TEST_URL = test_url


def pytest_configure(config: pytest.Config | None) -> None:
    """Apply the guard early when tests are addressed below this directory."""
    del config  # hook signature required by pytest
    _configure_test_database()


@pytest.fixture(scope="session", autouse=True)
def _enforce_test_database_boundary() -> None:
    """Backstop invocations where this conftest is discovered after configure."""
    _configure_test_database()
