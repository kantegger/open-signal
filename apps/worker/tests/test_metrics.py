"""30-day review metrics tests (OS-039). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import date

import pytest
from open_signal.ops.metrics import MetricsCollector


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        # editions: 2 published (one with lead), 1 sparse, 1 corrected
        for i, (status, lead, corrected) in enumerate(
            [("published", True, 0), ("published", False, 0), ("sparse", False, 0), ("published", True, 1)]
        ):
            conn.execute(
                text(
                    "INSERT INTO daily_editions (edition_date, generated_at, status, "
                    "included_section_ids, included_claim_ids, composer_version, "
                    "component_versions, generation_cost_usd, correction_count, edition_payload) "
                    "VALUES (:d, now() - make_interval(days => :i), :status, :sections, "
                    "ARRAY[]::uuid[], 'os-039', '{}'::jsonb, :cost, :corrected, :payload) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "d": date(2026, 8, 7),
                    "i": i,
                    "status": status,
                    "sections": ["expectations-moved"] if i % 2 == 0 else ["expectations-moved", "rules-moved"],
                    "cost": 0.1,
                    "corrected": corrected,
                    "payload": __import__("json").dumps({"lead": "L" if lead else None}),
                },
            )
        # runs: 1 abstained, 2 completed
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os039-desk', 'OS039', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os039-lineage', 'os039-desk', 'OS039', 'deepseek-chat', 'v1', "
                "'c', 'os-039', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        for status in ("abstained", "completed", "completed"):
            conn.execute(
                text(
                    "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                    "agent_lineage_id, model_version, charter_version, status, "
                    "estimated_cost_usd, started_at) "
                    "VALUES ('os039-desk', 's', 'c', 'os039-lineage', 'deepseek-chat', "
                    "'os-039', :status, 0.01, now())"
                ),
                {"status": status},
            )
        # claims: 1 rejected, 2 agent observations
        eb = conn.execute(
            text(
                "INSERT INTO evidence_bundles (primary_evidence, supporting_evidence, "
                "counter_evidence, data_calculation_ids, source_coverage, snapshot_hash) "
                "VALUES ('[]'::jsonb, '[]'::jsonb, '[]'::jsonb, ARRAY[]::uuid[], "
                "'{}'::jsonb, :h) RETURNING id"
            ),
            {"h": uuid.uuid4().hex},
        ).fetchone()
        run = conn.execute(
            text("SELECT id FROM investigation_runs ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
        for status, ctype in (("rejected", "derived_observation"), ("published", "agent_observation"), ("published", "agent_observation")):
            conn.execute(
                text(
                    "INSERT INTO claims (institution_id, desk_id, agent_lineage_id, model_version, "
                    "charter_version, run_id, section_id, capability_id, claim_type, "
                    "public_statement, structured_proposition, confidence, epistemic_status, "
                    "evidence_bundle_id, evidence_snapshot_hash, issued_at, status) "
                    "VALUES ('open-signal', 'os039-desk', 'os039-lineage', 'deepseek-chat', 'os-039', "
                    ":run, 'expectations-moved', 'c', :ctype, 'statement', "
                    "CAST('{\"subject_ids\": [\"x\"]}' AS jsonb), 0.5, 'derived', :eb, :h, now(), :status)"
                ),
                {"run": str(run[0]), "ctype": ctype, "eb": str(eb[0]), "h": uuid.uuid4().hex, "status": status},
            )
        # research candidates: 1 shadow_investigation, 1 rejected
        for status in ("shadow_investigation", "rejected"):
            conn.execute(
                text(
                    "INSERT INTO research_signal_candidates (candidate_type, subject_ids, "
                    "observation_window_start, observation_window_end, baseline_definition, "
                    "derived_metrics, evidence_relation_ids, candidate_generator_version, status) "
                    "VALUES ('institution_entry', ARRAY[]::uuid[], '2024-01-01', '2025-12-31', "
                    "'b', '{}'::jsonb, ARRAY[]::uuid[], 'os-039', :status)"
                ),
                {"status": status},
            )


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE daily_editions CASCADE"))
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM evidence_bundles"))
        conn.execute(text("DELETE FROM research_signal_candidates"))
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM agent_lineages"))
        conn.execute(text("DELETE FROM agent_desks"))


def test_all_metrics(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("TRUNCATE daily_editions CASCADE"))
        conn.execute(text("DELETE FROM research_signal_candidates"))
    _seed(engine)

    m = MetricsCollector(engine).collect(days=30)

    assert m["hero_fill_rate"] == pytest.approx(0.5)      # 2 of 4 editions have lead
    assert m["publishable_edition_rate"] == pytest.approx(0.75)  # 3 of 4 published
    assert m["correction_rate"] == pytest.approx(0.25)    # 1 of 4 corrected
    assert m["cost_per_edition_usd"] == pytest.approx(0.1)
    assert m["section_diversity"] >= 1.0
    assert m["agent_abstention_rate"] == pytest.approx(1 / 3, abs=0.01)  # 1 of 3 runs
    assert m["no_go_findings"] == 2  # 1 rejected claim + 1 rejected candidate
    assert m["research_value_rate"] == pytest.approx(2 / 3, abs=0.01)  # 2 of 3 claims agent_observation
    _cleanup(engine)


def test_empty_window(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("TRUNCATE daily_editions CASCADE"))
        conn.execute(text("DELETE FROM research_signal_candidates"))
    m = MetricsCollector(engine).collect(days=1)
    assert m["totals"]["editions"] == 0
    assert m["hero_fill_rate"] == 0.0
    assert m["cost_per_edition_usd"] == 0.0
    assert m["agent_abstention_rate"] == 0.0
