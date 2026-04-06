from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Collect metadata from every service so `alembic revision --autogenerate`
# can detect schema drift across the whole shared database.
# ---------------------------------------------------------------------------
try:
    from provisioning_service.Models import Base as _ProvBase
    _prov_meta = _ProvBase.metadata
except Exception:
    _prov_meta = None

try:
    from orders_service.Models import Base as _OrdBase
    _ord_meta = _OrdBase.metadata
except Exception:
    _ord_meta = None

try:
    from policy_service.Models import Base as _PolBase
    _pol_meta = _PolBase.metadata
except Exception:
    _pol_meta = None

# Use the richest metadata object (provisioning owns the most tables) as the
# primary target, with tables from other services merged in.
if _prov_meta is not None:
    target_metadata = _prov_meta
    for meta in filter(None, [_ord_meta, _pol_meta]):
        for table in meta.tables.values():
            if table.name not in _prov_meta.tables:
                table.tometadata(_prov_meta)
else:
    target_metadata = None


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required for Alembic migrations. "
            "Set DATABASE_URL before running 'alembic upgrade head'."
        )
    return url


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
