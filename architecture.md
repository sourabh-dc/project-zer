# ZeroQue Architecture Documentation

## Overview

ZeroQue is a comprehensive multi-service backend platform for retail operations, built as a microservices architecture with 19 core services handling different business domains. The system implements a **single-tenant site connection model** where each tenant manages sites, and each site manages stores.

## Current Architecture Model

### Entity Hierarchy

```
TENANTS (1) ──→ (N) SITES (1) ──→ (N) STORES
    │                    │              │
    │                    │              │
    ▼                    ▼              ▼
USERS ──────────────── ROLES ───────── MEMBERSHIPS
    │                    │
    │                    │
    ▼                    ▼
COST_CENTRES ───────── BUDGETS
```

### Key Characteristics

- **Single Tenant per Site**: Each site belongs to exactly one tenant
- **Single Site per Store**: Each store belongs to exactly one site
- **Scoped User Roles**: Users have roles within specific tenant/site/store scopes
- **Global Products**: Products are global entities without vendor ownership
- **Store-Specific Pricing**: Pricing can be customized per store
- **Budget Management**: Cost centres and budgets for spending control

## Database Schema

### Core Tables (52 Total)

#### 1. Organizational Structure (6 tables)

**tenants**

```sql
tenant_id VARCHAR(100) PRIMARY KEY
name VARCHAR(200) NOT NULL
```

**sites**

```sql
site_id VARCHAR(100) PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE
name VARCHAR(200) NOT NULL
```

**stores**

```sql
store_id VARCHAR(100) PRIMARY KEY
site_id VARCHAR(100) NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE
name VARCHAR(200) NOT NULL
```

**users**

```sql
user_id VARCHAR(100) PRIMARY KEY
email VARCHAR(255) UNIQUE NOT NULL
display_name VARCHAR(200) NOT NULL
```

**roles**

```sql
role_id VARCHAR(100) PRIMARY KEY
code VARCHAR(100) NOT NULL
description VARCHAR(200) NOT NULL DEFAULT ''
```

**memberships**

```sql
id SERIAL PRIMARY KEY
user_id VARCHAR(100) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
role_id VARCHAR(100) NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE
tenant_id VARCHAR(100) NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE
site_id VARCHAR(100) NULL REFERENCES sites(site_id) ON DELETE CASCADE
UNIQUE(user_id, role_id, tenant_id, site_id)
```

#### 2. Product & Inventory Management (4 tables)

**products**

```sql
sku TEXT PRIMARY KEY
name TEXT NOT NULL
description TEXT NULL
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

**prices**

```sql
id BIGSERIAL PRIMARY KEY
sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE
currency CHAR(3) NOT NULL
unit_minor INTEGER NOT NULL
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
UNIQUE (sku, currency)
```

**inventory**

```sql
store_id TEXT NOT NULL
sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE
qty INTEGER NOT NULL DEFAULT 0
PRIMARY KEY (store_id, sku)
```

**inventory_movements**

```sql
id BIGSERIAL PRIMARY KEY
store_id TEXT NOT NULL
sku TEXT NOT NULL
delta INTEGER NOT NULL
reason TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

#### 3. Advanced Pricing Engine (6 tables)

**store_products**

```sql
id BIGSERIAL PRIMARY KEY
store_id TEXT NOT NULL
sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE
active BOOLEAN NOT NULL DEFAULT TRUE
base_price_minor INTEGER NULL
currency CHAR(3) NOT NULL DEFAULT 'GBP'
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
UNIQUE (store_id, sku)
```

**price_rules**

```sql
id BIGSERIAL PRIMARY KEY
name TEXT NOT NULL
description TEXT NULL
rule_type TEXT NOT NULL  -- percentage|fixed|formula|override
rule_config JSONB NOT NULL
priority INTEGER NOT NULL DEFAULT 100
active BOOLEAN NOT NULL DEFAULT TRUE
tenant_id TEXT NULL
site_id TEXT NULL
store_id TEXT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

**price_rule_conditions**

```sql
id BIGSERIAL PRIMARY KEY
rule_id BIGINT NOT NULL REFERENCES price_rules(id) ON DELETE CASCADE
condition_type TEXT NOT NULL  -- sku|category|user_role|time|quantity|etc
condition_config JSONB NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**promotions**

