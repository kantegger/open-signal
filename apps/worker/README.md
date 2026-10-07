# Open Signal worker

Python ingestion, analysis, agents and composer (spec §117.2).

The `open_signal` core package lives at the repo root under `/python`; the
deployable command lives in this package.

```powershell
pip install -e ./python
pip install -e ./apps/worker[dev]
python -m open_signal_worker --mode once --offline
```

Runtime modes:

- `scheduled` (default): enqueue due buckets, drain all queues, then make no
  database query until the next schedule boundary. This is the Neon
  scale-to-zero-friendly production mode.
- `once`: one schedule/drain cycle for platform Cron or a smoke test.
- `poll`: dedicated always-on consumer. This is opt-in because polling an empty
  PostgreSQL queue prevents compute suspension.

Use `--role source|analysis|agent|publication` only when splitting the initial
single process into role-specific workers.

The hosted demo was discontinued on October 7, 2026. The example self-hosted
configuration invokes `once` once every three days. The platform passes the
scheduled occurrence through `OPEN_SIGNAL_SCHEDULED_AT` so a delayed or
duplicate invocation still uses the intended deterministic Job buckets.
Longer desk cadences remain in the machine-readable schedule registry and are
idempotently skipped between due boundaries. Self-hosters can choose a different
outer Cron and matching registry cadences; see the root README.

The retention report runs once per week and remains read-only. A separate
weekly schedule clears at most 1,000 expired, superseded raw payload bodies per
run. It always preserves the newest representation for every external object,
the raw row identity and content hash, normalized observations, and sealed
public evidence. Run the read-only report on demand with:

```powershell
python scripts/report_raw_retention.py
```
