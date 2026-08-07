"""30-day review metrics (spec §34.5, OS-039).

Eight operational metrics from the ledger:
Hero Fill Rate, Publishable Edition Rate, Research Value Rate,
Correction Rate, Cost per Edition, Section Diversity, Agent Abstention,
No-Go findings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text


class MetricsCollector:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def collect(self, days: int = 30) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        with self.engine.connect() as conn:
            editions = conn.execute(
                text(
                    "SELECT status, included_section_ids, generation_cost_usd, "
                    "correction_count, edition_payload->>'lead' IS NOT NULL AS has_lead "
                    "FROM daily_editions WHERE generated_at >= :since"
                ),
                {"since": since},
            ).fetchall()
            runs = conn.execute(
                text(
                    "SELECT status FROM investigation_runs WHERE started_at >= :since"
                ),
                {"since": since},
            ).fetchall()
            claims = conn.execute(
                text(
                    "SELECT status, claim_type FROM claims WHERE issued_at >= :since"
                ),
                {"since": since},
            ).fetchall()
            candidates = conn.execute(
                text(
                    "SELECT status FROM research_signal_candidates "
                    "WHERE created_at >= :since"
                ),
                {"since": since},
            ).fetchall()

        total_editions = len(editions)
        hero_fill = sum(1 for e in editions if e[4]) / total_editions if total_editions else 0.0
        publishable = sum(1 for e in editions if e[0] == "published") / total_editions if total_editions else 0.0
        corrected = sum(1 for e in editions if e[3] and e[3] > 0) / total_editions if total_editions else 0.0
        total_cost = sum(float(e[2] or 0) for e in editions)
        cost_per_edition = total_cost / total_editions if total_editions else 0.0
        section_counts = [len(e[1] or []) for e in editions]
        section_diversity = sum(section_counts) / len(section_counts) if section_counts else 0.0

        total_runs = len(runs)
        abstentions = sum(1 for r in runs if r[0] == "abstained")
        agent_abstention = abstentions / total_runs if total_runs else 0.0

        total_claims = len(claims)
        sum(1 for c in claims if c[0] == "rejected")
        research_claims = sum(
            1 for c in claims if c[1] in ("agent_observation", "research_observation", "rule_change_observation")
        )
        research_value = research_claims / total_claims if total_claims else 0.0

        total_candidates = len(candidates)
        no_go_findings = (
            sum(1 for c in claims if c[0] == "rejected")
            + sum(1 for c in candidates if c[0] in ("rejected", "abstained"))
        )

        return {
            "window_days": days,
            "hero_fill_rate": round(hero_fill, 4),
            "publishable_edition_rate": round(publishable, 4),
            "research_value_rate": round(research_value, 4),
            "correction_rate": round(corrected, 4),
            "cost_per_edition_usd": round(cost_per_edition, 4),
            "section_diversity": round(section_diversity, 2),
            "agent_abstention_rate": round(agent_abstention, 4),
            "no_go_findings": no_go_findings,
            "totals": {
                "editions": total_editions,
                "runs": total_runs,
                "claims": total_claims,
                "candidates": total_candidates,
            },
        }
