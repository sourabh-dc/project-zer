# ZeroQue V4.1 Database ER Diagram

## Multi-Tenant Marketplace Architecture with Event-Driven Microservices

### Core Tenant & Identity Management

```
TENANTS_NEW (1) ──→ (N) TENANT_SITES_NEW (N) ──→ (1) SITES_NEW (1) ──→ (N) SITE_STORES_NEW (N) ──→ (1) STORES_NEW
    │                        │                        │                        │                        │
    │                        │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼                        ▼
TENANT_LINKS_NEW         SCENARIOS_NEW            ACCESS_CONTROLS_NEW      USER_ACCESS_GRANTS_NEW   ERP_INTEGRATIONS_NEW
    │                        │                        │                        │                        │
    │                        │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼                        ▼
USERS_NEW ─────────────── ROLES_NEW ──────────── PERMISSIONS_NEW ─────── ROLE_PERMISSIONS_NEW ─── PERMISSION_GRANTS_NEW
    │                        │                        │                        │                        │
    │                        │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼                        ▼
COST_CENTRES_NEW         BUDGETS_NEW             USER_COST_CENTRES_NEW   APPROVAL_CHAINS_NEW     APPROVAL_STEPS_NEW
    │                        │                        │                        │                        │
    │                        │                        │                        │                        │
    ▼                        ▼                        ▼                        ▼                        ▼
LEDGER_ACCOUNTS_NEW      ACCOUNT_BALANCES_NEW     APPROVAL_REQUESTS_NEW   APPROVAL_REQUEST_APPROVERS_NEW  DATA_RETENTION_POLICIES_NEW
```

### Product & Marketplace Relationships

```
PRODUCT_MASTER_NEW (1) ──→ (N) PRODUCT_VARIANTS_NEW (1) ──→ (N) VENDOR_OFFERS_NEW (N) ──→ (1) VENDORS_NEW
    │                            │                            │                            │
    │                            │                            │                            │
    ▼                            ▼                            ▼                            ▼
PRODUCT_MEDIA_NEW            PRODUCT_RELATIONSHIPS_NEW    STORE_VENDORS_NEW            VENDOR_SETTLEMENTS_NEW
    │                            │                            │                            │
    │                            │                            │                            │
    ▼                            ▼                            ▼                            ▼
PRODUCT_TAX_CATEGORIES_NEW   ASSORTMENTS_NEW             CUSTOMER_SEGMENTS_NEW        VENDOR_SETTLEMENT_BATCHES_NEW
    │                            │                            │                            │
    │                            │                            │                            │
    ▼                            ▼                            ▼                            ▼
TAX_REGIONS_NEW              ASSORTMENT_SEGMENTS_NEW     PRICEBOOKS_NEW               VENDOR_SETTLEMENT_ITEMS_NEW
    │                            │                            │                            │
    │                            │                            │                            │
    ▼                            ▼                            ▼                            ▼
TAX_RULES_NEW                PRICEBOOK_ASSIGNMENTS_NEW   PRICEBOOK_ENTRIES_NEW        VENDOR_SETTLEMENT_ADJUSTMENTS_NEW
```

### Advanced Pricing & Rules Engine

```
PRICEBOOKS_NEW (1) ──→ (N) PRICEBOOK_ASSIGNMENTS_NEW (N) ──→ (1) TARGETS_NEW
    │                            │                                │
    │                            │                                │
    ▼                            ▼                                ▼
PRICEBOOK_ENTRIES_NEW         PRICING_VERSIONS_NEW            CALCULATED_PRICES_NEW
    │                            │                                │
    │                            │                                │
    ▼                            ▼                                ▼
PRICE_RULES_NEW              PRICE_HOOKS_NEW                 PRICE_RULE_CONDITIONS_NEW
    │                            │                                │
    │                            │                                │
    ▼                            ▼                                ▼
PROMOTIONS_NEW               EXCHANGE_RATES_NEW              CURRENCIES_NEW
```

### Order & Fulfillment Management

```
ORDERS_NEW (1) ──→ (N) SUB_ORDERS_NEW (1) ──→ (N) ORDER_ITEMS_NEW
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
RETURNS_NEW             ORDER_VENDOR_SPLITS_NEW   REFUNDS_NEW
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
LEDGER_ENTRIES_NEW     VENDOR_SETTLEMENTS_NEW    AUDIT_LOGS_NEW
    │                    │                        │
    │                    │                        │
    ▼                    ▼                        ▼
OUTBOX_EVENTS_NEW      USAGE_LEDGER_ENTRIES_NEW  ZEROQUE_RAILS_NEW
```

### Inventory & Movement Tracking

```
INVENTORY_NEW (1) ──→ (N) INVENTORY_MOVEMENTS_NEW
    │                        │
    │                        │
    ▼                        ▼
INVENTORY_RESERVATIONS_NEW  INVENTORY_ADJUSTMENTS_NEW
    │                        │
    │                        │
    ▼                        ▼
INVENTORY_LOCATIONS_NEW     INVENTORY_TRANSFERS_NEW
```

