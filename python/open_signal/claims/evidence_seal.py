"""Synchronous, content-addressed sealing for public Claim evidence.

The sealed object is deliberately smaller than a raw source payload.  It is
the public-safe, reproducible Evidence Bundle plus the exact Calculation
Records used by the Claim.  R2 read-back succeeds before the append-only
database receipt is written, so Composer can use the receipt as a hard gate.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from open_signal.sources.artifact_store import (
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
)

CLAIM_EVIDENCE_POLICY = "sealed-v1"
SEAL_POLICY_VERSION = "1.0.0"
CONTENT_TYPE = "application/json; charset=utf-8"
OBJECT_PREFIX = "public/evidence/v1"


class EvidenceSealService:
    """Seal and verify one Claim's minimal public evidence object."""

    def __init__(self, engine: Any, store: ArtifactStore) -> None:
        self.engine = engine
        self.store = store

    def seal_claim(self, claim_id: str, *, actor: str = "claim-verifier") -> dict[str, Any]:
        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    """
                    SELECT COALESCE(
                               current_version.evidence_bundle_id,
                               claim.evidence_bundle_id
                           ) AS evidence_bundle_id,
                           bundle.snapshot_hash AS evidence_snapshot_hash,
                           claim.evidence_policy_version
                    FROM claims claim
                    LEFT JOIN claim_versions current_version
                      ON current_version.id = claim.current_version_id
                    JOIN evidence_bundles bundle
                      ON bundle.id = COALESCE(
                          current_version.evidence_bundle_id,
                          claim.evidence_bundle_id
                      )
                    WHERE claim.id = :claim
                    """
                ),
                {"claim": claim_id},
            ).mappings().one_or_none()
        if claim is None:
            raise KeyError(f"claim {claim_id} not found")
        if claim["evidence_policy_version"] != CLAIM_EVIDENCE_POLICY:
            return {
                "status": "legacy",
                "claim_id": claim_id,
                "policy_version": str(claim["evidence_policy_version"]),
            }

        bundle_id = str(claim["evidence_bundle_id"])
        snapshot_hash = str(claim["evidence_snapshot_hash"])
        existing = self._receipt(bundle_id)
        if existing is not None:
            self._verify_receipt_object(existing)
            return {"status": "sealed", "claim_id": claim_id, **existing}

        payload = self._bundle_payload(bundle_id, snapshot_hash)
        body = _json_bytes(payload)
        object_hash = hashlib.sha256(body).hexdigest()
        storage_key = f"{OBJECT_PREFIX}/{object_hash}.json"

        if self.store.exists(storage_key):
            stored = self.store.get(storage_key)
            if stored != body:
                raise RuntimeError(f"immutable evidence object changed: {storage_key}")
        else:
            self.store.put(storage_key, body, content_type=CONTENT_TYPE)
        if self.store.get(storage_key) != body:
            raise RuntimeError(f"evidence read-back verification failed: {storage_key}")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO evidence_seals
                      (evidence_bundle_id, snapshot_hash, object_hash,
                       storage_key, byte_size, content_type, policy_version,
                       actor, detail)
                    VALUES
                      (:bundle, :snapshot, :object_hash, :storage_key,
                       :byte_size, :content_type, :policy, :actor,
                       CAST(:detail AS jsonb))
                    ON CONFLICT (evidence_bundle_id) DO NOTHING
                    """
                ),
                {
                    "bundle": bundle_id,
                    "snapshot": snapshot_hash,
                    "object_hash": object_hash,
                    "storage_key": storage_key,
                    "byte_size": len(body),
                    "content_type": CONTENT_TYPE,
                    "policy": SEAL_POLICY_VERSION,
                    "actor": actor,
                    "detail": json.dumps(
                        {
                            "claim_id": claim_id,
                            "verification": "r2-read-back-sha256",
                        }
                    ),
                },
            )

        receipt = self._receipt(bundle_id)
        if receipt is None:
            raise RuntimeError(f"evidence seal receipt missing for bundle {bundle_id}")
        expected = {
            "snapshot_hash": snapshot_hash,
            "object_hash": object_hash,
            "storage_key": storage_key,
            "byte_size": len(body),
        }
        if any(receipt[key] != value for key, value in expected.items()):
            raise RuntimeError(f"conflicting evidence seal receipt for bundle {bundle_id}")
        return {"status": "sealed", "claim_id": claim_id, **receipt}

    def _bundle_payload(self, bundle_id: str, snapshot_hash: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            bundle = conn.execute(
                text(
                    """
                    SELECT id, primary_evidence, supporting_evidence,
                           counter_evidence, data_calculation_ids,
                           source_coverage, unresolved_questions,
                           known_limitations, snapshot_hash, created_at
                    FROM evidence_bundles
                    WHERE id = :bundle
                    """
                ),
                {"bundle": bundle_id},
            ).mappings().one_or_none()
            if bundle is None:
                raise RuntimeError(f"evidence bundle {bundle_id} not found")
            if str(bundle["snapshot_hash"]) != snapshot_hash:
                raise RuntimeError(
                    f"claim snapshot does not match evidence bundle {bundle_id}"
                )

            calculations: list[dict[str, Any]] = []
            for calculation_id in bundle["data_calculation_ids"] or []:
                calculation = conn.execute(
                    text(
                        """
                        SELECT id, calculation_type, subject_id, subject_type,
                               input_snapshot, output, calculation_version,
                               calculated_at
                        FROM calculation_records
                        WHERE id = :calculation
                        """
                    ),
                    {"calculation": calculation_id},
                ).mappings().one_or_none()
                if calculation is None:
                    raise RuntimeError(
                        f"evidence bundle {bundle_id} references missing "
                        f"calculation {calculation_id}"
                    )
                calculations.append(dict(calculation))

        return {
            "contract": "open-signal.public-evidence/v1",
            "bundle_id": bundle_id,
            "snapshot_hash": snapshot_hash,
            "created_at": bundle["created_at"],
            "primary_evidence": bundle["primary_evidence"] or [],
            "supporting_evidence": bundle["supporting_evidence"] or [],
            "counter_evidence": bundle["counter_evidence"] or [],
            "source_coverage": bundle["source_coverage"] or {},
            "unresolved_questions": list(bundle["unresolved_questions"] or []),
            "known_limitations": list(bundle["known_limitations"] or []),
            "calculations": calculations,
        }

    def _receipt(self, bundle_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT snapshot_hash, object_hash, storage_key, byte_size,
                           content_type, policy_version, actor, sealed_at
                    FROM evidence_seals
                    WHERE evidence_bundle_id = :bundle
                    """
                ),
                {"bundle": bundle_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        result = dict(row)
        result["byte_size"] = int(result["byte_size"])
        result["sealed_at"] = result["sealed_at"].isoformat()
        return result

    def _verify_receipt_object(self, receipt: dict[str, Any]) -> None:
        key = str(receipt["storage_key"])
        if not self.store.exists(key):
            raise RuntimeError(f"sealed evidence object missing: {key}")
        body = self.store.get(key)
        if len(body) != int(receipt["byte_size"]):
            raise RuntimeError(f"sealed evidence size mismatch: {key}")
        if hashlib.sha256(body).hexdigest() != receipt["object_hash"]:
            raise RuntimeError(f"sealed evidence hash mismatch: {key}")


def from_environment(engine: Any) -> EvidenceSealService:
    """Build the R2 adapter in production and a persistent local store in dev."""

    values = {
        "endpoint_url": os.environ.get("OPEN_SIGNAL_R2_ENDPOINT_URL"),
        "access_key": os.environ.get("OPEN_SIGNAL_R2_ACCESS_KEY_ID"),
        "secret_key": os.environ.get("OPEN_SIGNAL_R2_SECRET_ACCESS_KEY"),
        "bucket": os.environ.get("OPEN_SIGNAL_R2_PUBLIC_BUCKET"),
    }
    if any(values.values()):
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(
                "incomplete evidence seal configuration: " + ", ".join(missing)
            )
        store: ArtifactStore = S3ArtifactStore(
            str(values["bucket"]),
            endpoint_url=str(values["endpoint_url"]),
            aws_access_key_id=str(values["access_key"]),
            aws_secret_access_key=str(values["secret_key"]),
            region_name="auto",
        )
    else:
        root = Path(
            os.environ.get("OPEN_SIGNAL_LOCAL_ARTIFACT_ROOT")
            or ".open-signal-artifacts"
        )
        store = LocalArtifactStore(root)
    return EvidenceSealService(engine, store)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
