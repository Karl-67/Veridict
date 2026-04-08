"""Alembic migration environment.

Wires Alembic against the Postgres database configured in Settings and exposes
the SQLAlchemy metadata declared in app.backend.db.models so that auto-generated
migrations include all run, clause, evidence, corpus, and human-review tables.
"""

from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Path fix: make sure the backend package is importable when alembic is
# invoked from the project root (e.g. `alembic -c app/backend/alembic.ini …`)
# ---------------------------------------------------------------------------
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ---------------------------------------------------------------------------
# Import project metadata and settings AFTER the path fix.
# db.models registers all ORM classes against `Base.metadata`.
# ---------------------------------------------------------------------------
from app.backend.db.models import (  # noqa: E402  – must be after sys.path fix
    RunRecord,
    StageExecutionRecord,
    FindingRecord,
    EvidenceRecord,
    ParsedClauseRecord,
    PolicyVersionRecord,
    ComplianceCorpusRecord,
    RunEventRecord,
    HumanReviewRecord,
)

# Import Base so we can hand its metadata to Alembic.
# All models above are registered on this Base automatically via their
# `__tablename__` declarations.
from app.backend.db.models import Base  # noqa: E402

from app.backend.core.config import get_settings  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object (gives access to values in alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Honour the Python logging config section inside alembic.ini if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Target metadata – Alembic uses this to diff the DB and generate migrations.
# ---------------------------------------------------------------------------
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Database URL: prefer the value already set in alembic.ini (`sqlalchemy.url`)
# but fall back to the application Settings so the same .env file is the
# single source of truth during development.
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        url = get_settings().postgres_dsn
    # Alembic runs migrations with a sync engine. The application's
    # POSTGRES_DSN typically uses the async asyncpg driver, which sync
    # SQLAlchemy can't open. Translate it to psycopg2 for migrations.
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg2")
    return url


# ---------------------------------------------------------------------------
# Offline migration (generates SQL without connecting to the DB)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This generates a SQL script that can be inspected or applied manually,
    useful in environments where a live DB connection is unavailable at
    migration-generation time.
    """
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare server defaults so that column default changes are detected.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration (connects to the DB and applies migrations directly)
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a live DB connection."""
    # Always resolve the URL via _get_db_url() so that an empty
    # `sqlalchemy.url` in alembic.ini falls through to POSTGRES_DSN from .env
    # (and asyncpg → psycopg2 translation is applied).
    ini_section = config.get_section(config.config_ini_section, {})
    ini_section["sqlalchemy.url"] = _get_db_url()

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # single-use connection per migration run
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes (e.g. VARCHAR length, NUMERIC precision).
            compare_type=True,
            # Detect server-default changes.
            compare_server_default=True,
            # Keep FK checks consistent across runs.
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
