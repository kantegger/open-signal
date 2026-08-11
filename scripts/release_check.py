"""Public Beta release check (spec §140, OS-040).

Pre-flight checks before the public beta: schema version, required env
secrets, operational tables with data, recent edition activity, and
audit/ops readiness. Run with: python scripts/release_check.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text

RESULT = dict[str, Any]
MIGRATION_HEAD = "0015"
MIN_OPS_TOKEN_LENGTH = 32


def ops_token_meets_minimum_length(token: str | None) -> bool:
    """Reject missing or obviously undersized server-side shared secrets."""
    return bool(token and len(token) >= MIN_OPS_TOKEN_LENGTH)


def run(engine: Any) -> list[RESULT]:
    checks: list[RESULT] = []
    now = datetime.now(timezone.utc)

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(
            {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail}
        )

    with engine.connect() as conn:
        # 1. schema version at head
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        add(
            "migrations at head",
            version == MIGRATION_HEAD,
            f"alembic_version={version}, expected={MIGRATION_HEAD}",
        )

        # 2. required secrets configured
        add(
            "DEEPSEEK_API_KEY set",
            bool(os.environ.get("DEEPSEEK_API_KEY")),
            "LLM provider key",
        )
        ops_token = os.environ.get("OPEN_SIGNAL_OPS_TOKEN")
        add(
            "OPEN_SIGNAL_OPS_TOKEN set",
            ops_token_meets_minimum_length(ops_token),
            f"server-side ops auth token ({MIN_OPS_TOKEN_LENGTH}+ characters)",
        )

        # 3. operational tables present + populated
        for table in (
            "sources",
            "daily_editions",
            "publication_channels",
            "claims",
            "feature_flags",
            "audit_events",
        ):
            exists = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            ).scalar_one()
            if not exists:
                add(f"table {table} exists", False, "missing")
                continue
            count = conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            add(f"table {table} populated", count > 0, f"{count} rows")

        # 4. recent edition activity
        recent = conn.execute(
            text("SELECT count(*) FROM daily_editions WHERE generated_at >= :since"),
            {"since": now - timedelta(days=7)},
        ).scalar_one()
        add("editions in last 7 days", recent > 0, f"{recent} editions")

        # 5. ops mode is normal
        mode = conn.execute(
            text(
                "SELECT enabled FROM feature_flags WHERE flag_name LIKE 'ops.mode.%' AND enabled = true"
            )
        ).fetchone()
        add("ops mode normal", mode is None, "no degraded-mode flag set")

        # 6. degraded/retracted sources
        bad_sources = conn.execute(
            text(
                "SELECT count(*) FROM sources WHERE status IN ('retracted', 'degraded')"
            )
        ).scalar_one()
        add("no retracted/degraded sources", bad_sources == 0, f"{bad_sources} flagged")

    return checks


def summary(checks: list[RESULT]) -> tuple[int, int]:
    failed = sum(1 for c in checks if c["status"] == "FAIL")
    return failed, len(checks)


def main() -> int:
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        print("FAIL: OPEN_SIGNAL_DATABASE_URL not set")
        return 1
    checks = run(create_engine(url))
    failed, total = summary(checks)
    for c in checks:
        print(f"[{c['status']}] {c['check']}: {c['detail']}")
    print(f"\n{total - failed}/{total} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
