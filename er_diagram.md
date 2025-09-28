# ZeroQue Database ER Diagram

## Core Entity Relationships

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
    │
    │
    ▼
COST_CENTRE_LINKS
```

## Product & Pricing Relationships

```
PRODUCTS (1) ──→ (N) PRICES
    │
    │
    ▼
STORE_PRODUCTS (1) ──→ (N) PRICE_RULES
    │                      │
    │                      │
    ▼                      ▼
INVENTORY              PRICE_RULE_CONDITIONS
    │
    │
    ▼
INVENTORY_MOVEMENTS
```

## Order & Payment Relationships

```
ORDERS (1) ──→ (N) ORDER_ITEMS
    │
    │
    ▼
LEDGER_ENTRIES
    │
    │
    ▼
TRADE_INVOICES
```

## Subscription System

```
SUBSCRIPTION_PLANS (1) ──→ (N) PLAN_FEATURES (N) ──→ (1) FEATURES
    │
    │
    ▼
SITE_SUBSCRIPTIONS (1) ──→ (1) SITE_BILLING_ACCOUNTS
    │
    │
    ▼
SUBSCRIPTION_USAGE
```

## RBAC System

```
PERMISSIONS (1) ──→ (N) ROLE_PERMISSIONS (N) ──→ (1) ROLES
    │
    │
    ▼
TENANT_LINKS (Parent-Child relationships)
```

## Enhanced Webhook System

```
WEBHOOK_MESSAGES
    │
    │
    ▼
PRODUCT_NORMALIZATION_CACHE
    │
    │
    ▼
PRICE_HOOKS
```

## Key Tables Summary

### Core Tables (10)

- tenants, sites, stores, users, roles, memberships
- cost_centres, budgets, products, prices

### Pricing Engine (6)

- store_products, price_rules, price_rule_conditions
- promotions, promotion_conditions, calculated_prices

### Order Processing (4)

- orders, order_items, ledger_entries, trade_invoices

### Subscription System (5)

- subscription_plans, features, plan_features
- site_subscriptions, site_billing_accounts, subscription_usage

### RBAC (3)

- permissions, role_permissions, tenant_links

### Enhanced Webhooks (3)

- webhook_messages, product_normalization_cache, price_hooks

### Supporting Tables (8)

- inventory, inventory_movements, stripe_customers, stripe_charges
- trade_accounts, usage_events, notifications, provider_mappings

**Total: 39 Tables**
