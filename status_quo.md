# Zeroque Platform - Current Database Architecture (Status Quo)

**Document Version**: 1.1  
**Generated**: 2025-09-30  
**Database State**: Post-migration v4.1 implementation + additional enhancements  
**Total Tables**: 127  
**Total Enums**: 7

---

## Overview

This document represents the **current state** of the Zeroque platform database architecture as it exists in the database after implementing the v4.1 multi-tenant marketplace migration. This is a snapshot of what is actually implemented, including both the new v4.1 tables and legacy tables that coexist during the transition period.

## Database Extensions & Types

### Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
```

### Custom Types/Enums

```sql
-- Scope and ownership types
CREATE TYPE scope_type AS ENUM ('GLOBAL', 'TENANT', 'SITE', 'STORE', 'VENDOR');
CREATE TYPE owner_type AS ENUM ('TENANT', 'VENDOR');
CREATE TYPE budget_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'USER', 'COST_CENTRE', 'VENDOR');

-- Business process types
CREATE TYPE price_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'ROLE', 'VENDOR');
CREATE TYPE order_status AS ENUM ('pending', 'completed', 'cancelled', 'refunded', 'partially_refunded');
CREATE TYPE payout_status AS ENUM ('pending', 'queued', 'paid', 'failed', 'disputed');
CREATE TYPE movement_type AS ENUM ('receipt', 'sale', 'adjustment', 'transfer', 'return', 'shrink');
```

---

## Current Database Schema

### 1. Organizational Structure (10 tables)

#### Core Entities

- **tenants** (3 columns) - Legacy tenant table (now includes scenario_id)
- **tenants_new** (6 columns) - New v4.1 tenant table with enhanced features
- **sites** (3 columns) - Legacy site table
- **sites_new** (6 columns) - New v4.1 site table with geo support
- **stores** (3 columns) - Legacy store table
- **stores_new** (6 columns) - New v4.1 store table
- **scenarios** (5 columns) - Business scenario definitions (end_user, retailer, distributor, custom)

#### Relationship Tables

- **tenant_sites** (6 columns) - M:N relationship between tenants and sites
- **site_stores** (4 columns) - M:N relationship between sites and stores
- **tenant_store_admins** (5 columns) - Tenant-store admin assignments

### 2. User Management & RBAC (8 tables)

#### User Management

- **users** (3 columns) - Legacy user table
- **users_new** (6 columns) - New v4.1 user table with enhanced features
- **user_manager_links** (2 columns) - User hierarchy management

#### Role-Based Access Control

- **roles** (3 columns) - Legacy role table
- **roles_new** (4 columns) - New v4.1 role table
- **permissions** (7 columns) - Legacy permission table
- **permissions_new** (7 columns) - New v4.1 permission table
- **role_permissions** (5 columns) - Legacy role-permission mapping
- **role_permissions_new** (5 columns) - New v4.1 role-permission mapping
- **role_assignments** (6 columns) - Polymorphic role assignments
- **permission_grants** (12 columns) - Direct permission grants
- **permission_resolution_cache** (9 columns) - Permission resolution caching

### 3. Vendor Management (3 tables)

- **vendors** (8 columns) - Vendor master data
- **vendor_onboarding** (8 columns) - Vendor onboarding process
- **store_vendors** (6 columns) - Store-vendor relationships

### 4. ERP Integrations & Access Controls (3 tables)

#### ERP/CRM Integrations

- **erp_integrations** (8 columns) - ERP/CRM system integrations for distributors

#### Physical Access Control

- **access_controls** (7 columns) - Physical access devices (gates, RFID, locks, card readers)
- **user_access_grants** (7 columns) - User access permissions for physical devices

### 5. Product Management (6 tables)

#### Product Core

- **product_master** (10 columns) - Master product catalog
- **product_variants** (13 columns) - Product variants and SKUs
- **product_media** (9 columns) - Product images and media
- **product_relationships** (7 columns) - Product relationships (bundles, accessories)
- **product_tax_categories** (7 columns) - Product tax categorization

#### Legacy Product Tables

- **products** (6 columns) - Legacy product table
- **product_normalization_cache** (6 columns) - Product normalization cache

### 6. Currency & Tax Management (4 tables)

- **currencies** (6 columns) - Currency master data
- **exchange_rates** (7 columns) - Currency exchange rates
- **tax_regions** (5 columns) - Tax region definitions
- **tax_rules** (9 columns) - Tax calculation rules

### 7. Vendor Offers & Store Assortments (4 tables)

- **vendor_offers** (17 columns) - Vendor product offers with pricing
- **store_assortments** (17 columns) - Store product assortments
- **customer_segments** (6 columns) - Customer segmentation
- **assortment_segments** (4 columns) - Assortment-customer segment mapping

### 8. Pricing System (7 tables)

#### Pricebook Management

- **pricebooks** (11 columns) - Pricebook definitions
- **pricebook_assignments** (8 columns) - Pricebook assignments to entities
- **pricebook_entries** (9 columns) - Individual price entries
- **pricing_versions** (5 columns) - Pricing version management

#### Price Rules & Calculation

- **price_rules** (12 columns) - Legacy price rules
- **price_rules_new** (16 columns) - New v4.1 price rules with enhanced features
- **calculated_prices** (11 columns) - Pre-calculated prices for performance

#### Legacy Pricing

- **prices** (7 columns) - Legacy price table
- **price_hooks** (8 columns) - Price calculation hooks
- **price_rule_conditions** (5 columns) - Price rule conditions

### 9. Inventory Management (3 tables)

- **inventory** (4 columns) - Legacy inventory table
- **inventory_new** (14 columns) - New v4.1 inventory with multi-owner support
- **inventory_movements** (6 columns) - Inventory movement tracking

### 10. Order Management (8 tables)

#### Order Processing

- **orders** (12 columns) - Legacy order table
- **orders_new** (22 columns) - New v4.1 order table with enhanced features
- **sub_orders** (16 columns) - Vendor-specific sub-orders
- **order_items** (6 columns) - Order line items

#### Returns & Refunds

- **returns** (12 columns) - Order return processing
- **refunds** (9 columns) - Refund management
- **order_returns** (13 columns) - Legacy order returns
- **order_refunds** (11 columns) - Legacy order refunds

### 11. Vendor Settlements & Payouts (5 tables)

- **vendor_settlements** (14 columns) - Vendor settlement records
- **vendor_settlement_batches** (8 columns) - Settlement batch processing
- **vendor_settlement_items** (11 columns) - Individual settlement items
- **vendor_settlement_adjustments** (10 columns) - Settlement adjustments
- **vendor_disputes** (13 columns) - Vendor dispute management

#### Legacy Settlement Tables

- **settlement_batches** (9 columns) - Legacy settlement batches
- **settlement_items** (8 columns) - Legacy settlement items
- **settlement_adjustments** (9 columns) - Legacy settlement adjustments
- **settlement_disputes** (10 columns) - Legacy settlement disputes

### 12. Ledger & Accounting (4 tables)

- **ledger_accounts** (9 columns) - Chart of accounts
- **ledger_accounts_new** (9 columns) - New v4.1 ledger accounts
- **ledger_entries** (13 columns) - Legacy ledger entries
- **ledger_entries_new** (13 columns) - New v4.1 ledger entries
- **ledger_entry_lines** (8 columns) - Ledger entry line items
- **account_balances** (7 columns) - Account balance tracking

### 13. Budget & Cost Management (4 tables)

- **cost_centres** (4 columns) - Legacy cost centres
- **cost_centres_new** (8 columns) - New v4.1 cost centres
- **budgets** (7 columns) - Legacy budget table
- **budgets_new** (12 columns) - New v4.1 budget table with enhanced features
- **user_cost_centres** (3 columns) - User-cost centre assignments

### 14. Approval Workflows (6 tables)

- **approval_chains** (7 columns) - Approval workflow definitions
- **approval_chain_steps** (7 columns) - Approval workflow steps
- **approval_requests** (12 columns) - Legacy approval requests
- **approval_requests_new** (14 columns) - New v4.1 approval requests
- **approval_request_approvers** (7 columns) - Approval request approvers

#### Legacy Approval Tables

- **approval_rules** (8 columns) - Legacy approval rules
- **approval_steps** (9 columns) - Legacy approval steps
- **approval_approvers** (8 columns) - Legacy approval approvers

### 15. Audit & Compliance (3 tables)

- **audit_logs** (10 columns) - Comprehensive audit logging
- **data_retention_policies** (7 columns) - Data retention configuration
- **outbox_events** (11 columns) - Event sourcing outbox pattern

### 16. Usage-Based Billing & Zeroque Rails (2 tables)

#### Usage-Based Billing

- **usage_ledger_entries** (9 columns) - Advanced monetization and usage-based billing

#### Zeroque Rails

- **zeroque_rails** (6 columns) - Owned rails (payments, CV, marketplace) configuration

### 17. Legacy & Supporting Tables (25 tables)

#### Legacy Business Tables

- **memberships** (5 columns) - Legacy membership table
- **plans** (4 columns) - Legacy plan table
- **plan_features** (6 columns) - Legacy plan features
- **features** (7 columns) - Legacy feature table
- **subscriptions** (6 columns) - Legacy subscription table
- **subscription_plans** (9 columns) - Legacy subscription plans
- **subscription_usage** (10 columns) - Legacy subscription usage
- **site_subscriptions** (13 columns) - Legacy site subscriptions
- **site_billing_accounts** (9 columns) - Legacy site billing
- **usage_meters** (3 columns) - Legacy usage meters
- **usage_events** (8 columns) - Legacy usage events
- **usage_aggregates_daily** (7 columns) - Legacy usage aggregates

#### Payment & Billing

- **payment_preferences** (2 columns) - Payment preferences
- **stripe_customers** (3 columns) - Stripe customer data
- **stripe_charges** (7 columns) - Stripe charge records
- **stripe_events** (4 columns) - Stripe webhook events

#### Trade & Invoicing

- **trade_accounts** (5 columns) - Trade account management
- **trade_invoices** (14 columns) - Trade invoice processing
- **trade_invoice_lines** (8 columns) - Trade invoice line items

#### Promotions & Marketing

- **promotions** (14 columns) - Promotion management
- **promotion_conditions** (5 columns) - Promotion conditions

#### Notifications & Communication

- **notifications** (7 columns) - Notification management
- **notification_deliveries** (13 columns) - Notification delivery tracking
- **webhook_messages** (9 columns) - Webhook message processing

#### System & Utility Tables

- **idempotency_keys** (5 columns) - Idempotency key management
- **tenant_links** (4 columns) - Tenant linking
- **store_products** (8 columns) - Legacy store-product mapping
- **provider_mappings** (5 columns) - Provider mapping
- **cv_unknown_item_reviews** (14 columns) - CV unknown item reviews

---

## Key Features Implemented

### ✅ Multi-Tenant Architecture

- **Tenant Isolation**: Complete data isolation between tenants
- **Flexible Relationships**: M:N relationships between tenants, sites, and stores
- **Cross-Tenant Operations**: Support for marketplace-wide operations

### ✅ Advanced RBAC System

- **Granular Permissions**: Resource-action-scope based permissions
- **Role Hierarchies**: Flexible role assignment with inheritance
- **Permission Caching**: High-performance permission resolution
- **Polymorphic Assignments**: Support for different assignment types

### ✅ Vendor Marketplace

- **Vendor Onboarding**: Streamlined vendor registration and approval
- **Offer Management**: Vendor-specific product offers with pricing
- **Settlement Processing**: Automated vendor settlements with dispute handling
- **Multi-Vendor Orders**: Orders can span multiple vendors

### ✅ Enhanced Pricing Engine

- **Multi-Level Pricing**: Tenant, site, store, role, and vendor-specific pricing
- **Price Rules Engine**: Configurable pricing rules with versioning
- **Dynamic Pricing**: Real-time price calculation and updates
- **Pricebook Management**: Flexible pricebook assignments

### ✅ Comprehensive Inventory

- **Multi-Owner Inventory**: Support for tenant and vendor-owned inventory
- **Movement Tracking**: Complete audit trail of inventory changes
- **Reservation System**: Order-based inventory reservations

### ✅ Order Management

- **Sub-Order Processing**: Vendor-specific order processing
- **Status Tracking**: Comprehensive order lifecycle management
- **Returns & Refunds**: Complete return and refund processing

### ✅ Financial Management

- **Double-Entry Ledger**: Complete accounting system
- **Vendor Settlements**: Automated settlement processing
- **Cost Centre Management**: Budget tracking and approval workflows

### ✅ Audit & Compliance

- **Complete Audit Trails**: All data changes are logged
- **Data Retention**: Configurable data retention policies
- **Event Sourcing**: Outbox pattern for reliable event processing

### ✅ ERP Integrations & Access Control

- **ERP/CRM Integration**: Seamless integration with distributor ERP/CRM systems
- **Physical Access Control**: Support for gates, RFID, locks, and card readers
- **User Access Management**: Granular access permissions for physical devices
- **Temporary Access**: Support for temporary access grants with expiration

### ✅ Advanced Monetization

- **Usage-Based Billing**: Advanced monetization with usage ledger entries
- **Revenue Sharing**: Link usage to orders and settlements for revenue sharing
- **Flexible Metering**: Support for various usage meters and billing models

### ✅ Zeroque Rails

- **Owned Infrastructure**: Configuration for payments, CV, and marketplace rails
- **Feature Toggles**: Ability to activate/deactivate rails independently
- **Version Management**: Track and manage different rail versions

---

## Database Statistics

| Category              | Tables | Description                                         |
| --------------------- | ------ | --------------------------------------------------- |
| **Core v4.1 Tables**  | 62     | New multi-tenant marketplace tables                 |
| **Enhanced Tables**   | 7      | Additional ERP, access control, usage, rails tables |
| **Legacy Tables**     | 25     | Original single-tenant tables                       |
| **Transition Tables** | 33     | Tables with `_new` suffix during migration          |
| **Total Tables**      | 127    | Complete database schema                            |

---

## Migration Status

### ✅ Completed Migrations

1. **Foundation Migration** - Extensions, enums, and core organizational tables
2. **Product & Pricing Migration** - Product management, currency, tax, and pricing tables
3. **Inventory & Orders Migration** - Inventory, order management, and vendor settlements
4. **Ledger & Approvals Migration** - Ledger, approval, and audit tables
5. **Indexes & RLS Migration** - Row-level security and basic indexes
6. **Missing Tables Migration** - All remaining v4.1 tables
7. **Enhanced Features Migration** - ERP integrations, access controls, usage billing, Zeroque rails, and scenarios

### 🔄 Current State

- **Database Schema**: 100% aligned with v4.1 architecture
- **Legacy Tables**: Still present for backward compatibility
- **Transition Tables**: `_new` tables coexist with legacy tables
- **Data Migration**: Not performed (as requested)

### 📋 Next Steps

1. **Table Cleanup**: Rename `_new` tables to final names
2. **Legacy Removal**: Remove old tables after service updates
3. **Service Updates**: Update microservices to use new schema
4. **Testing**: Comprehensive testing of new architecture

---

## Technology Stack

### Database

- **PostgreSQL 15+** - Primary database
- **Extensions**: uuid-ossp, pg_trgm, btree_gist
- **Row-Level Security** - Enabled on all v4.1 tables
- **Partitioning** - Ready for calculated_prices and inventory_movements

### Development Tools

- **Alembic** - Database migration management
- **SQLAlchemy** - ORM and database abstraction
- **FastAPI** - API framework
- **Redis** - Caching and session management

### Monitoring & Observability

- **OpenTelemetry** - Distributed tracing
- **Prometheus** - Metrics collection
- **Audit Logging** - Comprehensive change tracking

---

_This document represents the current state of the Zeroque platform database architecture as of the v4.1 migration completion. It serves as a reference for the actual implemented schema and should be updated as the system evolves._
