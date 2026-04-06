"""Fail-fast DB migration guard — call once at service startup.

Usage in a FastAPI lifespan:

    from alembic.db_check import assert_db_at_alembic_head

    @asynccontextmanager
    async def lifespan(app):
        assert_db_at_alembic_head(SETTINGS.DATABASE_URL)
        ...
        yield

The function raises RuntimeError if the database is not at the expected Alembic
head revision, preventing a service from starting against a stale schema.

Deployment contract:
    1. Run `alembic upgrade head` (migration job / init-container).
    2. Start services.

Services must NOT start unless the DB is fully migrated.
"""
from __future__ import annotations

import os

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine


def assert_db_at_alembic_head(database_url: str) -> None:
    """Raise RuntimeError if the database revision is not at Alembic head.

    Args:
        database_url: SQLAlchemy-compatible connection URL for the shared DB.

    Raises:
        RuntimeError: Schema mismatch — service startup should be aborted.
    """
    ini_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    )
    cfg = Config(ini_path)
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", database_url)

    script = ScriptDirectory.from_config(cfg)
    head_revs: set[str] = set(script.get_heads())

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_revs: set[str] = set(ctx.get_current_heads())
    finally:
        engine.dispose()

    if current_revs != head_revs:
        raise RuntimeError(
            "Database schema is not at migration head. "
            f"Current revision(s): {current_revs or 'none (unapplied)'}. "
            f"Expected head(s): {head_revs}. "
            "Run 'alembic upgrade head' before starting services."
        )
