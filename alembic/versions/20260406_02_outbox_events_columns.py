"""Move outbox_events column additions from runtime DDL into Alembic.

Previously provisioning_service added these columns at startup via inline ALTER
TABLE statements.  This revision makes the changes declarative and idempotent so
they are applied exactly once by the migration runner.

Revision ID: 20260406_02
Revises: 20260406_01
Create Date: 2026-04-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260406_02"
down_revision: Union[str, None] = "20260406_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use PostgreSQL IF NOT EXISTS guards so the migration is safe to run
    # against a database that already received these columns via the old
    # runtime path.
    op.execute(
        "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS "
        "aggregate_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS "
        "aggregate_id UUID"
    )
    # Rename event_data -> payload only when the old column still exists.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'event_data'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'payload'
            ) THEN
                ALTER TABLE outbox_events RENAME COLUMN event_data TO payload;
            END IF;
        END
        $$;
    """)
    op.execute(
        "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS "
        "payload JSONB NOT NULL DEFAULT '{}'"
    )
    # Back-fill aggregate_type from the event_type dot-prefix for existing rows.
    op.execute("""
        UPDATE outbox_events
        SET    aggregate_type = split_part(event_type, '.', 1)
        WHERE  aggregate_type IS NULL
    """)


def downgrade() -> None:
    # Intentionally left as no-op: dropping columns could destroy data and the
    # runtime code that previously created them is being removed.
    pass
