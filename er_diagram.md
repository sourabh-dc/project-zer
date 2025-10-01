# ZeroQue V2 Database ER Diagram

## Multi-Tenant Marketplace Architecture

### Core Tenant & Site Relationships

```
TENANTS (1) ──→ (N) TENANT_SITES (N) ──→ (1) SITES (1) ──→ (N) SITE_STORES (N) ──→ (1) STORES
    │                    │                    │                    │                    │
    │                    │                    │                    │                    │
    ▼                    ▼                    ▼                    ▼                    ▼
TENANT_LINKS         SCENARIOS            ACCESS_CONTROLS      USER_ACCESS_GRANTS   ERP_INTEGRATIONS
    │                    │                    │                    │                    │
    │                    │                    │                    │                    │
    ▼                    ▼                    ▼                    ▼                    ▼
USERS_NEW ──────────── ROLES_NEW ───────── PERMISSIONS_NEW ──── ROLE_PERMISSIONS ── PERMISSION_GRANTS
    │                    │                    │                    │                    │
    │                    │                    │                    │                    │
    ▼                    ▼                    ▼                    ▼                    ▼
COST_CENTRES         BUDGETS              USER_COST_CENTRES   APPROVAL_CHAINS     APPROVAL_STEPS
    │                    │                    │                    │                    │
    │                    │                    │                    │                    │
    ▼                    ▼                    ▼                    ▼                    ▼
LEDGER_ACCOUNTS      ACCOUNT_BALANCES     APPROVAL_REQUESTS   APPROVERS          DATA_RETENTION_POLICIES
```

### Product & Marketplace Relationships

```
PRODUCT_MASTER (1) ──→ (N) PRODUCT_VARIANTS (1) ──→ (N) VENDOR_OFFERS (N) ──→ (1) VENDORS
    │                        │                        │                        │
    │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼
PRODUCT_MEDIA            PRODUCT_RELATIONSHIPS    STORE_VENDORS            VENDOR_SETTLEMENTS
    │                        │                        │                        │
    │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼
PRODUCT_TAX_CATEGORIES   ASSORTMENTS             CUSTOMER_SEGMENTS        SETTLEMENT_BATCHES
    │                        │                        │                        │
    │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼
TAX_REGIONS              ASSORTMENT_SEGMENTS     PRICEBOOKS               SETTLEMENT_ITEMS
    │                        │                        │                        │
    │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼
TAX_RULES                PRICEBOOK_ASSIGNMENTS   PRICEBOOK_ENTRIES        SETTLEMENT_ADJUSTMENTS
```

### Advanced Pricing & Rules

```
PRICEBOOKS (1) ──→ (N) PRICEBOOK_ASSIGNMENTS (N) ──→ (1) TARGETS
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
PRICEBOOK_ENTRIES        PRICING_VERSIONS            CALCULATED_PRICES
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
PRICE_RULES_NEW          PRICE_HOOKS                 PRICE_RULE_CONDITIONS
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
PROMOTIONS               EXCHANGE_RATES              CURRENCIES
```

### Order & Fulfillment Relationships

```
ORDERS_NEW (1) ──→ (N) SUB_ORDERS (1) ──→ (N) ORDER_ITEMS_NEW
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
RETURNS                 ORDER_VENDOR_SPLITS       REFUNDS
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
LEDGER_ENTRIES_NEW     VENDOR_SETTLEMENTS        AUDIT_LOGS
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
OUTBOX_EVENTS          USAGE_LEDGER_ENTRIES     ZEROQUE_RAILS
```

### Inventory & Movement Tracking

```
INVENTORY (1) ──→ (N) INVENTORY_MOVEMENTS
    │                    │
    │                    │
    ▼                    ▼
INVENTORY_RESERVATIONS  INVENTORY_ADJUSTMENTS
    │                    │
    │                    │
    ▼                    ▼
INVENTORY_LOCATIONS     INVENTORY_TRANSFERS
```

### Usage & Analytics

```
USAGE_METERS (1) ──→ (N) USAGE_EVENTS (N) ──→ (1) USAGE_AGGREGATES_DAILY
    │                        │                        │
    │                        │                        │
    ▼                        ▼                        ▼
USAGE_LEDGER_ENTRIES     USAGE_AGGREGATES_MONTHLY   USAGE_REPORTS
```

## Key V2 Architecture Features

### Multi-Tenancy
- **Tenant Isolation**: All tables include `tenant_id` for complete data isolation
- **Row-Level Security (RLS)**: Automatic tenant-based access control
- **Tenant Hierarchies**: Parent-child tenant relationships via `tenant_links_new`

### Marketplace Model
- **Vendor Management**: Complete vendor onboarding and management
- **Product Catalog**: Master products with variants and vendor-specific offers
- **Assortment Management**: Store-specific product assortments
- **Customer Segmentation**: Targeted pricing and promotions

### Advanced Pricing
- **Pricebook System**: Hierarchical pricing with assignments
- **Dynamic Rules**: Complex pricing rules with conditions
- **Promotions**: Time-based promotional pricing
- **Multi-Currency**: Exchange rate support with currency conversion

### Order Management
- **Sub-Orders**: Vendor-specific order splitting
- **Vendor Splits**: Commission and settlement tracking
- **Returns & Refunds**: Complete return management
- **Inventory Integration**: Real-time inventory tracking

### Financial Management
- **Ledger System**: Double-entry accounting with accounts and balances
- **Settlement Processing**: Automated vendor settlements
- **Budget Management**: Cost center and budget tracking
- **Approval Workflows**: Multi-step approval processes

### Event-Driven Architecture
- **Event Sourcing**: Complete audit trail via `audit_logs`
- **Outbox Pattern**: Reliable event publishing via `outbox_events`
- **Service Integration**: Inter-service communication via events

### Data Management
- **Retention Policies**: Automated data lifecycle management
- **Usage Tracking**: Comprehensive usage analytics
- **ERP Integration**: External system synchronization
- **Access Control**: Physical access management for stores

## Database Features

### Performance Optimizations
- **Partitioning**: `calculated_prices` and `inventory_movements` tables
- **Indexing**: Comprehensive indexes for all foreign keys and search fields
- **Caching**: Redis-based caching for frequently accessed data

### Data Integrity
- **Constraints**: CHECK constraints for data validation
- **Foreign Keys**: Complete referential integrity
- **Unique Constraints**: Prevent duplicate data
- **Exclusion Constraints**: Prevent overlapping data ranges

### Security
- **RLS Policies**: Tenant-based access control
- **Encryption**: Sensitive data encryption at rest
- **Audit Logging**: Complete change tracking
- **Access Grants**: Fine-grained permission system