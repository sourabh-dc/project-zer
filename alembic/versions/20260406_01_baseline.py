"""Full baseline — creates all tables for a fresh database deployment.

All statements use IF NOT EXISTS / conditional DO blocks so this revision
is safe to apply against an already-initialised database as well.

Revision ID: 20260406_01
Revises: (none — root)
Create Date: 2026-04-06
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op


revision: str = "20260406_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # Lookup / catalogue tables (no tenant FK deps)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS colour_groups (
            id           SERIAL PRIMARY KEY,
            colour_name  VARCHAR(100) NOT NULL,
            colour_group VARCHAR(100) NOT NULL,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_colour_groups_colour_name  ON colour_groups (colour_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_colour_groups_colour_group ON colour_groups (colour_group)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS colours (
            colour_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name               VARCHAR(100) NOT NULL,
            abbreviation       VARCHAR(20),
            colour_group       VARCHAR(100),
            source_internal_id VARCHAR(100),
            created_at         TIMESTAMPTZ DEFAULT NOW(),
            updated_at         TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_colours_name               ON colours (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_colours_colour_group       ON colours (colour_group)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_colours_source_internal_id ON colours (source_internal_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS sizes (
            size_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name               VARCHAR(50) NOT NULL,
            abbreviation       VARCHAR(20),
            sort_order         INTEGER DEFAULT 0,
            source_internal_id VARCHAR(100),
            created_at         TIMESTAMPTZ DEFAULT NOW(),
            updated_at         TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sizes_name               ON sizes (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sizes_source_internal_id ON sizes (source_internal_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS fits (
            fit_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name       VARCHAR(100) NOT NULL,
            active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fits_name   ON fits (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fits_active ON fits (active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS uos_labels (
            label_id   SERIAL PRIMARY KEY,
            name       VARCHAR(100) NOT NULL,
            label_type VARCHAR(50),
            source_id  VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_uos_labels_name       ON uos_labels (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_uos_labels_label_type ON uos_labels (label_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_uos_labels_source_id  ON uos_labels (source_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            role_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        VARCHAR(100) NOT NULL UNIQUE,
            description VARCHAR(500),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_roles_code ON roles (code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          VARCHAR(150) NOT NULL UNIQUE,
            description   VARCHAR(500),
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_permissions_code ON permissions (code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            role_code       VARCHAR REFERENCES roles(code) ON DELETE CASCADE,
            permission_code VARCHAR REFERENCES permissions(code) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_role_permissions_role_code       ON role_permissions (role_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_role_permissions_permission_code ON role_permissions (permission_code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS carriers (
            carrier_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                  VARCHAR(255) NOT NULL,
            code                  VARCHAR(50) UNIQUE,
            carrier_type          VARCHAR(50),
            tracking_url_template VARCHAR(500),
            status                VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_carriers_name   ON carriers (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_carriers_code   ON carriers (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_carriers_status ON carriers (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS subscription_plans (
            plan_id     UUID PRIMARY KEY,
            code        VARCHAR(50) NOT NULL UNIQUE,
            name        VARCHAR(100) NOT NULL,
            description VARCHAR(500),
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_by  VARCHAR(100),
            created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_plans_code      ON subscription_plans (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_plans_is_active ON subscription_plans (is_active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS plan_price (
            plan_price_id          SERIAL PRIMARY KEY,
            plan_code              VARCHAR(50) NOT NULL UNIQUE REFERENCES subscription_plans(code) ON DELETE CASCADE,
            currency               VARCHAR(3) NOT NULL DEFAULT 'GBP',
            price_monthly_minor    NUMERIC NOT NULL,
            quarterly_discount_pct NUMERIC(5,2) NOT NULL DEFAULT 5.0,
            yearly_discount_pct    NUMERIC(5,2) NOT NULL DEFAULT 10.0,
            price_quarterly_minor  NUMERIC NOT NULL,
            price_yearly_minor     NUMERIC NOT NULL,
            created_at             TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at             TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_plan_price_plan_code ON plan_price (plan_code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS features (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code         VARCHAR(50) NOT NULL UNIQUE,
            name         VARCHAR(100) NOT NULL,
            description  VARCHAR(500),
            cluster      VARCHAR(50),
            usage_type   VARCHAR(50) NOT NULL DEFAULT 'count',
            max_unit     VARCHAR(50),
            reset_period VARCHAR(20) NOT NULL DEFAULT 'monthly',
            active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_features_code   ON features (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_features_active ON features (active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS plan_features (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_code    VARCHAR(50) NOT NULL REFERENCES subscription_plans(code) ON DELETE CASCADE,
            feature_code VARCHAR(50) NOT NULL REFERENCES features(code) ON DELETE CASCADE,
            enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            limits       JSON,
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at   TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_plan_features_plan_code    ON plan_features (plan_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_plan_features_feature_code ON plan_features (feature_code)")

    # ------------------------------------------------------------------
    # Tenants — owner_user_id FK added after users table exists
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_name           VARCHAR NOT NULL,
            tenant_type           VARCHAR NOT NULL,
            email                 VARCHAR NOT NULL,
            active                BOOLEAN NOT NULL DEFAULT TRUE,
            registration_number   VARCHAR,
            phone                 VARCHAR,
            default_currency      VARCHAR(3),
            timezone              VARCHAR,
            locale                VARCHAR,
            billing_email         VARCHAR,
            billing_address       JSONB,
            primary_domain        VARCHAR,
            logo                  VARCHAR,
            owner_user_id         UUID,
            industry              VARCHAR,
            tech_contact_email    VARCHAR,
            support_contact_email VARCHAR,
            created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_tenant_name ON tenants (tenant_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_email       ON tenants (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_active      ON tenants (active)")

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            site_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                     VARCHAR NOT NULL,
            site_type                VARCHAR NOT NULL,
            active                   BOOLEAN NOT NULL DEFAULT TRUE,
            currency                 VARCHAR(3),
            timezone                 VARCHAR,
            language                 VARCHAR,
            phone                    VARCHAR,
            fax                      VARCHAR,
            email                    VARCHAR,
            url                      VARCHAR,
            logo_url                 VARCHAR,
            primary_billing_address  JSONB,
            primary_shipping_address JSONB,
            shipping_addresses       JSONB,
            geo                      JSONB,
            external_id              VARCHAR,
            is_headquarter           BOOLEAN DEFAULT FALSE,
            created_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sites_active ON sites (active)")

    # ------------------------------------------------------------------
    # Stores (-> tenants, sites)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            store_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            site_id                  UUID REFERENCES sites(site_id) ON DELETE CASCADE,
            name                     VARCHAR NOT NULL,
            store_type               VARCHAR NOT NULL,
            active                   BOOLEAN NOT NULL DEFAULT TRUE,
            currency                 VARCHAR(3),
            timezone                 VARCHAR,
            phone                    VARCHAR,
            email                    VARCHAR,
            url                      VARCHAR,
            logo_url                 VARCHAR,
            primary_shipping_address JSONB,
            pickup_address           JSONB,
            geo                      JSONB,
            external_id              VARCHAR,
            fulfillment_mode         VARCHAR,
            inventory_policy         VARCHAR,
            created_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stores_tenant_id ON stores (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stores_site_id   ON stores (site_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stores_active    ON stores (active)")

    # ------------------------------------------------------------------
    # Org units — manager_user_id FK added after users table
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS org_units (
            org_unit_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name               VARCHAR NOT NULL,
            type               VARCHAR NOT NULL,
            status             VARCHAR NOT NULL,
            parent_org_unit_id UUID REFERENCES org_units(org_unit_id) ON DELETE SET NULL,
            code               VARCHAR,
            description        VARCHAR,
            manager_user_id    UUID,
            external_id        VARCHAR,
            path               VARCHAR,
            depth              INTEGER,
            created_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_tenant_id          ON org_units (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_type               ON org_units (type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_status             ON org_units (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_parent_org_unit_id ON org_units (parent_org_unit_id)")

    # ------------------------------------------------------------------
    # Users — home_org_unit_id FK added after org_units
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            email                    VARCHAR NOT NULL,
            password_hash            VARCHAR NOT NULL,
            first_name               VARCHAR NOT NULL,
            last_name                VARCHAR NOT NULL,
            is_active                BOOLEAN NOT NULL DEFAULT TRUE,
            display_name             VARCHAR,
            phone                    VARCHAR,
            position                 VARCHAR,
            profile_image            VARCHAR,
            is_sso_enabled           BOOLEAN DEFAULT FALSE,
            home_site_id             UUID REFERENCES sites(site_id),
            home_store_id            UUID REFERENCES stores(store_id),
            home_org_unit_id         UUID,
            all_locations            BOOLEAN DEFAULT FALSE,
            failed_login_attempts    INTEGER DEFAULT 0,
            last_login_at            TIMESTAMPTZ,
            refresh_token            VARCHAR,
            refresh_token_expires_at TIMESTAMPTZ,
            last_logout_at           TIMESTAMPTZ,
            max_order_limit_minor    INTEGER DEFAULT 10000000,
            created_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_is_active  ON users (is_active)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_tenant_email_unique ON users (tenant_id, email)")

    # ------------------------------------------------------------------
    # Resolve circular FK constraints
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'tenants_owner_user_id_fkey'
                  AND conrelid = 'tenants'::regclass
            ) THEN
                ALTER TABLE tenants
                    ADD CONSTRAINT tenants_owner_user_id_fkey
                    FOREIGN KEY (owner_user_id) REFERENCES users(user_id);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'org_units_manager_user_id_fkey'
                  AND conrelid = 'org_units'::regclass
            ) THEN
                ALTER TABLE org_units
                    ADD CONSTRAINT org_units_manager_user_id_fkey
                    FOREIGN KEY (manager_user_id) REFERENCES users(user_id);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'users_home_org_unit_id_fkey'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users
                    ADD CONSTRAINT users_home_org_unit_id_fkey
                    FOREIGN KEY (home_org_unit_id) REFERENCES org_units(org_unit_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------
    # Role / permission assignments
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            user_id    UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role_id    UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_roles_tenant_id ON user_roles (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_roles_user_id   ON user_roles (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_roles_role_id   ON user_roles (role_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_roles (
            role_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            code        VARCHAR(100) NOT NULL,
            description VARCHAR(500),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_roles_tenant_id  ON tenant_roles (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenant_role_unique ON tenant_roles (tenant_id, code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_role_permissions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_role_id  UUID NOT NULL REFERENCES tenant_roles(role_id) ON DELETE CASCADE,
            permission_code VARCHAR NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_tenant_role_id  ON tenant_role_permissions (tenant_role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_permission_code ON tenant_role_permissions (permission_code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_user_roles (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            tenant_role_id UUID NOT NULL REFERENCES tenant_roles(role_id) ON DELETE CASCADE,
            created_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_user_roles_tenant_id      ON tenant_user_roles (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_user_roles_user_id        ON tenant_user_roles (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_user_roles_tenant_role_id ON tenant_user_roles (tenant_role_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_org_assignments (
            assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            org_unit_id   UUID NOT NULL REFERENCES org_units(org_unit_id) ON DELETE CASCADE,
            role_id       UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
            assigned_by   UUID REFERENCES users(user_id) ON DELETE SET NULL,
            assigned_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_org_assignments_user_id     ON user_org_assignments (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_org_assignments_org_unit_id ON user_org_assignments (org_unit_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_org_assignments_role_id     ON user_org_assignments (role_id)")

    # ------------------------------------------------------------------
    # Vendors & vendor users
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name          VARCHAR(255) NOT NULL,
            contact_email VARCHAR(255),
            description   VARCHAR(500),
            status        VARCHAR(50) DEFAULT 'active',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendors_tenant_id ON vendors (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendors_status    ON vendors (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_users (
            user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id     UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            email         VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            first_name    VARCHAR(255) NOT NULL,
            role          VARCHAR(50) NOT NULL DEFAULT 'vendor_staff',
            active        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_users_vendor_id ON vendor_users (vendor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_users_active    ON vendor_users (active)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_vendor_users_vendor_email_unique ON vendor_users (vendor_id, email)")

    # ------------------------------------------------------------------
    # Tenant carriers & site tenants
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_carriers (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            carrier_id        UUID NOT NULL REFERENCES carriers(carrier_id) ON DELETE CASCADE,
            relationship_type VARCHAR(50) NOT NULL DEFAULT 'approved',
            integration_type  VARCHAR(50),
            account_number    VARCHAR(100),
            status            VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_carriers_tenant_id  ON tenant_carriers (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_carriers_carrier_id ON tenant_carriers (carrier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_carriers_status     ON tenant_carriers (status)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenant_carrier_unique ON tenant_carriers (tenant_id, carrier_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS site_tenants (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            site_id    UUID NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
            tenant_id  UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_tenants_site_id   ON site_tenants (site_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_tenants_tenant_id ON site_tenants (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_site_tenant_unique ON site_tenants (site_id, tenant_id)")

    # ------------------------------------------------------------------
    # Tenant subscriptions & usage
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_subscriptions (
            id                   SERIAL PRIMARY KEY,
            previous_sub_id      INTEGER REFERENCES tenant_subscriptions(id),
            tenant_id            UUID NOT NULL UNIQUE REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            plan_code            VARCHAR(50) NOT NULL REFERENCES subscription_plans(code),
            billing_cycle        VARCHAR(50) NOT NULL DEFAULT 'monthly',
            payment_method       VARCHAR(20) DEFAULT 'card',
            external_id          VARCHAR(100),
            current_period_start TIMESTAMPTZ NOT NULL,
            current_period_end   TIMESTAMPTZ NOT NULL,
            is_active            BOOLEAN NOT NULL DEFAULT TRUE,
            is_trial             BOOLEAN NOT NULL DEFAULT FALSE,
            canceled_at          TIMESTAMPTZ,
            cancellation_reason  VARCHAR(500),
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_subscriptions_tenant_id   ON tenant_subscriptions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenant_subscriptions_external_id ON tenant_subscriptions (external_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS subscription_usage (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            feature_code VARCHAR(50) NOT NULL REFERENCES features(code),
            usage_type   VARCHAR(50) NOT NULL,
            usage_count  INTEGER NOT NULL DEFAULT 0,
            period_start TIMESTAMPTZ NOT NULL,
            period_end   TIMESTAMPTZ NOT NULL,
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at   TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_tenant_id    ON subscription_usage (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_feature_code ON subscription_usage (feature_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_usage_type   ON subscription_usage (usage_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_period_start ON subscription_usage (period_start)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_period_end   ON subscription_usage (period_end)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_usage_composite    ON subscription_usage (tenant_id, feature_code, period_start)")

    # ------------------------------------------------------------------
    # Financial calendars, years, periods
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS financial_calendars (
            calendar_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name          VARCHAR(255) NOT NULL,
            description   TEXT,
            calendar_type VARCHAR(20) NOT NULL DEFAULT 'gregorian',
            start_month   INTEGER NOT NULL DEFAULT 1,
            currency      VARCHAR(3) DEFAULT 'GBP',
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            is_default    BOOLEAN NOT NULL DEFAULT FALSE,
            created_by    UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_calendars_tenant_id    ON financial_calendars (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_calendars_calendar_type ON financial_calendars (calendar_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_calendars_is_active    ON financial_calendars (is_active)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_financial_calendar_tenant_name ON financial_calendars (tenant_id, name)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS financial_years (
            year_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            calendar_id        UUID NOT NULL REFERENCES financial_calendars(calendar_id) ON DELETE CASCADE,
            tenant_id          UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            label              VARCHAR(50) NOT NULL,
            start_date         DATE NOT NULL,
            end_date           DATE NOT NULL,
            year_type          VARCHAR(20) NOT NULL DEFAULT 'full',
            status             VARCHAR(20) NOT NULL DEFAULT 'draft',
            total_budget_minor BIGINT,
            notes              TEXT,
            created_by         UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_years_calendar_id ON financial_years (calendar_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_years_tenant_id   ON financial_years (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_years_status      ON financial_years (status)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_financial_year_tenant_label ON financial_years (tenant_id, label)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS financial_periods (
            period_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            year_id       UUID NOT NULL REFERENCES financial_years(year_id) ON DELETE CASCADE,
            calendar_id   UUID NOT NULL REFERENCES financial_calendars(calendar_id) ON DELETE CASCADE,
            tenant_id     UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            period_number INTEGER NOT NULL,
            label         VARCHAR(50) NOT NULL,
            period_type   VARCHAR(20) NOT NULL DEFAULT 'month',
            start_date    DATE NOT NULL,
            end_date      DATE NOT NULL,
            created_at    TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_periods_year_id     ON financial_periods (year_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_periods_calendar_id ON financial_periods (calendar_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_financial_periods_tenant_id   ON financial_periods (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_fin_period_year_num ON financial_periods (year_id, period_number)")

    # ------------------------------------------------------------------
    # Cost centres & budget tables
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS cost_centres (
            cost_centre_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            code                  VARCHAR(50) NOT NULL,
            name                  VARCHAR(255) NOT NULL,
            description           VARCHAR(500),
            gl_code               VARCHAR(100),
            owner_user_id         UUID REFERENCES users(user_id),
            period_granularity    VARCHAR(20) DEFAULT 'month',
            carry_forward_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            default_calendar_id   UUID REFERENCES financial_calendars(calendar_id) ON DELETE SET NULL,
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cost_centres_tenant_id ON cost_centres (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cost_centres_gl_code   ON cost_centres (gl_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cost_centres_is_active ON cost_centres (is_active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS cost_center_budget (
            budget_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cost_centre_id              UUID NOT NULL REFERENCES cost_centres(cost_centre_id),
            tenant_id                   UUID NOT NULL REFERENCES tenants(tenant_id),
            fiscal_year                 INTEGER NOT NULL,
            period_type                 VARCHAR(20) NOT NULL,
            period_number               INTEGER NOT NULL,
            period_start                DATE NOT NULL,
            period_end                  DATE NOT NULL,
            budget_amount_minor         BIGINT NOT NULL,
            allocated_to_users_minor    BIGINT NOT NULL DEFAULT 0,
            remaining_to_allocate_minor BIGINT,
            total_spent_minor           BIGINT NOT NULL DEFAULT 0,
            lapsed_amount_minor         BIGINT,
            status                      VARCHAR(20) NOT NULL,
            closed_at                   TIMESTAMPTZ,
            closed_by                   UUID REFERENCES users(user_id),
            created_by                  UUID NOT NULL REFERENCES users(user_id),
            created_at                  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at                  TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_cost_centres (
            user_budget_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                UUID NOT NULL REFERENCES users(user_id),
            cost_centre_id         UUID NOT NULL REFERENCES cost_centres(cost_centre_id),
            cc_budget_id           UUID NOT NULL REFERENCES cost_center_budget(budget_id),
            max_budget_minor       BIGINT NOT NULL,
            allocated_minor        BIGINT NOT NULL,
            spent_minor            BIGINT NOT NULL,
            available_minor        BIGINT NOT NULL,
            recurring_amount_minor BIGINT NOT NULL,
            recurring_period       VARCHAR(20),
            next_recurring_at      TIMESTAMPTZ,
            is_blocked             BOOLEAN NOT NULL DEFAULT FALSE,
            blocked_reason         VARCHAR(255),
            blocked_at             TIMESTAMPTZ,
            created_at             TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at             TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS company_budget_caps (
            cap_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            year_id            UUID NOT NULL REFERENCES financial_years(year_id) ON DELETE CASCADE,
            calendar_id        UUID NOT NULL REFERENCES financial_calendars(calendar_id) ON DELETE CASCADE,
            currency           VARCHAR(3) NOT NULL DEFAULT 'GBP',
            total_budget_minor BIGINT NOT NULL,
            allocated_minor    BIGINT NOT NULL DEFAULT 0,
            committed_minor    BIGINT NOT NULL DEFAULT 0,
            spent_minor        BIGINT NOT NULL DEFAULT 0,
            hard_cap           BOOLEAN NOT NULL DEFAULT FALSE,
            notes              TEXT,
            created_by         UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at         TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_budget_caps_tenant_id ON company_budget_caps (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_budget_caps_year_id   ON company_budget_caps (year_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_company_cap_tenant_year ON company_budget_caps (tenant_id, year_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS cc_budget_versions (
            version_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cost_centre_id           UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            year_id                  UUID NOT NULL REFERENCES financial_years(year_id) ON DELETE CASCADE,
            period_id                UUID REFERENCES financial_periods(period_id) ON DELETE SET NULL,
            tenant_id                UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            currency                 VARCHAR(3) NOT NULL DEFAULT 'GBP',
            budget_minor             BIGINT NOT NULL,
            carry_forward_minor      BIGINT NOT NULL DEFAULT 0,
            allocated_to_users_minor BIGINT NOT NULL DEFAULT 0,
            committed_minor          BIGINT NOT NULL DEFAULT 0,
            spent_minor              BIGINT NOT NULL DEFAULT 0,
            status                   VARCHAR(20) NOT NULL DEFAULT 'draft',
            override_reason          TEXT,
            closed_at                TIMESTAMPTZ,
            closed_by                UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_by               UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at               TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cc_budget_versions_cost_centre_id ON cc_budget_versions (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cc_budget_versions_year_id        ON cc_budget_versions (year_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cc_budget_versions_period_id      ON cc_budget_versions (period_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cc_budget_versions_tenant_id      ON cc_budget_versions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cc_budget_versions_status         ON cc_budget_versions (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_transactions (
            txn_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            txn_type          VARCHAR(50) NOT NULL,
            source_version_id UUID REFERENCES cc_budget_versions(version_id) ON DELETE SET NULL,
            target_version_id UUID REFERENCES cc_budget_versions(version_id) ON DELETE SET NULL,
            amount_minor      BIGINT NOT NULL,
            currency          VARCHAR(3) NOT NULL DEFAULT 'GBP',
            reference_id      UUID,
            note              TEXT,
            performed_by      UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_transactions_tenant_id         ON budget_transactions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_transactions_txn_type          ON budget_transactions (txn_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_transactions_source_version_id ON budget_transactions (source_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_transactions_target_version_id ON budget_transactions (target_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_transactions_reference_id      ON budget_transactions (reference_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_cc_assignments (
            assignment_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            is_primary     BOOLEAN NOT NULL DEFAULT FALSE,
            is_active      BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from DATE,
            effective_to   DATE,
            assigned_by    UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_cc_assignments_user_id        ON user_cc_assignments (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_cc_assignments_cost_centre_id ON user_cc_assignments (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_cc_assignments_tenant_id      ON user_cc_assignments (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_cc_assign_unique ON user_cc_assignments (user_id, cost_centre_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_budget_limits (
            limit_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            cost_centre_id        UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            year_id               UUID NOT NULL REFERENCES financial_years(year_id) ON DELETE CASCADE,
            period_id             UUID REFERENCES financial_periods(period_id) ON DELETE SET NULL,
            tenant_id             UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            currency              VARCHAR(3) NOT NULL DEFAULT 'GBP',
            limit_type            VARCHAR(20) NOT NULL,
            window_type           VARCHAR(20) NOT NULL,
            limit_amount_minor    BIGINT NOT NULL,
            committed_minor       BIGINT NOT NULL DEFAULT 0,
            spent_minor           BIGINT NOT NULL DEFAULT 0,
            carry_forward_minor   BIGINT NOT NULL DEFAULT 0,
            carry_forward_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            window_start          DATE,
            window_end            DATE,
            next_reset_date       DATE,
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_by            UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_user_id        ON user_budget_limits (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_cost_centre_id ON user_budget_limits (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_year_id        ON user_budget_limits (year_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_period_id      ON user_budget_limits (period_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_tenant_id      ON user_budget_limits (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_limit_type     ON user_budget_limits (limit_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_budget_limits_window_type    ON user_budget_limits (window_type)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_limit_unique ON user_budget_limits (user_id, cost_centre_id, year_id, limit_type, window_type)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_approvers (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id              UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            cost_centre_id       UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            approval_limit_minor BIGINT NOT NULL,
            currency             VARCHAR(3) NOT NULL DEFAULT 'GBP',
            rule_set_id          UUID,
            status               VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_approvers_user_id        ON user_approvers (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_approvers_cost_centre_id ON user_approvers (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_approvers_status         ON user_approvers (status)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_approver_unique ON user_approvers (user_id, cost_centre_id)")

    # ------------------------------------------------------------------
    # Categories & Products
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name               VARCHAR(255) NOT NULL,
            code               VARCHAR(100) NOT NULL,
            description        VARCHAR(500),
            parent_category_id UUID REFERENCES categories(category_id) ON DELETE SET NULL,
            active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_at         TIMESTAMPTZ DEFAULT NOW(),
            updated_at         TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_tenant_id          ON categories (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_code               ON categories (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_parent_category_id ON categories (parent_category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_categories_active             ON categories (active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            external_id                 VARCHAR(100),
            aifi_product_id             VARCHAR(64),
            sku                         VARCHAR(100) NOT NULL,
            ean                         VARCHAR(128),
            mpn                         VARCHAR(100),
            vendor_id                   UUID REFERENCES vendors(vendor_id) ON DELETE SET NULL,
            category_id                 UUID REFERENCES categories(category_id) ON DELETE SET NULL,
            brand_id                    UUID,
            manufacturer                VARCHAR(255),
            is_matrix_item              BOOLEAN NOT NULL DEFAULT FALSE,
            matrix_type                 VARCHAR(20) NOT NULL DEFAULT 'standalone',
            matrix_parent_id            UUID REFERENCES products(product_id) ON DELETE SET NULL,
            colour_id                   UUID REFERENCES colours(colour_id) ON DELETE SET NULL,
            size_id                     UUID REFERENCES sizes(size_id) ON DELETE SET NULL,
            fit_id                      UUID REFERENCES fits(fit_id) ON DELETE SET NULL,
            item_option                 VARCHAR(255),
            display_name                VARCHAR(255) NOT NULL,
            web_display_name            VARCHAR(255),
            sales_description           TEXT,
            purchase_description        TEXT,
            packing_slip_description    TEXT,
            detailed_description        TEXT,
            additional_description      TEXT,
            weight                      NUMERIC(10,3),
            weight_unit                 VARCHAR(10),
            width                       NUMERIC(10,3),
            depth                       NUMERIC(10,3),
            height                      NUMERIC(10,3),
            outer_quantity              INTEGER,
            outer_label_id              INTEGER REFERENCES uos_labels(label_id) ON DELETE SET NULL,
            inner_quantity              INTEGER,
            inner_label_id              INTEGER REFERENCES uos_labels(label_id) ON DELETE SET NULL,
            reorder_multiple            INTEGER,
            purchase_price_minor        INTEGER NOT NULL,
            currency                    VARCHAR(3) NOT NULL DEFAULT 'GBP',
            tax_rate                    BIGINT NOT NULL DEFAULT 0,
            manufacturer_country        VARCHAR(100),
            commodity_code              VARCHAR(50),
            product_type                VARCHAR(50),
            colour_filter               VARCHAR(100),
            size_filter                 VARCHAR(100),
            search_keywords             TEXT,
            is_dangerous_goods          BOOLEAN NOT NULL DEFAULT FALSE,
            cas_number                  VARCHAR(50),
            un_number                   VARCHAR(50),
            proper_shipping_name        VARCHAR(255),
            transport_hazard_class      VARCHAR(50),
            packing_group               VARCHAR(20),
            adr_classification_code     VARCHAR(50),
            adr_tunnel_restriction_code VARCHAR(20),
            adr_hazard_id_number        VARCHAR(50),
            tax_code                    VARCHAR(64),
            restricted                  BOOLEAN NOT NULL DEFAULT FALSE,
            product_metadata            JSONB,
            comments                    TEXT,
            active                      BOOLEAN NOT NULL DEFAULT TRUE,
            deleted_at                  TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at                  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_tenant_id       ON products (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_external_id     ON products (external_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_aifi_product_id ON products (aifi_product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_ean             ON products (ean)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_vendor_id       ON products (vendor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_category_id     ON products (category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_brand_id        ON products (brand_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_matrix_parent_id ON products (matrix_parent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_colour_id       ON products (colour_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_size_id         ON products (size_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_fit_id          ON products (fit_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_restricted      ON products (restricted)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_active          ON products (active)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_tenant_sku_unique ON products (tenant_id, sku)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_tenant_ean_unique ON products (tenant_id, ean) WHERE ean IS NOT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            image_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            tenant_id  UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            image_url  VARCHAR(500) NOT NULL,
            position   INTEGER NOT NULL DEFAULT 1,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_images_product_id ON product_images (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_images_tenant_id  ON product_images (tenant_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS variants (
            variant_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id          UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            tenant_id           UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            sku                 VARCHAR(100) NOT NULL UNIQUE,
            name                VARCHAR(255) NOT NULL,
            attributes          JSONB,
            price_minor         INTEGER NOT NULL,
            currency            VARCHAR(3) NOT NULL DEFAULT 'GBP',
            stock_quantity      INTEGER NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER NOT NULL DEFAULT 10,
            active              BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_variants_product_id ON variants (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variants_tenant_id  ON variants (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variants_sku        ON variants (sku)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variants_active     ON variants (active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS store_products (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id            UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
            tenant_id           UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            product_id          UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            price_minor         INTEGER NOT NULL,
            currency            VARCHAR(3) NOT NULL DEFAULT 'GBP',
            is_available        BOOLEAN NOT NULL DEFAULT TRUE,
            stock_quantity      INTEGER NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER NOT NULL DEFAULT 10,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_store_products_store_id    ON store_products (store_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_store_products_tenant_id   ON store_products (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_store_products_product_id  ON store_products (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_store_products_is_available ON store_products (is_available)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_store_product_unique ON store_products (store_id, product_id)")

    # ------------------------------------------------------------------
    # Spending events
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS spending_events (
            event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type     VARCHAR(50) NOT NULL,
            user_id        UUID NOT NULL REFERENCES users(user_id),
            cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id),
            order_id       UUID,
            amount_minor   BIGINT NOT NULL,
            currency_code  VARCHAR(3) DEFAULT 'GBP',
            event_metadata JSONB,
            created_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_spending_events_user_id        ON spending_events (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_spending_events_cost_centre_id ON spending_events (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_spending_events_order_id       ON spending_events (order_id)")

    # ------------------------------------------------------------------
    # Approved ranges
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS approved_ranges (
            approved_range_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name              VARCHAR(255) NOT NULL,
            description       TEXT,
            is_universal      BOOLEAN NOT NULL DEFAULT FALSE,
            status            VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by        UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approved_ranges_tenant_id   ON approved_ranges (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approved_ranges_is_universal ON approved_ranges (is_universal)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approved_ranges_status       ON approved_ranges (status)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_approved_range_tenant_name ON approved_ranges (tenant_id, name)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approved_range_org_units (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            approved_range_id UUID NOT NULL REFERENCES approved_ranges(approved_range_id) ON DELETE CASCADE,
            org_unit_id       UUID NOT NULL REFERENCES org_units(org_unit_id) ON DELETE CASCADE,
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_aro_approved_range_id ON approved_range_org_units (approved_range_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_aro_org_unit_id       ON approved_range_org_units (org_unit_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_ar_org_unit_unique ON approved_range_org_units (approved_range_id, org_unit_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approved_range_products (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            approved_range_id UUID NOT NULL REFERENCES approved_ranges(approved_range_id) ON DELETE CASCADE,
            product_id        UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            added_by          UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_arp_approved_range_id ON approved_range_products (approved_range_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_arp_product_id        ON approved_range_products (product_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_ar_product_unique ON approved_range_products (approved_range_id, product_id)")

    # ------------------------------------------------------------------
    # Approval policies, stages, conditions, approvers
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_policies (
            policy_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            cost_centre_id        UUID REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            name                  VARCHAR(255) NOT NULL,
            description           TEXT,
            routing_mode          VARCHAR(20) NOT NULL DEFAULT 'hierarchical',
            broadcast_n           INTEGER NOT NULL DEFAULT 3,
            sox_sod_enforced      BOOLEAN NOT NULL DEFAULT TRUE,
            partial_approval_mode VARCHAR(20) NOT NULL DEFAULT 'block',
            zero_value_mode       VARCHAR(20) NOT NULL DEFAULT 'auto',
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_by            UUID REFERENCES users(user_id) ON DELETE SET NULL,
            created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_policies_tenant_id      ON approval_policies (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_policies_cost_centre_id ON approval_policies (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_policies_is_active      ON approval_policies (is_active)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_stages (
            stage_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_id                UUID NOT NULL REFERENCES approval_policies(policy_id) ON DELETE CASCADE,
            stage_order              INTEGER NOT NULL,
            name                     VARCHAR(255),
            parallel_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
            min_approvers            INTEGER NOT NULL DEFAULT 1,
            escalation_timeout_hours INTEGER
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_stages_policy_id ON approval_stages (policy_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_approval_stage_policy_order ON approval_stages (policy_id, stage_order)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_stage_conditions (
            condition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            stage_id     UUID NOT NULL REFERENCES approval_stages(stage_id) ON DELETE CASCADE,
            field        VARCHAR(50) NOT NULL,
            operator     VARCHAR(10) NOT NULL,
            value        JSONB NOT NULL,
            logic        VARCHAR(5) NOT NULL DEFAULT 'AND'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_stage_conditions_stage_id ON approval_stage_conditions (stage_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_stage_approvers (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            stage_id         UUID NOT NULL REFERENCES approval_stages(stage_id) ON DELETE CASCADE,
            approver_type    VARCHAR(30) NOT NULL,
            approver_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
            org_unit_id      UUID REFERENCES org_units(org_unit_id) ON DELETE SET NULL,
            role_code        VARCHAR(100)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_stage_approvers_stage_id ON approval_stage_approvers (stage_id)")

    # ------------------------------------------------------------------
    # Purchase requests, workflows, tasks
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS purchase_requests (
            request_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            requester_id           UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            cost_centre_id         UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            vendor_id              UUID REFERENCES vendors(vendor_id) ON DELETE SET NULL,
            category_id            UUID REFERENCES categories(category_id) ON DELETE SET NULL,
            year_id                UUID REFERENCES financial_years(year_id) ON DELETE SET NULL,
            period_id              UUID REFERENCES financial_periods(period_id) ON DELETE SET NULL,
            reference_number       VARCHAR(50),
            description            TEXT,
            line_items             JSONB,
            amount_minor           BIGINT NOT NULL,
            currency               VARCHAR(3) NOT NULL DEFAULT 'GBP',
            status                 VARCHAR(30) NOT NULL DEFAULT 'draft',
            approval_mode          VARCHAR(20),
            notes                  TEXT,
            rejection_reason       TEXT,
            approved_by            UUID REFERENCES users(user_id) ON DELETE SET NULL,
            approved_at            TIMESTAMPTZ,
            po_issued_at           TIMESTAMPTZ,
            po_reference           VARCHAR(100),
            vendor_action_token    VARCHAR(64) UNIQUE,
            vendor_response_status VARCHAR(30),
            vendor_response_at     TIMESTAMPTZ,
            created_at             TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at             TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_tenant_id          ON purchase_requests (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_requester_id       ON purchase_requests (requester_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_cost_centre_id     ON purchase_requests (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_vendor_id          ON purchase_requests (vendor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_category_id        ON purchase_requests (category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_year_id            ON purchase_requests (year_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_period_id          ON purchase_requests (period_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_reference_number   ON purchase_requests (reference_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_status             ON purchase_requests (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_purchase_requests_vendor_action_token ON purchase_requests (vendor_action_token)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_workflows (
            workflow_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id          UUID NOT NULL UNIQUE REFERENCES purchase_requests(request_id) ON DELETE CASCADE,
            policy_id           UUID REFERENCES approval_policies(policy_id) ON DELETE SET NULL,
            tenant_id           UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            current_stage_order INTEGER NOT NULL DEFAULT 1,
            status              VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_workflows_request_id ON approval_workflows (request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_workflows_tenant_id  ON approval_workflows (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_workflows_status     ON approval_workflows (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_tasks (
            task_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id          UUID NOT NULL REFERENCES approval_workflows(workflow_id) ON DELETE CASCADE,
            stage_id             UUID REFERENCES approval_stages(stage_id) ON DELETE SET NULL,
            tenant_id            UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            assignee_user_id     UUID REFERENCES users(user_id) ON DELETE SET NULL,
            stage_order          INTEGER NOT NULL,
            status               VARCHAR(20) NOT NULL DEFAULT 'pending',
            decided_at           TIMESTAMPTZ,
            decided_by           UUID REFERENCES users(user_id) ON DELETE SET NULL,
            note                 TEXT,
            escalated_to_task_id UUID REFERENCES approval_tasks(task_id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_tasks_workflow_id      ON approval_tasks (workflow_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_tasks_stage_id         ON approval_tasks (stage_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_tasks_tenant_id        ON approval_tasks (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_tasks_assignee_user_id ON approval_tasks (assignee_user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_approval_tasks_status           ON approval_tasks (status)")

    # ------------------------------------------------------------------
    # Budget change requests
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_change_requests (
            change_req_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            request_type     VARCHAR(30) NOT NULL,
            requester_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            cost_centre_id   UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
            from_version_id  UUID REFERENCES cc_budget_versions(version_id) ON DELETE SET NULL,
            to_version_id    UUID NOT NULL REFERENCES cc_budget_versions(version_id) ON DELETE SET NULL,
            amount_minor     BIGINT NOT NULL,
            currency         VARCHAR(3) NOT NULL DEFAULT 'GBP',
            justification    TEXT,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            approved_by      UUID REFERENCES users(user_id) ON DELETE SET NULL,
            approved_at      TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_tenant_id       ON budget_change_requests (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_request_type    ON budget_change_requests (request_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_requester_id    ON budget_change_requests (requester_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_cost_centre_id  ON budget_change_requests (cost_centre_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_from_version_id ON budget_change_requests (from_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_to_version_id   ON budget_change_requests (to_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_change_requests_status          ON budget_change_requests (status)")

    # ------------------------------------------------------------------
    # Outbox (transactional outbox pattern)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox_events (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL,
            aggregate_type VARCHAR(100),
            aggregate_id   UUID,
            event_type     VARCHAR NOT NULL,
            payload        JSONB NOT NULL DEFAULT '{}',
            status         VARCHAR NOT NULL DEFAULT 'pending',
            retry_count    INTEGER NOT NULL DEFAULT 0,
            max_retries    INTEGER NOT NULL DEFAULT 3,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_events_aggregate_type ON outbox_events (aggregate_type)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox_event_delivery (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id      UUID NOT NULL REFERENCES outbox_events(id),
            consumer      VARCHAR(50) NOT NULL,
            status        VARCHAR(20) NOT NULL DEFAULT 'pending',
            retry_count   INTEGER NOT NULL DEFAULT 0,
            max_retries   INTEGER NOT NULL DEFAULT 3,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at  TIMESTAMPTZ,
            error_message TEXT,
            CONSTRAINT uq_delivery_event_consumer UNIQUE (event_id, consumer)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_delivery_consumer_status         ON outbox_event_delivery (consumer, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_delivery_consumer_status_created ON outbox_event_delivery (consumer, status, created_at)")

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL,
            user_id       UUID,
            action        VARCHAR NOT NULL,
            resource_type VARCHAR NOT NULL,
            resource_id   VARCHAR,
            details       JSONB,
            ip_address    VARCHAR,
            user_agent    VARCHAR,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------
    # policy_service tables
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID,
            code        VARCHAR(150) NOT NULL,
            name        VARCHAR(255) NOT NULL,
            description VARCHAR(1000),
            policy_type VARCHAR(50) NOT NULL,
            priority    INTEGER NOT NULL DEFAULT 100,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by  UUID,
            created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policies_tenant_id   ON policies (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policies_code        ON policies (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policies_policy_type ON policies (policy_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policies_is_active   ON policies (is_active)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_policies_tenant_code_unique ON policies (tenant_id, code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_versions (
            version_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_id       UUID NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
            version_number  INTEGER NOT NULL DEFAULT 1,
            rules_json      JSONB,
            effective_from  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            effective_until TIMESTAMPTZ,
            change_reason   VARCHAR(500),
            created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_versions_policy_id ON policy_versions (policy_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_rules (
            rule_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            version_id           UUID NOT NULL REFERENCES policy_versions(version_id) ON DELETE CASCADE,
            rule_order           INTEGER NOT NULL DEFAULT 0,
            name                 VARCHAR(255) NOT NULL,
            condition_expression TEXT NOT NULL,
            effect               VARCHAR(30) NOT NULL DEFAULT 'deny',
            denial_reason        TEXT,
            approval_chain_id    UUID,
            actions              JSONB,
            is_active            BOOLEAN NOT NULL DEFAULT TRUE,
            created_at           TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_rules_version_id ON policy_rules (version_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_assignments (
            assignment_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_id         UUID NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
            scope_type        VARCHAR(30) NOT NULL DEFAULT 'global',
            scope_id          UUID,
            action_pattern    VARCHAR(200) NOT NULL,
            priority_override INTEGER,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            valid_from        TIMESTAMPTZ,
            valid_until       TIMESTAMPTZ,
            created_at        TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_assignments_policy_id      ON policy_assignments (policy_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_assignments_action_pattern ON policy_assignments (action_pattern)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_action_types (
            action_type_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code            VARCHAR(100) NOT NULL UNIQUE,
            name            VARCHAR(255) NOT NULL,
            subject_schema  JSONB,
            resource_schema JSONB,
            category        VARCHAR(50),
            created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_action_types_code     ON policy_action_types (code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_action_types_category ON policy_action_types (category)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS policy_decisions (
            decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            user_id          UUID,
            action           VARCHAR(200) NOT NULL,
            subject          JSONB NOT NULL,
            resource         JSONB NOT NULL,
            decision         VARCHAR(30) NOT NULL,
            matched_policies JSONB,
            reason           TEXT,
            evaluation_ms    INTEGER,
            correlation_id   VARCHAR(100),
            evaluated_at     TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_decisions_tenant_id     ON policy_decisions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_decisions_user_id       ON policy_decisions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_decisions_action        ON policy_decisions (action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_decisions_correlation_id ON policy_decisions (correlation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_decisions_tenant_action  ON policy_decisions (tenant_id, action)")


def downgrade() -> None:
    # Drop in reverse dependency order
    tables = [
        "policy_decisions", "policy_action_types", "policy_assignments",
        "policy_rules", "policy_versions", "policies",
        "audit_logs",
        "outbox_event_delivery", "outbox_events",
        "budget_change_requests",
        "approval_tasks", "approval_workflows", "purchase_requests",
        "approval_stage_approvers", "approval_stage_conditions",
        "approval_stages", "approval_policies",
        "approved_range_products", "approved_range_org_units", "approved_ranges",
        "spending_events",
        "store_products", "variants", "product_images", "products", "categories",
        "user_approvers", "user_budget_limits", "user_cc_assignments",
        "budget_transactions", "cc_budget_versions", "company_budget_caps",
        "user_cost_centres", "cost_center_budget", "cost_centres",
        "financial_periods", "financial_years", "financial_calendars",
        "vendor_users", "vendors",
        "user_org_assignments", "tenant_user_roles",
        "tenant_role_permissions", "tenant_roles", "user_roles",
        "subscription_usage", "tenant_subscriptions",
        "site_tenants", "tenant_carriers",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # Remove circular FK columns before dropping anchor tables
    op.execute("ALTER TABLE users      DROP COLUMN IF EXISTS home_org_unit_id")
    op.execute("ALTER TABLE org_units  DROP COLUMN IF EXISTS manager_user_id")
    op.execute("ALTER TABLE tenants    DROP COLUMN IF EXISTS owner_user_id")

    for t in ["users", "org_units", "stores", "sites", "tenants",
              "carriers", "plan_features", "features", "plan_price",
              "subscription_plans", "role_permissions", "permissions",
              "roles", "uos_labels", "fits", "sizes", "colours", "colour_groups"]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
