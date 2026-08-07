"""Composer component runtime tests (OS-025)."""

import pytest

from open_signal.composer.components import (
    ComponentRuntime,
    ComponentRuntimeError,
    FIRST_BATCH,
)
from open_signal.sources.registry import Registry


@pytest.fixture(scope="module")
def runtime() -> ComponentRuntime:
    return ComponentRuntime()


def test_first_batch_eight_components(runtime) -> None:
    batch = runtime.first_batch()
    assert len(batch) == 8
    ids = {b["component_id"] for b in batch}
    assert ids == set(FIRST_BATCH.keys())
    # every first-batch component exists in the registry
    for b in batch:
        assert b["version"] is not None, f"{b['component_id']} missing from registry"


def test_frontend_mapping(runtime) -> None:
    m = runtime.map_to_frontend("time-series.probability-move")
    assert m["frontend_key"] == "ProbabilityMoveChart"
    assert m["default_slot"] == "secondary"
    with pytest.raises(ComponentRuntimeError):
        runtime.map_to_frontend("no.such")


def _pm_fields(**extra) -> dict:
    fields = {
        "expectation_title": "Will X happen?",
        "current_probability": 0.6,
        "start_probability": 0.4,
        "delta_percentage_points": 20.0,
        "window": "24h",
        "series": [],
        "source_name": "Polymarket",
        "updated_at": "2026-08-07T12:00:00Z",
    }
    fields.update(extra)
    return fields


def test_validate_required_fields(runtime) -> None:
    candidate = {"display_fields": _pm_fields()}
    ok = runtime.validate_render("time-series.probability-move", candidate)
    assert ok["component_version"] == "1.0.0"
    assert ok["slot_id"] == "secondary"

    # missing one required field
    bad = {"display_fields": {"expectation_title": "X", "window": "24h"}}
    with pytest.raises(ComponentRuntimeError, match="missing required"):
        runtime.validate_render("time-series.probability-move", bad)


def test_validate_unknown_component(runtime) -> None:
    with pytest.raises(ComponentRuntimeError, match="unknown component"):
        runtime.validate_render("ghost.component", {"display_fields": {}})


def test_validate_slot_allowed(runtime) -> None:
    # main and secondary are allowed for time-series; lead is not
    ok = runtime.validate_render(
        "time-series.probability-move", {"slot_id": "main", "display_fields": _pm_fields()}
    )
    assert ok["slot_id"] == "main"
    with pytest.raises(ComponentRuntimeError, match="slot"):
        runtime.validate_render(
            "time-series.probability-move", {"slot_id": "lead", "display_fields": _pm_fields()}
        )


def test_validate_narrative_mode(runtime) -> None:
    candidate = {
        "narrative_mode": "judgment",  # registry says observation for probability-move
        "display_fields": _pm_fields(),
    }
    with pytest.raises(ComponentRuntimeError, match="narrative_mode"):
        runtime.validate_render("time-series.probability-move", candidate)


def test_build_render_plan_item(runtime) -> None:
    candidate = {
        "display_fields": {
            "rule_title": "CPSC Labeling",
            "previous_state": "proposed",
            "current_state": "final",
            "transition_date": "2026-08-01",
            "authority": "CPSC",
            "source_url": "https://federalregister.gov/d/2026-00001",
        }
    }
    item = runtime.build_render_plan_item(
        component_id="state-transition.rule-stage",
        render_candidate=candidate,
        claim_id="c1",
        section_instance_id="si1",
        slot_id="main",
    )
    assert item["claim_id"] == "c1"
    assert item["section_instance_id"] == "si1"
    assert item["slot_id"] == "main"
    assert item["component_version"] == "1.0.0"


def test_all_first_batch_validatable(runtime) -> None:
    """Smoke: every first-batch component has required fields known."""
    registry = Registry.load()
    for component_id in FIRST_BATCH:
        definition = registry.component(component_id)
        assert definition is not None
        assert definition.required_fields
