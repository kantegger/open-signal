# Contributing to Open Signal

Thank you for helping improve Open Signal. The project welcomes focused bug
fixes, source adapters, verification improvements, documentation, tests, and
careful product work that preserves the distinction between information and a
verified public signal.

## Before opening a change

- Read [`spec.md`](./spec.md) for the product philosophy and system contract.
- Check existing issues and pull requests before starting overlapping work.
- Open an issue first for changes to public contracts, editorial policy,
  database invariants, source rights, or deployment architecture.
- Never include credentials, private source material, production data, or
  personal data in code, fixtures, screenshots, logs, or commits.

## Development setup

The supported development baseline is Node.js 22+, Python 3.11+, and Docker
with Compose. Start with the root [`README.md`](./README.md), then install the
worker and web dependencies relevant to your change.

Database-backed tests are destructive by design and must use an isolated
`OPEN_SIGNAL_TEST_DATABASE_URL`. They must never fall back to the development
or production database. See [`docs/TESTING.md`](./docs/TESTING.md).

## Pull requests

1. Create a branch from `main`.
2. Keep the change focused and include tests for new behavior.
3. Update the machine-readable registries when changing Sections, Slots,
   Components, capabilities, schedules, or freshness policy.
4. Update documentation when changing a public interface or operating model.
5. Run the relevant checks locally and describe them in the pull request.
6. Wait for all required CI checks before merging.

Useful commands:

```powershell
pytest apps/worker/tests/ -q
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:e2e
npm --prefix infra/cloudflare run check
python -m ruff check python/ apps/api/
```

Generated contracts should be regenerated from their source definitions rather
than edited by hand. Do not weaken verification, evidence, or security gates
only to make a fixture or test pass.

## Contribution license

Unless you explicitly state otherwise, contributions intentionally submitted
for inclusion in Open Signal are provided under the Apache License 2.0, as
described in section 5 of [`LICENSE`](./LICENSE). No contributor license
agreement is currently required.
