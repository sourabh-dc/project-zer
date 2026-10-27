"""
Alembic environment — centralized schema management for the ZeroQue platform.

Schema ownership rules (important — read before adding models):

  * provisioning_service.Models  → OWNS the shared platform schema
    (tenants, users, vendors, products, outbox, supplier marketplace, ...).
    Autogenerate diffs against this metadata.

  * procurement_service          → owns its two procurement_orders* tables.
    Included in autogenerate.

  * orders_service.Models        → SHADOW read-models of provisioning tables
    (same table names, fewer columns). It must NEVER create or alter schema.
    Deliberately excluded here — including it would collide with the
    provisioning-owned tables of the same name.

  * data_intelligence_service    → raw-SQL tables (derived_knowledge, chat_*)
    created in the baseline revision. Future changes via new revisions with
    op.execute(). Excluded from autogenerate via include_object below.

URL resolution: DATABASE_URL env var wins; falls back to alembic.ini value.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Repo root on sys.path — service imports work from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from provisioning_service.Models import Base as ProvisioningBase
from procurement_service.core.db_config import Base as ProcurementBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Connection ─────────────────────────────────────────────────────
db_url = (os.getenv("DATABASE_URL") or "").strip()
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# ── Metadata under management ──────────────────────────────────────
target_metadata = [ProvisioningBase.metadata, ProcurementBase.metadata]

# Tables Alembic is allowed to diff (everything else in the DB is invisible
# to autogenerate — prevents it trying to drop raw-SQL / foreign tables).
_OWNED_TABLES = {t.name for md in target_metadata for t in md.tables.values()}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in _OWNED_TABLES
    table = getattr(obj, "table", None)
    if table is not None:
        return table.name in _OWNED_TABLES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