```sql
id BIGSERIAL PRIMARY KEY
name TEXT NOT NULL
description TEXT NULL
promo_type TEXT NOT NULL  -- discount|tax|bogo|bulk|etc
promo_config JSONB NOT NULL
priority INTEGER NOT NULL DEFAULT 100
active BOOLEAN NOT NULL DEFAULT TRUE
valid_from TIMESTAMPTZ NULL
valid_until TIMESTAMPTZ NULL
tenant_id TEXT NULL
site_id TEXT NULL
store_id TEXT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

**promotion_conditions**

```sql
id BIGSERIAL PRIMARY KEY
promotion_id BIGINT NOT NULL REFERENCES promotions(id) ON DELETE CASCADE
condition_type TEXT NOT NULL  -- sku|category|user_role|min_amount|time|etc
condition_config JSONB NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**calculated_prices**

```sql
id BIGSERIAL PRIMARY KEY
store_id TEXT NOT NULL
sku TEXT NOT NULL
user_id TEXT NULL
currency CHAR(3) NOT NULL DEFAULT 'GBP'
base_price_minor INTEGER NOT NULL
final_price_minor INTEGER NOT NULL
applied_rules JSONB NOT NULL DEFAULT '[]'
applied_promotions JSONB NOT NULL DEFAULT '[]'
calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
expires_at TIMESTAMPTZ NULL
UNIQUE (store_id, sku, user_id, currency)
```

#### 4. Order Processing (4 tables)

**orders**

```sql
order_id INTEGER PRIMARY KEY AUTOINCREMENT
tenant_id VARCHAR(100) NOT NULL
site_id VARCHAR(100) NOT NULL
store_id VARCHAR(100) NOT NULL
shopper_id VARCHAR(100) NOT NULL
cost_centre_id VARCHAR(100) NULL
provider VARCHAR(50) NOT NULL  -- e.g., 'aifi'
provider_order_id VARCHAR(200) NOT NULL
total_minor BIGINT NOT NULL
currency VARCHAR(3) DEFAULT 'GBP'
status VARCHAR(20) DEFAULT 'completed'
occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**order_items**

```sql
id SERIAL PRIMARY KEY
order_id INTEGER NOT NULL REFERENCES orders(order_id)
sku TEXT NOT NULL
qty INTEGER NOT NULL
unit_price_minor INTEGER NOT NULL
currency CHAR(3) NOT NULL DEFAULT 'GBP'
```

**ledger_entries**

```sql
id BIGSERIAL PRIMARY KEY
tenant_id TEXT NOT NULL
site_id TEXT NULL
store_id TEXT NULL
account VARCHAR(40) NOT NULL
entry_type VARCHAR(10) DEFAULT 'debit'
amount_minor INTEGER NOT NULL
currency CHAR(3) NOT NULL
description TEXT NULL
reference_id TEXT NULL
occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**trade_invoices**

```sql
id VARCHAR(120) PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL
site_id VARCHAR(100) NULL
order_id VARCHAR(100) NULL
amount_minor INTEGER NOT NULL
currency CHAR(3) NOT NULL
status VARCHAR(20) NOT NULL DEFAULT 'draft'
memo TEXT DEFAULT ''
invoice_code TEXT NULL
exported_at TIMESTAMPTZ NULL
export_batch_id TEXT NULL
posted_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

#### 5. Budget & Cost Management (4 tables)

**cost_centres**

```sql
cost_centre_id VARCHAR(100) PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL
name VARCHAR(200) NOT NULL
manager_user_id VARCHAR(100) NULL
```

**budgets**

```sql
budget_id VARCHAR(100) PRIMARY KEY
cost_centre_id VARCHAR(100) NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE
period VARCHAR(20) NOT NULL
currency CHAR(3) NOT NULL DEFAULT 'GBP'
limit_minor BIGINT NOT NULL
spent_minor BIGINT NOT NULL DEFAULT 0
hard_block BOOLEAN NOT NULL DEFAULT TRUE
```

**user_cost_centres**

```sql
id SERIAL PRIMARY KEY
user_id VARCHAR(100) NOT NULL
cost_centre_id VARCHAR(100) NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE
UNIQUE(user_id, cost_centre_id)
```

**approval_requests**

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT
tenant_id VARCHAR(100) NOT NULL
cost_centre_id VARCHAR(100) NOT NULL
requester_user_id VARCHAR(100) NOT NULL
user_scope_id VARCHAR(100) NULL
currency VARCHAR(3) DEFAULT 'GBP'
amount_minor BIGINT NOT NULL
remaining_minor BIGINT NOT NULL
status VARCHAR(20) DEFAULT 'pending'
approved_by VARCHAR(100) NULL
approved_at TIMESTAMPTZ NULL
notes TEXT NULL
expires_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

#### 6. Subscription System (5 tables)

**subscription_plans**

```sql
id BIGSERIAL PRIMARY KEY
code TEXT NOT NULL UNIQUE
name TEXT NOT NULL
description TEXT NULL
price_yearly_minor INTEGER NOT NULL
currency CHAR(3) NOT NULL DEFAULT 'GBP'
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

