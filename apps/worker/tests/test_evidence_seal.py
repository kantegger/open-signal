"""Synchronous public evidence seal and Composer database gate."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from open_signal.api.presenters import ClaimPagePresenter
from open_signal.claims.evidence_seal import EvidenceSealService
from open_signal.claims.verification import ClaimVerifier
from open_signal.composer.edition_writer import EditionWriter
from open_signal.sources.artifact_store import ArtifactStore
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


class MemoryStore(ArtifactStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key, data, *, content_type=None):
        assert content_type == "application/json; charset=utf-8"
        self.objects[key] = data

    def get(self, key):
        return self.objects[key]

    def exists(self, key):
        return key in self.objects

    def delete(self, key):
        self.objects.pop(key, None)

    def sign_url(self, key, expires_in=3600):
        del expires_in
        return f"memory://{key}"


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            # Test-only teardown uses TRUNCATE because the production contract
            # intentionally rejects row-level deletion of sealed receipts.
            conn.execute(text("TRUNCATE daily_editions CASCADE"))
            conn.execute(text("TRUNCATE evidence_seals"))
            conn.execute(text("TRUNCATE claims CASCADE"))
            conn.execute(text("DELETE FROM evidence_bundles"))
        engine.dispose()


def _seed_claim(engine, *, status: str = "draft") -> tuple[str, str]:
    suffix = uuid.uuid4().hex
    desk = f"seal-desk-{suffix}"
    lineage = f"seal-lineage-{suffix}"
    bundle_hash = hashlib.sha256(suffix.encode()).hexdigest()
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agent_desks
                  (id, title, editorial_mission, charter_version, maturity)
                VALUES (:desk, 'Seal test', 'Verify evidence sealing', 'v1', 'shadow')
                """
            ),
            {"desk": desk},
        )
        conn.execute(
            text(
                """
                INSERT INTO agent_lineages
                  (id, desk_id, name, foundation_model, model_version,
                   charter_id, charter_version, toolset_version,
                   context_builder_version, status, activated_at)
                VALUES
                  (:lineage, :desk, 'Seal test', 'deterministic', 'v1',
                   'seal-test', 'v1', 'v1', 'v1', 'active', :now)
                """
            ),
            {"lineage": lineage, "desk": desk, "now": now},
        )
        run_id = conn.execute(
            text(
                """
                INSERT INTO investigation_runs
                  (desk_id, section_id, capability_id, agent_lineage_id,
                   model_version, charter_version, status)
                VALUES
                  (:desk, 'expectations-moved', 'expectation.probability-change',
                   :lineage, 'v1', 'v1', 'completed')
                RETURNING id
                """
            ),
            {"desk": desk, "lineage": lineage},
        ).scalar_one()
        calculation_id = conn.execute(
            text(
                """
                INSERT INTO calculation_records
                  (calculation_type, subject_id, subject_type, input_snapshot,
                   output, calculation_version, calculated_at)
                VALUES
                  ('probability_move', :subject, 'source_market',
                   '{"start": 0.41, "end": 0.57}'::jsonb,
                   '{"delta_percentage_points": 16.0}'::jsonb, 'v1', :now)
                RETURNING id
                """
            ),
            {"subject": uuid.uuid4(), "now": now},
        ).scalar_one()
        bundle_id = conn.execute(
            text(
                """
                INSERT INTO evidence_bundles
                  (primary_evidence, supporting_evidence, counter_evidence,
                   data_calculation_ids, source_coverage, snapshot_hash)
                VALUES
                  (CAST(:primary AS jsonb), '[]'::jsonb, '[]'::jsonb,
                   ARRAY[:calculation]::uuid[],
                   '{"sources": 1, "source": "fixture"}'::jsonb, :hash)
                RETURNING id
                """
            ),
            {
                "primary": json.dumps(
                    [
                        {
                            "title": "Observed probability series",
                            "points": [
                                ["2026-08-11T00:00:00+00:00", 0.41],
                                ["2026-08-11T01:00:00+00:00", 0.57],
                            ],
                        }
                    ]
                ),
                "calculation": calculation_id,
                "hash": bundle_hash,
            },
        ).scalar_one()
        claim_id = conn.execute(
            text(
                """
                INSERT INTO claims
                  (institution_id, desk_id, agent_lineage_id, model_version,
                   charter_version, run_id, section_id, capability_id,
                   claim_type, public_statement, structured_proposition,
                   confidence, epistemic_status, evidence_bundle_id,
                   evidence_snapshot_hash, evidence_policy_version, issued_at,
                   status)
                VALUES
                  ('open-signal', :desk, :lineage, 'v1', 'v1', :run,
                   'expectations-moved', 'expectation.probability-change',
                   'derived_observation', 'Probability increased by 16 points.',
                   CAST(:proposition AS jsonb), 0.9, 'derived', :bundle,
                   :hash, 'sealed-v1', :now, :status)
                RETURNING id
                """
            ),
            {
                "desk": desk,
                "lineage": lineage,
                "run": run_id,
                "proposition": json.dumps(
                    {
                        "subject_ids": [str(uuid.uuid4())],
                        "value": 16.0,
                    }
                ),
                "bundle": bundle_id,
                "hash": bundle_hash,
                "now": now,
                "status": status,
            },
        ).scalar_one()
    return str(claim_id), str(bundle_id)


