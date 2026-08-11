# OS-053 — Permanent Edition Archive and Retention Boundary

## Decision

An Edition that has ever been public is a permanent public record. Its compiled
payload and Render Plans are never updated or deleted. Corrections, withdrawals,
supersession, and future storage moves are represented as append-only lifecycle
events.

This preserves the distinction at the center of Open Signal:

- a public Claim or Edition is an accountable statement about what readers saw;
- a raw source record is reproducible input, not automatically a permanent public
  artifact;
- operational rows may have a retention window, but publication history may not.

## Record classes

| Record | Class | Policy in OS-053 |
|---|---|---|
| `daily_editions` after first publication | `public_permanent` | Never update or delete |
| Render Plans belonging to a public Edition | `public_permanent` | Never update or delete |
| `edition_events` | append-only permanent ledger | Insert only |
| Draft/non-public Edition rows | `operational_ttl` | Mutable until publication; cannot be promoted in place |
| Public Claims, versions, evidence and lineage | permanent accountability record | Existing ledger rules continue |
| Raw source-record identity, hashes and provenance | durable reproducibility index | Keep the row and ID; never break downstream references |
| Raw source-record JSON payload | hot/cold operational input | Report-only classification exists; R2 movement is not active |
| High-frequency observations | operational/reproducibility input | Compaction remains deferred until replay and resolution validation exists |

`first_published_at` is the durable classification boundary. Status alone is not
used to decide whether a historical Edition remains discoverable: a withdrawn or
superseded Edition was still once public.

## Archive discovery contract

`GET /api/editions` provides keyset pagination ordered by
`(generated_at DESC, id DESC)`. It supports year, Section, and status filters and
returns an opaque cursor. The Archive page consumes this endpoint directly; the
bounded SEO index is no longer the Archive database.

Every Edition retains its permanent URL at `/editions/{edition_id}`. The raw API
record also exposes its payload hash and ordered lifecycle events.

## Database enforcement

Migration `0012`:

1. backfills every previously public Edition as `public_permanent`;
2. computes a canonical PostgreSQL `jsonb` SHA-256 payload hash;
3. backfills a publication event;
4. rejects `UPDATE` and `DELETE` for public Editions and their Render Plans;
5. rejects `UPDATE` and `DELETE` for all Edition events;
6. validates per-Edition event sequence and previous-hash linkage.

Corrections continue to work by cloning the source snapshot, publishing a new
Edition, and appending `corrected` / `superseded` events. There is no generic
session-level trigger bypass.

## Raw payload retention: report-only phase

The production measurement on 2026-08-11 found 37,448 raw records occupying
about 173 MB of total PostgreSQL relation storage. Polymarket accounted for
about 126 MB of logical JSON payload and 32,637 of its 36,782 rows were already
superseded representations. The database was only three days old, so a uniform
30-day hot window would allow avoidable growth before reclaiming anything.

Migration `0013` therefore models payload location separately from record
identity. The `raw_source_records` row, content hash, timestamps, source link and
all downstream foreign-key targets remain in PostgreSQL. A future executor may
set only the JSON `payload` to `NULL` after the bytes exist in verified private
R2 storage. This avoids deleting provenance rows or rewriting public evidence.

The two-tier workflow is:

1. keep the latest representation for every external object hot regardless of
   age;
2. classify only superseded payloads against source-specific hot windows and
   Rights Manifests;
3. report all public-evidence and provenance dependencies;
4. build deterministic gzip bytes under a content-addressed private R2 key;
5. upload, read the object back, and verify compressed and source-content
   SHA-256 hashes;
6. append a `raw_payload_archive_events` row;
7. in the same database transaction, change `retention_state` to `cold`, store
   the verified pointer, and clear only `payload`;
8. monitor the recovery grace period, replay/rehydration, table reuse and cost.

The machine-readable report policy starts with:

- keep the current raw representation for every live external object in Neon;
- classify superseded Polymarket payloads after 7 days, general payloads after
  30 days, ClinicalTrials after 90 days and Federal Register after 365 days;
- treat dependency-bearing rows as held until every read/replay path can hydrate
  a cold payload;
- let an explicit Rights Manifest denial or legal maximum block R2 copying and
  require review;
- compact old market observations only after replay and resolution scoring have
  been tested against the compacted representation.

`retention.report_raw` is scheduled daily and its handler accepts only
`mode=report_only`. Its PostgreSQL transaction is explicitly read-only. The
standalone `python scripts/report_raw_retention.py` command has the same
boundary. Neither code path uploads to R2, updates a raw row, nor deletes data.

Database triggers reject a hot-to-cold transition unless a matching immutable
archive event already exists. Once archive metadata exists it cannot be
rewritten; identical source content may be rehydrated to hot while retaining the
verified pointer. The archive-object module currently defines and tests the
deterministic bytes and read-back verification contract only.

Production activation requires a separate reviewed executor/runbook, private R2
binding or credentials, restore drill, dependency hydration tests, source-rights
review, a bounded batch limit, and observed PostgreSQL page reuse. Logical JSON
bytes in the report are not a promise that PostgreSQL files shrink immediately.

## Deployment order

1. Run migration `0012` before deploying code that writes `edition_events`.
2. Verify Edition backfill counts and payload hashes.
3. Run migration `0013` before deploying the raw-retention planner.
4. Verify every existing raw row is `hot` with a non-null payload and no archive
   pointer.
5. Deploy the API, writer, web Archive and report-only retention handler.
6. Confirm Archive cursor traversal reaches the oldest public Edition.
7. Inspect at least one daily retention report before designing an execution
   batch.

Production Neon and R2 are not modified merely by merging OS-053; migration and
any future archive execution remain explicit deployment steps.
