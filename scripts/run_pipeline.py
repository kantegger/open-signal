"""End-to-end pipeline runner (OS-PIPE).

Run:  $env:OPEN_SIGNAL_DATABASE_URL = "..."; python scripts/run_pipeline.py

Stages: discover → normalize → observe → canonicalize → detect → claim → edition

By default uses Polymarket fixtures (no API key needed) and deterministic
claim building (no LLM cost). Pass --real to use the Gamma API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from sqlalchemy import create_engine, text


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Signal pipeline runner")
    parser.add_argument(
        "--real", action="store_true", help="use live Gamma API instead of fixtures"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="max pages of markets to discover (default 3)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="use DeepSeek LLM agent for claim evaluation (costs $$)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="stop after candidate detection, no claims/edition",
    )
    args = parser.parse_args()

    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        print("ERROR: OPEN_SIGNAL_DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(url)
    now = datetime.now(timezone.utc)
    stats: dict[str, Any] = {}

    # ════════════════════════════════════════════════════════════════════
    # Stage 1 — Discover
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 1: Polymarket discovery ──")
    from open_signal.sources.polymarket import GammaClient, PolymarketAdapter

    # ensure sources + desks + lineages exist (needed for FK constraints)
    _seed_base_metadata(engine, now)

    # resolve source UUID from slug
    with engine.connect() as conn:
        source_row = conn.execute(
            text("SELECT id FROM sources WHERE slug = 'polymarket-gamma'")
        ).fetchone()
    if not source_row:
        print("ERROR: source 'polymarket-gamma' not found after seeding")
        sys.exit(1)
    source_uuid = str(source_row[0])

    client = GammaClient()
    adapter = PolymarketAdapter(
        engine=engine,
        client=client,
        source_id=source_uuid,
        adapter_version="pipeline-0.1.0",
        page_size=100,
        fixture_dir=str(REPO / "fixtures" / "polymarket"),
        offline=not args.real,
    )
    discovered = adapter.discover(max_pages=args.max_pages)
    print(f"  discover: {discovered['markets']} markets, {discovered['pages']} pages")
    stats["discover"] = discovered

    # ════════════════════════════════════════════════════════════════════
    # Stage 2 — Normalize (raw → source_markets)
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 2: Normalize raw → source_markets ──")
    normalized = _normalize(engine, now)
    print(
        f"  normalize: {normalized['created']} created, {normalized['skipped']} skipped"
    )
    stats["normalize"] = normalized

    if normalized["created"] == 0:
        print("  (no new markets — skipping downstream stages)")
        return

    source_market_ids = normalized["market_ids"]

    # ════════════════════════════════════════════════════════════════════
    # Stage 3 — Market Observations
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 3: Collect market observations ──")
    from open_signal.sources.market_obs import MarketObservationCollector

    collector = MarketObservationCollector(engine)
    external_map = _build_external_id_map(engine, source_market_ids)
    markets_data = _load_markets_from_raw(engine, source_market_ids)
    collected = 0
    # simulate time series with staggered timestamps (fixtures have single snapshots)
    import copy
    import random
    from datetime import timedelta

    rng = random.Random(42)
    for hours_ago in [24 * 7, 24 * 3, 24, 8, 4, 1, 0]:
        staggered_now = now - timedelta(hours=hours_ago)
        for m in markets_data:
            ext_id = external_map.get(str(m.get("id")))
            if ext_id:
                # simulate price drift over time
                m_varied = copy.deepcopy(m)
                prices = m_varied.get("outcomePrices") or []
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except (TypeError, ValueError):
                        prices = []
                if prices:
                    drift = rng.uniform(-0.05, 0.05)
                    new_p0 = min(
                        1.0,
                        max(0.0, float(prices[0]) + drift * (1 - hours_ago / (24 * 7))),
                    )
                    m_varied["outcomePrices"] = [
                        str(round(new_p0, 4)),
                        str(round(1 - new_p0, 4)),
                    ]
                n = collector._store_observation(
                    m_varied, external_id=ext_id, observed_at_override=staggered_now
                )
                collected += n  # type: ignore[assignment]
    print(f"  observe: {collected} observations stored")
    stats["observe"] = {"collected": collected}

    # ════════════════════════════════════════════════════════════════════
    # Stage 4 — Canonicalize
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 4: Canonicalize ──")
    from open_signal.canonical.canonicalizer import ExpectationCanonicalizer

    canon = ExpectationCanonicalizer(engine, version="pipeline-0.1.0")
    canonicalized = canon.canonicalize_all_eligible(limit=500)
    print(
        f"  canonicalize: {canonicalized['created']} created, {canonicalized['skipped']} skipped"
    )
    stats["canonicalize"] = canonicalized

    # ════════════════════════════════════════════════════════════════════
    # Stage 5 — Candidate Detection
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 5: Candidate detection ──")
    from open_signal.derived.candidates import CandidateDetector

    detector = CandidateDetector(engine, version="pipeline-0.1.0")
    candidates = detector.detect(source_market_ids=source_market_ids)
    eligible = [c for c in candidates if c.get("eligible")]
    print(f"  detect: {len(candidates)} candidates, {len(eligible)} eligible")
    stats["detect"] = {"total": len(candidates), "eligible": len(eligible)}

    if args.dry_run or len(eligible) == 0:
        print("  (dry-run or no eligible candidates — stopping)")
        _print_stats(stats)
        return

    # ════════════════════════════════════════════════════════════════════
    # Stage 6 — Agent (deterministic or LLM)
    # ════════════════════════════════════════════════════════════════════
    if args.llm:
        print("── Stage 6: DeepSeek agent evaluation (LLM) ──")
        _run_llm_agent(engine, eligible, stats)
    else:
        print("── Stage 6: Deterministic claim building ──")
        _run_deterministic_claims(engine, eligible, stats)

    # ════════════════════════════════════════════════════════════════════
    # Stage 7 — Verify claims
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 7: Verify claims ──")
    claim_ids = stats.get("claim_ids", [])
    verified_ids = _verify_claims(engine, claim_ids)
    print(f"  verify: {len(verified_ids)} claims verified")
    stats["verify"] = {
        "passed": len(verified_ids),
        "failed": len(claim_ids) - len(verified_ids),
    }

    # ════════════════════════════════════════════════════════════════════
    # Stage 8 — Edition
    # ════════════════════════════════════════════════════════════════════
    print("── Stage 8: Build edition ──")
    edition = _build_edition(engine, verified_ids, now)
    print(
        f"  edition: {edition.get('edition_id')} with {edition.get('item_count', 0)} items"
    )
    stats["edition"] = edition

    _print_stats(stats)


# ════════════════════════════════════════════════════════════════════════
# Normalization
# ════════════════════════════════════════════════════════════════════════


def _normalize(engine: Any, now: datetime) -> dict[str, Any]:
    """Read raw_source_records for polymarket-gamma, upsert into source_markets."""
    # resolve source UUID
    with engine.connect() as conn:
        src_row = conn.execute(
            text("SELECT id FROM sources WHERE slug = 'polymarket-gamma'")
        ).fetchone()
    if not src_row:
        return {"created": 0, "skipped": 0, "market_ids": []}
    source_uuid = str(src_row[0])

    with engine.begin() as conn:
        raw_rows = conn.execute(
            text(
                "SELECT id, external_id, payload FROM raw_source_records "
                "WHERE source_id = :sid AND record_type = 'market' "
                "ORDER BY id"
            ),
            {"sid": source_uuid},
        ).fetchall()

    created, skipped = 0, 0
    market_ids: list[str] = []
    with engine.begin() as conn:
        for raw_row in raw_rows:
            raw_id = str(raw_row[0])
            ext_id = str(raw_row[1])
            payload = (
                raw_row[2] if isinstance(raw_row[2], dict) else json.loads(raw_row[2])
            )

            question = payload.get("question", "")
            outcome_labels = payload.get("outcomes") or ["Yes", "No"]
            closed = payload.get("closed", False)
            ends_at_str = payload.get("endDate")
            ends_at = None
            if ends_at_str:
                try:
                    from datetime import datetime as dt

                    ends_at = dt.fromisoformat(ends_at_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # skip closed markets
            if closed:
                skipped += 1
                continue

            # upsert source_market
            existing = conn.execute(
                text(
                    "SELECT id FROM source_markets WHERE source_id = (SELECT id FROM sources WHERE slug='polymarket-gamma') AND external_market_id = :eid"
                ),
                {"eid": ext_id},
            ).fetchone()

            if existing:
                skipped += 1
                market_ids.append(str(existing[0]))
                continue

            mid = str(uuid.uuid4())
            # use ORM insert for correct ARRAY type binding
            from open_signal.db.models import source_markets as sm_table

            conn.execute(
                sm_table.insert().values(
                    id=mid,
                    source_id=source_uuid,
                    external_market_id=ext_id,
                    question=question,
                    outcome_labels=list(outcome_labels)
                    if isinstance(outcome_labels, list)
                    else ["Yes", "No"],
                    token_ids=list(payload.get("clobTokenIds") or []),
                    ends_at=ends_at or datetime(2027, 1, 1, tzinfo=timezone.utc),
                    status="active",
                    raw_source_record_id=raw_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
            market_ids.append(mid)

    return {"created": created, "skipped": skipped, "market_ids": market_ids}


# ════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════


def _build_external_id_map(engine: Any, market_ids: list[str]) -> dict[str, str]:
    """Map Gamma market ID (string) → source_markets.uuid."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT external_market_id, id::text FROM source_markets "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [uuid.UUID(m) for m in market_ids]},
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def _load_markets_from_raw(engine: Any, market_ids: list[str]) -> list[dict[str, Any]]:
    """Load raw market dicts from raw_source_records for given market IDs."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.payload FROM raw_source_records r "
                "JOIN source_markets sm ON sm.raw_source_record_id = r.id "
                "WHERE sm.id = ANY(:ids)"
            ),
            {"ids": [uuid.UUID(m) for m in market_ids]},
        ).fetchall()
    markets: list[dict[str, Any]] = []
    for (payload,) in rows:
        if isinstance(payload, dict):
            markets.append(payload)
        else:
            markets.append(json.loads(payload))
    return markets


# ════════════════════════════════════════════════════════════════════════
# Stage 6 — Deterministic claim building
# ════════════════════════════════════════════════════════════════════════


def _run_deterministic_claims(engine: Any, candidates: list[dict], stats: dict) -> None:
    """Create deterministic derived_observation claims without LLM."""
    from datetime import datetime as dt
    from datetime import timezone as tz

    now = dt.now(tz.utc)
    claim_ids = []
    with engine.begin() as conn:
        for c in candidates[:5]:  # limit to 5 to keep costs low
            mid = c.get("source_market_id")
            if not mid:
                continue
            # get canonical expectation
            exp_row = conn.execute(
                text(
                    "SELECT id, canonical_question FROM canonical_expectations "
                    "WHERE :mid = ANY(source_market_ids) ORDER BY created_at DESC LIMIT 1"
                ),
                {"mid": mid},
            ).fetchone()
            if not exp_row:
                continue

            question = exp_row[1]

            # build structured proposition
            delta = c.get("delta_24h", 0)
            direction = "increased" if c.get("direction", 0) > 0 else "decreased"
            trend = "up" if c.get("direction", 0) > 0 else "down"
            prob = 0.5 + delta / 200  # crude estimate

            proposition = {
                "en": {
                    "subject_ids": [str(mid)],
                    "headline": question,
                    "observation": f"Market probability {prob * 100:.0f}% YES.",
                    "analysis": f"Probability {direction} by {abs(delta):.1f}pp over 24h.",
                    "assessment": "Deterministic pipeline — medium confidence.",
                    "predicate": "probability_changed",
                    "operator": direction,
                    "value": prob,
                    "unit": "probability",
                    "probability": prob,
                    "trend": trend,
                }
            }

            # evidence bundle — use ORM insert for correct type binding
            bid = str(uuid.uuid4())
            from open_signal.db.models import evidence_bundles as eb_table

            conn.execute(
                eb_table.insert().values(
                    id=bid,
                    primary_evidence=json.dumps(
                        [{"type": "source_probability", "delta_24h": delta}]
                    ),
                    supporting_evidence=json.dumps([]),
                    counter_evidence=json.dumps([]),
                    data_calculation_ids=[uuid.uuid4()],
                    source_coverage=json.dumps({"sources": 1}),
                    unresolved_questions=[],
                    known_limitations=[],
                    snapshot_hash="pipe" * 16,
                    created_at=now,
                )
            )

            # investigation run — ORM insert
            run_id = str(uuid.uuid4())
            from open_signal.db.models import investigation_runs as ir_table

            conn.execute(
                ir_table.insert().values(
                    id=run_id,
                    desk_id="expectations-desk",
                    section_id="expectations-moved",
                    capability_id="expectations-detection",
                    agent_lineage_id="expectations-ml-v1",
                    model_version="pipeline",
                    charter_version="v1",
                    status="completed",
                    estimated_cost_usd=0.0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    started_at=now,
                )
            )

            # claim — ORM insert
            cid = str(uuid.uuid4())
            from open_signal.db.models import claims as cl_table

            conn.execute(
                cl_table.insert().values(
                    id=cid,
                    institution_id="open-signal",
                    desk_id="expectations-desk",
                    agent_lineage_id="expectations-ml-v1",
                    model_version="pipeline",
                    charter_version="v1",
                    run_id=run_id,
                    section_id="expectations-moved",
                    capability_id="expectations-detection",
                    claim_type="derived_observation",
                    public_statement=f"Probability of {question[:60]} shifted.",
                    structured_proposition=proposition,
                    confidence=0.7,
                    epistemic_status="medium-confidence",
                    evidence_bundle_id=bid,
                    evidence_snapshot_hash="pipe" * 16,
                    issued_at=now,
                    status="draft",
                )
            )

            # claim_version — ORM insert
            from open_signal.db.models import claim_versions as cv_table

            conn.execute(
                cv_table.insert().values(
                    id=str(uuid.uuid4()),
                    claim_id=cid,
                    version_number=1,
                    public_statement=f"Probability of {question[:60]} shifted.",
                    structured_proposition=proposition,
                    confidence=0.7,
                    evidence_bundle_id=bid,
                    change_type="create",
                    change_reason="Pipeline run",
                    created_at=now,
                    created_by_run_id=run_id,
                )
            )

            claim_ids.append(cid)
            print(f"  claim: {cid} ({question[:50]}...)")

    stats["claim_ids"] = claim_ids
    stats["claims"] = len(claim_ids)


# ════════════════════════════════════════════════════════════════════════
# Stage 6 (alt) — LLM agent
# ════════════════════════════════════════════════════════════════════════


def _run_llm_agent(engine: Any, candidates: list[dict], stats: dict) -> None:
    """Evaluate candidates via DeepSeek LLM agent."""
    from open_signal.agents.expectations_agent import ExpectationsCharterAgent
    from open_signal.agents.runtime import AgentRuntime, DeepSeekClient

    rt = AgentRuntime(engine, client=DeepSeekClient(model="deepseek-chat"))
    agent = ExpectationsCharterAgent(rt, engine)

    claim_ids = []
    for c in candidates[:3]:  # limit LLM calls
        result = agent.evaluate_candidate(
            source_market_id=c["source_market_id"],
            canonical_expectation_id=c.get("canonical_expectation_id", ""),
            calculation=c,
            lineage_id="expectations-ml-v1",
        )
        cid = result.get("claim_id")
        if cid:
            claim_ids.append(cid)
        print(
            f"  claim: {cid} | verdict: {result.get('verdict')} | cost: ${result.get('usage', {}).get('cost_usd', 0):.4f}"
        )

    stats["claim_ids"] = claim_ids
    stats["claims"] = len(claim_ids)


# ════════════════════════════════════════════════════════════════════════
# Stage 7 — Verify
# ════════════════════════════════════════════════════════════════════════


def _verify_claims(engine: Any, claim_ids: list[str]) -> list[str]:
    """Run verification gates on claim IDs."""
    from open_signal.claims.verification import ClaimVerifier

    if not claim_ids:
        return []
    verifier = ClaimVerifier(engine)
    verified_ids: list[str] = []
    for cid in claim_ids:
        try:
            if verifier.gate_for_composer(cid):
                verified_ids.append(cid)
        except Exception as exc:  # noqa: BLE001 - keep the remaining claims verifiable
            print(f"  verify warning: {cid}: {exc}")
    return verified_ids


# ════════════════════════════════════════════════════════════════════════
# Stage 8 — Edition
# ════════════════════════════════════════════════════════════════════════


def _build_edition(engine: Any, claim_ids: list[str], now: datetime) -> dict[str, Any]:
    """Build and write one edition from verified claims."""
    from open_signal.composer.edition_writer import EditionWriter

    if not claim_ids:
        return {"edition_id": None, "item_count": 0, "error": "no claims"}

    # build candidate list for composer with required display_fields
    candidates_list = []
    for idx, cid in enumerate(claim_ids[:3]):
        # fetch claim data for display_fields
        with engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT structured_proposition, status, claim_type "
                    "FROM claims WHERE id = :id"
                ),
                {"id": cid},
            ).fetchone()
        if claim is None or claim[1] not in {"verified", "published", "active"}:
            continue
        prop = (claim[0] or {}).get("en", {})
        prob = prop.get("probability", 0.5)

        is_lead = idx == 0
        component_id = (
            "signal-hero.expectations" if is_lead else "time-series.probability-move"
        )
        slots = ["lead", "secondary", "main"]
        headline = prop.get("headline", "Verified expectation signal")
        observation = prop.get("observation") or headline
        display_fields = {
            "expectation_title": headline[:100],
            "current_probability": round(prob * 100, 1),
            "start_probability": round((prob - 0.05) * 100, 1),
            "delta_percentage_points": round(abs(prop.get("delta", 5)), 1),
            "window": "7d",
            "series": [],
            "source_name": "Polymarket Gamma",
            "updated_at": now.isoformat(),
        }
        if is_lead:
            display_fields.update(
                {
                    "headline": headline,
                    "primary_observation": observation,
                    "observation": observation,
                    "analysis": prop.get("analysis"),
                    "assessment": prop.get("assessment"),
                }
            )
        candidates_list.append(
            {
                "claim_id": cid,
                "claim_status": claim[1],
                "claim_type": claim[2],
                "component_id": component_id,
                "component_version": "0.1.0",
                "slot_id": slots[idx],
                "section_id": "expectations-moved",
                "display_fields": display_fields,
                "priority": idx * 10 + 10,
            }
        )

    if not candidates_list:
        return {
            "edition_id": None,
            "item_count": 0,
            "error": "no verified claims",
        }

    writer = EditionWriter(engine)
    result = writer.build_edition(
        candidates=candidates_list,
        edition_date=now.date(),
        section_maturity="beta",
    )
    return result


def _print_stats(stats: dict) -> None:
    print("\n═══════════════════════════════════════")
    print("Pipeline summary:")
    for stage, value in stats.items():
        if isinstance(value, dict):
            items = ", ".join(f"{k}={v}" for k, v in value.items())
            print(f"  {stage}: {items}")
        else:
            print(f"  {stage}: {value}")
    print("═══════════════════════════════════════")


def _seed_base_metadata(engine: Any, now: datetime) -> None:
    """Ensure sources, desks, lineages exist (idempotent)."""
    with engine.begin() as conn:
        for slug, name, cat in [
            ("polymarket-gamma", "Polymarket Gamma", "prediction_market"),
            ("federal-register", "Federal Register", "government_filing"),
            ("openalex", "OpenAlex", "research_index"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO sources (slug, name, category, authority_level, "
                    "access_mode, adapter_id, status) VALUES (:s, :n, :c, 'secondary', "
                    "'public_api', :s, 'active') ON CONFLICT (slug) DO NOTHING"
                ),
                {"s": slug, "n": name, "c": cat},
            )
        for did, title in [
            ("expectations-desk", "Expectations Desk"),
            ("rules-desk", "Rules Desk"),
            ("research-desk", "Research Desk"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO agent_desks (id, title, editorial_mission, "
                    "charter_version, maturity) VALUES (:d, :t, :m, 'v1', 'beta') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"d": did, "t": title, "m": f"{title} mission"},
            )
        for lid, did in [
            ("expectations-ml-v1", "expectations-desk"),
            ("rules-ml-v1", "rules-desk"),
            ("research-ml-v1", "research-desk"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                    "model_version, charter_id, charter_version, toolset_version, "
                    "context_builder_version, status, activated_at) "
                    "VALUES (:l, :d, :l, 'deepseek-chat', 'v1', 'c', 'v1', 'v1', "
                    "'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
                ),
                {"l": lid, "d": did},
            )


if __name__ == "__main__":
    main()
