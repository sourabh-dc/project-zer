"""baseline — current platform schema

Captures the schema as it exists today:

  * provisioning_service models (shared platform schema, incl. S0 supplier
    marketplace tables: legal_organisations, supplier_profiles,
    tenants.legal_org_id)
  * procurement_service models (procurement_orders, procurement_order_details)
  * data_intelligence_service raw-SQL tables (derived_knowledge, chat_*)

ADOPTION — existing databases (schema already present, S0 SQL already run):

    alembic -c db/alembic.ini stamp 0001_baseline

Fresh databases:

    alembic -c db/alembic.ini upgrade head

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-27
"""
from alembic import op

# NOTE: service models are imported inside upgrade() — revision modules must
# stay import-safe without repo root on sys.path (alembic loads them directly).

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from provisioning_service.Models import Base as ProvisioningBase
    from procurement_service.core.db_config import Base as ProcurementBase

    conn = op.get_bind()

    # ORM-owned schema (idempotent — create_all skips existing tables).
    # NOTE: orders_service is intentionally absent; it holds shadow
    # read-models of provisioning tables and owns no schema.
    ProvisioningBase.metadata.create_all(bind=conn)
    ProcurementBase.metadata.create_all(bind=conn)

    # data_intelligence_service raw-SQL tables (previously applied via
    # data_intelligence_service/migrations/*.sql — now managed here).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_knowledge (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            fact_type   VARCHAR(100) NOT NULL,
            payload     JSONB NOT NULL DEFAULT '{}',
            version     INTEGER NOT NULL DEFAULT 1,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_tenant_type "
        "ON derived_knowledge (tenant_id, fact_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_tenant_type_version "
        "ON derived_knowledge (tenant_id, fact_type, version DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            user_id     UUID NOT NULL,
            client_ref  VARCHAR(128),
            title       VARCHAR(300),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at  TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user "
        "ON chat_sessions (tenant_id, user_id, updated_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role        VARCHAR(16) NOT NULL,
            content     TEXT NOT NULL,
            engine      VARCHAR(16),
            trace       JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_session "
        "ON chat_messages (session_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_feedback (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id  UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            user_id     UUID NOT NULL,
            tenant_id   UUID NOT NULL,
            rating      SMALLINT NOT NULL,
            comment     TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_feedback_message_user UNIQUE (message_id, user_id)
        )
        """
    )


def downgrade() -> None:
    # Baseline is the floor — there is nothing before it. Dropping the whole
    # platform schema automatically would be reckless; do it manually if ever
    # truly needed.
    raise RuntimeError("Cannot downgrade below the baseline revision.")
