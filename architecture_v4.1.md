# ZeroQue v4.1 Architecture Documentation

## Overview

ZeroQue v4.1 is a comprehensive **multi-tenant marketplace platform** for retail operations, built as a microservices architecture with enhanced capabilities for vendor management, marketplace operations, and advanced pricing. The system implements a **flexible multi-tenant model** where tenants can have multiple sites, stores can belong to multiple sites, and vendors can serve multiple stores.

## v4.1 Architecture Model

### Entity Hierarchy

```
TENANTS (1) ──→ (M:N) SITES (M:N) ──→ (N) STORES
    │                    │              │
    │                    │              │
    ▼                    ▼              ▼
USERS ──────────────── ROLES ───────── PERMISSIONS
    │                    │
    │                    │
    ▼                    ▼
VENDORS ──────────── OFFERS ───────── ASSORTMENTS
    │                    │              │
    │                    │              │
    ▼                    ▼              ▼
PRODUCTS ────────── VARIANTS ──────── INVENTORY
    │                    │              │
    │                    │              │
    ▼                    ▼              ▼
PRICING ──────────── SETTLEMENTS ──── LEDGER
```

### Key Characteristics

- **Multi-Tenant Marketplace**: Vendors can serve multiple tenants/stores
- **Flexible Site-Store Relationships**: M:N relationships between sites and stores
- **Vendor-Centric Products**: Products are owned by vendors with marketplace offers
- **Advanced Pricing Engine**: Multi-level pricing with pricebooks, rules, and calculated prices
- **Comprehensive Settlements**: Automated vendor settlements with dispute management
- **Enhanced RBAC**: Granular permissions with role-based access control
- **Audit & Compliance**: Complete audit trails and data retention policies

## Database Schema

### Extensions & Types

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TYPE scope_type AS ENUM ('GLOBAL', 'TENANT', 'SITE', 'STORE', 'VENDOR');
CREATE TYPE owner_type AS ENUM ('TENANT', 'VENDOR');
CREATE TYPE price_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'ROLE', 'VENDOR');
CREATE TYPE order_status AS ENUM ('pending', 'completed', 'cancelled', 'refunded', 'partially_refunded');
CREATE TYPE payout_status AS ENUM ('pending', 'queued', 'paid', 'failed', 'disputed');
CREATE TYPE movement_type AS ENUM ('receipt', 'sale', 'adjustment', 'transfer', 'return', 'shrink');
CREATE TYPE budget_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'USER', 'COST_CENTRE', 'VENDOR');
```

### Core Tables (80+ Total)

#### 1. Organizational Structure (10 tables)

**scenarios**

```sql
CREATE TABLE scenarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    config JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**tenants**

