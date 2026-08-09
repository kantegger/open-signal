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
- Expectations, Rules, and Research are separate failure domains. A failed
  Research investigation cannot stop an Expectations refresh or retire a Rules
  item.
- Research remains `shadow`: ingestion, candidate detection, and Agent
  investigation run, but they do not create a public Claim or occupy a public
  Slot until the Registry maturity changes.
- A Section refresh only recompiles the front page when it produced new verified
  meaning. Unchanged Sections retain their last verified output.
- Freshness reconciliation publishes only when an item ages, is demoted, or is
  retired. An hourly check must not manufacture hourly Edition snapshots.
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