### Usage & Analytics

```
USAGE_METERS_NEW (1) ──→ (N) USAGE_EVENTS_NEW (N) ──→ (1) USAGE_AGGREGATES_DAILY_NEW
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
USAGE_LEDGER_ENTRIES_NEW     USAGE_AGGREGATES_MONTHLY_NEW   USAGE_REPORTS_NEW
```

### Event-Driven Architecture

```
OUTBOX_EVENTS_NEW (1) ──→ (N) EVENT_SUBSCRIPTIONS_NEW (N) ──→ (1) EVENT_METRICS_NEW
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
EVENTS_NEW                   EVENT_PROCESSING_LOGS_NEW     EVENT_RETRY_QUEUE_NEW
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
SAGA_INSTANCES_NEW           SAGA_STEPS_NEW                SAGA_COMPENSATIONS_NEW
```

### Computer Vision Integration

```
ZEROQUE_RAILS_NEW (1) ──→ (N) PROVIDER_MAPPINGS_NEW (N) ──→ (1) CV_UNKNOWN_ITEM_REVIEWS_NEW
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
CV_CONFIGURATIONS_NEW        CV_PROVIDER_SETTINGS_NEW     CV_REVIEW_RESOLUTIONS_NEW
    │                            │                            │
    │                            │                            │
    ▼                            ▼                            ▼
CV_ORDER_MAPPINGS_NEW        CV_ITEM_MAPPINGS_NEW         CV_DISPUTE_RESOLUTIONS_NEW
```

### Payment Processing

```
PAYMENT_TRANSACTIONS_NEW (1) ──→ (N) PAYMENT_REFUNDS_NEW (N) ──→ (1) PAYMENT_ADJUSTMENTS_NEW
    │                                │                            │
    │                                │                            │
    ▼                                ▼                            ▼
CUSTOMERS_NEW                      PAYMENT_METHODS_NEW           PAYMENT_WEBHOOKS_NEW
    │                                │                            │
    │                                │                            │
    ▼                                ▼                            ▼
PAYMENT_INTENTS_NEW               PAYMENT_CONFIRMATIONS_NEW     PAYMENT_FAILURES_NEW
```

### Notification System

```
NOTIFICATION_DELIVERIES_NEW (1) ──→ (N) NOTIFICATION_TEMPLATES_NEW (N) ──→ (1) NOTIFICATION_PROVIDERS_NEW
    │                                    │                                    │
    │                                    │                                    │
    ▼                                    ▼                                    ▼
NOTIFICATION_RECIPIENTS_NEW           NOTIFICATION_CHANNELS_NEW           NOTIFICATION_LOGS_NEW
    │                                    │                                    │
    │                                    │                                    │
    ▼                                    ▼                                    ▼
NOTIFICATION_SCHEDULES_NEW             NOTIFICATION_PREFERENCES_NEW        NOTIFICATION_METRICS_NEW
```

### Entry & Access Control

```
ENTRY_CODES_NEW (1) ──→ (N) ENTRY_CODE_USAGE_NEW (N) ──→ (1) ENTRY_ACCESS_LOGS_NEW
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
ENTRY_PROVIDERS_NEW         ENTRY_VALIDATIONS_NEW        ENTRY_GRANTS_NEW
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
ENTRY_CONFIGURATIONS_NEW     ENTRY_RATE_LIMITS_NEW        ENTRY_AUDIT_LOGS_NEW
```

### Reports & Analytics

```
REPORT_JOBS_NEW (1) ──→ (N) REPORT_GENERATIONS_NEW (N) ──→ (1) REPORT_CACHES_NEW
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
REPORT_TEMPLATES_NEW         REPORT_SCHEDULES_NEW         REPORT_EXPORTS_NEW
    │                        │                            │
    │                        │                            │
    ▼                        ▼                            ▼
REPORT_METRICS_NEW           REPORT_PERFORMANCE_NEW       REPORT_ACCESS_LOGS_NEW
```

### Observability & Monitoring

```
SYSTEM_METRICS_NEW (1) ──→ (N) SERVICE_HEALTH_CHECKS_NEW (N) ──→ (1) ALERT_RULES_NEW
    │                            │                                │
    │                            │                                │
    ▼                            ▼                                ▼
PERFORMANCE_METRICS_NEW         HEALTH_CHECK_RESULTS_NEW         ALERT_NOTIFICATIONS_NEW
    │                            │                                │
    │                            │                                │
    ▼                            ▼                                ▼
RESOURCE_USAGE_NEW              SERVICE_DEPENDENCIES_NEW         ALERT_ESCALATIONS_NEW
```

## Key V4.1 Architecture Features

### Multi-Tenancy & Security

- **Complete Tenant Isolation**: All tables include `tenant_id` for complete data isolation
- **Row-Level Security (RLS)**: Automatic tenant-based access control with enhanced policies
- **Tenant Hierarchies**: Parent-child tenant relationships via `tenant_links_new`
- **Enhanced Authentication**: JWT-based authentication with role-based access control
- **Audit Logging**: Comprehensive audit trails for all operations

