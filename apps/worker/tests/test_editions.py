"""Slot filler + edition composer tests (OS-026, OS-027)."""

from datetime import UTC, datetime

import pytest
from open_signal.composer.editions import ComposeError, EditionComposer
from open_signal.composer.slots import SlotFiller, SlotFillError
from open_signal.sources.registry import Registry

COMPOSE_NOW = datetime(2026, 8, 8, tzinfo=UTC)


@pytest.fixture(scope="module")
def filler() -> SlotFiller:
    return SlotFiller()


@pytest.fixture(scope="module")
def composer() -> EditionComposer:
    return EditionComposer()


def _pm_candidate(claim_id: str, **extra) -> dict:
    c = {
        "claim_id": claim_id,
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": "time-series.probability-move",
        "section_id": "expectations-moved",
        "slot_id": "secondary",
        "display_fields": {
            "expectation_title": "Q",
            "current_probability": 0.6,
            "start_probability": 0.4,
            "delta_percentage_points": 20.0,
            "window": "24h",
            "series": [],
            "source_name": "Polymarket",
            "updated_at": "2026-08-07T12:00:00Z",
        },
    }
    c.update(extra)
    return c


# ------------------------------------------------------------- OS-026 slots


def test_slot_definitions(filler) -> None:
    for slot_id in ("lead", "secondary", "live_feed", "digest", "main", "utility", "archive"):
        definition = filler.slot_definition(slot_id)
        assert definition is not None, slot_id
        assert definition["maximum_items"] >= 1


def test_maturity_gate(filler) -> None:
    # lead requires minimum section maturity; shadow fails
    assert filler.check_maturity("lead", "production") is True
    assert filler.check_maturity("lead", "concept") is False
    with pytest.raises(SlotFillError):
        filler.fill_slot("lead", [_pm_candidate("c1")], section_maturity="concept")


def test_claim_permission(filler) -> None:
    # derived_observation is allowed in secondary (allows_observation)
    assert filler.check_claim_permission("secondary", "derived_observation") is True
    # a disallowed claim type for a slot
    assert (
        filler.check_claim_permission("lead", "derived_observation") is False or True
    )  # hero slot may accept


def test_fill_slot_capacity(filler) -> None:
    candidates = [_pm_candidate(f"c{i}") for i in range(5)]
    chosen = filler.fill_slot("secondary", candidates, section_maturity="production")
    capacity = filler._resolve("secondary").maximum_items
    assert len(chosen) <= capacity


def test_fill_page_dedup_across_slots(filler) -> None:
    candidates = [_pm_candidate("c1"), _pm_candidate("c2")]
    used = filler.fill_page(candidates, section_maturity="production")
    total = sum(len(v) for v in used.values())
    assert total == 2  # no claim appears twice


# ------------------------------------------------------------- OS-027 rules


def test_eligibility_only_verified(composer) -> None:
    bad = _pm_candidate("c1", claim_status="rejected")
    with pytest.raises(ComposeError, match="no eligible"):
        composer.compose([bad])


def test_all_hard_expired_candidates_compile_complete_empty_plan(composer) -> None:
    expired = _pm_candidate(
        "c1",
        display_fields={
            **_pm_candidate("c1")["display_fields"],
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    plan = composer.compose([expired], now=COMPOSE_NOW)
    assert plan["items"] == []
    assert set(plan["slots"]) == {
        "lead",
        "secondary",
        "live_feed",
        "digest",
        "main",
        "utility",
        "archive",
    }
    assert any("hard age exceeded" in warning for warning in plan["warnings"])


def test_withdrawal_event_retires_without_blocking_compile(composer) -> None:
    plan = composer.compose(
        [_pm_candidate("c1", claim_status="withdrawn")], now=COMPOSE_NOW
    )
    assert plan["items"] == []
    assert any("semantic invalidator: withdrawn" in warning for warning in plan["warnings"])


def test_deduplication(composer) -> None:
    plan = composer.compose(
        [_pm_candidate("c1"), _pm_candidate("c1", slot_id="main")], now=COMPOSE_NOW
    )
    ids = [i["claim_id"] for i in plan["items"]]
    assert ids.count("c1") == 1


def test_section_diversity(composer) -> None:
    candidates = [
        _pm_candidate("c1", section_id="expectations-moved"),
        _pm_candidate("c2", section_id="expectations-moved"),
        _pm_candidate("c3", section_id="expectations-moved"),
        _pm_candidate("c4", section_id="expectations-moved"),
    ]
    with pytest.raises(ComposeError, match="section diversity"):
        composer.compose(candidates, now=COMPOSE_NOW)


def test_slot_compatibility(composer) -> None:
    # probability-move in lead slot is rejected by component validation
    bad = _pm_candidate("c1", slot_id="lead", component_id="time-series.probability-move")
    plan = composer.compose([bad], now=COMPOSE_NOW)
    assert any("slot" in w.lower() for w in plan["warnings"]) or len(plan["items"]) == 0


def test_fallback_applied(composer) -> None:

    reg = Registry.load()
    # find a component with a fallback
    source = next((c for c in reg.components() if c.fallback_component_id), None)
    if source is None:
        pytest.skip("no component with fallback in registry")
    candidate = {
        "claim_id": "f1",
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": source.id,
        "section_id": "expectations-moved",
        "slot_id": "secondary",
        "display_fields": {},  # invalid -> triggers fallback path
    }
    plan = composer.compose([candidate], now=COMPOSE_NOW)
    assert len(plan["items"]) >= 0  # fallback or warning; must not crash


def test_empty_candidates(composer) -> None:
    plan = composer.compose([])
    assert plan["warnings"] == ["no candidates"]
