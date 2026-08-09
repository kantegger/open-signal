"""Operations console tests (OS-031). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migrations 0001-0007 applied).
"""

import os
from datetime import date

import pytest
from open_signal.api.ops import OpsPresenter


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def ops(engine) -> OpsPresenter:
    return OpsPresenter(engine)


def _seed(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sources (slug, name, category, authority_level, "
                "access_mode, adapter_id, status) "
                "VALUES ('ops-src', 'Ops', 'other', 'secondary_source', 'rest', 'v1', 'active') "
                "ON CONFLICT (slug) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO feature_flags (flag_name, enabled, description) "
                "VALUES ('beta.editions', true, 'enable editions') "
                "ON CONFLICT (flag_name) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO feature_flags (flag_name, enabled, description) "
                "VALUES ('agent.reasoner', false, 'disable reasoner') "
                "ON CONFLICT (flag_name) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO daily_editions (edition_date, generated_at, status, "
                "included_section_ids, included_claim_ids, composer_version, "
                "component_versions, generation_cost_usd, correction_count, edition_payload) "
                "VALUES (:d, now(), 'published', ARRAY['expectations-moved'], "
                "ARRAY[]::uuid[], 'os-028', '{}'::jsonb, 0.01, 1, '{}'::jsonb) "
                "ON CONFLICT DO NOTHING"
            ),
            {"d": date(2026, 8, 7)},
        )


def test_current_edition(ops, engine) -> None:
    _seed(engine)
    edition = ops.current_edition()
    assert edition is not None
    assert edition["status"] == "published"
    assert edition["correction_count"] == 1


def test_source_health(ops, engine) -> None:
    _seed(engine)
    rows = ops.source_health()
    assert any(r["slug"] == "ops-src" for r in rows)


def test_job_queue_and_agent_runs(ops, engine) -> None:
    counts = ops.job_queue()
    assert isinstance(counts, dict)
    runs = ops.agent_runs()
    assert isinstance(runs, list)


def test_feature_flags(ops, engine) -> None:
    _seed(engine)
    flags = ops.feature_flags()
    by_name = {f["flag_name"]: f for f in flags}
    assert by_name["agent.reasoner"]["enabled"] is False
    assert by_name["beta.editions"]["enabled"] is True


def test_claims_corrected(ops, engine) -> None:
    _seed(engine)
    corrected = ops.claims_corrected()
    assert any(c["correction_count"] == 1 for c in corrected)


def test_verification_failures_and_daily_cost(ops, engine) -> None:
    failures = ops.verification_failures()
    assert isinstance(failures, list)
    cost = ops.daily_cost(days=7)
    assert isinstance(cost, list)
