# Test database isolation

The Worker suite performs destructive cleanup, including `TRUNCATE ...
CASCADE`. It must never run against the development or production database.

## Environment contract

| Variable | Purpose |
|---|---|
| `OPEN_SIGNAL_DATABASE_URL` | Application/runtime database only |
| `OPEN_SIGNAL_TEST_DATABASE_URL` | Explicit database target for pytest |
| `OPEN_SIGNAL_TEST_BRANCH_ID` | Expected Neon branch identity |

At pytest startup, `apps/worker/tests/conftest.py` applies these rules before
any test body can access the database:

1. `OPEN_SIGNAL_DATABASE_URL` is never accepted as a fallback test target.
2. Test and application URLs may not resolve to the same endpoint/database.
3. A Neon test URL requires `OPEN_SIGNAL_TEST_BRANCH_ID`.
4. The connected Neon branch must report that exact branch ID.
5. Only after those checks pass is the test URL exposed to application code as
   `OPEN_SIGNAL_DATABASE_URL` inside the pytest process.

If neither database variable is present, database-backed tests keep their
existing skip behavior. If the application URL is present without the test
URL, pytest fails immediately.

## Local Neon environment

- Project: `open-signal`
- Branch: `test`
- Branch ID: `br-winter-boat-azqozrmc`
- Parent: `production`

The branch began as a copy-on-write snapshot of its parent. Changes and
cleanup performed by tests remain isolated on the `test` branch.

The connection string is stored as a Windows User environment variable and is
not committed to the repository. The guarded PowerShell entry point loads the
User-scoped variables automatically:

```powershell
& G:\NewSignal\scripts\test.ps1
```

Pass normal pytest arguments after the script name when running a subset:

```powershell
& G:\NewSignal\scripts\test.ps1 apps/worker/tests/test_hardening.py -q
```

## CI

GitHub Actions uses a job-scoped PostgreSQL service through
`OPEN_SIGNAL_TEST_DATABASE_URL`. Migration and smoke-test commands map that
ephemeral URL to `OPEN_SIGNAL_DATABASE_URL` only for the individual command.