```sql
CREATE TABLE tenants (
    tenant_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name VARCHAR(200) NOT NULL,
    type TEXT NOT NULL DEFAULT 'customer' CHECK (type IN ('customer', 'marketplace', 'vendor_org', 'partner')),
    scenario_id UUID NULL REFERENCES scenarios(id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**sites**

```sql
CREATE TABLE sites (
    site_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name VARCHAR(200) NOT NULL,
    geo JSONB NULL,  -- {address, latlng}
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**tenant_sites** (M:N)

```sql
CREATE TABLE tenant_sites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    role_type TEXT NOT NULL DEFAULT 'manager',  -- owner, operator, manager, viewer
    rights_expire_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, site_id)
);
```

**stores**

```sql
CREATE TABLE stores (
    store_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name VARCHAR(200) NOT NULL,
    timezone TEXT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**site_stores** (M:N)

```sql
CREATE TABLE site_stores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    site_id UUID NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(site_id, store_id)
);
```

**tenant_store_admins** (Multi-tenant store ops)

```sql
CREATE TABLE tenant_store_admins (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    role_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, store_id, role_code)
);
```

**vendors**

```sql
CREATE TABLE vendors (
    vendor_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    rating NUMERIC(3,2) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    UNIQUE(tenant_id)
);
```

**vendor_onboarding**

```sql
CREATE TABLE vendor_onboarding (
    onboarding_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    requirements JSONB NULL,  -- Docs checklist
    approver_id UUID NULL REFERENCES users(user_id),
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**tenant_links**

```sql
CREATE TABLE tenant_links (
    parent_tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    child_tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    relationship VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (parent_tenant_id, child_tenant_id)
);
```

#### 2. ERP Integrations & Access Controls (3 tables)

**erp_integrations**

```sql
CREATE TABLE erp_integrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL CHECK (type IN ('ERP', 'CRM')),
    config JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL))
);
```

**access_controls**

```sql
CREATE TABLE access_controls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL CHECK (type IN ('gate', 'RFID', 'lock', 'card_reader')),
    config JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    CHECK ((site_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**user_access_grants**

```sql
CREATE TABLE user_access_grants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    access_control_id UUID NOT NULL REFERENCES access_controls(id) ON DELETE CASCADE,
    grant_type VARCHAR(20) NOT NULL DEFAULT 'permanent',
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 3. User & RBAC (8 tables)

**users**

```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**roles**

```sql
CREATE TABLE roles (
    role_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    code VARCHAR(100) UNIQUE NOT NULL,
    description VARCHAR(200) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**role_assignments** (Polymorphic, replaces memberships)

```sql
CREATE TABLE role_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    scope_type scope_type NOT NULL DEFAULT 'GLOBAL',
    scope_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, role_id, scope_type, scope_id)
);
```

**permissions**

```sql
CREATE TABLE permissions (
    permission_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    category VARCHAR(50) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**role_permissions**

```sql
CREATE TABLE role_permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(role_id, permission_id)
);
```

**permission_grants**

```sql
CREATE TABLE permission_grants (
    grant_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    grantee_type TEXT NOT NULL CHECK (grantee_type IN ('user', 'role')),
    grantee_id UUID NOT NULL,
    permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    scope_type scope_type NOT NULL,
    scope_id UUID NULL,
    priority SMALLINT NOT NULL DEFAULT 1000,  -- Lower wins
    is_granted BOOLEAN NOT NULL DEFAULT TRUE,
    granted_by UUID NOT NULL REFERENCES users(user_id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(grantee_type, grantee_id, permission_id, scope_type, scope_id)
);
```

**permission_resolution_cache**

```sql
CREATE TABLE permission_resolution_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    scope_type scope_type NOT NULL,
    scope_id UUID NOT NULL,
    is_granted BOOLEAN NOT NULL,
    resolution_path JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, permission_id, scope_type, scope_id)
);
```

**user_manager_links** (For approval hierarchies)

```sql
CREATE TABLE user_manager_links (
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    manager_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, manager_user_id)
);
```

#### 3. Product & Variant Management (5 tables)

**product_master**

```sql
CREATE TABLE product_master (
    product_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    brand VARCHAR(200) NULL,
    category_hierarchy JSONB NULL,
    search_terms TSVECTOR,
    attributes_schema JSONB NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**product_variants**

```sql
CREATE TABLE product_variants (
    variant_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
    sku TEXT NOT NULL UNIQUE,
    gtin TEXT NULL,
    mpn TEXT NULL,
    uom VARCHAR(20) NOT NULL DEFAULT 'EA',
    package_quantity INTEGER NOT NULL DEFAULT 1,
    weight_grams INTEGER NULL,
    dimensions JSONB NULL,
    variant_attributes JSONB NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    UNIQUE(product_id, sku)
);
```

**product_media**

```sql
CREATE TABLE product_media (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
    variant_id UUID NULL REFERENCES product_variants(variant_id) ON DELETE CASCADE,
    media_type VARCHAR(20) NOT NULL,
    url TEXT NOT NULL,
    caption TEXT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**product_relationships**

```sql
CREATE TABLE product_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    from_product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
    to_product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    strength DECIMAL(3,2) NOT NULL DEFAULT 1.0,
    is_bidirectional BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (from_product_id != to_product_id)
);
```

**product_tax_categories**

```sql
CREATE TABLE product_tax_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
    region_id UUID NOT NULL REFERENCES tax_regions(region_id) ON DELETE CASCADE,
    tax_category VARCHAR(100) NOT NULL,
    effective_from DATE NOT NULL,
    effective_until DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(product_id, region_id, effective_from)
);
```

#### 4. Currency & Tax (4 tables)

**currencies**

```sql
CREATE TABLE currencies (
    iso_code CHAR(3) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    minor_unit SMALLINT NOT NULL DEFAULT 2,
    symbol VARCHAR(10) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**exchange_rates**

```sql
CREATE TABLE exchange_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    from_currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) ON DELETE CASCADE,
    to_currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) ON DELETE CASCADE,
    rate DECIMAL(15,6) NOT NULL,
    source VARCHAR(50) NOT NULL,
    effective_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(from_currency, to_currency, effective_date)
);
```

**tax_regions**

```sql
CREATE TABLE tax_regions (
    region_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    jurisdiction JSONB NOT NULL,  -- Geo polygon/country/state/GST code
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**tax_rules**

```sql
CREATE TABLE tax_rules (
    rule_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    region_id UUID NOT NULL REFERENCES tax_regions(region_id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,
    rate DECIMAL(5,4) NOT NULL,
    is_inclusive BOOLEAN NOT NULL DEFAULT FALSE,
    effective_from DATE NOT NULL,
    effective_until DATE NULL,
    description TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    EXCLUDE USING gist (region_id WITH =, category WITH =, daterange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
);
```

#### 5. Vendor Offers & Store Assortments (6 tables)

**vendor_offers**

```sql
CREATE TABLE vendor_offers (
    offer_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    variant_id UUID NOT NULL REFERENCES product_variants(variant_id) ON DELETE CASCADE,
    vendor_sku TEXT NOT NULL,
    vendor_product_name TEXT NULL,
    base_price_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    cost_price_minor BIGINT NULL,
    min_order_quantity INTEGER NOT NULL DEFAULT 1,
    lead_time_days INTEGER NULL,
    package_dimensions JSONB NULL,
    tax_category VARCHAR(100) NOT NULL DEFAULT 'standard',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    offer_valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    offer_valid_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    UNIQUE(vendor_id, variant_id),
    UNIQUE(vendor_id, vendor_sku)
);
```

**store_assortments**

```sql
CREATE TABLE store_assortments (
    assortment_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    assortment_type VARCHAR(20) NOT NULL DEFAULT 'primary',
    assortment_priority INTEGER NOT NULL DEFAULT 100,
    override_price_minor BIGINT NULL,
    override_reason TEXT NULL,
    stock_commitment INTEGER NULL,
    min_display_stock INTEGER NOT NULL DEFAULT 0,
    max_display_stock INTEGER NULL,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    eligibility_rules JSONB NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    UNIQUE(store_id, offer_id),
    EXCLUDE USING gist (store_id WITH =, offer_id WITH =, tstzrange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
);
```

**store_vendors**

```sql
CREATE TABLE store_vendors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    commission_rate DECIMAL(5,2) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(store_id, vendor_id)
);
```

**customer_segments**

```sql
CREATE TABLE customer_segments (
    segment_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    segment_rules JSONB NOT NULL,
    is_system_segment BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**assortment_segments**

```sql
CREATE TABLE assortment_segments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    assortment_id UUID NOT NULL REFERENCES store_assortments(assortment_id) ON DELETE CASCADE,
    segment_id UUID NOT NULL REFERENCES customer_segments(segment_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(assortment_id, segment_id)
);
```

#### 6. Pricing System (7 tables)

**pricebooks**

```sql
CREATE TABLE pricebooks (
    pricebook_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    pricebook_type VARCHAR(50) NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    hierarchy_rank INTEGER NOT NULL DEFAULT 100,  -- Lower first
    active BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**pricebook_assignments**

```sql
CREATE TABLE pricebook_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    pricebook_id UUID NOT NULL REFERENCES pricebooks(pricebook_id) ON DELETE CASCADE,
    target_type price_scope NOT NULL,
    target_id UUID NOT NULL,
    assignment_priority INTEGER NOT NULL DEFAULT 100,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    EXCLUDE USING gist (pricebook_id WITH =, target_type WITH =, target_id WITH =, tstzrange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
);
```

**pricebook_entries**

```sql
CREATE TABLE pricebook_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    pricebook_id UUID NOT NULL REFERENCES pricebooks(pricebook_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    price_minor BIGINT NOT NULL,
    min_quantity INTEGER NOT NULL DEFAULT 1,
    max_quantity INTEGER NULL,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(pricebook_id, offer_id, min_quantity),
    EXCLUDE USING gist (pricebook_id WITH =, offer_id WITH =, int4range(min_quantity, COALESCE(max_quantity, 2147483647)) WITH &&),
    CHECK (min_quantity > 0 AND (max_quantity IS NULL OR max_quantity >= min_quantity))
);
```

**price_rules**

```sql
CREATE TABLE price_rules (
    rule_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    rule_type VARCHAR(50) NOT NULL,
    rule_config JSONB NOT NULL,
    application_scope VARCHAR(50) NOT NULL,
    application_order INTEGER NOT NULL DEFAULT 100,
    priority INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    scope_type price_scope NULL,
    scope_id UUID NULL,
    valid_from TIMESTAMPTZ NULL,
    valid_until TIMESTAMPTZ NULL,
    version_created BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**pricing_versions**

```sql
CREATE TABLE pricing_versions (
    version_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    version_type VARCHAR(50) NOT NULL,
    version_number BIGINT NOT NULL,
    description TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(version_type, version_number)
);
```

**calculated_prices** (Partitioned)

```sql
CREATE TABLE calculated_prices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    role_bucket TEXT NULL,  -- Normalized roles/segments
    quantity INTEGER NOT NULL DEFAULT 1,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    base_price_minor BIGINT NOT NULL,
    final_price_minor BIGINT NOT NULL,
    tax_amount_minor BIGINT NOT NULL DEFAULT 0,
    price_breakdown JSONB NOT NULL,
    applied_pricebooks JSONB NOT NULL DEFAULT '[]',
    applied_rules JSONB NOT NULL DEFAULT '[]',
    assignments_version BIGINT NOT NULL,
    rules_version BIGINT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    cache_hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(cache_hash)
) PARTITION BY RANGE (calculated_at);
-- e.g., CREATE TABLE calculated_prices_2025 PARTITION OF calculated_prices FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
```

#### 7. Inventory Management (2 tables)

**inventory**

```sql
CREATE TABLE inventory (
    inventory_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    owner_type owner_type NOT NULL,
    owner_id UUID NOT NULL,
    ownership_type VARCHAR(20) NOT NULL DEFAULT 'owned',
    quantity_available INTEGER NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,
    quantity_on_order INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER NULL,
    max_stock_level INTEGER NULL,
    last_counted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL,
    UNIQUE(store_id, offer_id)
);
```

**inventory_movements** (Partitioned)

```sql
CREATE TABLE inventory_movements (
    movement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    owner_type owner_type NOT NULL,
    owner_id UUID NOT NULL,
    movement_type movement_type NOT NULL,
    delta INTEGER NOT NULL,
    previous_quantity INTEGER NOT NULL,
    new_quantity INTEGER NOT NULL,
    reason VARCHAR(100) NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    cost_price_minor BIGINT NULL,
    settlement_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    settled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE SET NULL
) PARTITION BY RANGE (created_at);
-- e.g., CREATE TABLE inventory_movements_2025 PARTITION OF inventory_movements FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
```

#### 8. Order Processing (8 tables)

**orders**

```sql
CREATE TABLE orders (
    order_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    shopper_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    order_status order_status NOT NULL DEFAULT 'pending',
    total_minor BIGINT NOT NULL,
    commission_total_minor BIGINT NOT NULL DEFAULT 0,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    checkout_completed_at TIMESTAMPTZ NULL,
    fulfilled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**sub_orders**

```sql
CREATE TABLE sub_orders (
    sub_order_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    sub_order_status order_status NOT NULL DEFAULT 'pending',
    fulfillment_type VARCHAR(20) NOT NULL DEFAULT 'vendor',
    subtotal_minor BIGINT NOT NULL,
    shipping_minor BIGINT NOT NULL DEFAULT 0,
    tax_minor BIGINT NOT NULL DEFAULT 0,
    shipping_carrier VARCHAR(100) NULL,
    tracking_number TEXT NULL,
    shipped_at TIMESTAMPTZ NULL,
    estimated_delivery TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**order_items**

```sql
CREATE TABLE order_items (
    order_item_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    variant_id UUID NOT NULL REFERENCES product_variants(variant_id) ON DELETE CASCADE,
    offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL,
    unit_price_minor BIGINT NOT NULL,
    commission_rate DECIMAL(5,4) NOT NULL,
    commission_minor BIGINT NOT NULL,
    vendor_earnings_minor BIGINT NOT NULL,
    tax_amount_minor BIGINT NOT NULL DEFAULT 0,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    fulfillment_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios

**returns**

```sql
CREATE TABLE returns (
    return_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    order_item_id UUID NOT NULL REFERENCES order_items(order_item_id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    reason VARCHAR(100) NOT NULL,
    condition VARCHAR(20) NOT NULL DEFAULT 'unopened',
    state VARCHAR(20) NOT NULL DEFAULT 'requested',
    refund_amount_minor BIGINT NULL,
    restocking_fee_minor BIGINT NOT NULL DEFAULT 0,
    processed_by UUID NULL REFERENCES users(user_id),
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

**refunds**

```sql
CREATE TABLE refunds (
    refund_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason VARCHAR(100) NOT NULL,
    provider_ref VARCHAR(200) NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'pending',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### 9. Settlements & Payouts (5 tables)

**vendor_settlements**

```sql
CREATE TABLE vendor_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    sub_order_id UUID NOT NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    net_sales_minor BIGINT NOT NULL,
    commission_minor BIGINT NOT NULL,
    fees_minor BIGINT NOT NULL DEFAULT 0,
    payout_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    status payout_status NOT NULL DEFAULT 'pending',
    scheduled_payout_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_batches**

```sql
CREATE TABLE vendor_settlement_batches (
    batch_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    total_payout_minor BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_items**

```sql
CREATE TABLE vendor_settlement_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
    settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    payout_amount_minor BIGINT NOT NULL,
    commission_amount_minor BIGINT NOT NULL,
    fee_amount_minor BIGINT NOT NULL DEFAULT 0,
    net_amount_minor BIGINT NOT NULL,
    settlement_status payout_status NOT NULL DEFAULT 'pending',
    paid_out_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**vendor_settlement_adjustments**

```sql
CREATE TABLE vendor_settlement_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    adjustment_type VARCHAR(50) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    reason TEXT NOT NULL,
    reference_type VARCHAR(50) NULL,
    reference_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(user_id)
);
```

**vendor_disputes**

```sql
CREATE TABLE vendor_disputes (
    dispute_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    dispute_type VARCHAR(50) NOT NULL,
    dispute_reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution VARCHAR(20) NULL,
    resolution_notes TEXT NULL,
    sla_deadline TIMESTAMPTZ NOT NULL,
    resolved_by UUID NULL REFERENCES users(user_id),
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NULL
);
```

#### 10. Ledger & Accounting (3 tables)

**ledger_accounts**

```sql
CREATE TABLE ledger_accounts (
    account_number TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset, liability, equity, revenue, expense
    sub_account_type TEXT NULL,  -- payable, receivable, inventory, cogs, commission_rev
    tenant_id UUID NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
);
```

**ledger_entries**

```sql
CREATE TABLE ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    site_id UUID NULL REFERENCES sites(site_id) ON DELETE SET NULL,
    store_id UUID NULL REFERENCES stores(store_id) ON DELETE SET NULL,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    description TEXT NULL,
    reference_type TEXT NULL,  -- order, settlement, adjustment, payout
    reference_id UUID NULL,
    effective_date DATE NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**account_balances**

```sql
CREATE TABLE account_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    account_number TEXT NOT NULL REFERENCES ledger_accounts(account_number),
    balance_date DATE NOT NULL,
    balance_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
    last_entry_id UUID NULL REFERENCES ledger_entries(entry_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_number, balance_date)
);
```

#### 11. Budget & Approvals (7 tables)

**cost_centres**

```sql
CREATE TABLE cost_centres (
    cost_centre_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    manager_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**budgets**

```sql
CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    description TEXT NULL,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    period_type TEXT NOT NULL,  -- monthly, quarterly, yearly, custom
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) DEFAULT 'GBP',
    total_budget_minor BIGINT NOT NULL,
    committed_minor BIGINT NOT NULL DEFAULT 0,
    spent_minor BIGINT NOT NULL DEFAULT 0,
    remaining_minor BIGINT NOT NULL,
    hard_limit BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**user_cost_centres**

```sql
CREATE TABLE user_cost_centres (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    cost_centre_id UUID NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
    UNIQUE(user_id, cost_centre_id)
);
```

**approval_chains**

```sql
CREATE TABLE approval_chains (
    approval_chain_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name TEXT NOT NULL,
    chain_type TEXT NOT NULL,  -- budget, purchase, access, payout
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_chain_steps**

```sql
CREATE TABLE approval_chain_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_chain_id UUID NOT NULL REFERENCES approval_chains(approval_chain_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approver_role TEXT NOT NULL,  -- Role code
    approver_scope scope_type NOT NULL,
    escalation_after_hours INTEGER NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(approval_chain_id, step_number)
);
```

**approval_requests**

```sql
CREATE TABLE approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    request_type TEXT NOT NULL,  -- budget, purchase, access, refund, vendor_payout
    requester_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope_type budget_scope NOT NULL,
    scope_id UUID NOT NULL,
    cost_centre_id UUID NULL REFERENCES cost_centres(cost_centre_id) ON DELETE SET NULL,
    currency CHAR(3) DEFAULT 'GBP' REFERENCES currencies(iso_code),
    amount_minor BIGINT NULL,
    remaining_budget_minor BIGINT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 1,
    approval_chain_id UUID NULL REFERENCES approval_chains(approval_chain_id),
    metadata JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**approval_request_approvers**

```sql
CREATE TABLE approval_request_approvers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    approval_request_id UUID NOT NULL REFERENCES approval_requests(approval_request_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    approved BOOLEAN NULL,
    approved_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    UNIQUE(approval_request_id, user_id, step_number)
);
```

#### 13. Audit & Events (3 tables)

**audit_logs**

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    actor_user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NULL,
    diff_json JSONB NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**data_retention_policies**

```sql
CREATE TABLE data_retention_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    table_name VARCHAR(100) NOT NULL,
    retention_period INTERVAL NOT NULL,
    archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**outbox_events**

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    topic TEXT NOT NULL,  -- e.g., PRICING.VERSION_CHANGED
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
```

## Key Features

### 1. Multi-Tenant Marketplace

- **Flexible Tenant Relationships**: Tenants can have multiple sites, sites can serve multiple stores
- **Vendor Marketplace**: Vendors can serve multiple tenants and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### 2. Advanced RBAC

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Session Management**: Secure user session handling

### 3. Vendor Management

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling

### 4. Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates

### 5. Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### 6. Order Management

- **Multi-Vendor Orders**: Orders can span multiple vendors
- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management

### 7. Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### 8. Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

## Indexes (Key Examples)

```sql
CREATE INDEX ix_role_assignments_user_scope ON role_assignments(user_id, scope_type, scope_id);
CREATE INDEX ix_permission_grants_lookup ON permission_grants(grantee_type, grantee_id, scope_type, scope_id, permission_id) WHERE active = TRUE;
CREATE INDEX ix_store_assortments_active ON store_assortments(store_id) WHERE status = 'active' AND (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_vendor_offers_active ON vendor_offers(vendor_id) WHERE status = 'active' AND (offer_valid_until IS NULL OR offer_valid_until > NOW());
CREATE INDEX ix_pricebook_assignments_target ON pricebook_assignments(target_type, target_id) WHERE (effective_until IS NULL OR effective_until > NOW());
CREATE INDEX ix_calculated_prices_lookup ON calculated_prices(store_id, offer_id, user_id, quantity, currency) WHERE expires_at > NOW();
CREATE INDEX ix_calculated_prices_hash ON calculated_prices(cache_hash);
CREATE INDEX ix_calculated_prices_expiry ON calculated_prices(expires_at);
CREATE INDEX ix_inventory_movements_time ON inventory_movements(store_id, offer_id, created_at DESC);
CREATE INDEX ix_outbox_unprocessed ON outbox_events(created_at) WHERE delivered_at IS NULL;
```

## Row-Level Security (RLS) Policies

Enable on all tables:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
```

Examples (expand as needed; use current_setting for 'app.user_id', 'app.current_tenant_id'):

**tenants**

```sql
CREATE POLICY tenants_isolation ON tenants
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants pg WHERE pg.grantee_id = current_setting('app.user_id')::UUID
                      AND pg.permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_TENANTS')
                      AND pg.is_granted AND pg.active));
```

**vendor_offers**

```sql
CREATE POLICY vendor_offers_isolation ON vendor_offers
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'VENDOR' AND ra.scope_id = vendor_id)
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**store_assortments**

```sql
CREATE POLICY store_assortments_visibility ON store_assortments
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM site_stores WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = store_assortments.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

**orders**

```sql
CREATE POLICY orders_isolation ON orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID
           OR shopper_id = current_setting('app.user_id')::UUID
           OR EXISTS (SELECT 1 FROM permission_grants WHERE grantee_id = current_setting('app.user_id')::UUID
                      AND permission_id IN (SELECT permission_id FROM permissions WHERE code = 'VIEW_ALL_ORDERS')
                      AND is_granted AND active));
```

**calculated_prices**

```sql
CREATE POLICY calculated_prices_isolation ON calculated_prices
    USING (store_id IN (SELECT store_id FROM store_assortments WHERE store_id IN
                       (SELECT store_id FROM site_stores ss JOIN tenant_sites ts ON ss.site_id = ts.site_id
                        WHERE ts.tenant_id = current_setting('app.current_tenant_id')::UUID))
           OR user_id = current_setting('app.user_id')::UUID);
```

**inventory**

```sql
CREATE POLICY inventory_isolation ON inventory
    USING (EXISTS (SELECT 1 FROM role_assignments ra JOIN roles r ON ra.role_id = r.role_id
                   WHERE ra.user_id = current_setting('app.user_id')::UUID
                   AND ((ra.scope_type = 'STORE' AND ra.scope_id = store_id)
                        OR (ra.scope_type = 'SITE' AND ra.scope_id IN (SELECT site_id FROM stores WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'TENANT' AND ra.scope_id IN (SELECT tenant_id FROM tenant_store_admins WHERE store_id = inventory.store_id))
                        OR (ra.scope_type = 'GLOBAL' AND r.code = 'MARKETPLACE_ADMIN'))));
```

## Microservices Architecture

### Core Services (19 services)

1. **Identity Service** - User authentication and session management
2. **RBAC Service** - Role-based access control and permissions
3. **Catalog Service** - Product and variant management
4. **Pricing Service** - Advanced pricing engine and rules
5. **Inventory Service** - Multi-owner inventory management
6. **Orders Service** - Multi-vendor order processing
7. **Payments Service** - Payment processing and reconciliation
8. **Settlements Service** - Vendor settlement processing
9. **Ledger Service** - Double-entry accounting system
10. **Approvals Service** - Workflow and approval management
11. **Notifications Service** - Event-driven notifications
12. **Reports Service** - Analytics and reporting
13. **Audit Service** - Audit logging and compliance
14. **Events Service** - Event sourcing and outbox processing
15. **Observability Service** - Monitoring and metrics
16. **CV Gateway Service** - Computer vision integration
17. **CV Connector Service** - CV provider management
18. **Billing Service** - Billing and invoicing
19. **Usage Service** - Usage tracking and metering

### Communication Patterns

- **Event-Driven Architecture**: Redis Streams + Celery for async processing
- **Synchronous APIs**: RESTful APIs for real-time operations
- **Message Queues**: Reliable message processing with retry mechanisms
- **Event Sourcing**: Complete audit trail with outbox pattern

## Security & Compliance

### Row Level Security (RLS)

- **Tenant Isolation**: Complete data isolation between tenants
- **Role-Based Access**: Granular permissions based on user roles
- **Audit Logging**: All data access and modifications are logged

### Data Protection

- **Encryption**: Data encrypted at rest and in transit
- **Data Retention**: Configurable retention policies
- **GDPR Compliance**: Built-in data privacy controls

## Performance & Scalability

### Database Optimization

- **Indexing Strategy**: Comprehensive indexing for all query patterns
- **Partitioning**: Time-based partitioning for large tables
- **Connection Pooling**: Efficient database connection management

### Caching Strategy

- **Permission Caching**: High-performance permission resolution
- **Query Result Caching**: Redis-based result caching
- **Session Caching**: Distributed session management

### Horizontal Scaling

- **Microservices**: Independent scaling of services
- **Database Sharding**: Tenant-based data sharding
- **Load Balancing**: Distributed request processing

## Migration Strategy

### Phase 1: Foundation ✅

- ✅ Database schema creation
- ✅ New table structures
- ✅ Basic data migration scripts

### Phase 2: Service Updates (Next)

- Service API enhancements
- Microservice integration
- Testing and validation

### Phase 3: Advanced Features

- Advanced pricing rules
- Marketplace features
- Analytics and reporting

## Technology Stack

- **Database**: PostgreSQL 15+ with extensions
- **Cache**: Redis 7+ for caching and message queues
- **Message Queue**: Redis Streams + Celery
- **API Framework**: FastAPI with async support
- **ORM**: SQLAlchemy 2.0+ with async support
- **Migrations**: Alembic for database versioning
- **Monitoring**: OpenTelemetry + Prometheus
- **Containerization**: Docker + Docker Compose

---

_This architecture document represents the complete v4.1 multi-tenant marketplace platform, providing a comprehensive foundation for scalable retail operations with advanced vendor management and marketplace capabilities._

## Additional Enhanced Features

### ERP Integrations & Access Controls

The v4.1 architecture includes enhanced features for ERP integrations and physical access control:

#### ERP/CRM Integrations

- **erp_integrations**: Seamless integration with distributor ERP/CRM systems
- **Multi-tenant Support**: Both tenant and vendor-level integrations
- **Flexible Configuration**: JSONB-based configuration for different ERP systems
- **Sync Tracking**: Last sync timestamps and status monitoring

#### Physical Access Control

- **access_controls**: Support for gates, RFID, locks, and card readers
- **user_access_grants**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration
- **Site/Store Level**: Access controls can be assigned to sites or stores

### Advanced Monetization

#### Usage-Based Billing

- **usage_ledger_entries**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models
- **Multi-level Tracking**: Tenant, site, and store-level usage tracking

### Zeroque Rails

#### Owned Infrastructure

- **zeroque_rails**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions
- **Future-Ready**: Infrastructure for owned payment and CV systems

### Business Scenarios

#### Scenario-Based Configuration

- **scenarios**: Business scenario definitions (end_user, retailer, distributor, custom)
- **Tenant Association**: Tenants can be associated with specific scenarios
- **Flexible Configuration**: JSONB-based scenario-specific settings
- **Extensible**: Easy addition of new business scenarios
