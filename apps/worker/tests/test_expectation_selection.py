from dataclasses import replace
from datetime import UTC, datetime, timedelta

from open_signal.derived.expectation_selection import (
    ExpectationFact,
    select_expectation_groups,
)


def test_multi_outcome_event_selects_signal_roles_instead_of_every_option() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    facts = [
        _fact(
            market_id="leader",
            probability=0.74,
            baseline=0.72,
            volume_24h=6200,
            option="Kimi Antonelli",
            as_of=as_of,
        ),
        _fact(
            market_id="mover",
            probability=0.10,
            baseline=0.04,
            volume_24h=18_000,
            option="Lewis Hamilton",
            as_of=as_of,
        ),
        _fact(
            market_id="challenger",
            probability=0.09,
            baseline=0.09,
            volume_24h=9000,
            option="Max Verstappen",
            as_of=as_of,
        ),
    ]
    facts.extend(
        _fact(
            market_id=f"longshot-{index}",
            probability=0.001,
            baseline=0.001,
            volume_24h=0,
            lifetime_volume=13_000_000 - index,
            option=f"Longshot {index}",
            as_of=as_of,
        )
        for index in range(17)
    )

    groups = select_expectation_groups(facts, as_of=as_of, page_size=12)

    assert len(groups) == 1
    group = groups[0]
    assert group.title == "2026 F1 Drivers' Champion"
    assert group.source_member_count == 20
    assert len(group.members) == 3
    assert {member.fact.market_id for member in group.members} >= {
        "leader",
        "mover",
    }
    assert group.suppressed_member_count == 17


def test_qualified_tail_anomaly_can_survive_event_compression() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    facts = [
        _fact(
            market_id="leader",
            probability=0.70,
            baseline=0.69,
            volume_24h=10_000,
            option="Leader",
            as_of=as_of,
        ),
        _fact(
            market_id="largest-mover",
            probability=0.20,
            baseline=0.10,
            volume_24h=12_000,
            option="Largest mover",
            as_of=as_of,
        ),
        _fact(
            market_id="tail-anomaly",
            probability=0.03,
            baseline=0.01,
            volume_24h=6000,
            option="Tail anomaly",
            as_of=as_of,
        ),
    ]

    group = select_expectation_groups(facts, as_of=as_of, page_size=12)[0]
    roles = {member.fact.market_id: member.selection_reason for member in group.members}

    assert roles["leader"] == "leader"
    assert roles["largest-mover"] == "largest_material_move"
    assert roles["tail-anomaly"] == "qualified_tail_anomaly"


def test_markets_without_event_identity_remain_independent_topics() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    first = _fact(
        market_id="one",
        probability=0.60,
        baseline=0.50,
        volume_24h=8000,
        option=None,
        as_of=as_of,
        external_event_id=None,
    )
    second = _fact(
        market_id="two",
        probability=0.55,
        baseline=0.50,
        volume_24h=8000,
        option=None,
        as_of=as_of,
        external_event_id=None,
    )

    groups = select_expectation_groups([first, second], as_of=as_of, page_size=12)

    assert len(groups) == 2
    assert {group.key for group in groups} == {
        "source-id:market:one",
        "source-id:market:two",
    }


def test_public_interest_orders_public_affairs_before_sports() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    sports = _fact(
        market_id="sports",
        probability=0.8,
        baseline=0.3,
        volume_24h=100_000,
        option="Driver",
        as_of=as_of,
    )
    election = replace(
        _fact(
            market_id="election",
            probability=0.55,
            baseline=0.50,
            volume_24h=6000,
            option=None,
            as_of=as_of,
            external_event_id="election-event",
        ),
        title="Will the governing party win the national election?",
        event_type="elections",
        event_title="National election",
        event_slug="national-election",
        tags=("Politics", "Elections"),
    )

    groups = select_expectation_groups([sports, election], as_of=as_of)

    assert [group.key for group in groups] == [
        election.event_key,
        sports.event_key,
    ]
    assert groups[0].editorial_scope.maximum_surface == "hero"
    assert groups[1].editorial_scope.maximum_surface == "explore"


def test_current_surface_excludes_explore_only_groups() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    sports = _fact(
        market_id="sports",
        probability=0.8,
        baseline=0.3,
        volume_24h=100_000,
        option="Driver",
        as_of=as_of,
    )

    groups = select_expectation_groups(
        [sports],
        as_of=as_of,
        minimum_surface="live_feed",
    )

    assert groups == []


def _fact(
    *,
    market_id: str,
    probability: float,
    baseline: float,
    volume_24h: float,
    option: str | None,
    as_of: datetime,
    lifetime_volume: float = 100_000,
    external_event_id: str | None = "f1-event",
) -> ExpectationFact:
    event_title = "2026 F1 Drivers' Champion" if external_event_id else None
    return ExpectationFact(
        topic_id=f"topic-{market_id}",
        market_id=market_id,
        source_id="source-id",
        source_slug="polymarket-gamma",
        title=(
            f"Will {option} be the 2026 F1 Drivers' Champion?"
            if option
            else f"Will proposition {market_id} resolve YES?"
        ),
        event_type="sports",
        deadline_at=as_of + timedelta(days=120),
        canonical_status="active",
        market_status="active",
        external_event_id=external_event_id,
        event_title=event_title,
        event_slug="2026-f1-drivers-champion" if external_event_id else None,
        group_item_title=option,
        neg_risk_market_id="neg-risk-f1" if external_event_id else None,
        is_exclusive_slate=external_event_id is not None,
        source_member_count=20 if external_event_id else 1,
        current_probability=probability,
        current_observed_at=as_of - timedelta(minutes=3),
        baseline_probability_24h=baseline,
        baseline_observed_at=as_of - timedelta(hours=25),
        spread=0.01,
        data_quality_flags=(),
        volume_24h=volume_24h,
        lifetime_volume=lifetime_volume,
        liquidity=50_000,
        monitoring_last_seen_at=as_of - timedelta(minutes=2),
        source_monitoring_at=as_of - timedelta(minutes=1),
        recent_claim_id=None,
        recent_claim_at=None,
        raw_payload={},
    )
