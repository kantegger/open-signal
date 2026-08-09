# OS-049 — Production Orchestration Contract

## Decision status

Accepted for the Public Beta release candidate.

## Governing principles

The runtime preserves the same boundary as the editorial system:

```text
machine-readable schedule
        ↓
idempotent PostgreSQL Job
        ↓
Section-owned handler and failure boundary
        ↓
verified Claim or shadow-only result
        ↓
atomic rolling-page compile when meaning changed
```

- The Scheduler only creates Jobs. It never performs source, Agent, Claim, or
  publication work directly.
- Every scheduled occurrence has a deterministic time-bucket idempotency key.
  A Section-owned schedule revision may be added to that key when a generator
  contract changes, allowing one bounded replay without replaying unrelated
  schedules in the same registry version.
- Expectations, Rules, and Research are separate failure domains. A failed
  Research investigation cannot stop an Expectations refresh or retire a Rules
  item.
- Research remains `shadow`: ingestion, candidate detection, and Agent
  investigation run, but they do not create a public Claim or occupy an
  editorial Slot until the Registry maturity changes. Qualified deterministic
  candidate metrics may appear only in the explicitly non-Claim Research Watch
  layer of the snapshot-bound `publication_context`.
- A Research refresh records qualification counts and stable rejection reasons.
  Source input with zero public-qualified output emits an Ops audit event; the
  public compiler still hides the empty layer rather than inventing content.
- A Section refresh only recompiles the front page when it produced new verified
  meaning. Unchanged Sections retain their last verified output.
- A compact Expectations observation refresh retains still-valid featured
  Expectations items while atomically recompiling the full Section. New items
  receive placement priority; carried items remain subject to normal freshness
  and capacity rules.
- Freshness reconciliation publishes only when an item ages, is demoted, is
  retired, or the qualified public Research screening set changes. An hourly
  check must not manufacture hourly Edition snapshots.
- If any handler or compiler fails, the current Edition pointer does not move.

## Scale-to-zero runtime mode

The production process is schedule-driven, not empty-queue polling:

1. enqueue every schedule due in the current deterministic bucket;
2. drain `source`, `analysis`, `agent`, and `publication` queues;
3. exit after the batch;
4. let the platform invoke the next hourly occurrence.

The shortest cadence is one hour. After a normal batch finishes this leaves a
large quiet window for the Worker to scale to zero and for the configured Neon
computes to suspend after five minutes. The platform occurrence timestamp is
passed into the Worker so delayed and duplicate Cron delivery retains stable
Job buckets. A continuous polling mode exists only as an explicit operational
choice for a future always-on deployment.

## Launch schedules

The authoritative values live in
`infra/registries/job-schedule-registry.yaml`:

| Work | Cadence | Public effect |
|---|---:|---|
| Polymarket source + observations | hourly | none until editorial batch |
| Expectations editorial batch | hourly | verified Section refresh |
| Federal Register source discovery | 4 hours | none until editorial batch |
| Rules editorial batch | 4 hours | verified Section refresh |
| ClinicalTrials discovery | 12 hours | shadow inputs only |
| OpenAlex discovery | daily | shadow inputs only |
| Research candidate + investigation | daily | shadow ledger only |
| Freshness reconciliation | hourly | only on age/retirement transition |
| R2 publication snapshot delivery | hourly | only advances after a complete snapshot |

The hourly Polymarket batch discovers active event envelopes rather than a
fixture or a single global market page. It monitors up to 500 activity-ranked
markets with a per-event cap, backfills up to seven days of hourly CLOB price
history for newly monitored markets, and evaluates two publication tiers:
three Featured candidates and up to twelve compact Scanner candidates. These
are bounded monitoring and layout budgets, not topic allowlists.

OpenAlex and ClinicalTrials raw records preserve every monitoring Topic that led
to their discovery inside `transport_metadata.monitoring_topics`. Repeated
discovery of identical source content merges this attribution without changing
the source payload hash or counting the record as newly ingested. Candidate
detection groups institutional and sponsor activity within those Topics;
legacy OpenAlex rows may be attributed conservatively from frozen concept
mappings, while unattributed records remain internal-only.

## Queue and retry semantics

- Claiming uses `FOR UPDATE SKIP LOCKED`.
- A handler heartbeat renews a long-running Job lock.
- Retryable failures retain their Section boundary and use queue backoff.
- An unknown Job type is a failed Job, never a silent success.
- The scheduled runner wakes for a known retry, but it does not otherwise poll
  PostgreSQL between schedule boundaries.
- Claim and Research candidate creation use content-derived idempotency keys in
  addition to Job idempotency, so replay cannot duplicate editorial objects.

## Deployment modes

- `once` (production): enqueue the platform occurrence buckets, drain in
  dependency order, and exit; suitable for an hourly platform Cron invocation.
- `scheduled` (local/alternative): one database-silent long-running process.
- `poll`: dedicated always-on queue consumer; deliberately opt-in and not the
  Public Beta default because it prevents database inactivity.

The accepted hosted topology and secret boundaries are recorded in
[`DEPLOYMENT.md`](./DEPLOYMENT.md).
