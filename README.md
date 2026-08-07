# Open Signal

A live front page of public signals — an AI-native, zero-editor runtime that
ingests public data, investigates changes with agents, verifies claims and
composes a daily front page. Long-term accountability via an append-only
Claim Ledger and public Track Record.

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

Next milestones: OS-024 Claim verification checks, OS-025 Composer.

## Database

Schema metadata: `python/open_signal/db/models.py` (SQLAlchemy Core, 36 tables).
Migrations: `infra/migrations/` (Alembic). To run against a database:

```powershell
$env:OPEN_SIGNAL_DATABASE_URL = "postgresql://..."
python -m alembic -c infra/migrations/alembic.ini upgrade head
python scripts/smoke_db.py
```
