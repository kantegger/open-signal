"""Rolling publication freshness policy tests."""

from datetime import UTC, datetime, timedelta

from open_signal.composer.freshness import FreshnessEvaluator

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _candidate(**extra):
    value = {
        "claim_id": "claim-1",
        "claim_status": "verified",
        "section_id": "expectations-moved",
        "slot_id": "secondary",
        "issued_at": (NOW - timedelta(hours=10)).isoformat(),
        "display_fields": {},
    }
    value.update(extra)
    return value


def test_expectations_soft_and_hard_age() -> None:
    evaluator = FreshnessEvaluator()
    current = evaluator.evaluate(_candidate(), now=NOW)
    aging = evaluator.evaluate(
        _candidate(issued_at=(NOW - timedelta(hours=30)).isoformat()), now=NOW
    )
    expired = evaluator.evaluate(
        _candidate(issued_at=(NOW - timedelta(hours=73)).isoformat()), now=NOW
    )
    assert current.state == "current"
    assert aging.state == "aging"
    assert expired.state == "expired"


def test_live_feed_policy_overrides_section_policy() -> None:
    decision = FreshnessEvaluator().evaluate(
        _candidate(
            slot_id="live_feed",
            issued_at=(NOW - timedelta(hours=25)).isoformat(),
        ),
        now=NOW,
    )
    assert decision.policy_id == "live-feed"
    assert decision.state == "expired"


def test_valid_until_and_semantic_state_override_elapsed_age() -> None:
    evaluator = FreshnessEvaluator()
    by_contract = evaluator.evaluate(
        _candidate(valid_until=(NOW - timedelta(seconds=1)).isoformat()), now=NOW
    )
    withdrawn = evaluator.evaluate(_candidate(claim_status="withdrawn"), now=NOW)
    assert by_contract.reason == "claim validity ended"
    assert withdrawn.state == "expired"


def test_lead_demotes_without_new_material_evidence() -> None:
    decision = FreshnessEvaluator().evaluate(
        _candidate(
            slot_id="lead",
            issued_at=(NOW - timedelta(hours=25)).isoformat(),
        ),
        now=NOW,
    )
    assert decision.eligible is True
    assert decision.demote_from_lead is True


def test_archive_has_no_elapsed_hard_expiry() -> None:
    decision = FreshnessEvaluator().evaluate(
        _candidate(
            slot_id="archive",
            issued_at=(NOW - timedelta(days=1000)).isoformat(),
        ),
        now=NOW,
    )
    assert decision.policy_id == "archive"
    assert decision.state == "current"
    assert decision.expires_at is None
