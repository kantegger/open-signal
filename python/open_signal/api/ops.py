"""Operations console presenter (spec §141, OS-031).

Eight read-only aggregations: Current Edition, Source Health, Job Queue,
Agent Runs, Verification Failures, Daily Cost, Feature Flags,
Claims Corrected.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


class OpsPresenter:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def current_edition(self) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, edition_date, status, included_claim_ids, generated_at, "
                    "correction_count FROM daily_editions "
                    "ORDER BY generated_at DESC LIMIT 1"
                )
            ).fetchone()
        if row is None:
            return None
        return {
            "edition_id": str(row[0]),
            "edition_date": row[1].isoformat(),
            "status": row[2],
            "claim_count": len(row[3] or []),
            "generated_at": row[4].isoformat(),
            "correction_count": row[5],
        }

    def source_health(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT s.id, s.slug, s.status, s.adapter_id,
                           count(r.id) AS records,
                           max(r.source_created_at) AS last_seen
                    FROM sources s
                    LEFT JOIN raw_source_records r ON r.source_id = s.id
                    GROUP BY s.id, s.slug, s.status, s.adapter_id
                    ORDER BY s.slug
                    """
                )
            ).fetchall()
        return [
            {
                "source_id": str(r[0]),
                "slug": r[1],
                "status": r[2],
                "adapter_id": r[3],
                "raw_records": r[4],
                "last_seen": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]

    def job_queue(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT status, count(*) FROM jobs GROUP BY status")
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def agent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, desk_id, capability_id, status, model_version, "
                    "total_input_tokens, total_output_tokens, estimated_cost_usd, "
                    "started_at FROM investigation_runs "
                    "ORDER BY started_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "run_id": str(r[0]),
                "desk_id": r[1],
                "capability_id": r[2],
                "status": r[3],
                "model": r[4],
                "input_tokens": r[5],
                "output_tokens": r[6],
                "cost_usd": float(r[7]) if r[7] is not None else 0.0,
                "started_at": r[8].isoformat(),
            }
            for r in rows
        ]

    def verification_failures(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, claim_type, public_statement, status, issued_at "
                    "FROM claims WHERE status = 'rejected' "
                    "ORDER BY issued_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "claim_id": str(r[0]),
                "claim_type": r[1],
                "statement": r[2][:120],
                "status": r[3],
                "issued_at": r[4].isoformat(),
            }
            for r in rows
        ]

    def daily_cost(self, days: int = 14) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT date(started_at) AS day, count(*), sum(estimated_cost_usd)
                    FROM investigation_runs
                    WHERE started_at >= now() - make_interval(days => :days)
                    GROUP BY date(started_at) ORDER BY day
                    """
                ),
                {"days": days},
            ).fetchall()
        return [
            {"day": r[0].isoformat(), "runs": r[1], "cost_usd": float(r[2] or 0)} for r in rows
        ]

    def feature_flags(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT flag_name, enabled, description, updated_at "
                    "FROM feature_flags ORDER BY flag_name"
                )
            ).fetchall()
        return [
            {"flag_name": r[0], "enabled": r[1], "description": r[2], "updated_at": r[3].isoformat()}
            for r in rows
        ]

    def claims_corrected(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, edition_date, correction_count, generated_at "
                    "FROM daily_editions WHERE correction_count > 0 "
                    "ORDER BY generated_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "edition_id": str(r[0]),
                "edition_date": r[1].isoformat(),
                "correction_count": r[2],
                "generated_at": r[3].isoformat(),
            }
            for r in rows
        ]
