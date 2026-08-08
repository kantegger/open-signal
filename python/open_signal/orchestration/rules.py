"""Conservative Federal Register state-fact publication pipeline (OS-049)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import text

from open_signal.claims.verification import ClaimVerifier
from open_signal.composer.edition_writer import EditionWriter
from open_signal.orchestration.metadata import ensure_runtime_metadata
from open_signal.sources.us_rule_status import map_document_status, transition_allowed

SECTION_ID = "rules-moved"
CAPABILITY_ID = "rule.state-transition"
DESK_ID = "rules-desk"
LINEAGE_ID = "rules-deterministic-v1"


class RulesSectionService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def run_editorial_batch(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = payload or {}
        maximum_claims = max(1, min(3, int(payload.get("maximum_claims") or 3)))
        source_id = ensure_runtime_metadata(self.engine)["federal-register"]
        self._ensure_lineage()
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT r.id, r.payload, r.content_hash, r.source_created_at
                    FROM raw_source_records r
                    WHERE r.source_id = :source
                      AND r.record_type = 'document'
                      AND r.status = 'active'
                      AND NOT EXISTS (
                        SELECT 1 FROM rule_versions version
                        WHERE r.id = ANY(version.source_document_ids)
                      )
                    ORDER BY r.source_created_at DESC NULLS LAST, r.ingested_at DESC
                    LIMIT :limit
                    """
                ),
                {"source": source_id, "limit": maximum_claims},
            ).fetchall()

        built: list[dict[str, Any]] = []
        conflicts = 0
        for raw_id, raw_payload, content_hash, source_created_at in rows:
            document = _object(raw_payload)
            if document.get("effective_on") and not document.get("effective_date"):
                document["effective_date"] = document["effective_on"]
            mapped_state = map_document_status(document)
            result = self._build_state_fact(
                raw_id=str(raw_id),
                document=document,
                content_hash=str(content_hash),
                source_created_at=source_created_at,
                current_state=mapped_state,
            )
            if result is None:
                conflicts += 1
                continue
            if result["created"]:
                built.append(result)

        verifier = ClaimVerifier(self.engine)
        candidates: list[dict[str, Any]] = []
        for index, result in enumerate(built):
            candidate = self._publication_candidate(result, index)
            if verifier.gate_for_composer(result["claim_id"], candidate):
                candidate["claim_status"] = "verified"
                candidates.append(candidate)

        edition: dict[str, Any] | None = None
        if candidates:
            edition = EditionWriter(self.engine).build_rolling_edition(
                candidates,
                refreshed_section_ids={SECTION_ID},
                trigger_type="section_refresh",
                generated_at=datetime.now(timezone.utc),
                section_maturity="beta",
            )
        return {
            "section_id": SECTION_ID,
            "documents_evaluated": len(rows),
            "transition_conflicts": conflicts,
            "claims_created": len(built),
            "claims_verified": len(candidates),
            "edition": edition,
        }

    def _ensure_lineage(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_lineages
                      (id, desk_id, name, foundation_model, model_version,
                       charter_id, charter_version, toolset_version,
                       context_builder_version, status, activated_at)
                    VALUES
                      (:id, :desk, 'Deterministic Rule Status', 'n/a',
                       'deterministic', 'rules-charter-v1', 'os-049', 'n/a',
                       'us-rule-status-v1', 'active', now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": LINEAGE_ID, "desk": DESK_ID},
            )

    def _build_state_fact(
        self,
        *,
        raw_id: str,
        document: dict[str, Any],
        content_hash: str,
        source_created_at: datetime | None,
        current_state: str,
    ) -> dict[str, Any] | None:
        identifier = str(document.get("document_number") or raw_id)
        title = str(document.get("title") or "Untitled federal rule")
        transition_at = source_created_at or datetime.now(timezone.utc)
        authority = _authority(document)
        source_url = str(
            document.get("html_url")
            or document.get("json_url")
            or "https://www.federalregister.gov/"
        )
        snapshot_hash = hashlib.sha256(
            json.dumps(
                {
                    "raw_id": raw_id,
                    "identifier": identifier,
                    "state": current_state,
                    "content_hash": content_hash,
                    "pipeline": "os-049",
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        idempotency_key = f"rule:{snapshot_hash}"

        with self.engine.connect() as conn:
            existing_claim = conn.execute(
                text(
                    "SELECT id FROM claims WHERE idempotency_key = :key"
                ),
                {"key": idempotency_key},
            ).fetchone()
        if existing_claim:
            return {"created": False, "claim_id": str(existing_claim[0])}

        with self.engine.begin() as conn:
            canonical = conn.execute(
                text(
                    """
                    SELECT id, current_state, current_version_id
                    FROM canonical_rules
                    WHERE official_identifier = :identifier
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"identifier": identifier},
            ).fetchone()
            if canonical:
                canonical_id = str(canonical[0])
                previous_state = str(canonical[1])
                previous_version_id = str(canonical[2]) if canonical[2] else None
                if (
                    previous_state != current_state
                    and not transition_allowed(previous_state, current_state)
                ):
                    return None
            else:
                canonical_id = str(
                    conn.execute(
                        text(
                            """
                            INSERT INTO canonical_rules
                              (title, rule_type, current_state, official_identifier,
                               docket_identifiers, announced_at, adopted_at,
                               effective_at, status, ontology_version)
                            VALUES
                              (:title, :type, :state, :identifier, :dockets,
                               :announced, :adopted, :effective, 'active',
                               'us-rule-status-v1')
                            RETURNING id
                            """
                        ),
                        {
                            "title": title,
                            "type": str(document.get("type") or "Rule"),
                            "state": current_state,
                            "identifier": identifier,
                            "dockets": _string_list(document.get("docket_ids")),
                            "announced": transition_at,
                            "adopted": transition_at
                            if current_state in {"final", "effective", "partially_effective"}
                            else None,
                            "effective": _as_datetime(document.get("effective_on")),
                        },
                    ).scalar_one()
                )
                previous_state = "not_published"
                previous_version_id = None

            document_date = transition_at.date()
            version_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO rule_versions
                          (canonical_rule_id, version_label, document_date,
                           source_document_ids, text_hash, state_at_version,
                           effective_at, supersedes_version_id)
                        VALUES
                          (:rule, :label, :date, ARRAY[:source]::uuid[],
                           :hash, :state, :effective, :supersedes)
                        RETURNING id
                        """
                    ),
                    {
                        "rule": canonical_id,
                        "label": f"{identifier}/{content_hash[:12]}",
                        "date": document_date,
                        "source": raw_id,
                        "hash": content_hash,
                        "state": current_state,
                        "effective": _as_datetime(document.get("effective_on")),
                        "supersedes": previous_version_id,
                    },
                ).scalar_one()
            )
            conn.execute(
                text(
                    """
                    UPDATE canonical_rules
                    SET previous_state = :previous,
                        current_state = :current,
                        current_version_id = :version,
                        title = :title,
                        effective_at = COALESCE(:effective, effective_at),
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "previous": previous_state,
                    "current": current_state,
                    "version": version_id,
                    "title": title,
                    "effective": _as_datetime(document.get("effective_on")),
                    "id": canonical_id,
                },
            )
            if previous_state != "not_published" and previous_state != current_state:
                conn.execute(
                    text(
                        """
                        INSERT INTO rule_transitions
                          (canonical_rule_id, from_state, to_state, occurred_at,
                           authoritative_source_record_ids,
                           transition_confidence, mapping_version, status)
                        VALUES
                          (:rule, :previous, :current, :occurred,
                           ARRAY[:source]::uuid[], 1.0,
                           'us-rule-status-v1', 'verified')
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "rule": canonical_id,
                        "previous": previous_state,
                        "current": current_state,
                        "occurred": transition_at,
                        "source": raw_id,
                    },
                )

            evidence_bundle_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO evidence_bundles
                          (primary_evidence, supporting_evidence,
                           counter_evidence, data_calculation_ids,
                           source_coverage, snapshot_hash)
                        VALUES
                          (CAST(:primary AS jsonb), '[]'::jsonb, '[]'::jsonb,
                           ARRAY[]::uuid[], CAST(:coverage AS jsonb), :hash)
                        RETURNING id
                        """
                    ),
                    {
                        "primary": json.dumps(
                            [
                                {
                                    "raw_source_record_id": raw_id,
                                    "document_number": identifier,
                                    "source_url": source_url,
                                    "authority": authority,
                                }
                            ]
                        ),
                        "coverage": json.dumps(
                            {
                                "source": "Federal Register",
                                "authority": "official_government",
                                "source_url": source_url,
                            }
                        ),
                        "hash": snapshot_hash,
                    },
                ).scalar_one()
            )
            run_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO investigation_runs
                          (desk_id, section_id, capability_id, candidate_id,
                           agent_lineage_id, model_version, charter_version,
                           started_at, completed_at, status,
                           total_input_tokens, total_output_tokens,
                           total_tool_calls, estimated_cost_usd,
                           output_judgment)
                        VALUES
                          (:desk, :section, :capability, :candidate, :lineage,
                           'deterministic', 'os-049', now(), now(), 'completed',
                           0, 0, 0, 0, CAST(:output AS jsonb))
                        RETURNING id
                        """
                    ),
                    {
                        "desk": DESK_ID,
                        "section": SECTION_ID,
                        "capability": CAPABILITY_ID,
                        "candidate": raw_id,
                        "lineage": LINEAGE_ID,
                        "output": json.dumps(
                            {
                                "previous_state": previous_state,
                                "current_state": current_state,
                            }
                        ),
                    },
                ).scalar_one()
            )
            statement = (
                f"{title} is recorded by the Federal Register as "
                f"{current_state.replace('_', ' ')}."
            )
            proposition = {
                "subject_ids": [canonical_id, raw_id],
                "predicate": "rule_state",
                "operator": "is",
                "unit": None,
                "baseline": {"previous_state": previous_state},
                "qualifiers": {
                    "authority": authority,
                    "document_number": identifier,
                },
                "proposition_version": "0.1.0",
            }
            claim_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO claims
                          (institution_id, desk_id, agent_lineage_id,
                           model_version, charter_version, run_id, section_id,
                           capability_id, claim_type, public_statement,
                           structured_proposition, confidence, confidence_label,
                           epistemic_status, evidence_bundle_id,
                           evidence_snapshot_hash, idempotency_key, issued_at,
                           status)
                        VALUES
                          ('open-signal', :desk, :lineage, 'deterministic',
                           'os-049', :run, :section, :capability, 'source_fact',
                           :statement, CAST(:proposition AS jsonb), 1.0, 'high',
                           'authoritative_primary', :evidence, :hash, :key,
                           :issued, 'draft')
                        RETURNING id
                        """
                    ),
                    {
                        "desk": DESK_ID,
                        "lineage": LINEAGE_ID,
                        "run": run_id,
                        "section": SECTION_ID,
                        "capability": CAPABILITY_ID,
                        "statement": statement,
                        "proposition": json.dumps(proposition),
                        "evidence": evidence_bundle_id,
                        "hash": snapshot_hash,
                        "key": idempotency_key,
                        "issued": transition_at,
                    },
                ).scalar_one()
            )
            version_row = conn.execute(
                text(
                    """
                    INSERT INTO claim_versions
                      (claim_id, version_number, public_statement,
                       structured_proposition, confidence, evidence_bundle_id,
                       change_type, change_reason, created_at,
                       created_by_run_id)
                    VALUES
                      (:claim, 1, :statement, CAST(:proposition AS jsonb), 1.0,
                       :evidence, 'initial', 'authoritative state record',
                       now(), :run)
                    RETURNING id
                    """
                ),
                {
                    "claim": claim_id,
                    "statement": statement,
                    "proposition": json.dumps(proposition),
                    "evidence": evidence_bundle_id,
                    "run": run_id,
                },
            ).scalar_one()
            conn.execute(
                text("UPDATE claims SET current_version_id = :version WHERE id = :claim"),
                {"version": version_row, "claim": claim_id},
            )
            section_instance_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO section_instances
                          (section_id, capability_id, subject_id, subject_type,
                           claim_id)
                        VALUES
                          (:section, :capability, :subject, 'canonical_rule',
                           :claim)
                        RETURNING id
                        """
                    ),
                    {
                        "section": SECTION_ID,
                        "capability": CAPABILITY_ID,
                        "subject": canonical_id,
                        "claim": claim_id,
                    },
                ).scalar_one()
            )
            conn.execute(
                text(
                    """
                    INSERT INTO claim_bundles
                      (section_instance_id, section_id, desk_id,
                       headline_claim_id, status)
                    VALUES (:instance, :section, :desk, :claim, 'draft')
                    """
                ),
                {
                    "instance": section_instance_id,
                    "section": SECTION_ID,
                    "desk": DESK_ID,
                    "claim": claim_id,
                },
            )

        return {
            "created": True,
            "claim_id": claim_id,
            "section_instance_id": section_instance_id,
            "run_id": run_id,
            "evidence_bundle_id": evidence_bundle_id,
            "headline": title,
            "display_fields": {
                "rule_title": title,
                "previous_state": previous_state,
                "current_state": current_state,
                "transition_date": transition_at.isoformat(),
                "authority": authority,
                "source_url": source_url,
                "effective_at": _iso(document.get("effective_on")),
                "observation": statement,
            },
            "data_as_of": transition_at.isoformat(),
        }

    @staticmethod
    def _publication_candidate(
        result: Mapping[str, Any], index: int
    ) -> dict[str, Any]:
        slots = ("lead", "secondary", "main")
        fields = dict(result["display_fields"])
        component_id = "state-transition.rule-stage"
        variant = "standard"
        if index == 0:
            component_id = "signal-hero.rules"
            variant = "lead"
            fields["headline"] = result["headline"]
            fields["primary_observation"] = fields["observation"]
        now = datetime.now(timezone.utc).isoformat()
        return {
            "component_id": component_id,
            "component_version": "1.0.0",
            "component_variant": variant,
            "slot_id": slots[index],
            "headline": result["headline"],
            "display_fields": fields,
            "hidden_detail_fields": {},
            "evidence_bundle_id": result["evidence_bundle_id"],
            "visual_priority": 1 + index,
            "mobile_priority": 1 + index,
            "generated_by": "os-049/rules-deterministic-v1",
            "claim_id": result["claim_id"],
            "claim_ids": [result["claim_id"]],
            "claim_type": "source_fact",
            "section_id": SECTION_ID,
            "section_instance_id": result["section_instance_id"],
            "capability_id": CAPABILITY_ID,
            "priority": 10 + index * 10,
            "data_as_of": result["data_as_of"],
            "assessed_at": now,
            "materially_updated_at": result["data_as_of"],
        }


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _authority(document: Mapping[str, Any]) -> str:
    agencies = document.get("agencies")
    if isinstance(agencies, list):
        names = [
            str(item.get("name"))
            for item in agencies
            if isinstance(item, dict) and item.get("name")
        ]
        if names:
            return ", ".join(names)
    return "U.S. Federal Register"


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.combine(
                date.fromisoformat(str(value)),
                time.min,
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _as_datetime(value)
    return parsed.isoformat() if parsed else None
