"""Raw payload retention report, archive boundary, and bounded purge."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.retention import (
    RawRetentionExecutor,
    RawRetentionPlanner,
    RawRetentionPolicy,
    build_archive_object,
    verify_archive_bytes,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        # Test-only reset for the append-only audit table. Production row
        # mutation remains prohibited; TRUNCATE is used only on the isolated
        # Neon test branch so later legacy cleanup fixtures can delete raws.
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE raw_payload_purge_events"))
        engine.dispose()


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seed_source(engine, slug: str) -> str:
    with engine.begin() as conn:
        return str(
            conn.execute(
                text(
                    """
                    INSERT INTO sources
                      (slug, name, category, authority_level, access_mode,
                       adapter_id, status)
                    VALUES
                      (:slug, :slug, 'other', 'secondary_source', 'rest',
                       'retention-test', 'active')
                    RETURNING id
                    """
                ),
                {"slug": slug},
            ).scalar_one()
        )


def _insert_raw(
    engine,
    *,
    source_id: str,
    external_id: str,
    payload: dict,
    seen_at: datetime,
    record_type: str = "fixture",
) -> str:
    with engine.begin() as conn:
        return str(
            conn.execute(
                text(
                    """
                    INSERT INTO raw_source_records
                      (source_id, external_id, record_type, mime_type, payload,
                       first_seen_at, last_seen_at, ingested_at, content_hash,
                       adapter_version, status)
                    VALUES
                      (:source, :external, :record_type, 'application/json',
                       CAST(:payload AS jsonb), :seen, :seen, :seen, :hash,
                       'retention-test', 'active')
                    RETURNING id
                    """
                ),
                {
                    "source": source_id,
                    "external": external_id,
                    "payload": json.dumps(payload),
                    "record_type": record_type,
                    "seen": seen_at,
                    "hash": _canonical_hash(payload),
                },
            ).scalar_one()
        )


def _source_report(report: dict, slug: str) -> dict:
    return next(item for item in report["sources"] if item["source_slug"] == slug)


def test_policy_activates_bounded_purge() -> None:
    policy = RawRetentionPolicy.load()

    assert policy.mode == "active"
    assert policy.hot_days_for("polymarket-gamma") == 2
    assert policy.hot_days_for("unknown-source") == 30
    assert policy.maximum_rows_per_run == 1000

    with pytest.raises(ValueError, match="report_only or active"):
        RawRetentionPolicy(version="bad", mode="delete").validate()


def test_archive_object_is_deterministic_and_detects_corruption() -> None:
    payload = {"question": "Will signal survive?", "probability": 0.73}
    content_hash = _canonical_hash(payload)

    first = build_archive_object(
        raw_source_record_id=str(uuid.uuid4()),
        source_slug="polymarket-gamma",
        content_hash=content_hash,
        payload=payload,
    )
    second = build_archive_object(
        raw_source_record_id=first.raw_source_record_id,
        source_slug="polymarket-gamma",
        content_hash=content_hash,
        payload=payload,
    )

    assert first.body == second.body
    assert first.archive_hash == second.archive_hash
    assert first.storage_key.endswith(f"/{content_hash}.json.gz")
    assert verify_archive_bytes(first, first.body) == payload
    corrupted = bytearray(first.body)
    corrupted[-1] ^= 1
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_archive_bytes(first, bytes(corrupted))


def test_planner_classifies_current_recent_and_eligible_without_writes(engine) -> None:
    as_of = datetime(2026, 8, 11, 12, tzinfo=UTC)
    slug = f"retention-plan-{uuid.uuid4().hex}"
    source_id = _seed_source(engine, slug)
    external_id = str(uuid.uuid4())
    _insert_raw(
        engine,
        source_id=source_id,
        external_id=external_id,
        payload={"version": "old"},
        seen_at=as_of - timedelta(days=10),
    )
    _insert_raw(
        engine,
        source_id=source_id,
        external_id=external_id,
        payload={"version": "recent"},
        seen_at=as_of - timedelta(days=3),
    )
    _insert_raw(
        engine,
        source_id=source_id,
        external_id=external_id,
        payload={"version": "current"},
        seen_at=as_of - timedelta(hours=1),
    )
    policy = RawRetentionPolicy(
        version="test",
        default_hot_days=7,
        source_hot_days={slug: 7},
    )

    report = RawRetentionPlanner(engine, policy).plan(as_of=as_of)
    source = _source_report(report, slug)

    assert report["mutation_permitted"] is False
    assert source["dispositions"]["eligible_report_only"]["rows"] == 1
    assert source["dispositions"]["superseded_hot"]["rows"] == 1
    assert source["dispositions"]["current_hot"]["rows"] == 1
    assert report["activation"]["dependency_free_rows"] >= 1


def test_database_requires_verified_event_before_payload_can_be_cold(engine) -> None:
    now = datetime(2026, 8, 11, 13, tzinfo=UTC)
    slug = f"retention-transition-{uuid.uuid4().hex}"
    payload = {"record": "immutable input", "sequence": 1}
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            source_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO sources
                          (slug, name, category, authority_level, access_mode,
                           adapter_id, status)
                        VALUES
                          (:slug, :slug, 'other', 'secondary_source', 'rest',
                           'retention-test', 'active')
                        RETURNING id
                        """
                    ),
                    {"slug": slug},
                ).scalar_one()
            )
            raw_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO raw_source_records
                          (source_id, external_id, record_type, mime_type, payload,
                           first_seen_at, last_seen_at, ingested_at, content_hash,
                           adapter_version, status)
                        VALUES
                          (:source, :external, 'fixture', 'application/json',
                           CAST(:payload AS jsonb), :seen, :seen, :seen, :hash,
                           'retention-test', 'active')
                        RETURNING id
                        """
                    ),
                    {
                        "source": source_id,
                        "external": str(uuid.uuid4()),
                        "payload": json.dumps(payload),
                        "seen": now - timedelta(days=40),
                        "hash": _canonical_hash(payload),
                    },
                ).scalar_one()
            )
            archive = build_archive_object(
                raw_source_record_id=raw_id,
                source_slug=slug,
                content_hash=_canonical_hash(payload),
                payload=payload,
            )

            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(
                    text(
                        "UPDATE raw_source_records "
                        "SET retention_state = 'cold', payload = NULL "
                        "WHERE id = :id"
                    ),
                    {"id": raw_id},
                )

            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(
                    text(
                        """
                        INSERT INTO raw_payload_archive_events
                          (raw_source_record_id, source_id, storage_key,
                           archive_hash, source_content_hash,
                           uncompressed_bytes, compressed_bytes, compression,
                           policy_version, actor)
                        VALUES
                          (:raw, :source, :key, :archive_hash, :wrong_hash,
                           :uncompressed, :compressed, 'gzip', 'test', 'pytest')
                        """
                    ),
                    {
                        "raw": raw_id,
                        "source": source_id,
                        "key": archive.storage_key,
                        "archive_hash": archive.archive_hash,
                        "wrong_hash": "f" * 64,
                        "uncompressed": archive.uncompressed_bytes,
                        "compressed": archive.compressed_bytes,
                    },
                )

            conn.execute(
                text(
                    """
                    INSERT INTO raw_payload_archive_events
                      (raw_source_record_id, source_id, storage_key, archive_hash,
                       source_content_hash, uncompressed_bytes, compressed_bytes,
                       compression, policy_version, actor)
                    VALUES
                      (:raw, :source, :key, :archive_hash, :content_hash,
                       :uncompressed, :compressed, 'gzip', 'test', 'pytest')
                    """
                ),
                {
                    "raw": raw_id,
                    "source": source_id,
                    "key": archive.storage_key,
                    "archive_hash": archive.archive_hash,
                    "content_hash": archive.source_content_hash,
                    "uncompressed": archive.uncompressed_bytes,
                    "compressed": archive.compressed_bytes,
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE raw_source_records
                    SET retention_state = 'cold', payload = NULL,
                        payload_storage_key = :key,
                        payload_archive_hash = :archive_hash,
                        payload_uncompressed_bytes = :uncompressed,
                        payload_compressed_bytes = :compressed,
                        payload_compression = 'gzip',
                        payload_archived_at = :archived,
                        retention_policy_version = 'test'
                    WHERE id = :raw
                    """
                ),
                {
                    "raw": raw_id,
                    "key": archive.storage_key,
                    "archive_hash": archive.archive_hash,
                    "uncompressed": archive.uncompressed_bytes,
                    "compressed": archive.compressed_bytes,
                    "archived": now,
                },
            )

            state = conn.execute(
                text(
                    "SELECT retention_state, payload, payload_storage_key "
                    "FROM raw_source_records WHERE id = :id"
                ),
                {"id": raw_id},
            ).one()
            assert tuple(state) == ("cold", None, archive.storage_key)

            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(
                    text(
                        "UPDATE raw_source_records "
                        "SET payload_storage_key = 'changed' WHERE id = :id"
                    ),
                    {"id": raw_id},
                )
            with pytest.raises(DBAPIError), conn.begin_nested():
                conn.execute(
                    text(
                        "DELETE FROM raw_payload_archive_events "
                        "WHERE raw_source_record_id = :id"
                    ),
                    {"id": raw_id},
                )

            # Reappearance of identical source content may rehydrate the
            # payload, but cannot erase or rewrite the verified pointer.
            conn.execute(
                text(
                    "UPDATE raw_source_records "
                    "SET retention_state = 'hot', payload = CAST(:payload AS jsonb) "
                    "WHERE id = :id"
                ),
                {"id": raw_id, "payload": json.dumps(payload)},
            )
            restored = conn.execute(
                text(
                    "SELECT retention_state, payload IS NOT NULL, "
                    "payload_storage_key FROM raw_source_records WHERE id = :id"
                ),
                {"id": raw_id},
            ).one()
            assert tuple(restored) == ("hot", True, archive.storage_key)
        finally:
            transaction.rollback()


