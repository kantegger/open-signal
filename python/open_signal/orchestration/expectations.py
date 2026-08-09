"""Production Expectations ingestion and editorial batch (OS-049)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from open_signal.agents.claim_builder import DeterministicClaimBuilder
from open_signal.canonical.canonicalizer import ExpectationCanonicalizer
from open_signal.claims.verification import ClaimVerifier
from open_signal.composer.edition_writer import EditionWriter
from open_signal.db.models import source_markets
from open_signal.derived.candidates import CandidateDetector
from open_signal.orchestration.metadata import ensure_runtime_metadata
from open_signal.sources.market_obs import MarketObservationCollector

SECTION_ID = "expectations-moved"


class ExpectationsSectionService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def ingest_observations(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Normalize latest raw markets, sample them, and update canonicals."""
        del payload
        source_id = ensure_runtime_metadata(self.engine)["polymarket-gamma"]
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (external_id)
                           id, external_id, payload
                    FROM raw_source_records
                    WHERE source_id = :source
                      AND record_type = 'market'
                      AND status = 'active'
                    ORDER BY external_id, ingested_at DESC
                    """
                ),
                {"source": source_id},
            ).fetchall()

        normalized: list[tuple[str, dict[str, Any]]] = []
        now = datetime.now(timezone.utc)
        for raw_id, external_id, raw_payload in rows:
            market = _object(raw_payload)
            ends_at = _timestamp(market.get("endDate"))
            if ends_at is None:
                continue
            outcomes = _string_list(market.get("outcomes")) or ["Yes", "No"]
            tokens = _string_list(market.get("clobTokenIds"))
            status = "closed" if market.get("closed") else "active"
            statement = insert(source_markets).values(
                source_id=source_id,
                external_market_id=str(external_id),
                external_event_id=_optional_text(market.get("eventId")),
                question=str(market.get("question") or "Untitled market"),
                description=_optional_text(market.get("description")),
                outcome_labels=outcomes,
                token_ids=tokens,
                starts_at=_timestamp(market.get("startDate")),
                ends_at=ends_at,
                rules_text=_optional_text(
                    market.get("rules") or market.get("description")
                ),
                liquidity=_number(market.get("liquidity")),
                volume=_number(market.get("volume")),
                status=status,
                raw_source_record_id=raw_id,
                updated_at=now,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    source_markets.c.source_id,
                    source_markets.c.external_market_id,
                ],
                set_={
                    "question": statement.excluded.question,
                    "description": statement.excluded.description,
                    "outcome_labels": statement.excluded.outcome_labels,
                    "token_ids": statement.excluded.token_ids,
                    "starts_at": statement.excluded.starts_at,
                    "ends_at": statement.excluded.ends_at,
                    "rules_text": statement.excluded.rules_text,
                    "liquidity": statement.excluded.liquidity,
                    "volume": statement.excluded.volume,
                    "status": statement.excluded.status,
                    "raw_source_record_id": statement.excluded.raw_source_record_id,
                    "updated_at": statement.excluded.updated_at,
                },
            ).returning(source_markets.c.id)
            with self.engine.begin() as conn:
                market_id = str(conn.execute(statement).scalar_one())
            if status == "active":
                normalized.append((market_id, market))

        collector = MarketObservationCollector(self.engine)
        observations = 0
        try:
            for market_id, market in normalized:
                observations += collector._store_observation(
                    market,
                    external_id=market_id,
                )
        finally:
            collector.close()

        canonicalizer = ExpectationCanonicalizer(
            self.engine,
            version="production-1.0.0",
        )
        canonicalized = 0
        for market_id, market in normalized:
            canonical_id = canonicalizer.canonicalize_source_market(
                market_id,
                question=str(market.get("question") or "Untitled market"),
                outcome_labels=_string_list(market.get("outcomes"))
                or ["Yes", "No"],
                ends_at=_timestamp(market.get("endDate")),
                event_type=_event_type(market),
                rules_text=_optional_text(
                    market.get("rules") or market.get("description")
                ),
                payload=market,
                force=True,
            )
            canonicalized += int(canonical_id is not None)

        return {
            "section_id": SECTION_ID,
            "raw_markets": len(rows),
            "active_markets": len(normalized),
            "observations_created": observations,
            "canonicals_updated": canonicalized,
        }

    def run_editorial_batch(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Detect material moves, verify new Claims, and refresh one Section."""
        payload = payload or {}
        maximum_claims = max(1, min(3, int(payload.get("maximum_claims") or 3)))
        now = datetime.now(timezone.utc)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT sm.id, ce.id
                    FROM source_markets sm
                    JOIN canonical_expectations ce
                      ON ce.source_market_ids @> ARRAY[sm.id]::uuid[]
                    WHERE sm.status = 'active' AND ce.status = 'active'
                    ORDER BY sm.updated_at DESC
                    LIMIT 500
                    """
                )
            ).fetchall()

        detector = CandidateDetector(self.engine, version="production-1.0.0")
        detected: list[tuple[float, str, str, dict[str, Any]]] = []
        for market_id, canonical_id in rows:
            output = detector.compute_for_market(str(market_id), now=now)
            calculation_id = detector.record_calculation(str(market_id), output)
            if not output["eligible"]:
                continue
            output["_calc_record_id"] = calculation_id
            detected.append(
                (
                    abs(float(output.get("delta_24h") or 0.0)),
                    str(market_id),
                    str(canonical_id),
                    output,
                )
            )
        detected.sort(key=lambda item: item[0], reverse=True)

        builder = DeterministicClaimBuilder(self.engine)
        built: list[dict[str, Any]] = []
        duplicates = 0
        for _, market_id, canonical_id, calculation in detected:
            result = builder.build_from_candidate(
                source_market_id=market_id,
                canonical_expectation_id=canonical_id,
                calculation=calculation,
                now=now,
            )
            if not result["created"]:
                duplicates += 1
                continue
            built.append(result)
            if len(built) >= maximum_claims:
                break

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
                generated_at=now,
                section_maturity="beta",
            )

        return {
            "section_id": SECTION_ID,
            "markets_evaluated": len(rows),
            "eligible_candidates": len(detected),
            "claims_created": len(built),
            "duplicate_claims_skipped": duplicates,
            "claims_verified": len(candidates),
            "edition": edition,
        }

    @staticmethod
    def _publication_candidate(
        result: Mapping[str, Any], index: int
    ) -> dict[str, Any]:
        candidate = dict(result["render_candidate"])
        fields = dict(candidate["display_fields"])
        slots = ("lead", "secondary", "main")
        if index == 0:
            candidate["component_id"] = "signal-hero.expectations"
            candidate["component_variant"] = "lead"
            fields["headline"] = candidate["headline"]
            fields["primary_observation"] = fields["observation"]
        candidate.update(
            {
                "slot_id": slots[index],
                "claim_id": result["claim_id"],
                "claim_ids": [result["claim_id"]],
                "claim_type": "derived_observation",
                "section_id": SECTION_ID,
                "section_instance_id": result["section_instance_id"],
                "capability_id": "expectation.probability-change",
                "priority": 10 + index * 10,
                "display_fields": fields,
            }
        )
        return candidate


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _event_type(market: Mapping[str, Any]) -> str:
    tags = market.get("tags")
    if isinstance(tags, list) and tags and isinstance(tags[0], dict):
        return str(tags[0].get("slug") or tags[0].get("label") or "general")
    return "general"
