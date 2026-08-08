"""OpenAlex + ClinicalTrials research source tests (OS-020).

Topic definitions and baseline queries are DB-free; discovery storage
requires a real PostgreSQL via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001).
Fixtures were captured from the live APIs.
"""

import os

import pytest
from open_signal.sources.clinicaltrials import ClinicalTrialsChain
from open_signal.sources.openalex import OpenAlexChain, OpenAlexClient


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
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
                "VALUES (:s, :name, :cat, 'open_aggregator', 'rest', :adapter, 'active') RETURNING id"
            ),
            {"s": slug, "name": slug, "cat": "scholarly_metadata" if "openalex" in slug else "clinical_registry", "adapter": "v1"},
        ).fetchone()
        return str(row[0])


def _cleanup(engine, source_id: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM raw_source_records WHERE source_id = :s"), {"s": source_id})


# ------------------------------------------------------------ topic definitions


def test_topic_definitions_frozen() -> None:
    chain = OpenAlexChain(None)
    topics = {t["id"] for t in chain.list_topics()}
    assert topics == {"oncology-immunotherapy", "synthetic-biology", "generative-ai", "quantum-computing"}
    assert chain.baseline_query("oncology-immunotherapy") == "CAR-T OR checkpoint inhibitor OR tumor immunotherapy"


def test_baseline_queries_present_for_all_topics() -> None:
    chain = OpenAlexChain(None)
    for topic in chain.list_topics():
        assert chain.baseline_query(topic["id"]), f"missing openalex query for {topic['id']}"
    ct = ClinicalTrialsChain(None)
    # oncology + synthetic biology have clinical queries; AI/quantum do not
    assert ct.baseline_query("oncology-immunotherapy") == "immunotherapy AND cancer"
    assert ct.baseline_query("generative-ai") is None


# --------------------------------------------------------- OpenAlex discovery


@pytest.fixture()
def oa_chain(engine, tmp_path) -> OpenAlexChain:
    source_uuid = _seed_source(engine, "openalex")
    chain = OpenAlexChain(
        engine,
        source_id=source_uuid,
        fixture_dir=tmp_path / "oa",
        offline=True,
    )
    _copy_fixtures(tmp_path / "oa", "openalex", ("oncology-immunotherapy_page_1.json",))
    return chain


def _copy_fixtures(dest, src_name: str, names: tuple[str, ...]) -> None:
    from pathlib import Path

    import open_signal.sources.openalex as m

    dest.mkdir(parents=True, exist_ok=True)
    base = Path(m.__file__).resolve().parents[3] / "fixtures" / src_name
    for name in names:
        src = base / name
        if src.exists():
            (dest / name).write_bytes(src.read_bytes())


def test_openalex_discover_topic(oa_chain: OpenAlexChain, engine) -> None:
    _cleanup(engine, oa_chain.source_id)
    result = oa_chain.discover_topic(topic_id="oncology-immunotherapy", max_pages=1)
    assert result["works"] == 5

    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT payload, source_created_at FROM raw_source_records "
                "WHERE source_id = :s LIMIT 1"
            ),
            {"s": oa_chain.source_id},
        ).fetchone()
    assert row[0]["type"] == "article"
    assert row[1] is not None


def test_openalex_discover_idempotent(oa_chain: OpenAlexChain, engine) -> None:
    _cleanup(engine, oa_chain.source_id)
    first = oa_chain.discover_topic(topic_id="oncology-immunotherapy", max_pages=1)
    second = oa_chain.discover_topic(topic_id="oncology-immunotherapy", max_pages=1)
    assert first["works"] == 5
    assert second["works"] == 0


def test_openalex_health_live() -> None:
    client = OpenAlexClient()
    try:
        assert client.health_check() is True
    finally:
        client.close()


# ------------------------------------------------- ClinicalTrials discovery


@pytest.fixture()
def ct_chain(engine, tmp_path) -> ClinicalTrialsChain:
    source_uuid = _seed_source(engine, "clinicaltrials-gov")
    chain = ClinicalTrialsChain(
        engine,
        source_id=source_uuid,
        fixture_dir=tmp_path / "ct",
        offline=True,
    )
    dest = tmp_path / "ct"
    dest.mkdir(parents=True, exist_ok=True)
    from pathlib import Path

    import open_signal.sources.clinicaltrials as m

    base = Path(m.__file__).resolve().parents[3] / "fixtures" / "clinicaltrials"
    for name in ("immunotherapy-and-cancer.json",):
        src = base / name
        if src.exists():
            (dest / name).write_bytes(src.read_bytes())
    return chain


def test_clinicaltrials_discover(ct_chain: ClinicalTrialsChain, engine) -> None:
    _cleanup(engine, ct_chain.source_id)
    result = ct_chain.discover_topic(topic_id="oncology-immunotherapy")
    assert result["studies"] == 3
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT external_id, payload FROM raw_source_records "
                "WHERE source_id = :s LIMIT 1"
            ),
            {"s": ct_chain.source_id},
        ).fetchone()
    assert row[0].startswith("NCT")
    assert row[1]["protocolSection"]["identificationModule"]["nctId"] == row[0]


def test_clinicaltrials_skips_ai_topic(ct_chain: ClinicalTrialsChain, engine) -> None:
    result = ct_chain.discover_topic(topic_id="generative-ai")
    assert result["studies"] == 0
    assert result["skipped"] == 1
