"""Artifact store tests (OS-006).

Store unit tests are DB-free; repository integration tests require a real
PostgreSQL via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid

import pytest
from open_signal.sources.artifact_repo import ArtifactRepository
from open_signal.sources.artifact_store import (
    LocalArtifactStore,
    S3ArtifactStore,
    sha256_hex,
)


@pytest.fixture()
def store(tmp_path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "objects", secret="test-secret")


# ------------------------------------------------------------- store (no DB)


def test_put_get_roundtrip(store: LocalArtifactStore) -> None:
    key = "private/" + sha256_hex(b"hello")
    store.put(key, b"hello", content_type="text/plain")
    assert store.get(key) == b"hello"
    assert store.exists(key)
    store.delete(key)
    assert not store.exists(key)


def test_content_addressed_dedup(store: LocalArtifactStore) -> None:
    data = b"same-content"
    key = "public/" + sha256_hex(data)
    store.put(key, data)
    store.put(key, data)  # idempotent write
    assert store.exists(key)


def test_unknown_bucket_raises(store: LocalArtifactStore) -> None:
    with pytest.raises(ValueError):
        store.put("other/abc", b"x")


def test_signed_url(store: LocalArtifactStore) -> None:
    key = "private/" + sha256_hex(b"secret-doc")
    store.put(key, b"secret-doc")
    url = store.sign_url(key, expires_in=60)
    assert store.verify_signed_url(url)
    # tampered signature
    assert not store.verify_signed_url(url[:-1] + ("0" if url[-1] != "0" else "1"))


def test_signed_url_expired(store: LocalArtifactStore) -> None:
    key = "private/" + sha256_hex(b"old")
    store.put(key, b"old")
    url = store.sign_url(key, expires_in=-1)  # already expired
    assert not store.verify_signed_url(url)


class _StorageError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code},
        }


class _HeadClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def head_object(self, **kwargs) -> None:
        del kwargs
        raise self.error


def _s3_store_with_head_error(error: _StorageError) -> S3ArtifactStore:
    store = object.__new__(S3ArtifactStore)
    store.bucket = "test"
    store._client = _HeadClient(error)
    store._client_error_type = _StorageError
    return store


def test_s3_exists_treats_only_missing_objects_as_absent() -> None:
    assert not _s3_store_with_head_error(_StorageError(404, "NotFound")).exists(
        "public/missing"
    )


def test_s3_exists_propagates_authentication_failures() -> None:
    with pytest.raises(_StorageError):
        _s3_store_with_head_error(_StorageError(403, "AccessDenied")).exists(
            "public/protected"
        )


# ------------------------------------------------------- repository (needs DB)


@pytest.fixture()
def repo(store: LocalArtifactStore):
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    engine = create_engine(url)
    return ArtifactRepository(store, engine=engine)


def _ensure_source(repo: ArtifactRepository, slug: str) -> str:
    from sqlalchemy import text

    with repo.engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM sources WHERE slug = :s"), {"s": slug}
        ).fetchone()
        if row:
            return str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO sources (slug, name, category, authority_level, "
                "access_mode, adapter_id, status) "
                "VALUES (:s, :name, 'other', 'secondary_source', 'rest', 'os006-test', 'active') "
                "RETURNING id"
            ),
            {"s": slug, "name": slug},
        ).fetchone()
        return str(row[0])


def test_store_artifact_and_dedup(repo: ArtifactRepository, store: LocalArtifactStore) -> None:
    source_id = _ensure_source(repo, f"os006-{uuid.uuid4().hex[:6]}")
    data = b"%PDF-1.4 fake document " + uuid.uuid4().hex.encode()

    a1 = repo.store_artifact(
        source_id=source_id,
        artifact_type="pdf",
        data=data,
        source_url="https://example.gov/doc.pdf",
        retention_policy_id="r1",
    )
    a2 = repo.store_artifact(
        source_id=source_id,
        artifact_type="pdf",
        data=data,
        source_url="https://example.gov/doc.pdf",
        retention_policy_id="r1",
    )
    # dedup: same content_hash -> same row
    assert a1.id == a2.id
    assert a1.content_hash == sha256_hex(data)
    assert a1.byte_size == len(data)
    assert a1.storage_key.startswith("private/")

    # bytes roundtrip
    assert repo.read_bytes(a1.id) == data

    # signed URL works and verifies for private bucket
    url = repo.signed_url(a1.id, expires_in=60)
    assert store.verify_signed_url(url)

    # list view
    listed = repo.list_by_source(source_id)
    assert any(r.id == a1.id for r in listed)


def test_public_bucket(repo: ArtifactRepository, store: LocalArtifactStore) -> None:
    source_id = _ensure_source(repo, f"os006-{uuid.uuid4().hex[:6]}")
    rec = repo.store_artifact(
        source_id=source_id,
        artifact_type="html",
        data=b"<html>public</html>",
        source_url="https://example.org/page",
        public=True,
    )
    assert rec.storage_key.startswith("public/")


def test_invalid_artifact_type(repo: ArtifactRepository) -> None:
    with pytest.raises(ValueError):
        repo.store_artifact(
            source_id="x", artifact_type="exe", data=b"", source_url="u"
        )