### Event-Driven Microservices

- **Event Sourcing**: Complete audit trail via `audit_logs_new`
- **Outbox Pattern**: Reliable event publishing via `outbox_events_new`
- **Saga Pattern**: Distributed transaction management with compensation
- **Circuit Breaker**: Fault tolerance and resilience patterns
- **Service Discovery**: Dynamic service registration and health monitoring

### Advanced Marketplace Model

- **Vendor Management**: Complete vendor onboarding, settlements, and dispute resolution
- **Product Catalog**: Master products with variants and vendor-specific offers
- **Assortment Management**: Store-specific product assortments with segmentation
- **Customer Segmentation**: Targeted pricing and promotions
- **Multi-Provider Support**: Dynamic provider configuration via `zeroque_rails_new`

### Enhanced Pricing Engine

- **Dynamic Pricebooks**: Hierarchical pricing with real-time updates
- **Complex Rules Engine**: Advanced pricing rules with conditions and hooks
- **Promotional Pricing**: Time-based promotional pricing with validation
- **Multi-Currency**: Exchange rate support with real-time conversion
- **Price Resolution**: Real-time price calculation with caching

### Order Management & Fulfillment

- **Sub-Orders**: Vendor-specific order splitting with commission tracking
- **Vendor Splits**: Automated settlement processing and dispute resolution
- **Returns & Refunds**: Complete return management with approval workflows
- **Inventory Integration**: Real-time inventory tracking with reservations
- **Computer Vision**: AI-powered checkout and inventory management

### Financial Management

- **Double-Entry Ledger**: Complete accounting system with accounts and balances
- **Settlement Processing**: Automated vendor settlements with batch processing
- **Budget Management**: Cost center and budget tracking with approval workflows
- **Payment Processing**: Multi-provider payment processing with webhooks
- **Financial Reporting**: Comprehensive financial analytics and reporting

### Usage & Analytics

- **Real-Time Metering**: Usage tracking with real-time aggregation
- **Usage Analytics**: Comprehensive usage reports and insights
- **Performance Monitoring**: System performance metrics and health monitoring
- **Business Intelligence**: Advanced reporting with caching and scheduling
- **Predictive Analytics**: Usage forecasting and capacity planning

### Computer Vision Integration

- **Multi-Provider Support**: Dynamic CV provider configuration
- **Item Recognition**: AI-powered product recognition and mapping
- **Dispute Resolution**: Automated review and resolution of unknown items
- **Provider Mapping**: Dynamic mapping between internal and external systems
- **Configuration Management**: Runtime configuration updates via `zeroque_rails_new`

### Notification System

- **Multi-Channel Support**: Email, SMS, push notifications, and webhooks
- **Template Management**: Dynamic template rendering with personalization
- **Provider Abstraction**: Support for Twilio, SendGrid, and custom providers
- **Delivery Tracking**: Complete delivery status tracking and retry logic
- **Scheduling**: Advanced notification scheduling and batching

### Entry & Access Control

- **Dynamic Entry Codes**: QR code generation and validation
- **Provider Integration**: Integration with external access control systems
- **Rate Limiting**: Advanced rate limiting and access control
- **Audit Logging**: Complete access audit trails
- **Temporary Grants**: Dynamic access grant management

## Database Features

### Performance Optimizations

- **Partitioning**: Advanced partitioning for high-volume tables
- **Indexing**: Comprehensive indexes for all foreign keys and search fields
- **Caching**: Redis-based caching with TTL and invalidation
- **Connection Pooling**: Optimized database connection management
- **Query Optimization**: Materialized views and query optimization

### Data Integrity & Consistency

- **ACID Compliance**: Full ACID compliance with transaction management
- **Constraints**: Enhanced CHECK constraints for data validation
- **Foreign Keys**: Complete referential integrity with cascade options
- **Unique Constraints**: Prevent duplicate data with composite keys
- **Exclusion Constraints**: Prevent overlapping data ranges

### Security & Compliance

- **RLS Policies**: Enhanced tenant-based access control
- **Encryption**: Sensitive data encryption at rest and in transit
- **Audit Logging**: Complete change tracking with user attribution
- **Access Grants**: Fine-grained permission system with inheritance
- **Data Retention**: Automated data lifecycle management

### Scalability & Reliability

- **Horizontal Scaling**: Support for read replicas and sharding
- **Event Processing**: Asynchronous event processing with retry logic
- **Circuit Breakers**: Fault tolerance and graceful degradation
- **Health Monitoring**: Comprehensive health checks and monitoring
- **Disaster Recovery**: Automated backup and recovery procedures

### Monitoring & Observability

- **Metrics Collection**: Comprehensive metrics collection and aggregation
- **Distributed Tracing**: End-to-end request tracing across services
- **Log Aggregation**: Centralized logging with structured data
- **Alerting**: Proactive alerting with escalation policies
- **Performance Insights**: Real-time performance analysis and recommendations