**features**

```sql
id BIGSERIAL PRIMARY KEY
code TEXT NOT NULL UNIQUE
name TEXT NOT NULL
description TEXT NULL
category TEXT NULL
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**plan_features**

```sql
id BIGSERIAL PRIMARY KEY
plan_code TEXT NOT NULL
feature_code TEXT NOT NULL
enabled BOOLEAN NOT NULL DEFAULT TRUE
limits JSONB NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
UNIQUE (plan_code, feature_code)
```

**site_subscriptions**

```sql
id BIGSERIAL PRIMARY KEY
tenant_id TEXT NOT NULL
site_id TEXT NOT NULL
plan_code TEXT NOT NULL REFERENCES subscription_plans(code)
payment_method TEXT NOT NULL
status TEXT NOT NULL DEFAULT 'active'
external_id TEXT NOT NULL
current_period_start TIMESTAMPTZ NULL
current_period_end TIMESTAMPTZ NULL
trial_end TIMESTAMPTZ NULL
canceled_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
UNIQUE (tenant_id, site_id)
```

**site_billing_accounts**

```sql
id BIGSERIAL PRIMARY KEY
tenant_id TEXT NOT NULL
site_id TEXT NOT NULL
payment_method TEXT NOT NULL
external_id TEXT NOT NULL
active BOOLEAN NOT NULL DEFAULT TRUE
metadata JSONB NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
UNIQUE (tenant_id, site_id, payment_method)
```

#### 7. RBAC System (3 tables)

**permissions**

```sql
id BIGSERIAL PRIMARY KEY
code TEXT NOT NULL UNIQUE
name TEXT NOT NULL
description TEXT NULL
category TEXT NULL
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**role_permissions**

```sql
id BIGSERIAL PRIMARY KEY
role_code TEXT NOT NULL
permission_code TEXT NOT NULL
granted BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
UNIQUE (role_code, permission_code)
```

**tenant_links**

```sql
parent_tenant_id VARCHAR(100) NOT NULL
child_tenant_id VARCHAR(100) NOT NULL
relationship VARCHAR(50) NOT NULL  -- distributor, partner, etc.
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
PRIMARY KEY (parent_tenant_id, child_tenant_id)
```

#### 8. Payment & Billing (4 tables)

**payment_preferences**

```sql
tenant_id VARCHAR(100) PRIMARY KEY
method VARCHAR(20) NOT NULL CHECK (method IN ('stripe','trade'))
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**stripe_customers**

```sql
id SERIAL PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL
stripe_customer_id VARCHAR(120) UNIQUE NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**stripe_charges**

```sql
id SERIAL PRIMARY KEY
tenant_id VARCHAR(100) NULL
site_id VARCHAR(100) NULL
order_id VARCHAR(100) NULL
payment_intent_id VARCHAR(120) UNIQUE
charge_id VARCHAR(120) NULL
amount_minor INTEGER NULL
currency CHAR(3) NULL
status VARCHAR(40) NULL
receipt_url TEXT NULL
raw JSONB NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
```

**trade_accounts**

```sql
id SERIAL PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL
ar_customer_code VARCHAR(100) NOT NULL
terms VARCHAR(50) NOT NULL DEFAULT 'net30'
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
UNIQUE (tenant_id, ar_customer_code)
```

#### 9. Usage Tracking (3 tables)

**usage_meters**

```sql
id SERIAL PRIMARY KEY
code VARCHAR(100) UNIQUE NOT NULL
description VARCHAR(255) NOT NULL DEFAULT ''
```

**usage_events**

