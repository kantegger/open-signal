"""Seed demo data using actual models — no column name guesswork."""
import sys, os, uuid, json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from datetime import date, datetime, timezone
from sqlalchemy import create_engine
from open_signal.db import models

url = os.environ["OPEN_SIGNAL_DATABASE_URL"]
engine = create_engine(url)
now = datetime.now(timezone.utc)
today = date.today()

DESK = "expectations-desk"
LINEAGE = "expectations-ml-v1"
RUN_ID = uuid.uuid4()
BUNDLE_ID = uuid.uuid4()

with engine.begin() as conn:
    # ── sources ──
    source_ids = {}
    for slug, name, cat in [
        ("polymarket-gamma", "Polymarket Gamma", "prediction_market"),
        ("federal-register", "Federal Register", "government_filing"),
        ("openalex", "OpenAlex", "research_index"),
    ]:
        sid = uuid.uuid4()
        source_ids[slug] = sid
        conn.execute(
            models.sources.insert().values(
                id=sid, slug=slug, name=name, category=cat, authority_level="secondary",
                access_mode="public_api", adapter_id=slug, status="active",
            )
        )

    # ── desks ──
    for did, title in [
        ("expectations-desk", "Expectations Desk"),
        ("rules-desk", "Rules Desk"),
        ("research-desk", "Research Desk"),
    ]:
        conn.execute(
            models.agent_desks.insert().values(
                id=did, title=title, editorial_mission=f"{title} mission",
                charter_version="v1", maturity="beta",
            )
        )

    # ── lineages ──
    for lid, did in [
        ("expectations-ml-v1", "expectations-desk"),
        ("rules-ml-v1", "rules-desk"),
        ("research-ml-v1", "research-desk"),
    ]:
        conn.execute(
            models.agent_lineages.insert().values(
                id=lid, desk_id=did, name=lid, foundation_model="deepseek-chat",
                model_version="v1", charter_id="c", charter_version="v1",
                toolset_version="v1", context_builder_version="v1", status="active",
                activated_at=now,
            )
        )

    # ── investigation_runs ──
    conn.execute(
        models.investigation_runs.insert().values(
            id=RUN_ID, desk_id=DESK, section_id="expectations-moved",
            capability_id="expectations-detection", agent_lineage_id=LINEAGE,
            model_version="deepseek-chat", charter_version="v1", status="completed",
            estimated_cost_usd=0.15, total_input_tokens=1200, total_output_tokens=400,
            started_at=now,
        )
    )

    # ── evidence_bundles ──
    conn.execute(
        models.evidence_bundles.insert().values(
            id=BUNDLE_ID, primary_evidence=json.dumps([{"type": "source_probability", "value": 0.6}]),
            supporting_evidence=json.dumps([]), counter_evidence=json.dumps([]),
            data_calculation_ids=[uuid.uuid4()],
            source_coverage=json.dumps({"sources": 1}),
            unresolved_questions=["Whether probability persists"],
            known_limitations=["Limited 30d window"],
            snapshot_hash="a" * 64,
            created_at=now,
        )
    )

    # ── source_markets ──
    mk_ids = []
    for eid, q in [
        ("559651", "Will the US impose tariffs on China above 60%?"),
        ("560001", "Will the Fed cut rates in Q1 2026?"),
        ("560002", "Will AI regulation pass Congress in 2026?"),
    ]:
        mid = uuid.uuid4()
        mk_ids.append((mid, q))
        conn.execute(
            models.source_markets.insert().values(
                id=mid, source_id=source_ids["polymarket-gamma"],
                external_market_id=eid, question=q,
                outcome_labels=["Yes", "No"], token_ids=[],
                ends_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                status="active", created_at=now, updated_at=now,
            )
        )

    # ── canonical_expectations ──
    for mid, q in mk_ids:
        conn.execute(
            models.canonical_expectations.insert().values(
                id=uuid.uuid4(),
                canonical_question=q,
                subject_entity_ids=[],
                event_type="binary_outcome",
                outcome_type="binary",
                resolution_deadline_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                resolution_rule_summary="Market resolves YES if event occurs.",
                resolution_rule_hash="a" * 64,
                source_market_ids=[mid],
                status="active",
                canonicalization_version="0.1.0",
                created_at=now,
                updated_at=now,
            )
        )

    # ── claims ──
    cids = []
    for i, (mid, q) in enumerate(mk_ids):
        cid = uuid.uuid4()
        cids.append(cid)
        sp = {"en": {
            "headline": f"Signal: {q}",
            "observation": f"Market probability {45+i*20}% YES.",
            "analysis": f"Shifted {10+i*5}pp in 30d.",
            "assessment": "Medium-confidence; order-book depth.",
        }}
        conn.execute(
            models.claims.insert().values(
                id=cid, institution_id="open-signal", desk_id=DESK,
                agent_lineage_id=LINEAGE, model_version="deepseek-chat",
                charter_version="v1", run_id=RUN_ID,
                section_id="expectations-moved",
                capability_id="expectations-detection",
                claim_type="derived_observation",
                public_statement=f"Probability of {q[:50]} shifted.",
                structured_proposition=sp,
                confidence=0.85,
                epistemic_status="high-confidence",
                evidence_bundle_id=BUNDLE_ID,
                evidence_snapshot_hash="a" * 64,
                issued_at=now,
                status="published",
            )
        )

    # ── daily_edition ──
    ed = uuid.uuid4()
    conn.execute(
        models.daily_editions.insert().values(
            id=ed, edition_date=today, generated_at=now, status="published",
            included_section_ids=["expectations-moved", "rules-moved", "research-frontier"],
            included_claim_ids=cids,
            composer_version="0.1.0", component_versions=json.dumps({}),
            generation_cost_usd=0.05, correction_count=0,
            edition_payload=json.dumps({"title": f"Daily Edition — {today}"}),
        )
    )

    # ── section_instances ──
    sec_defs = [
        ("expectations-moved", "Expectations Shift"),
        ("rules-moved", "Regulatory Activity"),
        ("research-frontier", "Research Frontier"),
    ]
    for idx, (sec, headline) in enumerate(sec_defs):
        si = uuid.uuid4()
        conn.execute(
            models.section_instances.insert().values(
                id=si, section_id=sec, capability_id="expectations-detection",
                subject_id=mk_ids[idx % len(mk_ids)][0],
                subject_type="canonical_expectation",
                claim_id=cids[idx % len(cids)],
                edition_id=ed, created_at=now,
            )
        )
        conn.execute(
            models.render_plans.insert().values(
                id=uuid.uuid4(), edition_id=ed,
                slot_id="main" if idx == 0 else "secondary",
                section_instance_id=si,
                claim_ids=[cids[idx % len(cids)]],
                component_id="time-series.probability-move",
                component_version="0.1.0", component_variant="default",
                headline=headline, dek="Probability movement detected",
                display_fields=json.dumps({"trend": "up" if idx % 2 == 0 else "neutral"}),
                hidden_detail_fields=json.dumps({}),
                visual_priority=idx * 10 + 10,
                mobile_priority=idx * 10 + 5,
                generated_by="seed-script",
            )
        )

    # ── claim_versions ──
    for i, cid in enumerate(cids):
        conn.execute(
            models.claim_versions.insert().values(
                id=uuid.uuid4(), claim_id=cid, version_number=1,
                public_statement="Initial publication",
                structured_proposition={"en": {"headline": f"Signal {i+1}", "observation": "Market probability shifted."}},
                confidence=0.85,
                evidence_bundle_id=BUNDLE_ID,
                change_type="create",
                change_reason="First issue",
                created_at=now,
                created_by_run_id=RUN_ID,
            )
        )

    print(f"edition: {ed}")
    for cid in cids:
        print(f"claim:   {cid}")

print("\n✅ seed done — refresh http://localhost:3000")
