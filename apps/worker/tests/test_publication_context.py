from datetime import UTC, datetime, timedelta

from open_signal.composer.publication_context import PublicationContextBuilder
from open_signal.derived.series_contract import market_series_snapshot


def test_complete_series_uses_only_observed_points() -> None:
    captured_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    start = captured_at - timedelta(days=7)
    observations = [
        (
            start + timedelta(hours=index),
            0.42 + index * 0.0005 + (0.012 if index % 9 == 0 else 0),
        )
        for index in range(169)
    ]

    snapshot = market_series_snapshot(observations, captured_at=captured_at)

    assert snapshot["quality"]["coverage_status"] == "complete"
    assert snapshot["quality"]["observation_count"] == 169
    assert len(snapshot["points"]) <= 48
    observed_points = {(timestamp.isoformat(), value) for timestamp, value in observations}
    assert all(tuple(point) in observed_points for point in snapshot["points"])
    assert snapshot["points"][0] == [observations[0][0].isoformat(), observations[0][1]]
    assert snapshot["points"][-1] == [observations[-1][0].isoformat(), observations[-1][1]]


def test_partial_history_is_not_chartable() -> None:
    captured_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    observations = [
        (captured_at - timedelta(hours=100 - index * 10), 0.45 + index * 0.01)
        for index in range(11)
    ]

    snapshot = market_series_snapshot(observations, captured_at=captured_at)

    assert snapshot["quality"]["coverage_status"] == "insufficient_observations"
    assert snapshot["quality"]["observation_count"] == 11


def test_flat_history_degrades_instead_of_drawing_a_line() -> None:
    captured_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    start = captured_at - timedelta(days=7)
    observations = [(start + timedelta(hours=index * 6), 0.5) for index in range(29)]

    snapshot = market_series_snapshot(observations, captured_at=captured_at)

    assert snapshot["quality"]["coverage_status"] == "no_material_variation"
    assert snapshot["quality"]["probability_range_percentage_points"] == 0


def test_research_context_uses_public_gate_and_event_first_headline() -> None:
    complete_metrics = {
        "topic_id": "generative-ai",
        "topic_label": "Generative AI and foundation models",
        "institution": "Microsoft Research Asia",
        "recent_works": 5,
        "prior_works": 0,
        "representative_works": [{"id": "W1", "title": "A source work"}],
        "evidence_count": 5,
        "window_label": "2025–2026 YTD",
        "baseline_label": "Before 2025",
    }
    incomplete_metrics = {
        "institution": "Unattributed Lab",
        "recent_works": 12,
        "prior_works": 0,
    }
    captured_at = datetime(2026, 8, 9, 8, tzinfo=UTC)
    connection = _ResearchConnection(
        [
            (
                "candidate-complete",
                "institution_entry",
                complete_metrics,
                "generated",
                captured_at,
                captured_at - timedelta(days=365),
                captured_at,
                "works before 2025: 0",
                [],
            ),
            (
                "candidate-incomplete",
                "institution_entry",
                incomplete_metrics,
                "generated",
                captured_at,
                captured_at - timedelta(days=365),
                captured_at,
                "works before 2025: 0",
                [],
            ),
        ]
    )

    items, eligible_total = PublicationContextBuilder()._research(
        connection,
        captured_at=captured_at,
    )

    assert eligible_total == 1
    assert len(items) == 1
    assert items[0]["headline"] == (
        "New institutional output appeared in Generative AI and foundation models"
    )
    assert items[0]["entity"] == "Microsoft Research Asia"
    assert "Microsoft Research Asia" not in items[0]["headline"]


class _ResearchConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return self

    def fetchall(self) -> list[tuple]:
        return self.rows
