"""Read-only report for the bounded raw payload purge policy."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from open_signal.retention.policy import RawRetentionPolicy

_UUID_PATTERN = (
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

_REPORT_SQL = """
WITH ranked AS (
    SELECT r.id,
           s.slug AS source_slug,
           r.payload,
           COALESCE(pg_column_size(r.payload), 0)::bigint AS payload_bytes,
           COALESCE(r.payload_compressed_bytes, 0)::bigint AS archived_bytes,
           r.last_seen_at,
           r.ingested_at,
           r.retention_state,
           {hot_days_case} AS hot_days,
           row_number() OVER (
               PARTITION BY r.source_id, r.record_type, r.external_id
               ORDER BY r.last_seen_at DESC,
                        r.ingested_at DESC,
                        r.id DESC
           ) AS representation_rank,
           rights.id AS rights_manifest_id,
           rights.maximum_retention_days,
           rights.allowed_operations ->> 'rawCaching' AS raw_caching
    FROM raw_source_records r
    JOIN sources s ON s.id = r.source_id
    LEFT JOIN LATERAL (
        SELECT rm.id, rm.maximum_retention_days, rm.allowed_operations
        FROM rights_manifests rm
        WHERE rm.id = r.rights_manifest_id
           OR (r.rights_manifest_id IS NULL AND rm.source_id = r.source_id)
        ORDER BY (rm.id = r.rights_manifest_id) DESC, rm.reviewed_at DESC, rm.id DESC
        LIMIT 1
    ) rights ON true
), classified AS (
    SELECT ranked.*,
           CASE
               WHEN retention_state = 'purged' THEN 'purged'
               WHEN retention_state = 'cold' THEN 'cold'
               WHEN representation_rank = 1 THEN 'current_hot'
               WHEN last_seen_at > :as_of - make_interval(days => hot_days)
                   THEN 'superseded_hot'
               ELSE 'eligible_report_only'
           END AS disposition,
           CASE
               WHEN rights_manifest_id IS NULL THEN 'unreviewed'
               WHEN raw_caching = 'false' THEN 'raw_caching_denied'
               WHEN maximum_retention_days IS NOT NULL
                    AND ingested_at <= :as_of
                        - make_interval(days => maximum_retention_days)
                   THEN 'maximum_retention_exceeded'
               ELSE 'reviewed'
           END AS rights_state,
           last_seen_at + make_interval(days => hot_days) AS eligible_at
    FROM ranked
), refs AS (
    SELECT raw_source_record_id AS raw_id, 'raw_artifact'::text AS reason
    FROM raw_artifacts WHERE raw_source_record_id IS NOT NULL
    UNION ALL
    SELECT raw_source_record_id, 'source_market'
    FROM source_markets WHERE raw_source_record_id IS NOT NULL
    UNION ALL
    SELECT raw_source_record_id, 'market_observation'
    FROM market_observations WHERE raw_source_record_id IS NOT NULL
    UNION ALL
    SELECT source_record.raw_id, 'rule_version'
    FROM rule_versions rv
    CROSS JOIN LATERAL unnest(rv.source_document_ids) AS source_record(raw_id)
    UNION ALL
    SELECT source_record.raw_id, 'rule_transition'
    FROM rule_transitions rt
    CROSS JOIN LATERAL unnest(rt.authoritative_source_record_ids)
        AS source_record(raw_id)
    UNION ALL
    SELECT source_record.raw_id, 'research_work'
    FROM research_works rw
    CROSS JOIN LATERAL unnest(rw.source_record_ids) AS source_record(raw_id)
    UNION ALL
    SELECT source_record.raw_id, 'research_relation'
    FROM research_relations rr
    CROSS JOIN LATERAL unnest(rr.source_record_ids) AS source_record(raw_id)
    UNION ALL
    SELECT source_record.raw_id, 'resolution_record'
    FROM resolution_records resolution
    CROSS JOIN LATERAL unnest(resolution.resolution_source_record_ids)
        AS source_record(raw_id)
    UNION ALL
    SELECT (found.value)[1]::uuid, 'public_evidence'
    FROM evidence_bundles eb
    CROSS JOIN LATERAL regexp_matches(
        concat_ws(
            ' ', eb.primary_evidence::text, eb.supporting_evidence::text,
            eb.counter_evidence::text, eb.source_coverage::text
        ),
        :uuid_pattern,
        'g'
    ) AS found(value)
    WHERE EXISTS (
        SELECT 1 FROM claims c
        WHERE c.evidence_bundle_id = eb.id
          AND c.status IN ('verified', 'published', 'active')
    ) OR EXISTS (
        SELECT 1 FROM claim_versions cv WHERE cv.evidence_bundle_id = eb.id
    )
    UNION ALL
    SELECT (found.value)[1]::uuid, 'public_edition'
    FROM daily_editions edition
    CROSS JOIN LATERAL regexp_matches(
        edition.edition_payload::text,
        :uuid_pattern,
        'g'
    ) AS found(value)
    WHERE edition.first_published_at IS NOT NULL
), ref_summary AS (
    SELECT raw_id, array_agg(DISTINCT reason ORDER BY reason) AS reasons
    FROM refs
    WHERE raw_id IS NOT NULL
    GROUP BY raw_id
)
SELECT c.source_slug,
       c.hot_days,
       c.disposition,
       c.rights_state,
       COALESCE(refs.reasons, ARRAY[]::text[]) AS dependency_reasons,
       count(*)::bigint AS row_count,
       COALESCE(sum(c.payload_bytes), 0)::bigint AS logical_payload_bytes,
       COALESCE(sum(c.archived_bytes), 0)::bigint AS archived_payload_bytes,
       min(c.ingested_at) AS oldest_ingested_at,
       max(c.ingested_at) AS newest_ingested_at,
       min(c.eligible_at) FILTER (WHERE c.disposition = 'superseded_hot')
           AS next_eligible_at
