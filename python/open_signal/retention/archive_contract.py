"""Deterministic, content-addressed raw payload archive objects.

This module does not perform an upload or a database update.  It defines the
bytes that a future executor must write to private R2 and the verification that
must succeed on bytes read back from R2 before a hot payload can be cleared.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
from dataclasses import dataclass
from typing import Any

_SOURCE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RawPayloadArchiveObject:
    raw_source_record_id: str
    source_slug: str
    storage_key: str
    source_content_hash: str
    archive_hash: str
    uncompressed_bytes: int
    compressed_bytes: int
    compression: str
    body: bytes

    def event_fields(self, *, policy_version: str) -> dict[str, Any]:
        """Return the exact fields required by raw_payload_archive_events."""
        return {
            "raw_source_record_id": self.raw_source_record_id,
            "storage_key": self.storage_key,
            "archive_hash": self.archive_hash,
            "source_content_hash": self.source_content_hash,
            "uncompressed_bytes": self.uncompressed_bytes,
            "compressed_bytes": self.compressed_bytes,
            "compression": self.compression,
            "policy_version": policy_version,
        }


def build_archive_object(
    *,
    raw_source_record_id: str,
    source_slug: str,
    content_hash: str,
    payload: Any,
    object_prefix: str = "raw-payload/v1",
) -> RawPayloadArchiveObject:
    """Build deterministic gzip bytes and a content-addressed private key."""
    if not _SOURCE_SLUG.fullmatch(source_slug):
        raise ValueError("source_slug is not safe for an object key")
    if not _SHA256.fullmatch(content_hash):
        raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
    prefix = object_prefix.strip("/")
    if not prefix or ".." in prefix.split("/"):
        raise ValueError("object_prefix is not safe")

    canonical_payload = _canonical_payload(payload)
    calculated_source_hash = hashlib.sha256(canonical_payload).hexdigest()
    if calculated_source_hash != content_hash:
        raise ValueError(
            "payload does not reproduce raw_source_records.content_hash"
        )
    compressed_buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=compressed_buffer,
        mtime=0,
    ) as archive_file:
        archive_file.write(canonical_payload)
    compressed = compressed_buffer.getvalue()
    archive_hash = hashlib.sha256(compressed).hexdigest()
    storage_key = (
        f"{prefix}/{source_slug}/sha256/{content_hash[:2]}/"
        f"{content_hash}.json.gz"
    )
    return RawPayloadArchiveObject(
        raw_source_record_id=raw_source_record_id,
        source_slug=source_slug,
        storage_key=storage_key,
        source_content_hash=content_hash,
        archive_hash=archive_hash,
        uncompressed_bytes=len(canonical_payload),
        compressed_bytes=len(compressed),
        compression="gzip",
        body=compressed,
    )


def verify_archive_bytes(
    archive: RawPayloadArchiveObject,
    downloaded: bytes,
) -> Any:
    """Verify bytes read back from object storage and return the JSON payload."""
    if len(downloaded) != archive.compressed_bytes:
        raise ValueError("archive compressed size mismatch")
    if hashlib.sha256(downloaded).hexdigest() != archive.archive_hash:
        raise ValueError("archive object hash mismatch")
    try:
        payload_bytes = gzip.decompress(downloaded)
    except (OSError, EOFError) as exc:
        raise ValueError("archive object is not valid gzip") from exc
    if len(payload_bytes) != archive.uncompressed_bytes:
        raise ValueError("archive uncompressed size mismatch")
    if hashlib.sha256(payload_bytes).hexdigest() != archive.source_content_hash:
        raise ValueError("archive source content hash mismatch")
    try:
        return json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("archive payload is not valid UTF-8 JSON") from exc


def _canonical_payload(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
