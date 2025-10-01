"""migrate_to_v4.1_part5_indexes_rls_constraints

Revision ID: 3e3cb325a0ea
Revises: d7bbc65fcf8d
Create Date: 2025-09-30 14:44:51.805059+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3e3cb325a0ea'
down_revision = 'd7bbc65fcf8d'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Enable Row Level Security on tables that actually exist
    op.execute(sa.text("""
        ALTER TABLE tenants_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE sites_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE stores_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE users_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE roles_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE permissions_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE role_permissions_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_sites ENABLE ROW LEVEL SECURITY;
        ALTER TABLE site_stores ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_store_admins ENABLE ROW LEVEL SECURITY;
        ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_onboarding ENABLE ROW LEVEL SECURITY;
        ALTER TABLE role_assignments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE permission_grants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE permission_resolution_cache ENABLE ROW LEVEL SECURITY;
        ALTER TABLE product_master ENABLE ROW LEVEL SECURITY;
        ALTER TABLE product_variants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_offers ENABLE ROW LEVEL SECURITY;
        ALTER TABLE inventory_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE orders_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE sub_orders ENABLE ROW LEVEL SECURITY;
        ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_settlements ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ledger_accounts_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ledger_entries_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cost_centres_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE budgets_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_chains ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_requests_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_approvers ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
    """))


def downgrade() -> None:
    # Disable Row Level Security
    op.execute(sa.text("""
        ALTER TABLE tenants_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE sites_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE stores_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE users_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE roles_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE permissions_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE role_permissions_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_sites DISABLE ROW LEVEL SECURITY;
        ALTER TABLE site_stores DISABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_store_admins DISABLE ROW LEVEL SECURITY;
        ALTER TABLE vendors DISABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_onboarding DISABLE ROW LEVEL SECURITY;
        ALTER TABLE role_assignments DISABLE ROW LEVEL SECURITY;
        ALTER TABLE permission_grants DISABLE ROW LEVEL SECURITY;
        ALTER TABLE permission_resolution_cache DISABLE ROW LEVEL SECURITY;
        ALTER TABLE product_master DISABLE ROW LEVEL SECURITY;
        ALTER TABLE product_variants DISABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_offers DISABLE ROW LEVEL SECURITY;
        ALTER TABLE inventory_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE orders_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE sub_orders DISABLE ROW LEVEL SECURITY;
        ALTER TABLE order_items DISABLE ROW LEVEL SECURITY;
        ALTER TABLE vendor_settlements DISABLE ROW LEVEL SECURITY;
        ALTER TABLE ledger_accounts_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE ledger_entries_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE cost_centres_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE budgets_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_chains DISABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_steps DISABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_requests_new DISABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_approvers DISABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;
        ALTER TABLE outbox_events DISABLE ROW LEVEL SECURITY;
    """))


