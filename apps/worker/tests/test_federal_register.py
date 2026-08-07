"""Federal Register source chain tests (OS-012). Discovery/artifact paths use
fixtures (offline); storage requires a real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from open_signal.sources.artifact_repo import ArtifactRepository
from open_signal.sources.artifact_store import LocalArtifactStore
from open_signal.sources.federal_register import (
    FIXTURE_DIR,
    FederalRegisterChain,
    FederalRegisterClient,
)

TEST_SOURCE = "federal-register-test"


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_source(engine, slug: str) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM sources WHERE slug = :s"), {"s": slug}).fetchone()
        if row:
            return str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO sources (slug, name, category, authority_level, "
                "access_mode, adapter_id, status) "
                "VALUES (:s, :name, 'government_regulation', 'official_government', "
                "'rest', 'federal-register-v1', 'active') RETURNING id"
            ),
            {"s": slug, "name": slug},
        ).fetchone()
        return str(row[0])


@pytest.fixture()
def chain(engine, tmp_path) -> FederalRegisterChain:
    source_uuid = _seed_source(engine, TEST_SOURCE)
    store = LocalArtifactStore(tmp_path / "objects")
    repo = ArtifactRepository(store, engine=engine)
    return FederalRegisterChain(
        engine,
        source_id=source_uuid,
        artifact_repo=repo,
        fixture_dir=tmp_path / "fr",
        offline=True,
    )


def _copy_fixtures(tmp_path) -> Path:
    dest = tmp_path / "fr"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("documents_page_1.json", "documents_page_2.json", "document_sample.html"):
        src = FIXTURE_DIR / name
        if src.exists():
            (dest / name).write_bytes(src.read_bytes())
    return dest


def _cleanup(chain, engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM raw_artifacts WHERE raw_source_record_id IN "
                "(SELECT id FROM raw_source_records WHERE source_id = :s)"
            ),
            {"s": chain.source_id},
        )
        conn.execute(text("DELETE FROM raw_source_records WHERE source_id = :s"), {"s": chain.source_id})


# ------------------------------------------------------------------- discovery


def test_discover_stores_documents_idempotent(chain: FederalRegisterChain, engine) -> None:
    from sqlalchemy import text

    _cleanup(chain, engine)
    chain.fixture_dir = _copy_fixtures(Path(chain.fixture_dir).parent)

    first = chain.discover(max_pages=2, per_page=10)
    second = chain.discover(max_pages=2, per_page=10)  # same fixtures
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM raw_source_records WHERE source_id = :s"),
            {"s": chain.source_id},
        ).scalar_one()
    assert first["documents"] >= 10
    assert second["documents"] == 0
    assert count == first["documents"]

    # payload fields preserved
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT payload, source_created_at FROM raw_source_records "
                "WHERE source_id = :s LIMIT 1"
            ),
            {"s": chain.source_id},
        ).fetchone()
    assert row[0]["type"] in ("Rule", "RULE")
    assert row[1] is not None  # publication date mapped


def test_latest_publication_date(chain: FederalRegisterChain, engine) -> None:
    from sqlalchemy import text

    _cleanup(chain, engine)
    chain.fixture_dir = _copy_fixtures(Path(chain.fixture_dir).parent)
    chain.discover(max_pages=1)
    latest = chain.latest_publication_date()
    assert latest is not None
    assert latest.startswith("2026-")


# ------------------------------------------------------------------- artifact


def test_fetch_artifact_public_content_addressed(chain: FederalRegisterChain, engine) -> None:
    from sqlalchemy import text

    _cleanup(chain, engine)
    chain.fixture_dir = _copy_fixtures(Path(chain.fixture_dir).parent)
    chain.discover(max_pages=1)

    with engine.connect() as conn:
        record = conn.execute(
            text("SELECT id, payload FROM raw_source_records WHERE source_id = :s LIMIT 1"),
            {"s": chain.source_id},
        ).fetchone()
    raw_id = str(record[0])
    html_url = record[1]["html_url"]

    result = chain.fetch_artifact(
        raw_source_record_id=raw_id, html_url=html_url, source_id=chain.source_id
    )
    assert result["artifact_id"] is not None
    assert result["byte_size"] > 100
    assert result["content_hash"]
    assert result["storage_key"].startswith("public/")

    # dedup: same content -> same artifact
    again = chain.fetch_artifact(
        raw_source_record_id=raw_id, html_url=html_url, source_id=chain.source_id
    )
    assert again["artifact_id"] == result["artifact_id"]


# ------------------------------------------------------------------- fixtures


def test_save_fixture_roundtrip(tmp_path) -> None:
    chain = FederalRegisterChain(None, fixture_dir=tmp_path)
    data = {"count": 1, "results": [{"document_number": "2026-00001"}]}
    path = chain.save_fixture(1, data)
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    assert loaded == data
