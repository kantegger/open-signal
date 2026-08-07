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

Monorepo bootstrap (OS-001). Next milestones: OS-002 Pydantic contract
source, OS-003 database migrations, OS-004 PostgreSQL job queue.
