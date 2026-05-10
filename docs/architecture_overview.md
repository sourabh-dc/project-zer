# ZeroQue Platform — Complete Architecture Overview

> **Generated**: 2026-03-15  
> **Monorepo**: `project-zer`  
> **Runtime**: Python 3.11+ · FastAPI · PostgreSQL 16 · Neo4j · Azure Service Bus · Azure OpenAI

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Microservices Summary](#2-microservices-summary)
3. [Provisioning Service (Port 8001)](#3-provisioning-service-port-8001)
4. [Policy Service (Port 8004)](#4-policy-service-port-8004)
5. [Graph Service (Port 8005)](#5-graph-service-port-8005)
6. [Vector Service (Port 8006)](#6-vector-service-port-8006)
7. [Intelligence Service (Port 8007)](#7-intelligence-service-port-8007)
8. [Data Flow — End-to-End Request Lifecycle](#8-data-flow--end-to-end-request-lifecycle)
9. [Event-Driven Architecture (Outbox Pattern)](#9-event-driven-architecture-outbox-pattern)
10. [The Two-Gate Security Model](#10-the-two-gate-security-model)
11. [Approved Universe — Product Governance](#11-approved-universe--product-governance)
12. [Budgetary Control](#12-budgetary-control)
13. [Shared Infrastructure](#13-shared-infrastructure)
14. [Deployment Topology](#14-deployment-topology)
15. [Key Design Decisions](#15-key-design-decisions)

---

## 1. High-Level Architecture

```
                         ┌──────────────┐
                         │   Frontend   │
                         │  (React/Web) │
                         └──────┬───────┘
                                │ HTTPS
                ┌───────────────┼───────────────────┐
                │               │                   │
                ▼               ▼                   ▼
┌──────────────────────┐ ┌────────────────┐ ┌────────────────────┐
│ Provisioning Service │ │ Policy Service │ │ Intelligence       │
│      (8001)          │─│    (8004)      │ │   Service (8007)   │
│ Main API gateway     │ │ Evaluate rules │ │ NL query interface │
└──────────┬───────────┘ └────────────────┘ └─────────┬──────────┘
           │                                          │
           │ outbox_events table                      │ HTTP calls
           │ (Transactional Outbox)                   │
           ▼                                          ▼
┌────────────────────┐                   ┌────────────────────┐
│   Graph Service    │                   │   Vector Service   │
│     (8005)         │◄──────────────────│     (8006)         │
│  Neo4j projection  │   approved IDs   │  pgvector search   │
└────────┬───────────┘                   └──────────┬─────────┘
         │                                          │
         ▼                                          ▼
   ┌──────────┐    ┌──────────────┐    ┌────────────────────┐
   │  Neo4j   │    │  PostgreSQL  │    │  PostgreSQL        │
   │  (graph) │    │  (shared DB) │    │  (pgvector ext.)   │
   └──────────┘    └──────────────┘    └────────────────────┘
                          ▲
                          │
                   ┌──────┴──────┐
                   │ Azure       │
                   │ Service Bus │
                   │  (queue)    │
                   └─────────────┘
```

**All five services** share a single PostgreSQL database (each owning its own set of tables). Neo4j and pgvector are secondary data stores that receive **projections** from PostgreSQL via the Transactional Outbox pattern.

---

## 2. Microservices Summary

| Service | Port | Role | Depends On |
|---------|------|------|------------|
| **Provisioning Service** | 8001 | Main API — all CRUD, auth, payments, budgets, approvals | Policy Service, Azure Service Bus |
| **Policy Service** | 8004 | Governance rules evaluation engine | PostgreSQL (shared DB) |
| **Graph Service** | 8005 | Neo4j projection of governance topology; serves Approved Universe queries | PostgreSQL (outbox polling), Neo4j |
| **Vector Service** | 8006 | Product semantic search with pgvector embeddings | PostgreSQL (outbox polling), Graph Service, Azure OpenAI |
| **Intelligence Service** | 8007 | Natural language → Cypher/SQL/Vector query routing via LLM | Graph Service, Vector Service, PostgreSQL, Azure OpenAI |

---

## 3. Provisioning Service (Port 8001)

### Purpose
The **entry point** for all platform operations. Every user-facing API request starts here. It handles CRUD for all entities, authentication, payments, budgets, and purchase requests.

### Route Modules

| File | Prefix | Responsibility |
|------|--------|----------------|
| `tenant_onboarding.py` | `/onboard` | Tenant signup, sign-in, subscription websocket check |
| `auth_routes.py` | `/auth` | Login, logout, refresh JWT, password reset, forgot-password, OTP |
| `provisioning_routes.py` | (root) | CRUD for sites, stores, users, vendors, cost centres, roles, org units, user-role and org-unit-user assignments, budget assignment/renewal |
| `catalog_routes.py` | `/catalog` | Categories, products, variants, store-products, bulk upload |
| `internal_routes.py` | `/internal` | Platform admin — plans, features, plan-features, global roles, permissions |
| `plan_routes.py` | `/plans` | Public plan listing with pricing |
| `subscriptions_routes.py` | `/subscriptions` | Renew, upgrade, downgrade, cancel subscriptions |
| `payments_routes.py` | `/payments` | Stripe checkout, billing portal, webhook |
| `approved_range_routes.py` | `/approved-ranges` | Approved range CRUD, org-unit mapping, product add/remove |
| `calendar_routes.py` | `/financial-calendars` | Financial calendars, years, periods |
| `budget_routes.py` | `/budgets` | Company budget caps, cost-centre versions, reallocation |
| `user_budget_routes.py` | `/user-budgets` | User-cost-centre assignments, per-user budget limits |
| `approval_policy_routes.py` | `/approval-policies` | Approval chain CRUD (multi-stage, threshold-based) |
| `purchase_request_routes.py` | `/purchase-requests` | Submit PR, decide approval tasks, issue PO |
| `budget_change_request_routes.py` | `/budget-change-requests` | Bring-forward, top-up, reallocation requests |

### Core Components

| File | Purpose |
|------|---------|
| `core/config.py` | Settings — DB URL, JWT config, Stripe keys, AiFi, Service Bus. Uses Azure Key Vault in non-local environments. |
| `core/db_config.py` | SQLAlchemy engine, `SessionLocal`, `get_db` FastAPI dependency |
| `core/user_auth.py` | JWT decode (`decode_jwt_with_settings`), RBAC check (`check_user_authorization`) — **Gate 1** |
| `core/policy_client.py` | HTTP client to Policy Service + `require_policy()` FastAPI dependency — **Gate 2** |
| `core/sb_client.py` | Azure Service Bus sender (singleton `MessagingClient`) |
| `core/approval_engine.py` | Approval workflow creation (multi-stage chains) |
| `core/budget_engine.py` | Budget calculations, spending validation |
| `core/entitlement_helpers.py` | Feature limit checks (`check_feature_limit`) and usage recording |
| `core/period_calculator.py` | Financial period date calculations |

### Async Workers

| File | Trigger | What It Does |
|------|---------|--------------|
| `core/helpers/outbox_worker.py` | Service Bus message `{outbox_id}` | Generic worker — routes to the correct handler based on `event_type` |
| `core/tasks/tenant_worker.py` | `tenant.signup` | Creates admin user, assigns `tenant_admin` role, generates password, sends welcome email |
| `core/tasks/user_worker.py` | `user.created` | Post-create processing (e.g., AiFi sync) |
| `core/tasks/product_worker.py` | `product.created`, `product.bulk_created` | Post-create processing |

### Models (`Models.py`)

The model file defines **all PostgreSQL tables** shared across the platform:

- **Multi-tenancy**: `Tenant`, `TenantSubscription`
- **Org structure**: `Site`, `SiteTenant`, `Store`, `OrgUnit`
- **Users**: `User`, `UserRole`, `Role`, `Permission`, `RolePermission`
- **Catalog**: `Category`, `Product`, `Variant`, `StoreProduct`, `Colour`, `Size`, `Fit`, `UosLabel`
- **Budgets**: `CostCentre`, `CostCentreBudget`, `UserCostCentre`, `CompanyBudgetCap`, `CostCentreBudgetVersion`, `UserBudgetLimit`, `BudgetTransaction`
- **Approvals**: `ApprovalPolicy`, `ApprovalStage`, `ApprovalChain`, `ApprovalChainStep`, `ApprovalWorkflow`, `ApprovalTask`
- **Procurement**: `PurchaseRequest`, `SpendingEvent`
- **Approved Ranges**: `ApprovedRange`, `ApprovedRangeOrgUnit`, `ApprovedRangeProduct`
- **Financial Calendar**: `FinancialCalendar`, `FinancialYear`, `FinancialPeriod`
- **Subscriptions**: `SubscriptionPlan`, `Feature`, `PlanFeature`, `SubscriptionPlanPricing`
- **Vendors**: `Vendor`, `VendorUser`
- **Budget Change**: `BudgetChangeRequest`
- **Events**: `OutboxEvent`, `AuditLog`

### Startup Sequence

```
1. Start Azure Service Bus connection (messaging_service.start())
2. Base.metadata.create_all()              — create/sync all DB tables
3. Migrate outbox_events                   — add aggregate_type, aggregate_id, rename event_data→payload
4. Load permissions.csv → permissions table
5. Load features.csv → features table
6. Load plan_features.xlsx → plan_features table
```

---

## 4. Policy Service (Port 8004)

### Purpose
The **governance and decisioning engine**. A standalone microservice that evaluates policies for every action. Has **zero code dependency** on provisioning_service — communicates only via the shared PostgreSQL database.

### How It Works

```
Provisioning Service                    Policy Service
       │                                      │
       │  POST /evaluate                      │
       │  {action, subject, resource,         │
       │   tenant_id}                         │
       ├─────────────────────────────────────►│
       │                                      │ 1. Enrich subject context (DB lookup)
       │                                      │ 2. Find applicable policies (by action pattern + tenant)
       │                                      │ 3. Evaluate rules (AST-safe expression parser)
       │                                      │ 4. Return decision
       │  {decision: allow|deny|              │
       │   require_approval,                  │
       │   reason, matched_policies,          │
       │   evaluation_ms}                     │
       │◄─────────────────────────────────────┤
       │                                      │ 5. Log decision to policy_decisions table
```

### Key Components

| File | Purpose |
|------|---------|
| `services/policy_master.py` | CRUD endpoints for policies, versions, rules, assignments, action types |
| `services/policy_evaluator.py` | `POST /evaluate` and `POST /evaluate/dry-run` — the core evaluation logic |
| `core/expression_parser.py` | AST-based safe expression evaluator (no `eval()`). Supports: comparisons, boolean logic, dot-access (`subject.budget_remaining > 0`), membership tests |
| `core/context_enricher.py` | Queries the shared DB to build a rich subject context: roles, permissions, budget remaining, subscription status, approved product IDs, org unit info |
| `core/cache.py` | In-memory TTL cache for user context and policy lookups |

### Policy Data Model

```
Policy (1) ──► (N) PolicyVersion (1) ──► (N) PolicyRule
   │
   └──► (N) PolicyAssignment  ← scopes WHERE/WHEN a policy applies
                                 (action_pattern, scope_type, valid_from/until)
```

- **Policy**: Named governance rule (e.g., `budget_guard`, `entitlement_limiter`)
- **PolicyVersion**: Immutable snapshot of rules. Only one version is "current" (`effective_until IS NULL`)
- **PolicyRule**: Individual condition + effect. Evaluated in `rule_order`
  - `condition_expression`: Safe Python-like syntax, e.g., `subject.budget_remaining < resource.amount_minor`
  - `effect`: `allow` | `deny` | `require_approval`
  - `denial_reason`: Human-readable message (supports `{variable}` interpolation)
- **PolicyAssignment**: Binds a policy to an action pattern (e.g., `order.create`, `cost_centre.*`, `*`), with scope (global/tenant/site/store/org_unit/user) and time window

### Evaluation Logic (Deny-First)

```
For each applicable policy (sorted by priority, lowest first):
    For each rule (sorted by rule_order):
        Evaluate condition_expression against {subject, resource} context
        If condition is TRUE:
            If effect == "deny"            → IMMEDIATELY return DENY
            If effect == "require_approval" → accumulate (return later if no deny)
            If effect == "allow"           → note, keep evaluating

If any require_approval accumulated  → return REQUIRE_APPROVAL
Otherwise                            → return ALLOW

Default (no policies match)          → return DENY (governance-first)
```

---

## 5. Graph Service (Port 8005)

### Purpose
Maintains a **Neo4j graph projection** of the governance topology. Consumes events from the `outbox_events` table (polling pattern) and creates/updates/deletes nodes and edges in Neo4j. Exposes REST query endpoints for other services.

### Graph Schema (Neo4j Nodes & Edges)

```
(:Tenant)─[:HAS_SITE]─►(:Site)─[:CONTAINS]─►(:Store)
    │                                           │
    ├─[:HAS_ORG_UNIT]─►(:OrgUnit)             │
    │                      │                    │
    │                      ├─[:GOVERNED_BY]─►(:ApprovedRange)─[:INCLUDES]─►(:Product)
    │                      │                                                  │
    │                      └─[:REPORTS_TO]─►(:OrgUnit)                       │
    │                                                                [:IN_CATEGORY]
    ├─[:HAS_COST_CENTRE]─►(:CostCentre)                                     │
    │                                                                        ▼
    ├─[:HAS_USER]─►(:User)─[:BELONGS_TO]─►(:OrgUnit)                 (:Category)
    │                  │
    │                  └─[:HAS_ROLE]─►(:Role)
    │
    └─[:HAS_VENDOR]─►(:Vendor)─[:SUPPLIES]─►(:Product)
```

### Outbox Consumer Flow

```
1. Poll outbox_events WHERE status='pending', batch of 50
2. Atomically claim: SET status='processing' (FOR UPDATE SKIP LOCKED)
3. Route event to handler by aggregate_type prefix:
   - "tenant"   → tenant_handler
   - "site"     → site_handler
   - "store"    → store_handler
   - "product"  → product_handler  (update/delete only — created via approved_range)
   - "category" → category_handler
   - "user"     → user_handler
   - "org_unit" → org_unit_handler
   - "vendor"   → vendor_handler
   - "role"     → role_handler
   - "cost_centre"    → cost_centre_handler
   - "approved_range" → approved_range_handler
   - "policy"         → policy_handler
4. On success: SET status='processed'
5. On failure: retry_count++, back to 'pending' (or 'dead_letter' after max_retries)
```

### REST Query Endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /graph/approved-products/{user_id}?tenant_id=` | List of product IDs the user can see/order (Approved Universe) |
| `GET /graph/approved-products/org-unit/{org_unit_id}?tenant_id=` | Product IDs approved for an org unit |
| `GET /graph/user-context/{user_id}?tenant_id=` | User's governance context (roles, org units, cost centres) |
| `GET /graph/user-hierarchy/{user_id}` | Org unit reporting chain |
| `GET /graph/store/{store_id}/products` | Product IDs stocked in a store |
| `GET /graph/product/{product_id}/stores` | Store IDs that carry a product |
| `GET /graph/tenant/{tenant_id}/topology` | Full tenant topology tree |

### Important Rule: Products in Graph
Products are **NOT** projected to Neo4j on creation. They enter the graph **only** when added to an Approved Range (via `approved_range_handler`). This ensures the graph only contains governed, curated products.

---

## 6. Vector Service (Port 8006)

### Purpose
Provides **governance-filtered semantic search** for products using pgvector embeddings. Consumes product events from the outbox, generates embeddings via Azure OpenAI, and stores them in a `product_embeddings` table.

### How It Works

```
1. Product created in Provisioning Service
2. OutboxEvent written to outbox_events (aggregate_type='product')
3. Graph Service processes the event first (status → 'processed')
4. Vector Service polls for processed product/category events
   that haven't been handled (tracked via vector_event_log table)
5. Generates text embedding from product display_name + description + SKU
6. Stores embedding in product_embeddings table (vector or JSONB column)
7. Records event_id in vector_event_log
```

### Dual-Mode Storage

| Mode | When | Column Type | Search |
|------|------|-------------|--------|
| **Native pgvector** | Extension available (production) | `vector(1536)` | PostgreSQL `<=>` cosine distance operator, IVFFlat index |
| **JSONB fallback** | Extension unavailable (local dev) | `JSONB` array | Cosine similarity computed in Python |

### Search Endpoint

```
POST /vector/search
{
  "query": "cleaning supplies",
  "tenant_id": "...",
  "user_id": "...",          ← optional, for governance filtering
  "top_k": 20,
  "skip_governance": false
}
```

**Search flow:**
1. Embed the query text using Azure OpenAI `text-embedding-3-small`
2. If `user_id` provided and `skip_governance=false`:
   - Call Graph Service `GET /graph/approved-products/{user_id}` to get the user's Approved Universe
3. Run cosine similarity search restricted to approved product IDs only
4. Return top-K results with similarity scores

This means a user **can only find products they are approved to see** — governance is enforced at the search layer.

---

## 7. Intelligence Service (Port 8007)

### Purpose
A **natural language query interface** for platform administrators. Accepts a question in plain English, classifies it, routes it to the correct data engine(s), executes the query, and returns a human-readable answer.

### Query Routing Architecture

```
Admin asks: "Which users in Mumbai spent more than 50k?"

                    ┌────────────────────────┐
                    │   Azure OpenAI (LLM)   │
                    │  Classifies + generates │
                    │  query plan             │
                    └────────┬───────────────┘
                             │
                             ▼
                    ┌────────────────────────┐
                    │    Query Router Agent   │
                    │                        │
                    │ Plan:                  │
                    │ Step 1 (graph):        │
                    │   MATCH users in Mumbai│
                    │ Step 2 (sql):          │
                    │   SELECT spending > 50k│
                    │   WHERE user_id IN ... │
                    └────────┬───────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         ┌─────────┐  ┌──────────┐  ┌──────────────┐
         │  Neo4j  │  │ Postgres │  │ Vector Svc   │
         │ (graph) │  │  (SQL)   │  │  (semantic)  │
         └─────────┘  └──────────┘  └──────────────┘
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌────────────────────────┐
                    │   LLM Summarization    │
                    │   "3 users in Mumbai   │
                    │    exceeded 50k..."    │
                    └────────────────────────┘
```

### Query Types

| Type | Engine | Example Questions |
|------|--------|-------------------|
| `graph` | Neo4j (Cypher) | "Show me the org hierarchy for tenant X", "Which vendors supply the most products?" |
| `sql` | PostgreSQL (SELECT only) | "What is the total budget spent across all cost centres?", "How many users are active?" |
| `vector` | Vector Service | "Find products similar to cleaning supplies" |
| `hybrid` | Multiple engines | "Which users in Mumbai spent more than 50k?" (graph for Mumbai users + SQL for spending) |

### Safety
- SQL: Only `SELECT` statements allowed. Parameterized queries with `:tenant_id`
- Cypher: Only `MATCH/RETURN` queries. Never `CREATE/DELETE/SET/MERGE`
- All queries are filtered by `tenant_id` for multi-tenant isolation

---

## 8. Data Flow — End-to-End Request Lifecycle

### Example: Creating a Product

```
Client                Provisioning Svc          Policy Svc         PostgreSQL        Service Bus      Outbox Worker      Graph Svc        Vector Svc
  │                         │                       │                  │                 │                │                │                │
  │  POST /catalog/products │                       │                  │                 │                │                │                │
  ├────────────────────────►│                       │                  │                 │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                    Gate 1: RBAC                  │                  │                 │                │                │                │
  │                    JWT → check_user_authorization│                  │                 │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                    Gate 2: Policy                │                  │                 │                │                │                │
  │                         │  POST /evaluate       │                  │                 │                │                │                │
  │                         │  {action:             │                  │                 │                │                │                │
  │                         │   "product.create",   │                  │                 │                │                │                │
  │                         │   subject, resource}  │                  │                 │                │                │                │
  │                         ├──────────────────────►│                  │                 │                │                │                │
  │                         │                       │  enrich context  │                 │                │                │                │
  │                         │                       │  (budget, roles, │                 │                │                │                │
  │                         │                       │   entitlements)  │                 │                │                │                │
  │                         │                       ├─────────────────►│                 │                │                │                │
  │                         │                       │◄─────────────────┤                 │                │                │                │
  │                         │                       │  evaluate rules  │                 │                │                │                │
  │                         │  {decision: "allow"}  │                  │                 │                │                │                │
  │                         │◄──────────────────────┤                  │                 │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                    Business logic:              │                  │                 │                │                │                │
  │                    - Check entitlement limit    │                  │                 │                │                │                │
  │                    - INSERT product             │                  │                 │                │                │                │
  │                    - INSERT outbox_event        │                  │                 │                │                │                │
  │                    - COMMIT                     │                  │                 │                │                │                │
  │                         ├─────────────────────────────────────────►│                 │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                         │  send {outbox_id}     │                  │                 │                │                │                │
  │                         ├──────────────────────────────────────────────────────────►│                 │                │                │
  │  201 Created            │                       │                  │                 │                │                │                │
  │◄────────────────────────┤                       │                  │                 │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                         │                       │                  │    (async)       │                │                │                │
  │                         │                       │                  │◄────────────────┤                │                │                │
  │                         │                       │                  │  load outbox     │                │                │                │
  │                         │                       │                  │  run handler     │                │                │                │
  │                         │                       │                  │  mark completed  │                │                │                │
  │                         │                       │                  │                 │                │                │                │
  │                         │                       │                  │         (polling, every 2s)      │                │                │
  │                         │                       │                  │◄────────────────────────────────┤                │                │
  │                         │                       │                  │  claim batch     │                │                │                │
  │                         │                       │                  │  (status=pending)│                │                │                │
  │                         │                       │                  │                  │    handler()   │                │                │
  │                         │                       │                  │                  │    MERGE node  │                │                │
  │                         │                       │                  │                  │    in Neo4j    │                │                │
  │                         │                       │                  │  mark processed  │                │                │                │
  │                         │                       │                  │                  │                │                │                │
  │                         │                       │                  │         (polling, every 3s)                       │                │
  │                         │                       │                  │◄────────────────────────────────────────────────┤                  │
  │                         │                       │                  │  claim batch (status=processed,                  │                │
  │                         │                       │                  │   aggregate_type IN (product))                   │                │
  │                         │                       │                  │                  │                │   embed text   │                │
  │                         │                       │                  │                  │                │   store vector │
  │                         │                       │                  │                  │                │   log in       │
  │                         │                       │                  │                  │                │   vector_event │
```

---

## 9. Event-Driven Architecture (Outbox Pattern)

### Overview

The platform uses the **Transactional Outbox Pattern** to ensure reliable event propagation without distributed transactions.

```
┌──────────────────────────────────────────────────────┐
│                    PostgreSQL                         │
│                                                      │
│  BEGIN TRANSACTION                                    │
│    INSERT INTO products (...)                         │
│    INSERT INTO outbox_events (                        │
│      aggregate_type='product',                       │
│      aggregate_id=<product_uuid>,                    │
│      event_type='product.created',                   │
│      payload={...},                                  │
│      status='pending'                                │
│    )                                                 │
│  COMMIT                                              │
│                                                      │
│  ► Both writes succeed or both fail — no partial     │
│    state, no message lost                            │
└──────────────────────────────────────────────────────┘
```

### Three Consumers of `outbox_events`

| Consumer | How | Filter | Status Flow |
|----------|-----|--------|-------------|
| **Outbox Worker** (provisioning_service) | Azure Service Bus queue message `{outbox_id}` | `status='pending'`, specific event_types (tenant.signup, user.created, product.created) | pending → processing → completed/failed |
| **Graph Service** | PostgreSQL polling (every 2s) | `status='pending'`, all aggregate types | pending → processing → processed/dead_letter |
| **Vector Service** | PostgreSQL polling (every 3s) | `status='processed'` AND `aggregate_type IN ('product','category')` AND `id NOT IN vector_event_log` | Uses separate `vector_event_log` tracking table |

### `outbox_events` Table Schema

```sql
id               UUID PRIMARY KEY
tenant_id        UUID NOT NULL
aggregate_type   VARCHAR(100)       -- e.g., 'product', 'site', 'user'
aggregate_id     UUID               -- entity's primary key
event_type       VARCHAR            -- e.g., 'product.created', 'site.updated'
payload          JSONB              -- event data (was 'event_data', renamed)
status           VARCHAR            -- pending → processing → processed/completed/failed/dead_letter
retry_count      INT DEFAULT 0
max_retries      INT DEFAULT 3
created_at       TIMESTAMPTZ
updated_at       TIMESTAMPTZ
```

### Auto-Derivation

When `create_outbox_event()` is called without explicit `aggregate_type`/`aggregate_id`:
- `aggregate_type` ← extracted from `event_type` prefix (e.g., `"product.created"` → `"product"`)
- `aggregate_id` ← scanned from the payload dict for well-known ID keys (`product_id`, `site_id`, `user_id`, etc.)

---

## 10. The Two-Gate Security Model

Every mutating endpoint in the provisioning service passes through two sequential security checks:

### Gate 1: RBAC (Authentication + Permission Check)

```python
@router.post("/stores")
async def create_store(
    req: StoreRequest,
    ctx = Depends(check_user_authorization("stores.manage")),  # ← Gate 1
    ...
):
```

**Flow:**
1. Extract JWT from `Authorization: Bearer <token>` header
2. Decode and verify signature, expiry
3. Extract `roles` claim from JWT payload
4. Query `role_permissions` table: does any of the user's roles have the required permission?
5. If yes → pass (return claims dict). If no → HTTP 403

### Gate 2: Policy Engine (Contextual Authorization)

```python
@router.post("/stores")
async def create_store(
    req: StoreRequest,
    ctx = Depends(check_user_authorization("stores.manage")),  # ← Gate 1
    policy = Depends(require_policy("store.create")),          # ← Gate 2
    ...
):
```

**Flow:**
1. Build `subject` from JWT claims (user_id, tenant_id, roles, permissions)
2. Extract `resource` from request body
3. Call Policy Service `POST /evaluate` with `{action, subject, resource, tenant_id}`
4. Policy Service enriches context (budget, subscription, entitlements from DB)
5. Policy Service evaluates all matching rules
6. Returns: `allow` (continue) / `deny` (HTTP 403) / `require_approval` (HTTP 202)

### Exempted Endpoints (No Gate 2)
- `auth_routes.py` — Pre-auth flows (login, signup, password reset)
- `tenant_onboarding.py` — Signup/sign-in (no JWT yet)
- `payments_routes.py` — Stripe webhooks (machine-to-machine)
- `internal_routes.py` — Platform admin (plans, features, global roles/permissions)

---

## 11. Approved Universe — Product Governance

The **Approved Universe** is the set of products a user is allowed to see, search, and order. It enforces curated procurement — users can only interact with products that their org unit has been assigned.

### Data Model

```
Tenant
  └── OrgUnit (department)
        └── ApprovedRange (named collection, e.g., "Office Supplies Q1")
              └── Product (many-to-many via approved_range_products)
```

### Graph Traversal (Neo4j)

```cypher
// User's approved products
MATCH (u:User {user_id: $uid})-[:BELONGS_TO]->(d:OrgUnit)
      -[:GOVERNED_BY]->(ar:ApprovedRange {status: 'active'})
      -[:INCLUDES]->(p:Product {status: 'active'})
RETURN DISTINCT p.product_id

UNION

// Universal ranges (apply to all org units in tenant)
MATCH (t:Tenant {tenant_id: $tid})-[:HAS_APPROVED_RANGE]->(ar:ApprovedRange {is_universal: true})
      -[:INCLUDES]->(p:Product)
RETURN DISTINCT p.product_id
```

### Where It's Enforced

| Layer | How |
|-------|-----|
| **Vector Service** (search) | Before returning search results, calls Graph Service to get approved IDs, filters results |
| **Policy Service** (evaluation) | Context enricher loads `approved_product_ids` into subject context. Policy rules can check `resource.product_id in subject.approved_product_ids` |
| **Intelligence Service** (NL query) | Graph queries automatically traverse the governed topology |

---

## 12. Budgetary Control

### Budget Hierarchy

```
CompanyBudgetCap (annual cap per tenant per year)
  └── CostCentreBudgetVersion (budget allocated to each cost centre)
        └── UserCostCentre (budget allocated to each user within a cost centre)
              └── UserBudgetLimit (per-category or per-period spending limits)
```

### Budget Flow

1. **Company sets annual cap** → `CompanyBudgetCap` (e.g., £500,000 for FY2026)
2. **Finance allocates to cost centres** → `CostCentreBudgetVersion` (e.g., Marketing: £100,000)
3. **Manager assigns to users** → `UserCostCentre` (e.g., John: £20,000 from Marketing)
4. **Optional per-user limits** → `UserBudgetLimit` (e.g., max £5,000/month on supplies)
5. **User creates purchase request** → Policy engine checks:
   - Does the user have sufficient budget? (`subject.budget_remaining >= resource.amount_minor`)
   - Is the amount within their order limit? (`resource.amount_minor <= subject.max_order_limit_minor`)
   - Does the cost centre have sufficient allocated budget?
6. **On approval** → `SpendingEvent` recorded, budgets decremented
7. **Budget change requests** → Bring-forward, top-up, reallocation (with approval workflow)

---

## 13. Shared Infrastructure

### PostgreSQL (Shared Database)

All five services connect to the **same PostgreSQL instance**:
- **Provisioning Service** — owns all entity tables, writes outbox events
- **Policy Service** — owns policy tables (`policies`, `policy_versions`, `policy_rules`, `policy_assignments`, `policy_decisions`). Reads shared tables (users, roles, budgets) for context enrichment
- **Graph Service** — reads `outbox_events` table (polling). Writes no relational data
- **Vector Service** — reads `outbox_events` table (polling). Owns `product_embeddings` and `vector_event_log` tables

### Azure Service Bus

- **Queue**: `outbox-task-queue`
- **Purpose**: Triggers the provisioning service's outbox worker for heavy async tasks (tenant signup, user creation, product processing)
- **Message format**: `{"outbox_id": "<uuid>"}`
- **Auth**: `DefaultAzureCredential` (Managed Identity in Azure, local dev credentials locally)

### Azure Key Vault

All services fetch secrets from Key Vault in non-local environments:
```python
environment = os.getenv("ENVIRONMENT", "local").lower()
if environment != "local":
    # Fetch from Azure Key Vault using DefaultAzureCredential
else:
    # Load from .env file
```

### Azure OpenAI

Used by Vector Service (embeddings) and Intelligence Service (query generation + summarization):
- **Embedding model**: `text-embedding-3-small` (1536 dimensions)
- **LLM model**: `gpt-5-nano` (for query routing and summarization)

### Stripe

Integrated in Provisioning Service for subscription payments:
- `POST /payments/create-checkout-session` — Creates Stripe checkout
- `POST /payments/webhook` — Handles payment completion events
- `POST /payments/create-portal-session` — Billing portal for self-service

### Azure Communication Services

Used for sending emails:
- Welcome emails (tenant signup)
- Password reset links
- OTP codes

---

## 14. Deployment Topology

### Local Development

```
provisioning_service  →  uvicorn ... --port 8001
graph_service         →  uvicorn ... --port 8005
vector_service        →  uvicorn ... --port 8006
intelligence_service  →  uvicorn ... --port 8007
outbox_worker         →  python provisioning_service/core/helpers/outbox_worker.py

PostgreSQL            →  localhost:5432
Neo4j                 →  bolt://localhost:7687
Redis                 →  localhost:6379
```

### Production (Azure)

Each service runs as a separate container/app. All use:
- `ENVIRONMENT` env var (not `"local"`) → secrets from Key Vault
- `KEYVAULT_NAME` env var → identifies the vault
- `DefaultAzureCredential` → Managed Identity authentication

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 80
CMD ["uvicorn", "zeroque_core_app:app", "--host", "0.0.0.0", "--port", "80"]
```

---

## 15. Key Design Decisions

### 1. Shared Database, Separate Services
All services share one PostgreSQL database but have **zero code-level dependency** on each other. The policy engine reads `users`, `roles`, `budgets` tables via raw SQL, not by importing provisioning_service models.

### 2. Transactional Outbox (Not Message-First)
Entity writes and outbox events are committed in the same database transaction. This guarantees no message is lost even if the Service Bus is temporarily down. The graph/vector services are **eventually consistent** projections.

### 3. Governance-First (Default-Deny)
When no policies match an action, the default decision is **DENY**. This ensures nothing slips through without explicit policy authorization. The Approved Universe returns an **empty set** if no ranges are assigned — users see nothing by default.

### 4. Products Enter Graph Only via Approved Ranges
Products are not projected to Neo4j on creation. They appear in the graph **only** when added to an Approved Range. This prevents ungoverned products from appearing in search results or being orderable.

### 5. Two-Gate Security on Every Mutation
Every mutating endpoint has both RBAC (Gate 1) and Policy Engine (Gate 2) checks. Gate 1 answers "who are you?", Gate 2 answers "can you do this right now with these parameters?".

### 6. AST-Based Expression Parser (No eval())
Policy rules use a safe expression language parsed via Python's `ast` module. Supports comparisons, boolean logic, dot-access, and membership tests — but blocks function calls, imports, and arbitrary code execution.

### 7. Dual-Mode Vector Storage
The vector service falls back to JSONB + Python cosine similarity when the pgvector extension isn't available. This allows local development on Windows without compiling native extensions, while production uses hardware-accelerated vector search.

### 8. GraphRAG Intelligence Layer
The Intelligence Service combines all three data engines (SQL, Graph, Vector) via LLM-driven query routing. This enables natural language access to the full governance topology without exposing raw database access to admins.

---

## Appendix: Service Communication Matrix

| From → To | Protocol | Purpose |
|-----------|----------|---------|
| Provisioning → Policy | HTTP `POST /evaluate` | Gate 2 policy evaluation |
| Provisioning → Service Bus | AMQP | Dispatch outbox messages for async processing |
| Service Bus → Outbox Worker | AMQP | Trigger tenant/user/product post-processing |
| Graph ← PostgreSQL | SQL polling | Consume outbox events, project to Neo4j |
| Vector ← PostgreSQL | SQL polling | Consume processed product events, generate embeddings |
| Vector → Graph | HTTP `GET /graph/approved-products/{user_id}` | Fetch Approved Universe for search filtering |
| Intelligence → Graph | HTTP (Cypher proxy) | Execute graph queries |
| Intelligence → Vector | HTTP `POST /vector/search` | Execute semantic search |
| Intelligence → PostgreSQL | SQL (read-only) | Execute aggregation queries |
| Intelligence → Azure OpenAI | HTTPS | LLM query classification + summarization |
| Vector → Azure OpenAI | HTTPS | Generate text embeddings |
| Provisioning → Stripe | HTTPS | Payment processing |
| Provisioning → Azure Email | HTTPS | Send emails (welcome, password reset, OTP) |
| All Services → Key Vault | HTTPS | Fetch secrets (non-local environments) |

