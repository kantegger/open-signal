from datetime import UTC, datetime, timedelta

from open_signal.composer.edition_writer import _public_interest_allows_slot
from open_signal.derived.public_interest import (
    classify_expectation_scope,
    load_editorial_scope_policy,
)
from open_signal.orchestration.expectations import ExpectationsSectionService

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)


def _decision(
    title: str,
    *,
    tags: tuple[str, ...] = (),
    hours: int = 72,
    probability: float = 0.5,
    delta: float = 10,
):
    return classify_expectation_scope(
        title=title,
        tags=tags,
        as_of=NOW,
        deadline_at=NOW + timedelta(hours=hours),
        current_probability=probability,
        delta_24h=delta,
    )


def test_policy_is_versioned_and_uses_ordered_surfaces() -> None:
    policy = load_editorial_scope_policy()
    assert policy["version"] == "1.0.0"
    assert policy["surface_order"] == [
        "monitor",
        "explore",
        "live_feed",
        "secondary",
        "hero",
    ]


def test_routine_temperature_is_explore_only() -> None:
    decision = _decision(
        "Will the highest temperature in Shanghai be 29°C on August 11?",
        tags=("Weather",),
        hours=24,
    )
    assert decision.category == "routine_weather"
    assert decision.maximum_surface == "explore"
    assert decision.allows("explore") is True
    assert decision.allows("live_feed") is False


def test_sports_and_social_counts_are_not_editorial_candidates() -> None:
    sports = _decision(
        "Will George Russell win the 2026 F1 Drivers' Championship?",
        tags=("Sports", "F1"),
        hours=24 * 100,
    )
    social = _decision(
        "Will Elon Musk post more than 120 tweets this week?",
        tags=("Social Media",),
        hours=48,
    )
    assert sports.maximum_surface == "explore"
    assert social.maximum_surface == "explore"


def test_short_horizon_crypto_price_is_explore_but_long_horizon_is_not() -> None:
    short = _decision(
        "Will Bitcoin reach $70,000 on August 11?",
        tags=("Crypto", "Bitcoin"),
        hours=24,
    )
    long = _decision(
        "Will Bitcoin reach a new all-time high before 2027?",
        tags=("Crypto", "Bitcoin"),
        hours=24 * 180,
    )
    assert short.maximum_surface == "explore"
    assert long.maximum_surface == "secondary"


def test_public_consequence_can_enter_hero() -> None:
    decision = _decision(
        "Will Russia target Kyiv by August 12?",
        tags=("Kyiv", "Geopolitics", "Military Actions"),
        hours=24,
    )
    assert decision.category == "geopolitics_security"
    assert decision.maximum_surface == "hero"


def test_severe_weather_is_contextual_not_routine_but_stays_below_hero() -> None:
    decision = _decision(
        "Will a hurricane make landfall in Florida this week?",
        tags=("Weather",),
        hours=72,
    )
    assert decision.category == "public_hazard"
    assert decision.maximum_surface == "secondary"


def test_near_resolution_convergence_demotes_an_otherwise_hero_signal() -> None:
    decision = _decision(
        "Will Russia target Kyiv by midnight?",
        tags=("Geopolitics", "Military Actions"),
        hours=2,
        probability=0.08,
        delta=-52,
    )
    assert decision.maximum_surface == "secondary"
    assert "near_resolution_convergence" in decision.matched_terms


def test_featured_candidate_needs_explicit_hero_permission_for_lead() -> None:
    result = {
        "claim_id": "claim-1",
        "section_instance_id": "section-1",
        "render_candidate": {
            "component_id": "time-series.probability-move",
            "component_version": "1.0.0",
            "component_variant": "standard",
            "slot_id": "secondary",
            "headline": "Contextual expectation",
            "display_fields": {"observation": "YES moved up."},
            "hidden_detail_fields": {},
        },
    }
    contextual = ExpectationsSectionService._publication_candidate(
        result,
        tier="featured",
        index=0,
        use_hero=False,
    )
    hero = ExpectationsSectionService._publication_candidate(
        result,
        tier="featured",
        index=0,
        use_hero=True,
    )
    assert contextual["slot_id"] == "secondary"
    assert contextual["component_id"] == "time-series.probability-move"
    assert hero["slot_id"] == "lead"
    assert hero["component_id"] == "signal-hero.expectations"


def test_legacy_weather_hero_cannot_survive_continuity() -> None:
    weather = {
        "section_id": "expectations-moved",
        "slot_id": "lead",
        "headline": "Will the highest temperature in Paris be 31°C tomorrow?",
        "display_fields": {
            "current_probability": 0.8,
            "delta_percentage_points": 35,
            "resolution_deadline_at": (NOW + timedelta(hours=24)).isoformat(),
        },
        "hidden_detail_fields": {},
    }
    geopolitics = {
        **weather,
        "headline": "Will a ceasefire agreement be signed this month?",
        "display_fields": {
            **weather["display_fields"],
            "tags": ["Geopolitics"],
            "resolution_deadline_at": (NOW + timedelta(days=10)).isoformat(),
        },
    }
    assert _public_interest_allows_slot(weather, now=NOW) is False
    assert _public_interest_allows_slot(geopolitics, now=NOW) is True


def test_unclassified_legacy_hero_keeps_editorial_placement() -> None:
    legacy = {
        "section_id": "expectations-moved",
        "slot_id": "lead",
        "headline": "Will the agreement be completed this month?",
        "display_fields": {},
        "hidden_detail_fields": {},
    }

    assert _public_interest_allows_slot(legacy, now=NOW) is True
