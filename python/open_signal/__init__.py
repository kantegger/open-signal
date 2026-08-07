"""Open Signal worker package.

Monorepo skeleton (OS-001). Module responsibilities follow spec §117–§120:

- sources: source adapters and ingestion
- canonical: canonical layer models
- derived: feature and change detection
- agents: agent runtime, desk and shared roles
- claims: claim ledger core
- composer: deterministic composition engine
- jobs: PostgreSQL-backed job queue
- observability: logging, metrics and cost records
"""

__version__ = "0.1.0"
