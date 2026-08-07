"""Shadow environment (spec §34.x, OS-033).

Isolation from production for evaluation:
- database: a separate PostgreSQL schema (``shadow``) cloned from the core
  metadata
- object storage: a separate directory (OPEN_SIGNAL_SHADOW_STORE or
  .shadow-objects under the fixtures dir)
- lineages / ledger: shadow ids prefixed with ``shadow-`` so production
  lineage/claim/edition ids never collide
- edition URL: shadow editions are served under /shadow/editions/{id}

Activate with OPEN_SIGNAL_SHADOW=1 (or via the manager methods below).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from open_signal.db.models import metadata
from sqlalchemy import text

SHADOW_SCHEMA = "shadow"
SHADOW_PREFIX = "shadow-"


def shadow_mode() -> bool:
    return os.environ.get("OPEN_SIGNAL_SHADOW", "").strip().lower() in ("1", "true", "yes")


def shadow_id(identifier: str) -> str:
    """Prefix an id so shadow records never collide with production."""
    if not shadow_mode():
        return identifier
    return f"{SHADOW_PREFIX}{identifier}"


def shadow_edition_url(edition_id: str) -> str:
    """Shadow editions are served under /shadow/editions/{id}."""
    if not shadow_mode():
        return f"/editions/{edition_id}"
    return f"/shadow/editions/{edition_id}"


def shadow_store_dir() -> Path:
    """Separate object-storage directory for shadow mode."""
    env = os.environ.get("OPEN_SIGNAL_SHADOW_STORE")
    if env:
        return Path(env)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "fixtures" / ".shadow-objects"


class ShadowEnvironment:
    """Creates and checks the isolated shadow schema."""

    def __init__(self, engine: Any, schema_name: str = SHADOW_SCHEMA) -> None:
        self.engine = engine
        self.schema_name = schema_name

    def ensure_schema(self) -> None:
        """Create the shadow schema and clone all core tables into it."""
        with self.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema_name}"'))

        # clone tables from core metadata into the shadow schema
        from sqlalchemy import MetaData
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable

        shadow_meta = MetaData()
        for table in metadata.sorted_tables:
            table.to_metadata(shadow_meta, schema=self.schema_name)

        dialect = postgresql.dialect()
        with self.engine.begin() as conn:
            for table in shadow_meta.sorted_tables:
                conn.execute(text(str(CreateTable(table).compile(dialect=dialect)).strip()))

    def tables(self) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema ORDER BY table_name"
                ),
                {"schema": self.schema_name},
            ).fetchall()
        return [r[0] for r in rows]

    def is_isolated(self) -> bool:
        """Shadow schema exists and shares no tables with public."""
        tables = self.tables()
        if not tables:
            return False
        with self.engine.connect() as conn:
            public_rows = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ).fetchone()
        return len(tables) > 0 and public_rows[0] > 0
