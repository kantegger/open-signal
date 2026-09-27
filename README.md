# Open Signal

A live front page of public signals — an AI-native, zero-editor runtime that
ingests public data, investigates changes with agents, verifies claims and
recomposes a rolling front page when verified meaning changes. Long-term
accountability comes from an append-only Claim Ledger and frozen Edition
history.

The authoritative product and system specification lives in
[`spec.md`](./spec.md) (v0.1 draft). Machine-readable registries are extracted
under [`infra/registries/`](./infra/registries/).

## Monorepo layout (spec §118)

```text
/apps
  /web        Next.js public site and operations console
  /worker     Python ingestion, analysis, agents and composer
/packages
  /contracts  generated JSON Schema and TypeScript types
  /ui         shared frontend components
  /edition-renderer  Render Plan validation and component mapping
/python
  /open_signal  sources / canonical / derived / agents / claims /
                composer / jobs / observability
/fixtures     recorded source responses, historical test documents,
              agent evaluation cases
/infra
  /registries  machine-readable Section / Capability / Slot / Component /
               Resolution-template registries
  /migrations  database migrations (OS-003)
```

## Quick start

Prerequisites: Docker with compose, Node.js 22+, Python 3.11+.

```powershell
# one command: PostgreSQL + worker + web
docker compose up --build

# local web (without docker)
cd apps/web
npm install
npm run dev

# local worker package
pip install -e ./apps/worker[dev]
python -c "import open_signal; print(open_signal.__version__)"
```

Production topology, configuration, deployment and rollback are documented in
[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md). Destructive database-test isolation
is documented separately in [`docs/TESTING.md`](./docs/TESTING.md).

## Reference deployment and update cadence

