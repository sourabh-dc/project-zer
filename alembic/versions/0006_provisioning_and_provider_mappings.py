"""provisioning core tables + provider_mappings

Revision ID: 0006_prov_maps
Revises: 0005_trade_invoices
Create Date: 2025-09-25 00:25:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0006_prov_maps'
down_revision = '0005_trade_invoices'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE TABLE IF NOT EXISTS tenants (
          tenant_id VARCHAR(100) PRIMARY KEY,
          name VARCHAR(200) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sites (
          site_id VARCHAR(100) PRIMARY KEY,
          tenant_id VARCHAR(100) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
          name VARCHAR(200) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_sites_tenant ON sites(tenant_id);

        CREATE TABLE IF NOT EXISTS stores (
          store_id VARCHAR(100) PRIMARY KEY,
          site_id VARCHAR(100) NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
          name VARCHAR(200) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stores_site ON stores(site_id);

        CREATE TABLE IF NOT EXISTS roles (
          role_id VARCHAR(100) PRIMARY KEY,
          code VARCHAR(100) NOT NULL,
          description VARCHAR(200) NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_roles_code ON roles(code);

        CREATE TABLE IF NOT EXISTS users (
          user_id VARCHAR(100) PRIMARY KEY,
          email VARCHAR(255) UNIQUE NOT NULL,
          display_name VARCHAR(200) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memberships (
          id SERIAL PRIMARY KEY,
          user_id VARCHAR(100) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
          role_id VARCHAR(100) NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
          tenant_id VARCHAR(100) NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
          site_id VARCHAR(100) NULL REFERENCES sites(site_id) ON DELETE CASCADE,
          UNIQUE(user_id, role_id, tenant_id, site_id)
        );

        CREATE TABLE IF NOT EXISTS provider_mappings (
          id SERIAL PRIMARY KEY,
          provider VARCHAR(50) NOT NULL,
          entity_type VARCHAR(50) NOT NULL,
          local_id VARCHAR(100) NOT NULL,
          external_id VARCHAR(200) NOT NULL,
          UNIQUE(provider, entity_type, local_id)
        );
        """
    ))


def downgrade() -> None:
    pass