def test_executor_purges_only_expired_superseded_payloads(engine) -> None:
    as_of = datetime(2026, 8, 11, 15, tzinfo=UTC)
    slug = f"retention-purge-{uuid.uuid4().hex}"
    source_id = _seed_source(engine, slug)
    external_id = str(uuid.uuid4())
    old_id = _insert_raw(
        engine,
        source_id=source_id,
        external_id=external_id,
        payload={"version": "old"},
        seen_at=as_of - timedelta(days=10),
    )
    current_id = _insert_raw(
        engine,
        source_id=source_id,
        external_id=external_id,
        payload={"version": "current"},
        seen_at=as_of - timedelta(hours=1),
    )
    policy = RawRetentionPolicy(
        version="test-purge-v1",
        mode="active",
        # Keep unrelated rows left by other isolated integration tests out of
        # this one-row batch; only this test source uses the seven-day TTL.
        default_hot_days=36_500,
        source_hot_days={slug: 7},
        maximum_rows_per_run=1,
    )

    result = RawRetentionExecutor(engine, policy).purge(as_of=as_of)

    assert result["purged_rows"] == 1
    assert result["raw_source_record_ids"] == [old_id]
    assert result["more_may_be_eligible"] is True
    with engine.connect() as conn:
        old = conn.execute(
            text(
                "SELECT retention_state, payload, payload_purged_at, "
                "purge_policy_version FROM raw_source_records WHERE id = :id"
            ),
            {"id": old_id},
        ).one()
        current = conn.execute(
            text(
                "SELECT retention_state, payload IS NOT NULL "
                "FROM raw_source_records WHERE id = :id"
            ),
            {"id": current_id},
        ).one()
        event_count = conn.execute(
            text(
                "SELECT count(*) FROM raw_payload_purge_events "
                "WHERE raw_source_record_id = :id"
            ),
            {"id": old_id},
        ).scalar_one()
    assert old[0] == "purged"
    assert old[1] is None
    assert old[2] is not None
    assert old[3] == "test-purge-v1"
    assert tuple(current) == ("hot", True)
    assert event_count == 1

    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE raw_source_records SET retention_state = 'purged', "
                "payload = NULL, payload_purged_at = :now, "
                "purge_policy_version = 'bypass' WHERE id = :id"
            ),
            {"id": current_id, "now": as_of},
        )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM raw_payload_purge_events "
                "WHERE raw_source_record_id = :id"
            ),
            {"id": old_id},
        )

    # Identical content may reappear. The adapter clears purge metadata and
    # starts a new hot cycle while the prior audit event remains immutable.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE raw_source_records SET retention_state = 'hot', "
                "payload = '{\"version\": \"old\"}'::jsonb, "
                "payload_purged_at = NULL, purge_policy_version = NULL "
                "WHERE id = :id"
            ),
            {"id": old_id},
        )
    with engine.connect() as conn:
        restored = conn.execute(
            text(
                "SELECT retention_state, payload IS NOT NULL "
                "FROM raw_source_records WHERE id = :id"
            ),
            {"id": old_id},
        ).one()
    assert tuple(restored) == ("hot", True)


