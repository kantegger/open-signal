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
