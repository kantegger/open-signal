"""raw_artifacts repository over an ArtifactStore (spec §95, OS-006).

Stores bytes content-addressed in the object store and keeps the
``raw_artifacts`` row (content_hash, storage_key, byte_size, retention
metadata) in PostgreSQL. Deduplication: identical ``(content_hash,
artifact_type)`` reuses the existing row.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text

from open_signal.sources.artifact_store import (
    PRIVATE_BUCKET,
    PUBLIC_BUCKET,
    ArtifactStore,
    sha256_hex,
)

ARTIFACT_TYPES = ("pdf", "html", "xml", "json", "csv", "image", "text")


@dataclass
class ArtifactRecord:
    id: str
    source_id: str
    raw_source_record_id: str | None
    artifact_type: str
    storage_key: str
    content_hash: str
    byte_size: int
    fetched_at: str
    source_url: str
    rights_manifest_id: str | None
    retention_policy_id: str | None


class ArtifactRepository:
    """Combines object store bytes with the raw_artifacts table."""

    def __init__(self, store: ArtifactStore, engine: Any = None) -> None:
        self.store = store
        self.engine = engine or create_engine(os.environ["OPEN_SIGNAL_DATABASE_URL"])

    # ------------------------------------------------------------------ write
    def store_artifact(
        self,
        *,
        source_id: str,
        artifact_type: str,
        data: bytes,
        source_url: str,
        raw_source_record_id: str | None = None,
        rights_manifest_id: str | None = None,
        retention_policy_id: str | None = None,
        public: bool = False,
    ) -> ArtifactRecord:
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"artifact_type must be one of {ARTIFACT_TYPES}")

        content_hash = sha256_hex(data)
        bucket = PUBLIC_BUCKET if public else PRIVATE_BUCKET
        storage_key = f"{bucket}/{content_hash}"

        # Content-addressed deduplication at the store level.
        if not self.store.exists(storage_key):
            self.store.put(storage_key, data, content_type=_mime(artifact_type))

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO raw_artifacts
                      (source_id, raw_source_record_id, artifact_type, storage_key,
                       content_hash, byte_size, fetched_at, source_url,
                       rights_manifest_id, retention_policy_id)
                    VALUES
                      (:source_id, :raw_source_record_id, :artifact_type, :storage_key,
                       :content_hash, :byte_size, :fetched_at, :source_url,
                       :rights_manifest_id, :retention_policy_id)
                    ON CONFLICT (content_hash, artifact_type) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "source_id": source_id,
                    "raw_source_record_id": raw_source_record_id,
                    "artifact_type": artifact_type,
                    "storage_key": storage_key,
                    "content_hash": content_hash,
                    "byte_size": len(data),
                    "fetched_at": datetime.now(timezone.utc),
                    "source_url": source_url,
                    "rights_manifest_id": rights_manifest_id,
                    "retention_policy_id": retention_policy_id,
                },
            ).fetchone()
            if row is None:  # conflict -> reuse existing row
                row = conn.execute(
                    text(
                        "SELECT id FROM raw_artifacts "
                        "WHERE content_hash = :h AND artifact_type = :t"
                    ),
                    {"h": content_hash, "t": artifact_type},
                ).fetchone()
            artifact_id = row[0]

        return self.get(artifact_id)

    # ------------------------------------------------------------------- read
    def get(self, artifact_id: str) -> ArtifactRecord:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, source_id, raw_source_record_id, artifact_type, "
                    "storage_key, content_hash, byte_size, fetched_at, source_url, "
                    "rights_manifest_id, retention_policy_id "
                    "FROM raw_artifacts WHERE id = :id"
                ),
                {"id": artifact_id},
            ).fetchone()
        if row is None:
            raise KeyError(f"artifact {artifact_id} not found")
        return ArtifactRecord(*row)

    def read_bytes(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        return self.store.get(record.storage_key)

    def signed_url(self, artifact_id: str, expires_in: int = 3600) -> str:
        record = self.get(artifact_id)
        return self.store.sign_url(record.storage_key, expires_in)

    def list_by_source(self, source_id: str, limit: int = 100) -> list[ArtifactRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, source_id, raw_source_record_id, artifact_type, "
                    "storage_key, content_hash, byte_size, fetched_at, source_url, "
                    "rights_manifest_id, retention_policy_id "
                    "FROM raw_artifacts WHERE source_id = :sid "
                    "ORDER BY fetched_at DESC LIMIT :limit"
                ),
                {"sid": source_id, "limit": limit},
            ).fetchall()
        return [ArtifactRecord(*r) for r in rows]


def _mime(artifact_type: str) -> str:
    return {
        "pdf": "application/pdf",
        "html": "text/html",
        "xml": "application/xml",
        "json": "application/json",
        "csv": "text/csv",
        "image": "application/octet-stream",
        "text": "text/plain",
    }[artifact_type]
