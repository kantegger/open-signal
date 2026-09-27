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
| Raw source-record JSON payload | hot/purged operational input | Keep the newest representation; clear only expired superseded bodies |
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

## Raw payload retention: bounded active purge

The production measurement on 2026-08-11 found 37,448 raw records occupying
about 173 MB of total PostgreSQL relation storage. Polymarket accounted for
about 126 MB of logical JSON payload and 32,637 of its 36,782 rows were already
superseded representations. The database was only three days old, so a uniform
30-day hot window would allow avoidable growth before reclaiming anything.

Migration `0013` models payload location separately from record identity.
Migration `0014` adds the active `purged` state and an append-only purge-event
ledger. The `raw_source_records` row, content hash, timestamps, source link and
all downstream foreign-key targets remain in PostgreSQL; only an eligible JSON
`payload` body is cleared. Public Claims no longer depend on that mutable hot
body: new Claims must seal their exact public Evidence Bundle to a verified,
content-addressed R2 object before they can enter a public Edition.

The active workflow is:

1. keep the latest representation for every `(source, record type, external
   ID)` hot regardless of age;
2. classify only superseded payloads against source-specific hot windows;
3. select no more than 1,000 rows per execution with `FOR UPDATE SKIP LOCKED`;
4. append a `raw_payload_purge_events` audit row and clear only `payload` in the
   same database transaction;
5. retain source identity, content hash, timestamps and downstream references;
6. rehydrate an identical payload as hot if an adapter observes it again;
7. monitor logical bytes cleared, PostgreSQL page reuse and storage cost.

The machine-readable report policy starts with:

- keep the current raw representation for every live external object in Neon;
- classify superseded Polymarket payloads after 2 days, general payloads after
  30 days, ClinicalTrials after 90 days and Federal Register after 365 days;
- keep sealed public Evidence Bundles in R2 permanently and independently from
  the raw-payload TTL;
- compact old market observations only after replay and resolution scoring have
  been tested against the compacted representation.

`retention.report_raw` is scheduled weekly and its handler accepts only
`mode=report_only`. Its PostgreSQL transaction is explicitly read-only. The
standalone `python scripts/report_raw_retention.py` command has the same
boundary. `retention.purge_raw` reuses the existing three-day scheduler with a
phase offset and processes at most 1,000 rows per run; it does not increase the
Cloudflare Cron frequency or add a separate Neon wake-up.

Database triggers reject direct payload clearing unless the same transaction
has inserted the matching immutable purge event. Purge events cannot be updated
or deleted. The older cold/archive schema remains readable for backward
compatibility, but there is no asynchronous raw-payload-to-R2 archive job.

Logical JSON bytes cleared are not a promise that PostgreSQL files or Neon
storage metrics shrink immediately; the first objective is to stop avoidable
growth while PostgreSQL vacuum and page reuse catch up.

## Deployment order

1. Run migration `0012` before deploying code that writes `edition_events`.
2. Verify Edition backfill counts and payload hashes.
3. Run migration `0013`, then the expand migration `0014`. Its transitional
   Claim default remains legacy so the previous worker can continue safely.
4. Verify every existing raw row is `hot` with a non-null payload and no archive
   pointer.
5. Deploy the API, writers, web Archive, evidence sealer, report handler and
   bounded purge handler. Every new writer explicitly selects `sealed-v1`.
6. After the new worker is healthy, run contract migration `0015` to make
   `sealed-v1` the database default. Downgrade to `0014` before rolling the
   application back to a pre-sealing release.
7. Confirm Archive cursor traversal reaches the oldest public Edition.
8. Inspect the first weekly report and weekly purge audit before raising the
   1,000-row batch ceiling.

Production Neon and R2 are not modified merely by merging OS-053; migrations and
the first deployed scheduler execution remain explicit deployment steps.
