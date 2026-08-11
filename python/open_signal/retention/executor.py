"""Bounded executor that clears only superseded raw payload bodies."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from open_signal.retention.policy import RawRetentionPolicy

_ELIGIBLE_SQL = """
WITH ranked AS (
    SELECT r.id,
           row_number() OVER (
               PARTITION BY r.source_id, r.record_type, r.external_id
               ORDER BY r.last_seen_at DESC,
                        r.ingested_at DESC,
                        r.id DESC
           ) AS representation_rank
    FROM raw_source_records r
    WHERE r.retention_state = 'hot'
)
SELECT r.id, r.source_id, s.slug AS source_slug, r.content_hash,
       r.last_seen_at, COALESCE(pg_column_size(r.payload), 0)::bigint AS payload_bytes
FROM ranked
JOIN raw_source_records r ON r.id = ranked.id
JOIN sources s ON s.id = r.source_id
WHERE ranked.representation_rank > 1
  AND r.retention_state = 'hot'
  AND r.payload IS NOT NULL
  AND r.last_seen_at <= :as_of - make_interval(days => {hot_days_case})
ORDER BY r.last_seen_at, r.id
LIMIT :maximum_rows
FOR UPDATE OF r SKIP LOCKED
"""

_INSERT_AUDIT_EVENTS_SQL = """
INSERT INTO raw_payload_purge_events
  (raw_source_record_id, source_id, source_content_hash,
   policy_version, actor, reason, detail)
SELECT r.id,
       r.source_id,
       r.content_hash,
       :policy,
       :actor,
       :reason,
       jsonb_build_object(
           'source_slug', s.slug,
           'last_seen_at', r.last_seen_at,
           'payload_bytes', COALESCE(pg_column_size(r.payload), 0),
           'row_identity_preserved', true
       )
FROM raw_source_records r
JOIN sources s ON s.id = r.source_id
WHERE r.id = ANY(CAST(:raw_ids AS uuid[]))
  AND r.retention_state = 'hot'
  AND r.payload IS NOT NULL
RETURNING id, raw_source_record_id, created_at
"""

_PURGE_PAYLOADS_SQL = """
UPDATE raw_source_records r
SET payload = NULL,
    retention_state = 'purged',
    payload_purged_at = event.created_at,
    purge_policy_version = :policy
FROM raw_payload_purge_events event
WHERE event.id = ANY(CAST(:event_ids AS uuid[]))
  AND r.id = event.raw_source_record_id
  AND r.retention_state = 'hot'
  AND r.payload IS NOT NULL
RETURNING r.id
"""


class RawRetentionExecutor:
    """Purge a small deterministic batch while preserving provenance rows."""

    def __init__(self, engine: Any, policy: RawRetentionPolicy | None = None) -> None:
        self.engine = engine
        self.policy = policy or RawRetentionPolicy.load()
        self.policy.validate()

    def purge(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        if self.policy.mode != "active":
            raise RuntimeError("raw payload purge requires an active retention policy")
        as_of = as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            raise ValueError("retention purge as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
        executed_at = datetime.now(timezone.utc)
        hot_days_case, parameters = self._hot_days_case()
        parameters.update(
            {
                "as_of": as_of,
                "maximum_rows": self.policy.maximum_rows_per_run,
            }
        )

        source_rows: Counter[str] = Counter()
        source_bytes: Counter[str] = Counter()
        purged_ids: list[str] = []
        with self.engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout = '60s'"))
            rows = conn.execute(
                text(_ELIGIBLE_SQL.format(hot_days_case=hot_days_case)),
                parameters,
            ).mappings().all()
            if rows:
                raw_ids = [str(row["id"]) for row in rows]
                event_rows = (
                    conn.execute(
                        text(_INSERT_AUDIT_EVENTS_SQL),
                        {
                            "raw_ids": raw_ids,
                            "policy": self.policy.version,
                            "actor": "retention-executor",
                            "reason": (
                                "superseded representation exceeded source TTL"
                            ),
                        },
                    )
                    .mappings()
                    .all()
                )
                if len(event_rows) != len(rows):
                    raise RuntimeError(
                        "raw payload audit batch changed during purge: "
                        f"selected={len(rows)} audited={len(event_rows)}"
                    )
                event_ids = [str(event["id"]) for event in event_rows]
                updated_ids = {
                    str(row_id)
                    for row_id in conn.execute(
                        text(_PURGE_PAYLOADS_SQL),
                        {
                            "event_ids": event_ids,
                            "policy": self.policy.version,
                        },
                    ).scalars()
                }
                if updated_ids != set(raw_ids):
                    raise RuntimeError(
                        "raw payload batch changed during purge: "
                        f"selected={len(raw_ids)} updated={len(updated_ids)}"
                    )

            for row in rows:
                slug = str(row["source_slug"])
                source_rows[slug] += 1
                source_bytes[slug] += int(row["payload_bytes"])
                purged_ids.append(str(row["id"]))

        return {
            "mode": "active",
            "policy_version": self.policy.version,
            "eligibility_as_of": as_of.isoformat(),
            "executed_at": executed_at.isoformat(),
            "purged_rows": len(purged_ids),
            "logical_payload_bytes_cleared": sum(source_bytes.values()),
            "sources": [
                {
                    "source_slug": slug,
                    "purged_rows": source_rows[slug],
                    "logical_payload_bytes_cleared": source_bytes[slug],
                }
                for slug in sorted(source_rows)
            ],
            "raw_source_record_ids": purged_ids,
            "maximum_rows_per_run": self.policy.maximum_rows_per_run,
            "more_may_be_eligible": len(purged_ids)
            == self.policy.maximum_rows_per_run,
        }

    def _hot_days_case(self) -> tuple[str, dict[str, Any]]:
        parameters: dict[str, Any] = {
            "default_hot_days": self.policy.default_hot_days
        }
        clauses: list[str] = []
        for index, (slug, days) in enumerate(sorted(self.policy.source_hot_days.items())):
            parameters[f"source_slug_{index}"] = slug
            parameters[f"source_hot_days_{index}"] = days
            clauses.append(
                f"WHEN s.slug = :source_slug_{index} "
                f"THEN :source_hot_days_{index}"
            )
        return (
            "CASE " + " ".join(clauses) + " ELSE :default_hot_days END",
            parameters,
        )
