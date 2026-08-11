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
from open_signal.derived.expectation_selection import (
    ExpectationFact,
    eligible_expectation_facts,
    load_expectation_facts,
)
from open_signal.derived.public_interest import (
    EditorialScopeDecision,
    classify_expectation_scope,
    surface_rank,
)
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
        payload = payload or {}
        source_id = ensure_runtime_metadata(self.engine)["polymarket-gamma"]
        monitor_window_hours = max(
            1,
            min(24, int(payload.get("monitor_window_hours") or 2)),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (external_id)
                           id, external_id, payload, last_seen_at
                    FROM raw_source_records
                    WHERE source_id = :source
                      AND record_type = 'market'
                      AND status = 'active'
                      AND last_seen_at >= now() - make_interval(hours => :hours)
                    ORDER BY external_id, last_seen_at DESC, ingested_at DESC
                    """
                ),
                {"source": source_id, "hours": monitor_window_hours},
            ).fetchall()

        normalized: list[tuple[str, dict[str, Any], datetime]] = []
        for raw_id, external_id, raw_payload, last_seen_at in rows:
            market = _object(raw_payload)
            ends_at = _timestamp(market.get("endDate"))
            if ends_at is None:
                continue
            outcomes = _string_list(market.get("outcomes")) or ["Yes", "No"]
            tokens = _string_list(market.get("clobTokenIds"))
            status = (
                "closed"
                if market.get("closed")
                or market.get("archived")
                or market.get("active") is False
                else "active"
            )
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
                volume_24h=_number(
                    market.get("volume24hr") or market.get("volume24h")
                ),
                volume=_number(market.get("volume")),
                monitoring_last_seen_at=last_seen_at,
                status=status,
                raw_source_record_id=raw_id,
                updated_at=last_seen_at,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    source_markets.c.source_id,
                    source_markets.c.external_market_id,
                ],
                set_={
                    "external_event_id": statement.excluded.external_event_id,
                    "question": statement.excluded.question,
                    "description": statement.excluded.description,
                    "outcome_labels": statement.excluded.outcome_labels,
                    "token_ids": statement.excluded.token_ids,
                    "starts_at": statement.excluded.starts_at,
                    "ends_at": statement.excluded.ends_at,
                    "rules_text": statement.excluded.rules_text,
                    "liquidity": statement.excluded.liquidity,
                    "volume_24h": statement.excluded.volume_24h,
                    "volume": statement.excluded.volume,
                    "monitoring_last_seen_at": (
                        statement.excluded.monitoring_last_seen_at
                    ),
                    "status": statement.excluded.status,
                    "raw_source_record_id": statement.excluded.raw_source_record_id,
                    "updated_at": statement.excluded.updated_at,
                },
            ).returning(source_markets.c.id)
            with self.engine.begin() as conn:
                market_id = str(conn.execute(statement).scalar_one())
            if status == "active":
                normalized.append((market_id, market, last_seen_at))

        collector = MarketObservationCollector(self.engine)
        observations = 0
        history = {"markets": 0, "batches": 0, "observations": 0, "errors": 0}
        try:
            for market_id, market, _ in normalized:
                observations += collector._store_observation(
                    market,
                    external_id=market_id,
                )
            if _truthy(payload.get("history_backfill")):
                history_limit = max(
                    0,
                    min(500, int(payload.get("history_market_limit") or 200)),
                )
                ranked = sorted(
                    normalized,
                    key=lambda item: (
                        _number(
                            item[1].get("volume24hr")
                            or item[1].get("volume24h")
                        )
                        or 0.0,
                        _number(item[1].get("volume")) or 0.0,
                    ),
                    reverse=True,
                )
                history_targets = []
                for market_id, market, _ in ranked[:history_limit]:
                    tokens = _string_list(market.get("clobTokenIds"))
                    if tokens:
                        history_targets.append((market_id, tokens[0]))
                history = collector.backfill_history(
                    history_targets,
                    days=max(1, min(14, int(payload.get("history_days") or 7))),
                )
        finally:
            collector.close()

        canonicalizer = ExpectationCanonicalizer(
            self.engine,
            version="production-1.0.0",
        )
        canonicalized = 0
        for market_id, market, _ in normalized:
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
            "history_backfill": history,
            "canonicals_updated": canonicalized,
        }

    def run_editorial_batch(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Detect material moves, verify new Claims, and refresh one Section."""
        payload = payload or {}
        maximum_featured = max(
            1,
            min(
                3,
                int(
                    payload.get("maximum_featured_claims")
                    or payload.get("maximum_claims")
                    or 3
                ),
            ),
        )
        maximum_scanner = max(
            0,
            min(20, int(payload.get("maximum_scanner_claims") or 12)),
        )
        now = datetime.now(timezone.utc)
        with self.engine.connect() as conn:
            facts = eligible_expectation_facts(
                load_expectation_facts(conn, as_of=now),
                as_of=now,
            )[:500]

        detector = CandidateDetector(self.engine, version="production-1.0.0")
        detected: list[dict[str, Any]] = []
        scope_suppressed = 0
        for fact in facts:
            output = detector.compute_for_market(fact.market_id, now=now)
            editorial_scope = _editorial_scope(fact, output=output, as_of=now)
            output["editorial_scope"] = editorial_scope.as_dict()
            calculation_id = detector.record_calculation(fact.market_id, output)
            if not output["scanner_eligible"]:
                continue
            output["_calc_record_id"] = calculation_id
            if not editorial_scope.allows("live_feed"):
                scope_suppressed += 1
                continue
            tier = str(output["publication_tier"])
            detected.append(
                {
                    "tier": tier,
                    "tier_rank": 0 if tier == "featured" else 1,
                    "signal_score": float(output.get("signal_score") or 0.0),
                    "market_id": fact.market_id,
                    "canonical_id": fact.topic_id,
                    "event_key": fact.event_key,
                    "calculation": output,
                    "editorial_scope": editorial_scope,
                    "fact": fact,
                }
            )
        detected.sort(
            key=lambda item: (
                item["tier_rank"],
                -surface_rank(item["editorial_scope"].maximum_surface),
                -item["editorial_scope"].importance_score,
                -item["signal_score"],
                item["event_key"],
            )
        )

        builder = DeterministicClaimBuilder(self.engine)
        built: list[
            tuple[
                str,
                str,
                dict[str, Any],
                EditorialScopeDecision,
                ExpectationFact,
            ]
        ] = []
        duplicates = 0
        built_by_tier = {"featured": 0, "scanner": 0}
        used_events: set[str] = set()
        for item in detected:
            tier = str(item["tier"])
            market_id = str(item["market_id"])
            canonical_id = str(item["canonical_id"])
            event_key = str(item["event_key"])
            calculation = item["calculation"]
            limit = maximum_featured if tier == "featured" else maximum_scanner
            if built_by_tier[tier] >= limit or event_key in used_events:
                continue
            used_events.add(event_key)
            result = builder.build_from_candidate(
                source_market_id=market_id,
                canonical_expectation_id=canonical_id,
                calculation=calculation,
                now=now,
            )
            if not result["created"]:
                duplicates += 1
                continue
            built.append(
                (
                    tier,
                    event_key,
                    result,
                    item["editorial_scope"],
                    item["fact"],
                )
            )
            built_by_tier[tier] += 1
            if (
                built_by_tier["featured"] >= maximum_featured
                and built_by_tier["scanner"] >= maximum_scanner
            ):
                break

        verifier = ClaimVerifier(self.engine)
        candidates: list[dict[str, Any]] = []
        verified_claim_ids: set[str] = set()
        hero_used = False
        featured_nonhero_index = 0
        scanner_index = 0
        for tier, event_key, result, editorial_scope, fact in built:
            use_hero = (
                tier == "featured"
                and not hero_used
                and editorial_scope.allows("hero")
            )
            if use_hero:
                index = 0
                hero_used = True
            elif tier == "featured":
                index = featured_nonhero_index
                featured_nonhero_index += 1
            else:
                index = scanner_index
                scanner_index += 1
            candidate = self._publication_candidate(
                result,
                tier=tier,
                index=index,
                use_hero=use_hero,
            )
            candidate["continuity_key"] = event_key
            hidden = dict(candidate.get("hidden_detail_fields") or {})
            publication = dict(hidden.get("publication") or {})
            publication["event_key"] = event_key
            hidden["publication"] = publication
            hidden["public_interest"] = editorial_scope.as_dict()
            candidate["hidden_detail_fields"] = hidden
            fields = dict(candidate.get("display_fields") or {})
            fields.update(
                {
                    "event_title": fact.event_title,
                    "event_type": fact.event_type,
                    "tags": list(fact.tags),
                    "resolution_deadline_at": fact.deadline_at.isoformat(),
                }
            )
            candidate["display_fields"] = fields
            if verifier.gate_for_composer(result["claim_id"], candidate):
                candidate["claim_status"] = "verified"
                candidates.append(candidate)
                verified_claim_ids.add(str(result["claim_id"]))
                if tier == "featured":
                    candidates.append(self._index_echo(candidate))

        edition: dict[str, Any] | None = None
        if candidates:
            edition = EditionWriter(self.engine).build_rolling_edition(
                candidates,
                refreshed_section_ids={SECTION_ID},
                retain_refreshed_items=True,
                trigger_type="section_refresh",
                generated_at=now,
                section_maturity="beta",
            )

        return {
            "section_id": SECTION_ID,
            "markets_evaluated": len(facts),
            "eligible_candidates": len(detected),
            "featured_candidates": sum(
                1 for item in detected if item["tier"] == "featured"
            ),
            "scanner_candidates": sum(
                1 for item in detected if item["tier"] == "scanner"
            ),
            "editorial_scope_suppressed": scope_suppressed,
            "event_families_considered": len(
                {str(item["event_key"]) for item in detected}
            ),
            "claims_created": len(built),
            "duplicate_claims_skipped": duplicates,
            "claims_verified": len(verified_claim_ids),
            "render_candidates": len(candidates),
            "edition": edition,
        }

    @staticmethod
    def _publication_candidate(
        result: Mapping[str, Any], *, tier: str, index: int, use_hero: bool = False
    ) -> dict[str, Any]:
        candidate = dict(result["render_candidate"])
        fields = dict(candidate["display_fields"])
        if tier == "featured":
            if use_hero:
                candidate["component_id"] = "signal-hero.expectations"
                candidate["component_variant"] = "lead"
                fields["headline"] = candidate["headline"]
                fields["primary_observation"] = fields["observation"]
                slot_id = "lead"
                priority = 10
            else:
                slots = ("secondary", "main", "main")
                slot_id = slots[min(index, len(slots) - 1)]
                priority = 20 + index * 10
        else:
            candidate["component_id"] = "signal-feed.compact-change"
            candidate["component_variant"] = "compact"
            slot_id = "live_feed"
            priority = 100 + index
            fields = ExpectationsSectionService._compact_fields(candidate, fields)
        candidate.update(
            {
                "slot_id": slot_id,
                "claim_id": result["claim_id"],
                "claim_ids": [result["claim_id"]],
                "claim_type": "derived_observation",
                "section_id": SECTION_ID,
                "section_instance_id": result["section_instance_id"],
                "capability_id": "expectation.probability-change",
                "priority": priority,
                "presentation_role": "primary",
                "display_fields": fields,
            }
        )
        return candidate

    @staticmethod
    def _compact_fields(
        candidate: Mapping[str, Any], fields: Mapping[str, Any]
    ) -> dict[str, Any]:
        compact = dict(fields)
        delta = float(compact.get("delta_percentage_points") or 0.0)
        current = compact.get("current_probability")
        current_label = (
            f" · {float(current) * 100:.0f}%" if current is not None else ""
        )
        compact.update(
            {
                "change_title": str(candidate.get("headline") or "Expectation moved"),
                "change_value": f"{delta:+.1f}pp{current_label}",
                "claim_type": "derived_observation",
                "source_name": compact.get("source_name") or "Polymarket Gamma",
                "updated_at": compact.get("updated_at"),
                "trend": "up" if delta > 0 else "down" if delta < 0 else "neutral",
            }
        )
        return compact

    @staticmethod
    def _index_echo(candidate: Mapping[str, Any]) -> dict[str, Any]:
        echo = dict(candidate)
        fields = ExpectationsSectionService._compact_fields(
            candidate,
            dict(candidate.get("display_fields") or {}),
        )
        echo.update(
            {
                "component_id": "signal-feed.compact-change",
                "component_variant": "compact",
                "slot_id": "digest",
                "priority": int(candidate.get("priority") or 10) + 200,
                "presentation_role": "index_echo",
                "display_fields": fields,
            }
        )
        return echo


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _event_key(source_id: str, external_event_id: str | None, market_id: str) -> str:
    if external_event_id:
        return f"{source_id}:event:{external_event_id}"
    return f"{source_id}:market:{market_id}"


def _editorial_scope(
    fact: ExpectationFact,
    *,
    output: Mapping[str, Any],
    as_of: datetime,
) -> EditorialScopeDecision:
    return classify_expectation_scope(
        title=fact.title,
        event_title=fact.event_title,
        event_slug=fact.event_slug,
        event_type=fact.event_type,
        tags=fact.tags,
        deadline_at=fact.deadline_at,
        current_probability=fact.current_probability,
        delta_24h=float(output.get("delta_24h") or 0.0),
        as_of=as_of,
    )
