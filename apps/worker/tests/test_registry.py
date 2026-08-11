"""Registry and rights tests (OS-005).

Registry loading and validation are DB-free; desk sync requires a real
PostgreSQL via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os

import pytest
from open_signal.sources.registry import Registry
from open_signal.sources.rights import check_operation


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load()


# ------------------------------------------------------------ registry views


def test_load_counts(registry: Registry) -> None:
    assert len(registry.sections()) == 3
    assert len(registry.capabilities()) == 15
    assert len(registry.slots()) == 7
    assert len(registry.components()) == 19
    assert len(registry.templates()) == 3
    assert len(registry.freshness_policies()) == 7
    assert registry.freshness_policy_version == "1.0.0"
    assert len(registry.job_schedules()) == 13
    assert registry.job_schedule_version == "2.2.0"


def test_validation_passes(registry: Registry) -> None:
    errors = registry.validate()
    assert errors == [], f"registry errors: {errors}"


def test_lookup(registry: Registry) -> None:
    assert registry.section("expectations-moved") is not None
    assert registry.section("nope") is None
    assert registry.capability("expectation.probability-change") is not None
    assert registry.component("time-series.probability-move") is not None
    assert registry.slot("lead-region") is not None


def test_capabilities_for_section(registry: Registry) -> None:
    caps = registry.capabilities_for_section("expectations-moved")
    assert len(caps) == 6
    assert all(c.section_id == "expectations-moved" for c in caps)


def test_components_for_section(registry: Registry) -> None:
    comps = registry.components_for_section("expectations-moved")
    ids = {c.id for c in comps}
    assert "time-series.probability-move" in ids
    assert "signal-feed.near-deadline" in ids


def test_section_fields(registry: Registry) -> None:
    sec = registry.section("research-frontier")
    assert sec is not None
    assert sec.maturity == "shadow"
    assert sec.can_be_hero is False
    assert sec.daily_cost_budget_usd == 8.0
    assert "signal-hero.research" in sec.allowed_component_ids


def test_component_fallback_exists(registry: Registry) -> None:
    for comp in registry.components():
        if comp.fallback_component_id:
            assert registry.component(comp.fallback_component_id) is not None


def test_freshness_policy_is_rolling_and_complete(registry: Registry) -> None:
    expectations = registry.freshness_policy("expectations")
    assert expectations is not None
    assert expectations.soft_age_hours == 24
    assert expectations.hard_age_hours == 72
    assert expectations.lead_tenure_hours == 24
    assert registry.freshness_policy("default") is not None


def test_job_schedules_preserve_section_boundaries(registry: Registry) -> None:
    schedules = registry.job_schedules()
    sections = {
        schedule.payload.get("section_id")
        for schedule in schedules
        if schedule.payload.get("section_id")
    }
    assert sections == {
        "expectations-moved",
        "rules-moved",
        "research-frontier",
    }
    research_agent = registry.job_schedule("research-shadow-investigation")
    assert research_agent is not None
    assert research_agent.queue_name == "agent"
    delivery = registry.job_schedule("publication-snapshot-delivery")
    assert delivery is not None
    assert delivery.priority > registry.job_schedule(
        "publication-freshness-reconcile"
    ).priority
    assert min(schedule.cadence_seconds for schedule in schedules) == 3600


# ---------------------------------------------------------------- rights


def test_rights_tri_state() -> None:
    manifest = {
        "internalAnalysis": True,
        "fullTextStorage": False,
        "excerptDisplay": None,  # unknown
    }
    assert check_operation(manifest, "internalAnalysis") == "allowed"
    assert check_operation(manifest, "fullTextStorage") == "denied"
    assert check_operation(manifest, "excerptDisplay") == "internal_only"


def test_rights_unknown_operation_raises() -> None:
    with pytest.raises(ValueError):
        check_operation({}, "not-an-operation")


def test_can_publicly_display(registry: Registry) -> None:
    # explicit headline allow -> display OK
    assert (
        _display({"headlineDisplay": True}) is True
    )
    # unknown headline -> no public display
    assert (
        _display({"headlineDisplay": None}) is False
    )
    # explicit deny
    assert (
        _display({"headlineDisplay": False}) is False
    )
    # full text requires storage allowance
    assert _fulltext({"fullTextStorage": True, "headlineDisplay": True}) is True
    assert _fulltext({"fullTextStorage": None, "headlineDisplay": True}) is False


def _display(ops):
    from open_signal.sources.rights import can_publicly_display

    return can_publicly_display(ops)


def _fulltext(ops):
    from open_signal.sources.rights import can_publicly_display

    return can_publicly_display(ops, full_text=True)


# ---------------------------------------------------------------- db sync


@pytest.fixture()
def engine():
    from sqlalchemy import create_engine

    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    return create_engine(url)


def test_sync_desks(registry: Registry, engine) -> None:
    from sqlalchemy import text

    registry.sync_desks(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, title, maturity FROM agent_desks ORDER BY id")
        ).fetchall()
    ids = {r[0] for r in rows}
    assert {
        "expectations-desk",
        "rules-desk",
        "research-frontier-desk",
    } <= ids
    by_id = {r[0]: r for r in rows}
    assert by_id["research-frontier-desk"][2] == "shadow"
