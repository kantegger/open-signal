# infra

Deployment, registries and migrations.

## registries

Machine-readable runtime baseline extracted from spec appendix A:

- `section-registry.yaml` — 3 Sections
- `capability-registry.yaml` — 15 Capabilities
- `slot-registry.yaml` — 7 Slots
- `component-registry.yaml` — 19 Components
- `resolution-template-registry.yaml` — 3 Resolution Templates

Regeneration: extract the YAML blocks from `spec.md` appendix A. Keep these
files in sync with the spec — production code reads these, not the Markdown.

## migrations

Database migrations (Alembic, OS-003).
