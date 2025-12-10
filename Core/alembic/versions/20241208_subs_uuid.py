"""reshape tenant_subscriptions to UUID PK and new columns

Revision ID: 20241208_subs_uuid
Revises: a74ea1c0df1e
Create Date: 2025-12-08
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20241208_subs_uuid'
down_revision: Union[str, None] = 'a74ea1c0df1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    op.execute('ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS tenant_subscription_id uuid')
    op.execute('ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS plan_selected VARCHAR(50)')
    op.execute('ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS created_by uuid')
    op.execute('ALTER TABLE tenant_subscriptions ALTER COLUMN payment_method TYPE VARCHAR(50)')
    op.execute("ALTER TABLE tenant_subscriptions ALTER COLUMN tenant_subscription_id SET DEFAULT uuid_generate_v4()")

    op.execute("UPDATE tenant_subscriptions SET plan_selected = plan_code WHERE plan_selected IS NULL")
    op.execute("UPDATE tenant_subscriptions SET tenant_subscription_id = uuid_generate_v4() WHERE tenant_subscription_id IS NULL")

    op.execute("ALTER TABLE tenant_subscriptions DROP CONSTRAINT IF EXISTS tenant_subscriptions_pkey")
    op.create_primary_key("pk_tenant_subscriptions_uuid", "tenant_subscriptions", ["tenant_subscription_id"])

    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS id")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS previous_sub_id")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS plan_code")

    op.alter_column('tenant_subscriptions', 'tenant_subscription_id', server_default=None, nullable=False)
    op.alter_column('tenant_subscriptions', 'plan_selected', nullable=False)


def downgrade() -> None:
    op.add_column('tenant_subscriptions', sa.Column('plan_code', sa.VARCHAR(length=50), nullable=True))
    op.add_column('tenant_subscriptions', sa.Column('previous_sub_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('tenant_subscriptions', sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False))
    op.execute("UPDATE tenant_subscriptions SET plan_code = plan_selected WHERE plan_code IS NULL")
    op.execute("ALTER TABLE tenant_subscriptions DROP CONSTRAINT IF EXISTS pk_tenant_subscriptions_uuid")
    op.create_primary_key("tenant_subscriptions_pkey", "tenant_subscriptions", ["id"])
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS payment_method")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS plan_selected")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS tenant_subscription_id")