```sql
id SERIAL PRIMARY KEY
tenant_id VARCHAR(100) NOT NULL
site_id VARCHAR(100) NULL
store_id VARCHAR(100) NULL
meter_code VARCHAR(100) NOT NULL
subject_id VARCHAR(100) NULL
value INTEGER NOT NULL DEFAULT 1
occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**usage_aggregates_daily**

```sql
id SERIAL PRIMARY KEY
day DATE NOT NULL
tenant_id VARCHAR(100) NOT NULL
site_id VARCHAR(100) NULL
store_id VARCHAR(100) NULL
meter_code VARCHAR(100) NOT NULL
value INTEGER NOT NULL DEFAULT 0
UNIQUE(day, tenant_id, site_id, store_id, meter_code)
```

#### 10. Enhanced Features (8 tables)

**idempotency_keys**

```sql
id SERIAL PRIMARY KEY
scope VARCHAR(80) NOT NULL
request_id VARCHAR(120) NOT NULL
response JSONB NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
UNIQUE(scope, request_id)
```

**webhook_messages**

```sql
id TEXT PRIMARY KEY
payload JSONB NOT NULL
status TEXT NOT NULL DEFAULT 'pending'
retry_count INTEGER NOT NULL DEFAULT 0
max_retries INTEGER NOT NULL DEFAULT 3
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
error_message TEXT NULL
processing_attempts JSONB NULL
```

**product_normalization_cache**

```sql
id BIGSERIAL PRIMARY KEY
external_id TEXT NOT NULL
provider TEXT NOT NULL
normalized_data JSONB NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NULL
UNIQUE (external_id, provider)
```

**price_hooks**

```sql
id BIGSERIAL PRIMARY KEY
hook_type TEXT NOT NULL
trigger_event TEXT NOT NULL
target_service TEXT NOT NULL
target_endpoint TEXT NOT NULL
config JSONB NULL
active BOOLEAN NOT NULL DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**cv_unknown_item_reviews**

```sql
id SERIAL PRIMARY KEY
provider VARCHAR(40) NOT NULL
tenant_id VARCHAR(100) NOT NULL
site_id VARCHAR(100) NOT NULL
store_id VARCHAR(100) NOT NULL
external_sku VARCHAR(120) NOT NULL
name TEXT NOT NULL
qty INTEGER NOT NULL
price_minor INTEGER NOT NULL
payload_json JSONB NOT NULL
status VARCHAR(20) NOT NULL DEFAULT 'pending'
mapped_sku VARCHAR(120) NULL
notes TEXT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**stripe_events**

```sql
id SERIAL PRIMARY KEY
event_id VARCHAR(120) UNIQUE NOT NULL
event_type VARCHAR(120) NOT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**notification_deliveries**

