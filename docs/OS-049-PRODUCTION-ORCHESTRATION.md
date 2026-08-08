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

The default process is schedule-driven, not empty-queue polling:

1. enqueue every schedule due in the current deterministic bucket;
2. drain `source`, `analysis`, `agent`, and `publication` queues;
3. sleep locally until the earliest next schedule boundary;
4. make no database query during that sleep.

The shortest cadence is 15 minutes. After a normal batch finishes this leaves
more than the five-minute database inactivity window required by the configured
Neon computes. A continuous polling mode exists only as an explicit operational
choice for a future always-on deployment.

## Launch schedules

The authoritative values live in
`infra/registries/job-schedule-registry.yaml`:

| Work | Cadence | Public effect |
|---|---:|---|
| Polymarket source observations | 15 minutes | none until editorial batch |
| Expectations editorial batch | 2 hours | verified Section refresh |
| Federal Register source discovery | 2 hours | none until editorial batch |
| Rules editorial batch | 4 hours | verified Section refresh |
| OpenAlex / ClinicalTrials discovery | daily | shadow inputs only |
| Research candidate + investigation | daily | shadow ledger only |
| Freshness reconciliation | hourly | only on age/retirement transition |

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

- `scheduled` (default): one scale-to-zero-friendly long-running process.
- `once`: enqueue current schedule buckets, drain, and exit; suitable for a
  platform Cron invocation.
- `poll`: dedicated always-on queue consumer; deliberately opt-in and not the
  Public Beta default because it prevents database inactivity.
