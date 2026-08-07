"""Alembic environment.

DATABASE_URL resolution order:
1. OPEN_SIGNAL_DATABASE_URL env var
2. sqlalchemy.url in alembic.ini
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the repo-root `python` package importable regardless of CWD.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from open_signal.db import models  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = models.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
