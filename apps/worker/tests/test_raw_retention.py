"""Raw payload report-only retention and cold-storage safety boundary."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.retention import (
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
                      (:source, :external, 'fixture', 'application/json',
                       CAST(:payload AS jsonb), :seen, :seen, :seen, :hash,
                       'retention-test', 'active')
                    RETURNING id
                    """
                ),
                {
                    "source": source_id,
                    "external": external_id,
                    "payload": json.dumps(payload),
                    "seen": seen_at,
                    "hash": _canonical_hash(payload),
                },
            ).scalar_one()
        )


def _source_report(report: dict, slug: str) -> dict:
    return next(item for item in report["sources"] if item["source_slug"] == slug)


def test_policy_is_explicitly_report_only() -> None:
    policy = RawRetentionPolicy.load()

    assert policy.mode == "report_only"
    assert policy.hot_days_for("polymarket-gamma") == 7
    assert policy.hot_days_for("unknown-source") == 30
    assert policy.compression == "gzip"

    with pytest.raises(ValueError, match="report_only"):
        RawRetentionPolicy(version="bad", mode="execute").validate()


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