FROM classified c
LEFT JOIN ref_summary refs ON refs.raw_id = c.id
GROUP BY c.source_slug, c.hot_days, c.disposition, c.rights_state, refs.reasons
ORDER BY c.source_slug, c.disposition, c.rights_state, refs.reasons
"""

_TABLE_STATS_SQL = """
SELECT count(*)::bigint AS row_count,
       pg_total_relation_size('raw_source_records')::bigint AS total_relation_bytes,
       COALESCE(sum(pg_column_size(payload)), 0)::bigint AS logical_hot_payload_bytes,
       COALESCE(sum(payload_compressed_bytes), 0)::bigint AS logical_cold_payload_bytes
FROM raw_source_records
"""


class RawRetentionPlanner:
    """Produce an aggregate report without acquiring write privileges."""

    def __init__(self, engine: Any, policy: RawRetentionPolicy | None = None) -> None:
        self.engine = engine
        self.policy = policy or RawRetentionPolicy.load()
        self.policy.validate()

    def plan(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        as_of = as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            raise ValueError("retention report as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
        hot_days_case, parameters = self._hot_days_case()
        parameters.update({"as_of": as_of, "uuid_pattern": _UUID_PATTERN})

        with self.engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '60s'"))
            table_stats = conn.execute(text(_TABLE_STATS_SQL)).mappings().one()
            rows = conn.execute(
                text(_REPORT_SQL.format(hot_days_case=hot_days_case)),
                parameters,
            ).mappings().all()

        report = self._assemble(rows)
        report.update(
            {
                "mode": "report_only",
                "mutation_permitted": False,
                "generated_at": as_of.isoformat(),
                "policy": self.policy.as_public_dict(),
                "table": {key: int(value or 0) for key, value in table_stats.items()},
            }
        )
        report["warnings"] = self._warnings(report)
        return report

    def _hot_days_case(self) -> tuple[str, dict[str, Any]]:
        parameters: dict[str, Any] = {
            "default_hot_days": self.policy.default_hot_days
        }
        clauses: list[str] = []
        for index, (slug, days) in enumerate(sorted(self.policy.source_hot_days.items())):
            parameters[f"source_slug_{index}"] = slug
            parameters[f"source_hot_days_{index}"] = days
            clauses.append(
                f"WHEN s.slug = :source_slug_{index} THEN :source_hot_days_{index}"
            )
        return (
            "CASE " + " ".join(clauses) + " ELSE :default_hot_days END",
            parameters,
        )

    @staticmethod
    def _assemble(rows: list[Any]) -> dict[str, Any]:
        sources: dict[str, dict[str, Any]] = {}
        totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"rows": 0, "logical_payload_bytes": 0}
        )
        activation = {
            "eligible_rows": 0,
            "eligible_logical_payload_bytes": 0,
            "provenance_held_rows": 0,
            "provenance_held_logical_payload_bytes": 0,
            "dependency_free_rows": 0,
            "dependency_free_logical_payload_bytes": 0,
            "blocked_by_rights_rows": 0,
            "dependency_reasons": {},
        }

        for row in rows:
            slug = str(row["source_slug"])
            source = sources.setdefault(
                slug,
                {
                    "source_slug": slug,
                    "hot_days": int(row["hot_days"]),
                    "rows": 0,
                    "logical_payload_bytes": 0,
                    "dispositions": {},
                    "rights_states": {},
                    "next_eligible_at": None,
                },
            )
            count = int(row["row_count"] or 0)
            payload_bytes = int(row["logical_payload_bytes"] or 0)
            disposition = str(row["disposition"])
            rights_state = str(row["rights_state"])
            dependencies = sorted(str(value) for value in row["dependency_reasons"] or [])

            source["rows"] += count
            source["logical_payload_bytes"] += payload_bytes
            _increment(source["dispositions"], disposition, count, payload_bytes)
            _increment(source["rights_states"], rights_state, count, payload_bytes)
            _increment(totals, disposition, count, payload_bytes)

            next_eligible_at = row["next_eligible_at"]
            if next_eligible_at is not None:
                current = source["next_eligible_at"]
                candidate = next_eligible_at.isoformat()
                if current is None or candidate < current:
                    source["next_eligible_at"] = candidate

            if disposition != "eligible_report_only":
                continue
            activation["eligible_rows"] += count
            activation["eligible_logical_payload_bytes"] += payload_bytes
            if rights_state in {"raw_caching_denied", "maximum_retention_exceeded"}:
                activation["blocked_by_rights_rows"] += count
                continue
            if dependencies:
                activation["provenance_held_rows"] += count
                activation["provenance_held_logical_payload_bytes"] += payload_bytes
                for reason in dependencies:
                    activation["dependency_reasons"][reason] = (
                        activation["dependency_reasons"].get(reason, 0) + count
                    )
            else:
                activation["dependency_free_rows"] += count
                activation["dependency_free_logical_payload_bytes"] += payload_bytes

        return {
            "totals": dict(sorted(totals.items())),
            "sources": [sources[key] for key in sorted(sources)],
            "activation": activation,
        }

    @staticmethod
    def _warnings(report: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        unreviewed = sum(
            source["rights_states"].get("unreviewed", {}).get("rows", 0)
            for source in report["sources"]
        )
        if unreviewed:
            warnings.append(
                f"{unreviewed} rows have no reviewed Rights Manifest; "
                "the report keeps that governance gap visible."
            )
        held = report["activation"]["provenance_held_rows"]
        if held:
            warnings.append(
                f"{held} otherwise eligible rows have legacy provenance references. "
                "The purge executor preserves row identity and hashes and relies on "
                "sealed-v1 bundles for new public evidence."
            )
        if report["activation"]["blocked_by_rights_rows"]:
            warnings.append(
                "Some rows have restrictive source-rights metadata; purging reduces "
                "stored source content and never copies it to public R2."
            )
        warnings.append(
            "This report measures logical payload bytes, not immediately reclaimable "
            "PostgreSQL file bytes; activation also requires vacuum/reuse monitoring."
        )
        return warnings


def _increment(
    target: dict[str, dict[str, int]],
    key: str,
    rows: int,
    payload_bytes: int,
) -> None:
    bucket = target.setdefault(key, {"rows": 0, "logical_payload_bytes": 0})
    bucket["rows"] += rows
    bucket["logical_payload_bytes"] += payload_bytes