```sql
id SERIAL PRIMARY KEY
channel TEXT NOT NULL  -- dev_log | email_smtp | webhook
tenant_id TEXT NULL
subject TEXT NULL
payload JSONB NOT NULL
to_addr TEXT NULL
url TEXT NULL
headers JSONB NULL
status TEXT NOT NULL DEFAULT 'queued'  -- queued|sent|dead
attempts INTEGER NOT NULL DEFAULT 0
next_attempt_at TIMESTAMPTZ DEFAULT NOW()
error TEXT NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**provider_mappings**

```sql
id SERIAL PRIMARY KEY
provider VARCHAR(50) NOT NULL
entity_type VARCHAR(50) NOT NULL
local_id VARCHAR(100) NOT NULL
external_id VARCHAR(200) NOT NULL
UNIQUE(provider, entity_type, local_id)
```

## Service Architecture

### Core Business Services (7 services)

| Service          | Port | Purpose                        | Key Features                                  |
| ---------------- | ---- | ------------------------------ | --------------------------------------------- |
| **Provisioning** | 8201 | Tenant & user management       | Tenants, sites, stores, users, roles, budgets |
| **Catalog**      | 8202 | Product & inventory management | Products, prices, inventory tracking          |
| **Pricing**      | 8209 | Dynamic pricing engine         | Store-specific pricing, rules, promotions     |
| **Orders**       | 8208 | Order processing               | Order creation, validation, settlement        |
| **Entry**        | 8204 | Entry code system              | Issue/validate entry codes                    |
| **Identity**     | 8210 | Authentication                 | Guest/loyalty tokens                          |
| **Billing**      | 8206 | Payment & invoicing            | Stripe integration, trade invoices            |

### Advanced Services (4 services)

| Service           | Port | Purpose                 | Key Features                       |
| ----------------- | ---- | ----------------------- | ---------------------------------- |
| **Entitlements**  | 8203 | Feature access control  | Usage tracking, feature limits     |
| **Subscriptions** | 8211 | Subscription management | Plans, features, billing accounts  |
| **Events**        | 8213 | Event processing        | Event publishing, queuing, metrics |
| **Observability** | 8214 | System monitoring       | Health checks, metrics, alerts     |

### Integration Services (2 services)

| Service          | Port | Purpose            | Key Features                       |
| ---------------- | ---- | ------------------ | ---------------------------------- |
| **CV Gateway**   | 8000 | Webhook processing | AiFi integration, retry logic, DLQ |
| **CV Connector** | 8100 | Provider adapters  | External system integration        |

### Supporting Services (6 services)

| Service           | Port | Purpose             | Key Features                        |
| ----------------- | ---- | ------------------- | ----------------------------------- |
| **Approvals**     | 8205 | Approval workflow   | Request approval, budget validation |
| **Ledger**        | 8207 | Accounting system   | Double-entry bookkeeping, balances  |
| **Notifications** | 8215 | Notification system | Message delivery, retry logic       |
| **Payments**      | 8216 | Payment processing  | Stripe integration, webhooks        |
| **Reports**       | 8217 | Reporting system    | Sales, inventory, analytics         |
| **Usage**         | 8218 | Usage tracking      | API usage, metrics, billing         |

## Enhanced Communication System

### Event-Driven Architecture

- **Redis Streams**: Service-specific event streams for better isolation
- **Celery Workers**: Background task processing with 15 specialized queues
- **Circuit Breaker Pattern**: Prevents cascade failures with intelligent fallback
- **Saga Pattern**: Manages distributed transactions with compensation
- **Event Sourcing**: Complete audit trail with event replay capabilities

### Service Communication Patterns

- **Service Bus**: Enhanced event bus with targeted publishing
- **Service Discovery**: Dynamic service registration and discovery
- **Health Monitoring**: Continuous health checking with alerting
- **Circuit Breakers**: Automatic fallback mechanisms for service calls

## Security & Access Control

### Row-Level Security (RLS)

- Database-level tenant isolation
- Automatic tenant context setting
- Defense-in-depth security model
- 16 core tables protected with RLS policies

### RBAC System

- **Permissions**: Granular permission definitions
- **Role-Permission Mapping**: Flexible role assignment
- **Tenant-Scoped Access**: Users limited to their tenant context
- **Cross-Tenant Links**: Support for distributor relationships

### Default Roles

- **Admin**: Full access to all features
- **Manager**: Most permissions except tenant/subscription management
- **Employee**: Limited to store operations and order processing

## Data Flow Architecture

### Order Processing Flow

```
User Order → Entry Validation → Budget Check → Inventory Reserve →
Pricing Calculation → Payment Processing → Order Creation →
Inventory Update → Ledger Entry → Notification
```

### Pricing Engine Flow

```
Product Request → Store Product Lookup → Price Rules Application →
Promotion Application → Commission Calculation → Final Price Cache
```

### Event Processing Flow

```
Service Action → Event Bus → Redis Stream → Celery Worker →
Background Processing → Side Effects (Inventory, Notifications, Analytics)
```

## Key Architectural Strengths

1. **Microservices Design**: 19 specialized services with clear boundaries
2. **Event-Driven Architecture**: Asynchronous processing with Redis Streams
3. **Advanced Communication**: Circuit breakers, sagas, service discovery
4. **Comprehensive RBAC**: Multi-level permission system
5. **Row-Level Security**: Database-level tenant isolation
6. **Flexible Pricing**: Rule-based pricing engine with promotions
7. **Multi-Payment Support**: Stripe and trade account integration
8. **Usage Tracking**: Comprehensive metrics and analytics
9. **Subscription Management**: Feature-based subscription system
10. **Computer Vision Integration**: AiFi provider integration

## Current Limitations

1. **Single Vendor Model**: No vendor concept or multi-vendor support
2. **Simple Pricing**: No multi-vendor product offerings
3. **Basic RBAC**: Limited to tenant-scoped roles only
4. **Single Payment Model**: One billing account per tenant/site
5. **No Marketplace Features**: No vendor onboarding or commission management
6. **Limited Cross-Tenant Access**: No marketplace-wide user management

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy
- **Database**: PostgreSQL with Row-Level Security
- **Cache**: Redis for sessions and event streaming
- **Message Queue**: Redis Streams + Celery workers
- **Containerization**: Docker & Docker Compose
- **Migration**: Alembic for database schema management
- **Monitoring**: Custom observability service with health checks
- **Integration**: Computer vision (AiFi), Stripe payments, webhooks

This architecture provides a solid foundation for retail operations with room for enhancement toward a multi-tenant marketplace model.