This repository contains the complete runtime. [`os.yhleo.com`](https://os.yhleo.com)
is the maintainer's reference deployment and product showcase; it is not a
required service or a hosted backend for other installations.

The reference deployment runs one Cloudflare batch every three days. A batch
may ingest new source data, update derived observations, reconcile freshness,
and deliver a new immutable Edition, but it does **not** manufacture an Edition
when verified meaning has not changed. Existing signals keep their original
timestamps until their freshness policy demotes or retires them.

Self-hosters control frequency at two layers:

1. `infra/cloudflare/wrangler.jsonc` sets the outer UTC Cron that starts the
   one-shot Container.
2. `infra/registries/job-schedule-registry.yaml` sets each job's cadence in
   seconds. Rules, research, publication and retention can therefore run at
   different rates.

Common outer Cron choices are:

| Profile | Wrangler Cron | Typical use |
|---|---|---|
| Hourly | `0 * * * *` | Higher-freshness public monitor |
| Every 4 hours | `0 */4 * * *` | More frequent monitoring |
| Every 3 days (default) | `0 0 */3 * *` | Low-cost reference deployment |
| Weekly | `0 0 * * 0` | Demonstration or archival use |

If the outer Cron is slower than a registry cadence, it becomes the effective
global limit; missed hourly buckets are not replayed. To make the declared job
cadences match reality, update the corresponding `cadence_seconds` values as
well (`3600`, `14400`, `43200`, `86400`, `259200`, or `604800`). The outer Cron
should run at least as often as the shortest cadence you expect to preserve. See
[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md#scheduling-and-inactivity) for the
full schedule and cost trade-offs.

## Registries

The YAML registries are the runtime baseline — production code must not infer
Sections, Components, Slots or permissions from natural-language docs
(spec appendix A). Generated from `spec.md`:

| File | Contents |
|---|---|
| `section-registry.yaml` | 3 Sections |
| `capability-registry.yaml` | 15 Capabilities |
| `slot-registry.yaml` | 7 Slots |
| `component-registry.yaml` | 19 Components |
| `resolution-template-registry.yaml` | 3 Resolution Templates |

## Status

- OS-001 Monorepo bootstrap — done
- OS-002 Pydantic contract source — done (9 first-batch objects, JSON Schema
  + generated TypeScript types under `packages/contracts`)
- OS-003 Database migration foundation — done (36 tables from spec appendix C,
  Alembic; verified against real PostgreSQL: 52 FKs, 3 triggers, smoke test
  passing)
- OS-004 PostgreSQL job queue — done (enqueue / claim SKIP LOCKED / retry /
  dead-letter / idempotency / heartbeat; 9 tests against real PostgreSQL)
- OS-005 Source Registry & Rights Manifest — done (YAML loader with read
  views + reference validation, rights capability checks, agent_desks sync;
  11 tests, registry passes validation)
- OS-006 Raw Artifact Store — done (content-addressed SHA-256 store with
  deduplication, public/private buckets, retention metadata, signed access;
  Local + S3 adapters; 8 tests)
- OS-007 Polymarket Gamma Adapter — done (market discovery, pagination,
  cursor persistence via new source_cursors table (migration 0002),
  raw record storage, health check, fixtures; 6 tests, live API verified)
- OS-008 Market Observation — done (bucketed idempotent price sampling,
  midpoint/spread, data quality flags, rate-limit retry; default partition
  migration 0003; 5 tests)
- OS-009 Expectation Canonicalizer — done (single-source canonical
  expectations from binary source markets with explicit deadline and YES
  direction; idempotent; 6 tests)
- OS-010 Candidate Detection — done (delta_1h/24h/7d, direction,
  persistence, acceleration, reversal, data completeness; §32.5
  thresholds; every evaluation writes a Calculation Record (migration
  0004); 6 tests)
- OS-011 Deterministic Claim Construction — done (candidate → Observation
  Claim + Section Instance + Claim Bundle + Probability Move render
  candidate; migration 0005 section_instances; 2 tests)
- OS-012 Federal Register Source Chain — done (US rules discovery with
  document metadata, authoritative HTML artifact into public content-
  addressed store, version hash, publication dates, fixtures from live
  API; 4 tests)
- OS-013 US Rule Status Mapping — done (ontology YAML with 7 states +
  transitions, FR document mapping, transition validation,
  partial-effectiveness detection; 11 tests)
- OS-014 Rule Change Detection — done (paragraph alignment, add/delete/
  change hunks, technical-change filtering, Rule Change Type candidates;
  materiality deferred to agent; 11 tests)
- OS-015 Agent Tool Registry — done (JSON-Schema validated tools,
  permission scopes, cost tracking, result-size limits, tool-call log via
  agent_tool_calls (migration 0006); no arbitrary SQL/URL — 4 built-in
  read-only tools; 12 tests)
- OS-016 Evidence Bundle Builder — done (primary/historical evidence,
  counterexample candidates, computed metrics, token budget + estimate,
  content-only snapshot hash; 3 tests)
- OS-017 DeepSeek Agent Runtime — done (charter loader, agent lineage,
  structured JSON output with schema validation, abstention, token/cost
  recording on investigation_runs, retry policy; live DeepSeek API
  verified; 11 tests)
- OS-018 Rules Desk Charter Agent — done (LLM materiality judgment on
  rule-change candidates → Observation, Materiality, Affected categories,
  Limitations, Preferred component; rule_change_observation claims; live
  DeepSeek end-to-end verified; 5 tests)
- OS-019 Expectations Desk Charter Agent — done (persistence judgment +
  noise check over candidate metrics; hard guardrails: no psychological
  attribution, no investment advice — enforced in prompt + output
  validation + abstention path; agent_observation claims; live DeepSeek
  end-to-end verified; 5 tests)
- OS-020 Research Domain — done (4 frozen launch topics:
  oncology-immunotherapy / synthetic-biology / generative-ai /
  quantum-computing; topic definitions + baseline queries + entity
  mappings in infra/topics/research-frontier.yaml; OpenAlex + 
  ClinicalTrials.gov adapters with real-API fixtures; 7 tests)
- OS-021 Investigation Candidates — done (deterministic institution-entry,
  trial stage-transition, cross-topic relation detection →
  research_signal_candidates only, no Claims; 6 tests)
- OS-022 Research Domain Agent — done (Historian + Skeptic + Verification
  roles, verdict → Shadow Ledger only (no Claims), abstention path;
  runtime gained corrective schema retry; live DeepSeek end-to-end
  verified; 4+1 tests)
- OS-023 Claims Ledger — done (create/update/status-transition over
  claims + claim_versions + claim_events; SHA-256 event hash chain with
  verification; append-only enforced by DB triggers; Claim page read API;
  6 tests)
- OS-024 Claim Verification — done (8 gates: source / citation / number /
  date / rights / claim type / component fields / prohibited language
  (investment advice + psychological attribution); failed claims rejected
  and never reach the Composer; 8 tests)
- OS-025 Composer Component Runtime — done (8 launch components mapped to
  frontend keys; runtime validation against component registry (required
  fields / allowed slots / narrative mode / prohibited uses); render plan
  item assembly; 8 tests)
- OS-026 Slot Filler — done (7 slot types from registry with maturity
  gates and claim-type permissions, per-slot capacity, page filling with
  cross-slot dedup; 5 tests)
- OS-027 Edition Composer — done (hard rules: eligibility=verified only,
  claim dedup, section diversity cap, family repetition avoidance, slot
  compatibility, registry fallback; 6 tests)
- OS-028 Edition Orchestration — done (Lead/Lead Set, page pacing,
  component choice, Sparse Edition threshold; claims never mutated;
  part of EditionWriter)
- OS-029 Edition Writer — done (render_plans + daily_editions rows,
  Edition JSON, content-addressed CDN cache key, immutable archive
  snapshot, rollback and correction as new rows; 8 tests)
- OS-030 Public Claim Page — done (8 display blocks: Observation,
  Analysis, Assessment, Evidence, Counterevidence, Agent lineage, Claim
  ID, Version history; ClaimPagePresenter + FastAPI read-only endpoints
  (apps/api) + Next.js claim page (apps/web); 3 tests, web build passes)
- OS-031 Operations Console — done (8 read-only views: Current Edition,
  Source Health, Job Queue, Agent Runs, Verification Failures, Daily
  Cost, Feature Flags (migration 0007), Claims Corrected; 6 tests)
- OS-032 Budget Guard — done (per-run / daily desk / monthly global
  limits; soft limit → degraded mode; hard limit → deterministic-only,
  blocks new LLM runs; 5 tests)
- OS-035 Source Retraction — done (invalidate source + raw records,
  retire canonical expectations, degrade claims via ledger, correct
  editions, immutable archive record; idempotent; 3 tests)
- OS-036 Resolution MVP — done (binary expectation resolution via final
  probability, rule effective-by-date, Resolution Records with Brier
  contributions, Recently Resolved component view; 5 tests)
- OS-037 Degraded Modes — done (normal / static_edition /
  deterministic_only / section_restricted / archive_only via ops.mode.*
  feature flags + budget hard-limit fallback; edition + LLM policies;
  6 tests)
- OS-038 Security Hardening — done (prompt-injection detection +
  fixtures, SSRF guard (https + host allowlist + internal-IP rejection),
  size limits, secret scanning, ops auth (Authorization Bearer, fail closed;
  temporary X-Ops-Token compatibility),
  audit_events (migration 0008); ops API endpoints now require the token;
  23 tests)
- OS-039 30-day Review Metrics — done (Hero Fill Rate, Publishable
  Edition Rate, Research Value Rate, Correction Rate, Cost per Edition,
  Section Diversity, Agent Abstention Rate, No-Go findings; 2 tests)
- OS-033 Shadow Environment — done (isolated shadow schema cloned from
  core metadata, shadow object-store dir, shadow- prefixed lineages/
  ledger ids, /shadow/editions URLs under OPEN_SIGNAL_SHADOW=1; fixed
  source_cursors.source_id type mismatch Text→Uuid; 6 tests)
- OS-034 Evaluation Harness — done (fixture cases + agent rubrics
  (evidence grounding / guardrails / numerical accuracy / conciseness),
  lineage comparison, composer edition scoring, cost report; 9 tests)
- OS-040 Public Beta Release — done (docs/OS-040-PUBLIC-BETA.md: launch
  scope (front page / 3 sections / archive / claim page / method / system
  status), explicit non-goals (accounts / payments / alerts / public API /
  scorecard), deploy + rollback runbooks; scripts/release_check.py
  pre-flight with 12 checks; 3 tests)

**All 40 OS milestones complete — 275/275 tests pass.**

## Database

Schema metadata: `python/open_signal/db/models.py` (SQLAlchemy Core, 36 tables).
Migrations: `infra/migrations/` (Alembic). To run against a database:

```powershell
$env:OPEN_SIGNAL_DATABASE_URL = "postgresql://..."
python -m alembic -c infra/migrations/alembic.ini upgrade head
python scripts/smoke_db.py
```

## Safe database tests

Database-backed tests contain destructive cleanup and therefore require an
explicit `OPEN_SIGNAL_TEST_DATABASE_URL`. Pytest validates the configured
target before mapping it to application code; it will not fall back to
`OPEN_SIGNAL_DATABASE_URL`.

On Windows, run the guarded test entry point from any directory:

```powershell
& G:\NewSignal\scripts\test.ps1
```

The local configuration targets the isolated Neon `test` branch. CI uses its
own ephemeral PostgreSQL service. See [`docs/TESTING.md`](./docs/TESTING.md).

## Contributing and license

Contributions are welcome; see [`CONTRIBUTING.md`](./CONTRIBUTING.md). Report
security issues privately according to [`SECURITY.md`](./SECURITY.md).

Open Signal is licensed under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). See
[`LICENSE`](./LICENSE). The pre-publication security review and open-source
operating model are recorded in [`docs/OPEN_SOURCE.md`](./docs/OPEN_SOURCE.md).