def test_executor_purges_multiple_payloads_as_one_batch(engine) -> None:
    as_of = datetime(2026, 8, 11, 15, 30, tzinfo=UTC)
    slug = f"retention-purge-batch-{uuid.uuid4().hex}"
    source_id = _seed_source(engine, slug)
    old_ids: list[str] = []
    current_ids: list[str] = []
    for index in range(3):
        external_id = str(uuid.uuid4())
        old_ids.append(
            _insert_raw(
                engine,
                source_id=source_id,
                external_id=external_id,
                payload={"version": "old", "index": index},
                seen_at=as_of - timedelta(days=10, minutes=index),
            )
        )
        current_ids.append(
            _insert_raw(
                engine,
                source_id=source_id,
                external_id=external_id,
                payload={"version": "current", "index": index},
                seen_at=as_of - timedelta(hours=1),
            )
        )
    policy = RawRetentionPolicy(
        version="test-purge-batch-v1",
        mode="active",
        default_hot_days=36_500,
        source_hot_days={slug: 7},
        maximum_rows_per_run=3,
    )

    result = RawRetentionExecutor(engine, policy).purge(as_of=as_of)

    assert result["purged_rows"] == 3
    assert set(result["raw_source_record_ids"]) == set(old_ids)
    with engine.connect() as conn:
        purged = conn.execute(
            text(
                "SELECT count(*) FROM raw_source_records "
                "WHERE id = ANY(CAST(:ids AS uuid[])) "
                "AND retention_state = 'purged' AND payload IS NULL"
            ),
            {"ids": old_ids},
        ).scalar_one()
        current = conn.execute(
            text(
                "SELECT count(*) FROM raw_source_records "
                "WHERE id = ANY(CAST(:ids AS uuid[])) "
                "AND retention_state = 'hot' AND payload IS NOT NULL"
            ),
            {"ids": current_ids},
        ).scalar_one()
        audit_events = conn.execute(
            text(
                "SELECT count(*) FROM raw_payload_purge_events "
                "WHERE raw_source_record_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": old_ids},
        ).scalar_one()
    assert purged == 3
    assert current == 3
    assert audit_events == 3