def _candidate(claim_id: str, bundle_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": "time-series.probability-move",
        "section_id": "expectations-moved",
        "slot_id": "secondary",
        "headline": "Probability increased by 16 points.",
        "display_fields": {
            "expectation_title": "Will the fixture resolve?",
            "current_probability": 0.57,
            "start_probability": 0.41,
            "delta_percentage_points": 16.0,
            "window": "24h",
            "series": [],
            "source_name": "Fixture",
            "updated_at": datetime.now(UTC).isoformat(),
        },
        "evidence_bundle_id": bundle_id,
    }


def test_verifier_seals_before_claim_becomes_verified(engine) -> None:
    claim_id, bundle_id = _seed_claim(engine)
    store = MemoryStore()
    verifier = ClaimVerifier(
        engine,
        evidence_sealer=EvidenceSealService(engine, store),
    )

    assert verifier.gate_for_composer(claim_id) is True
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM claims WHERE id = :claim"),
            {"claim": claim_id},
        ).scalar_one()
        seal = conn.execute(
            text(
                "SELECT storage_key, object_hash, byte_size "
                "FROM evidence_seals WHERE evidence_bundle_id = :bundle"
            ),
            {"bundle": bundle_id},
        ).one()

    assert status == "verified"
    assert seal[0] == f"public/evidence/v1/{seal[1]}.json"
    body = store.get(seal[0])
    assert len(body) == seal[2]
    assert hashlib.sha256(body).hexdigest() == seal[1]
    payload = json.loads(body)
    assert payload["contract"] == "open-signal.public-evidence/v1"
    assert payload["calculations"][0]["output"]["delta_percentage_points"] == 16.0
    page = ClaimPagePresenter(engine).build(claim_id)
    assert page is not None
    assert page["claim"]["evidence_policy_version"] == "sealed-v1"
    assert page["evidence_record"]["object_key"] == seal[0]
    assert page["evidence_record"]["object_hash"] == seal[1]

    second = verifier.evidence_sealer.seal_claim(claim_id)
    assert second["status"] == "sealed"
    assert len(store.objects) == 1

    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text("UPDATE evidence_seals SET actor = 'changed' WHERE evidence_bundle_id = :bundle"),
            {"bundle": bundle_id},
        )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text("UPDATE evidence_bundles SET source_coverage = '{}'::jsonb WHERE id = :bundle"),
            {"bundle": bundle_id},
        )


def test_public_edition_rejects_unsealed_cutover_claim(engine) -> None:
    claim_id, bundle_id = _seed_claim(engine, status="verified")
    candidate = _candidate(claim_id, bundle_id)

    with pytest.raises(DBAPIError, match="requires sealed evidence"):
        EditionWriter(engine).build_edition([candidate])

    EvidenceSealService(engine, MemoryStore()).seal_claim(claim_id)
    published = EditionWriter(engine).build_edition([candidate])
    assert published["claim_ids"] == [claim_id]

    # A later Claim version cannot reuse the first version's receipt. The
    # effective bundle follows current_version_id throughout seal, API, and
    # the database publication trigger.
    next_hash = hashlib.sha256(f"next:{claim_id}".encode()).hexdigest()
    with engine.begin() as conn:
        next_bundle = conn.execute(
            text(
                """
                INSERT INTO evidence_bundles
                  (primary_evidence, supporting_evidence, counter_evidence,
                   data_calculation_ids, source_coverage, snapshot_hash)
                VALUES
                  ('[{"title": "Updated observed series"}]'::jsonb,
                   '[]'::jsonb, '[]'::jsonb, ARRAY[]::uuid[],
                   '{"sources": 1}'::jsonb, :hash)
                RETURNING id
                """
            ),
            {"hash": next_hash},
        ).scalar_one()
        version_id = conn.execute(
            text(
                """
                INSERT INTO claim_versions
                  (claim_id, version_number, public_statement,
                   structured_proposition, confidence, evidence_bundle_id,
                   change_type, change_reason)
                SELECT id, 1, public_statement, structured_proposition,
                       confidence, :bundle, 'update', 'new evidence'
                FROM claims WHERE id = :claim
                RETURNING id
                """
            ),
            {"bundle": next_bundle, "claim": claim_id},
        ).scalar_one()
        conn.execute(
            text("UPDATE claims SET current_version_id = :version WHERE id = :claim"),
            {"version": version_id, "claim": claim_id},
        )

    updated_candidate = {**candidate, "evidence_bundle_id": str(next_bundle)}
    with pytest.raises(DBAPIError, match="requires sealed evidence"):
        EditionWriter(engine).build_edition([updated_candidate])

    updated_seal = EvidenceSealService(engine, MemoryStore()).seal_claim(claim_id)
    assert updated_seal["snapshot_hash"] == next_hash
    updated_page = ClaimPagePresenter(engine).build(claim_id)
    assert updated_page is not None
    assert updated_page["evidence_record"]["object_hash"] == updated_seal["object_hash"]
    EditionWriter(engine).build_edition([updated_candidate])
