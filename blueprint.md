ZeroQue Pricing & Entitlement Implementation Blueprint
Purpose
To define the architecture Sourabh should begin building to support:
Multi-dimensional entitlements (Tenant Type × Tier × Role)
Modular feature control (via feature flags)
Flexible, scalable pricing that aligns with usage and value

1. Architectural Overview
   ZeroQue’s commercial model must be native to the platform — meaning the entitlement system drives access, usage, and billing automatically.
   Core Stack Components to Build:
   Service Purpose
   Entitlement Service Stores which features each tenant, tier, and role can access.
   Pricing Config Service Maps cost rules (per store, per user, per API call, etc.) to entitlements.
   Usage Metering Service Tracks feature usage events (API calls, orders, storage, transactions).
   Billing Service Aggregates base subscription + usage + add-ons; pushes invoices to Stripe.
   Feature Flag API Returns TRUE/FALSE to other services (e.g., “canAccessAnalytics”).
   All 5 services are modular microservices under the “Commerce Layer” — a layer between business logic and infrastructure.
2. Core Entities
   Tenant
   Has a tenantType (End-User / Retailer / Distributor)
   Has an entitlementPlan (Core / Pro / Enterprise)
   Has multiple users with defined roles
   User
   Has a role (Admin / Manager / Shopper)
   Inherits entitlements based on Tenant Type + Tier + Role
   Feature
   A modular capability cluster (e.g. “Reporting”, “Payments”, “Budget Controls”)
   Features have associated usage metrics (e.g., reports generated, orders placed)
   PricingRule
   Defines cost model for each feature
   e.g. baseCost, usageCost, overageThreshold
3. Technical Flow (Simplified)
   [User Action]
   ↓
   Entitlement Service → checks if feature allowed
   ↓Usage Metering → logs usage event (API call, transaction, etc.)
   ↓
   Pricing Config → retrieves rate based on tenant & feature
   ↓
   Billing Service → aggregates usage at end of billing cycle ↓
   Stripe API → generates invoice
   ↓Admin Portal → displays usage + charges per tenant
   This creates real-time usage visibility and a clean revenue data trail.
4. Immediate Build Priorities for Sourabh
   Step 1 — Entitlement Service
   Design schema: TenantType, Tier, Role, Feature, AccessMatrix
   Define a JSON-driven entitlement matrix for easy updates (no code changes)
   Example structure:
   {"retailer": {"core": { "reporting": true, "analytics": false },"pro": { "reporting": true, "analytics": true }} }
   Output: API to query any tenant/role → returns allowed features
   Step 2 — Pricing Config Service
   Create a pricing table (or JSON config) mapping feature → cost model
   {"reporting.basic": { "baseCost": 0, "usageCost": 0 },"analytics.predictive": { "baseCost": 200, "usageCost": 0.02 } }
   Allow costs to vary by tier and tenant type
   Build lightweight admin UI for internal config management
   Step 3 — Usage Metering Service
   Collect and aggregate usage data:
   Transactions
   API calls
   Camera events (AiFi)
   Storage / data usage
   Use Azure Service Bus or Event Hub for scalable event logging
   Persist into Postgres or Cosmos DB (aligned with your existing architecture)
   Step 4 — Billing Service
   Pulls entitlement + usage data
   Calculates:
   Base fee (subscription)
   Usage overages
   Add-ons
   Integrates with Stripe Billing API for:
   Subscription management
   Add-on billing
   Proration logic
   Stores results in internal tenant_billing_ledger for analytics
   Step 5 — Feature Flag API
   Provides a unified API call for any service to query feature access:
   Supports caching (Redis) to reduce latency.
5. Data Models (Initial Draft)
   Table Key Fields Description
   tenants id, name, type, tier, billing_id Stores tenant profile
   features id, name, cluster, default_cost Master feature registry
   entitlements tenant_id, feature_id, access, limit Access rules per tenant
   usage_logs tenant_id, feature_id, metric, value Tracks consumption
   pricing_rules feature_id, tier, cost_model Defines cost parameters
   billing_ledger tenant_id, period, amount, breakdown Stores calculated invoices
6. Output Requirements
   Admin Portal Views:
   Tenant Entitlement Matrix
   Usage by Feature / Cost Breakdown
   Active Subscriptions & Invoices
   APIs for Integration:
   /entitlements
   /pricing
   /usage
   /billing
   /feature-flags
7. Governance & Extensibility
   Future-Proof Schema: Entitlements should allow new clusters (AI, biometric, IoT, etc.) without refactoring.
   Event-Driven Billing: Everything logged as event → billed asynchronously.
   Auditable Ledger: Immutable transaction history (potential to move to blockchain later).
   Multi-Currency Support: GBP first → structure for multi-currency later.
   GET /feature-flags?tenantId=XYZ&feature=analytics.predictive
   → { "enabled": true, "usageLimit": 500 }