def test_executor_keeps_current_representation_for_each_record_type(engine) -> None:
    as_of = datetime(2026, 8, 11, 16, tzinfo=UTC)
    slug = f"retention-identity-{uuid.uuid4().hex}"
    source_id = _seed_source(engine, slug)
    shared_external_id = str(uuid.uuid4())
    event_id = _insert_raw(
        engine,
        source_id=source_id,
        external_id=shared_external_id,
        payload={"kind": "event"},
        seen_at=as_of - timedelta(days=10),
        record_type="event",
    )
    market_id = _insert_raw(
        engine,
        source_id=source_id,
        external_id=shared_external_id,
        payload={"kind": "market"},
        seen_at=as_of - timedelta(hours=1),
        record_type="market",
    )
    policy = RawRetentionPolicy(
        version="test-record-type-identity",
        mode="active",
        default_hot_days=36_500,
        source_hot_days={slug: 7},
        maximum_rows_per_run=10,
    )

    result = RawRetentionExecutor(engine, policy).purge(as_of=as_of)

    assert result["purged_rows"] == 0
    with engine.connect() as conn:
        states = conn.execute(
            text(
                "SELECT id, retention_state, payload IS NOT NULL "
                "FROM raw_source_records WHERE id IN (:event, :market)"
            ),
            {"event": event_id, "market": market_id},
        ).all()
    assert {tuple(row[1:]) for row in states} == {("hot", True)}
