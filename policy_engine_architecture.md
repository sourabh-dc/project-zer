# ZeroQue Policy Engine — Proposed Architecture

> **Status**: DRAFT — For team review  
> **Date**: 2026-02-19  
> **Reference**: ZeroQue Engineering Lock v1.1, project-zer-old/policy_engine

---

## 1. Core Concept: The Control Tower

The Policy Engine is the **governance and decisioning layer** that sits on top of the entire application. Like an airport control tower that decides whether an aircraft can land on runway X at time T — the Policy Engine decides whether user U can perform action A on resource R under conditions C.

Every API call passes through **two sequential gates**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INCOMING API REQUEST                           │
│                   (User wants to do something)                         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      GATE 1: AUTHENTICATION (RBAC)                     │
│                                                                         │
│  "Does this user have the PERMISSION to call this endpoint?"           │
│                                                                         │
│  JWT → Extract roles → Lookup RolePermission table → Allow/Deny        │
│                                                                         │
│  Example:                                                               │
│    User has role: cost_centre_admin                                     │
│    Role maps to permission: cost_centre.create                         │
│    Endpoint requires: cost_centre.create                               │
│    ✅ Pass — user is who they say they are and has the right role       │
│                                                                         │
│  This answers: "WHO are you?"                                          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ (only if Gate 1 passes)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    GATE 2: AUTHORIZATION (POLICY ENGINE)                │
│                                                                         │
│  "Given this user + action + context, is THIS SPECIFIC INSTANCE        │
│   of the action allowed?"                                              │
│                                                                         │
│  Build context → Fetch applicable policies → Evaluate rules →          │
│  Return: ALLOW / DENY / REQUIRE_APPROVAL                               │
│                                                                         │
│  Example:                                                               │
│    Action: cost_centre.create                                          │
│    Context: Tenant is on "Core" plan (limit: 50 cost centres)          │
│    Current count: 50                                                    │
│    Policy rule: resource.would_exceed_limit == True → DENY             │
│    ❌ Denied — "Cost centre limit reached for your plan (50/50)"       │
│                                                                         │
│  This answers: "CAN you do this, right now, with these parameters?"    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ (only if Gate 2 allows)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         BUSINESS LOGIC EXECUTES                        │
│                  (Create cost centre, place order, etc.)               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. What the Policy Engine Does

### 2.1 Input (Evaluation Request)

Every policy evaluation takes three inputs:

| Input | Description | Example |
|-------|-------------|---------|
| **Action** | What is being attempted | `order.create`, `product.search`, `cost_centre.create` |
| **Subject** | Who is doing it (enriched with DB data) | `{user_id, tenant_id, roles, budget_remaining, org_unit_id, ...}` |
| **Resource** | What they are acting on | `{order_total: 150000, products: [...], cost_centre_id: ...}` |

### 2.2 Output (Decision)

| Decision | Meaning | What Happens |
|----------|---------|--------------|
| `allow` | Action permitted | Proceed with business logic |
| `deny` | Action blocked | Return 403 with human-readable reason |
| `require_approval` | Action needs approval | Create approval request, block until approved |

### 2.3 Policy Categories

| Category | What It Governs | Examples |
|----------|----------------|---------|
| **Entitlement** | Plan/quota limits | "Can tenant create more cost centres?" |
| **Budget** | Financial limits | "Does user have sufficient budget?" |
| **Approval** | Threshold-based workflows | "Order > ₹1L needs manager approval" |
| **Product** | Product restrictions | "Restricted product needs special approval" |
| **Access** | Visibility and reach | "User can only see products in their Approved Range" |
| **Vendor** | Vendor portal rules | "Only vendor users can access vendor portal" |

---

## 3. Architecture

### 3.1 Deployment Model

> **🔵 DECISION POINT 1: Deployment topology**
>
> | Option | Pros | Cons |
> |--------|------|------|
> | **A) Embedded module** inside provisioning_service | Zero network latency, simpler deployment, shared DB session | Tightly coupled, can't scale independently, single point of failure |
> | **B) Separate microservice** (as in old code — port 8004) | Independent scaling, clear boundary, can be shared across services | Network latency on every API call (~2-5ms), needs service discovery, more complex deployment |
> | **C) Hybrid** — embedded evaluator + separate admin API | Fast evaluation (in-process), policy CRUD is separate, Redis-synced | Moderate complexity, needs cache invalidation strategy |
>
> **Old code used**: Option B (separate FastAPI service on port 8004)
>
> **Recommendation**: Option C — the evaluator runs in-process for zero latency on the hot path, but policy CRUD/admin endpoints live in a separate internal service. Policy changes are synced via Redis cache invalidation.

### 3.2 Component Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        PROVISIONING SERVICE                             │
│                                                                          │
│  ┌─────────────────┐    ┌─────────────────────────────────────────────┐ │
│  │  API Endpoints   │───▶│           POLICY MIDDLEWARE                 │ │
│  │  (FastAPI routes) │    │                                             │ │
│  └─────────────────┘    │  1. check_user_authorization (RBAC - Gate 1) │ │
│                          │  2. evaluate_policy (Policy Engine - Gate 2) │ │
│                          └───────────┬─────────────────────────────────┘ │
│                                      │                                    │
│                          ┌───────────▼─────────────────────────────────┐ │
│                          │        POLICY EVALUATOR (in-process)        │ │
│                          │                                              │ │
│                          │  ┌──────────────┐  ┌──────────────────────┐ │ │
│                          │  │  Expression   │  │  Context Enricher    │ │ │
│                          │  │  Parser       │  │  (User, Budget, Org, │ │ │
│                          │  │  (safe eval)  │  │   Subscription,      │ │ │
│                          │  └──────────────┘  │   ApprovedRange)     │ │ │
│                          │                     └──────────────────────┘ │ │
│                          │  ┌──────────────┐  ┌──────────────────────┐ │ │
│                          │  │  Policy       │  │  Decision Logger     │ │ │
│                          │  │  Resolver     │  │  (audit every eval)  │ │ │
│                          │  │  (fetch &     │  └──────────────────────┘ │ │
│                          │  │   cache)      │                           │ │
│                          │  └──────────────┘                           │ │
│                          └─────────────────────────────────────────────┘ │
│                                      │                                    │
│                          ┌───────────▼───────────┐                       │
│                          │    Redis Cache         │                       │
│                          │  (policy definitions,  │                       │
│                          │   enriched context)    │                       │
│                          └───────────────────────┘                       │
│                                      │                                    │
│                          ┌───────────▼───────────┐                       │
│                          │    PostgreSQL (SoR)    │                       │
│                          │  - policies            │                       │
│                          │  - policy_versions     │                       │
│                          │  - policy_rules        │                       │
│                          │  - policy_assignments  │                       │
│                          │  - policy_decisions    │                       │
│                          │  - policy_action_types │                       │
│                          └───────────────────────┘                       │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                    INTERNAL ADMIN SERVICE (separate)                     │
│                                                                          │
│  Policy CRUD endpoints:                                                  │
│  - POST/PUT/DELETE /policies                                             │
│  - POST/PUT/DELETE /policies/{id}/rules                                  │
│  - POST/PUT/DELETE /policies/{id}/assignments                            │
│  - GET /policy-decisions (audit log)                                     │
│  - POST /policies/evaluate (dry-run testing)                             │
│  - POST /policies/seed (seed defaults)                                   │
│                                                                          │
│  On any policy change → invalidate Redis cache                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Models

### 4.1 Policy Tables (already existed in project-zer-old)

```
┌─────────────────────┐
│      policies       │
├─────────────────────┤       ┌──────────────────────┐
│ policy_id (PK)      │       │   policy_versions    │
│ tenant_id (nullable)│───┐   ├──────────────────────┤
│ code (unique/tenant)│   │   │ version_id (PK)      │
│ name                │   └──▶│ policy_id (FK)       │
│ description         │       │ version_number       │     ┌──────────────────────┐
│ policy_type         │       │ rules_json (JSONB)   │     │    policy_rules      │
│ priority            │       │ effective_from       │     ├──────────────────────┤
│ is_active           │       │ effective_until      │────▶│ rule_id (PK)         │
│ status              │       │ change_reason        │     │ version_id (FK)      │
│ created_at          │       └──────────────────────┘     │ rule_order           │
│ updated_at          │                                     │ name                 │
│ created_by          │       ┌──────────────────────┐     │ condition_expression │
└─────────────────────┘       │ policy_assignments   │     │ effect (allow/deny/  │
          │                   ├──────────────────────┤     │   require_approval)  │
          └──────────────────▶│ assignment_id (PK)   │     │ denial_reason        │
                              │ policy_id (FK)       │     │ approval_chain_id    │
                              │ scope_type           │     │ actions (JSONB)      │
                              │ scope_id             │     │ is_active            │
                              │ action_pattern       │     └──────────────────────┘
                              │ priority_override    │
                              │ is_active            │     ┌──────────────────────┐
                              │ valid_from           │     │  policy_decisions    │
                              │ valid_until          │     ├──────────────────────┤
                              └──────────────────────┘     │ decision_id (PK)     │
                                                           │ tenant_id            │
                              ┌──────────────────────┐     │ action               │
                              │ policy_action_types  │     │ subject (JSONB)      │
                              ├──────────────────────┤     │ resource (JSONB)     │
                              │ action_type_id (PK)  │     │ decision             │
                              │ code (unique)        │     │ matched_policies     │
                              │ name                 │     │ reason               │
                              │ subject_schema       │     │ evaluation_ms        │
                              │ resource_schema      │     │ correlation_id       │
                              │ category             │     │ evaluated_at         │
                              └──────────────────────┘     └──────────────────────┘
```

### 4.2 Key Relationships

- A **Policy** has many **PolicyVersions** (immutable snapshots of rules)
- Only the version where `effective_until IS NULL` is the current/active version
- A **PolicyVersion** has many **PolicyRules**
- A **Policy** has many **PolicyAssignments** (scoping: where/when does it apply)
- A **PolicyAssignment** has a `scope_type` (global / tenant / site / store / org_unit / user) and `action_pattern` (supports wildcards like `order.*`)
- Every evaluation is logged in **PolicyDecisionLog** (immutable audit trail)

### 4.3 Approved Range Models (new — to be added)

```
┌──────────────────────────┐
│     approved_ranges      │
├──────────────────────────┤       ┌──────────────────────────┐
│ approved_range_id (PK)   │       │  approved_range_products │
│ tenant_id (FK→tenants)   │       ├──────────────────────────┤
│ name                     │──────▶│ id (PK)                  │
│ description              │       │ approved_range_id (FK)   │
│ org_unit_id (FK→org_units│       │ product_id (FK→products) │
│   nullable — see DP2)    │       │ status                   │
│ status                   │       │ added_by                 │
│ created_by               │       │ created_at               │
│ created_at               │       └──────────────────────────┘
│ updated_at               │
└──────────────────────────┘
```

> **🔵 DECISION POINT 2: Approved Range assignment level**
>
> | Option | Description | Example |
> |--------|-------------|---------|
> | **A) OrgUnit only** | Each approved range belongs to one org unit | "Lab Dept" → "Lab Chemicals Range" |
> | **B) Multi-level** | Approved ranges can be assigned at tenant (global default), org_unit (department-level), or user (override) level | Tenant default range for all users + department overrides + user-specific exceptions |
> | **C) Via PolicyAssignment** | Approved ranges are just another policy — assigned via the same scope mechanism as all other policies | Most flexible, reuses existing scoping system |
>
> **Recommendation**: Option B for data model, but enforcement via the Policy Engine (Option C's spirit). The `approved_ranges` table holds the range + products, but a policy like `product.visibility` uses the Approved Range data as context during evaluation.

---

## 5. Evaluation Flow (Detailed)

### 5.1 Request Lifecycle

```
 User calls POST /orders
       │
       ▼
 ┌─────────────────────────┐
 │ 1. RBAC Check            │  check_user_authorization("orders.create")
 │    JWT → roles →         │  → 403 if no permission
 │    permission lookup     │
 └───────────┬─────────────┘
             │ ✅ has permission
             ▼
 ┌─────────────────────────┐
 │ 2. Build Eval Context    │  Subject: {user_id, tenant_id}
 │                          │  Resource: {order_total, products, ...}
 │                          │  Action: "order.create"
 └───────────┬─────────────┘
             │
             ▼
 ┌─────────────────────────┐
 │ 3. Context Enrichment    │  Fetch from DB / cache:
 │    (automatic)           │  - User roles, budget, org_unit
 │                          │  - Tenant subscription & plan
 │                          │  - User's approved ranges
 │                          │  - Product restrictions
 │                          │  - Subordinate IDs
 └───────────┬─────────────┘
             │
             ▼
 ┌─────────────────────────┐
 │ 4. Fetch Applicable      │  Match by:
 │    Policies              │  - tenant_id (global + tenant-specific)
 │                          │  - action pattern ("order.create" matches "order.*")
 │                          │  - scope (site/store/org_unit if in context)
 │                          │  - validity period (valid_from/until)
 │                          │  Sorted by priority (lower = first)
 └───────────┬─────────────┘
             │
             ▼
 ┌─────────────────────────┐
 │ 5. Evaluate Rules        │  For each policy (in priority order):
 │                          │    For each rule (in rule_order):
 │                          │      Parse condition_expression
 │                          │      Evaluate against enriched context
 │                          │      If condition_met:
 │                          │        "deny" → STOP, return denied
 │                          │        "require_approval" → accumulate
 │                          │        "allow" → continue
 └───────────┬─────────────┘
             │
             ▼
 ┌─────────────────────────┐
 │ 6. Log Decision          │  Insert into policy_decisions table
 │    (immutable audit)     │  {action, subject, resource, decision,
 │                          │   matched_policies, reason, duration_ms}
 └───────────┬─────────────┘
             │
             ▼
 ┌─────────────────────────┐
 │ 7. Return Decision       │  ALLOW → proceed to business logic
 │                          │  DENY → HTTPException 403 + reason
 │                          │  REQUIRE_APPROVAL → create approval
 │                          │    request, return 202 Accepted
 └─────────────────────────┘
```

### 5.2 Expression Examples

The safe expression parser evaluates conditions against the enriched context:

```python
# Budget check — deny if insufficient
"subject.budget_remaining < resource.order_total"

# Large order approval — require approval if over threshold
"resource.order_total > subject.max_order_limit_minor"

# Restricted product — deny without approval
"resource.restricted == true and not subject.has_approval"

# Quota check — deny if plan limit exceeded
"resource.would_exceed_limit == true"

# Cross-tenant prevention
"subject.tenant_id != resource.tenant_id"

# Role-based access
"not subject.roles CONTAINS 'admin'"

# Combined conditions
"resource.order_total > 5000 and subject.budget_remaining < resource.order_total"

# Approved range — product visibility
"not resource.product_id in subject.approved_product_ids"
```

---

## 6. Approved Range — Product Visibility

### 6.1 How It Works

```
  ┌─────────┐    ┌─────────────┐    ┌──────────────────┐    ┌──────────┐
  │  User    │───▶│  OrgUnit    │───▶│  ApprovedRange   │───▶│ Products │
  │ (Lab     │    │ (Lab Dept)  │    │ (Lab Chemicals)  │    │ Chem A   │
  │  Scientist)   └─────────────┘    │ (Lab Equipment)  │    │ Chem B   │
  └─────────┘                        └──────────────────┘    │ Reagent X│
                                                              │ Microscope
                                                              └──────────┘

  When user searches for "products":
  1. Context enricher fetches user's org_unit_id
  2. Fetches all approved_ranges for that org_unit
  3. Fetches all product_ids in those ranges
  4. Adds to subject context: approved_product_ids = [...]
  5. Product search query is FILTERED to only those product_ids

  If user searches "laptop":
  → laptop product_id is NOT in approved_product_ids
  → Product is invisible (not returned in search results)
```

### 6.2 Enforcement Mechanism

> **🔵 DECISION POINT 3: How Approved Range filtering works**
>
> | Option | Description | Latency Impact |
> |--------|-------------|----------------|
> | **A) Query-time filter** | Product search SQL adds `WHERE product_id IN (user's approved products)` — the Policy Engine provides the list, the query applies it | Fast — single DB query with IN clause. But IN clause can be huge for large ranges. |
> | **B) Policy evaluation per product** | Each product in search results is evaluated individually against the Approved Range policy | Very slow for large catalogs — N policy evaluations per search |
> | **C) Materialized view / pre-computed** | Background job pre-computes `user_visible_products` table. Search queries join against it. Outbox events trigger recomputation when ranges change. | Fastest reads, but stale data until recomputed. Additional storage. |
> | **D) Hybrid** | Use Option A for search (fast), Option B for individual actions (order.create — verify product is in range) | Good balance of speed and accuracy |
>
> **Recommendation**: Option D — for search/listing endpoints, the context enricher provides the approved product IDs as a filter. For write actions (ordering, adding to cart), the policy engine individually evaluates whether the product is in range.

---

## 7. RBAC Integration (Gate 1) — Current State + Improvements

### 7.1 Current RBAC Flow (already working)

```
JWT Token contains:
  {
    "sub": "user-uuid",
    "tenant_id": "tenant-uuid",
    "roles": ["cost_centre_admin", "catalog_viewer"],
    "permissions": ["cost_centre.create", "catalog.products.view"],
    "exp": 1740000000
  }

check_user_authorization("cost_centre.create"):
  1. Validate JWT (signature, expiry)
  2. Check direct permissions in token (supports "*" wildcard)
  3. If not found → DB lookup: UserRole → Role → RolePermission → Permission
  4. If match → return claims context
  5. If no match → 403 Forbidden
```

### 7.2 Current Permission Catalog (50+ permissions)

```
Tenant:       tenants.create, tenants.manage, tenant.admin
Sites:        sites.manage
Stores:       stores.manage, stores.admin
Users:        users.manage, users.view, users.create, users.admin
Roles:        roles.assign, roles.manage
Catalog:      catalog.manage, catalog.products.manage, catalog.products.view
Budgets:      budgets.manage, budgets.instant.approve
Approvals:    approvals.chains.manage, approvals.requests.create/view/respond
Cost Centres: cost_centre.create, cost_centre.manage
Org Units:    org_units.manage, org_units.assign
Orders:       orders.create, orders.manage, orders.view
Subscriptions: subscription.manage
Vendors:      vendors.manage, vendors.view
Entitlements: entitlements.check, entitlements.usage.record
```

### 7.3 Proposed Improvement: Policy-Aware RBAC

> **🔵 DECISION POINT 4: Should Gate 1 (RBAC) also go through the Policy Engine?**
>
> | Option | Description |
> |--------|-------------|
> | **A) Keep separate** | RBAC stays as-is (fast JWT check). Policy Engine is Gate 2 only. |
> | **B) Unify** | All authorization (including RBAC) goes through Policy Engine. Permission checks become policies. |
> | **C) RBAC first, policy enriches** | RBAC stays fast (Gate 1). Policy Engine can override/restrict further (Gate 2). RBAC never denies something the Policy Engine would allow, but Policy Engine can deny something RBAC allows. |
>
> **Recommendation**: Option C — RBAC is the fast, coarse-grained gate. Policy Engine is the fine-grained, context-aware gate. They work in sequence, not as alternatives.

---

## 8. Policy Lifecycle & Management

### 8.1 Policy Definition

Policies are defined as data, not code. Each policy consists of:

```yaml
Policy:
  code: "order.budget.check"
  name: "Budget Limit Policy"
  type: "budget"
  priority: 10              # lower = evaluated first
  tenant_id: null            # null = global (applies to all tenants)

  Version (current):
    rules:
      - order: 0
        name: "Budget Exceeded Check"
        condition: "subject.budget_remaining < resource.order_total"
        effect: "deny"
        reason: "Insufficient budget. Available: {subject.budget_remaining}"

      - order: 1
        name: "Large Order Approval"
        condition: "resource.order_total > subject.max_order_limit_minor"
        effect: "require_approval"
        reason: "Order exceeds your limit of {subject.max_order_limit_minor}"

  Assignments:
    - scope: global
      action_pattern: "order.create"
```

### 8.2 Who Can Create/Modify Policies?

> **🔵 DECISION POINT 5: Policy management access**
>
> | Option | Description |
> |--------|-------------|
> | **A) System-only** | Policies are seeded by us. Tenants cannot create/modify. |
> | **B) Tenant-configurable** | Tenant admins can create policies within their scope. Cannot modify global policies. |
> | **C) Tiered** | System global defaults + tenant overrides. Higher plans get more policy customization. |
>
> **Recommendation**: Option C — start with system-seeded defaults (Phase 1). Add tenant-level policy CRUD as a premium feature later.

### 8.3 Default (Seed) Policies

These ship with the system and apply to all tenants:

| Policy Code | Type | Action Pattern | Rule | Effect |
|------------|------|---------------|------|--------|
| `entitlement.plan_limit` | entitlement | `*` | `resource.would_exceed_limit == true` | deny |
| `entitlement.subscription_required` | entitlement | `*` | `subject.subscription_active == false` | deny |
| `order.budget.check` | budget | `order.create` | `subject.budget_remaining < resource.order_total` | deny |
| `order.large_order_approval` | approval | `order.create` | `resource.order_total > subject.max_order_limit_minor` | require_approval |
| `product.restriction` | product | `product.purchase` | `resource.restricted == true and not subject.has_approval` | deny |
| `product.visibility` | access | `product.search` | `not resource.product_id in subject.approved_product_ids` | deny |
| `discount.authorization` | approval | `order.discount.apply` | `resource.discount_percent > 20 and not 'finance' in subject.roles` | require_approval |
| `order.quantity_limit` | budget | `order.create` | `resource.quantity > 100` | deny |
| `vendor.portal_access` | access | `vendor.*` | `subject.user_type != 'vendor' and resource.portal == 'vendor'` | deny |
| `cross_tenant.prevention` | access | `*` | `subject.tenant_id != resource.tenant_id` | deny |

---

## 9. Integration Points

### 9.1 How Routes Call the Policy Engine

```python
# BEFORE (current code — hardcoded checks)
@router.post("/cost-centres", status_code=201)
async def create_cost_centre(
    req: CostCentreRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("cost_centre.create"))  # Gate 1
):
    # Hardcoded quota check
    check_feature_limit(db, req.tenant_id, "cost_centres.manage", count=1)
    # ... business logic ...


# AFTER (policy-driven)
@router.post("/cost-centres", status_code=201)
async def create_cost_centre(
    req: CostCentreRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("cost_centre.create"))  # Gate 1 (unchanged)
):
    # Gate 2 — Policy Engine decides
    decision = await policy_engine.evaluate(
        action="cost_centre.create",
        subject={"user_id": str(ctx["user_id"]), "tenant_id": str(req.tenant_id)},
        resource={"cost_centre_name": req.name, "tenant_id": str(req.tenant_id)}
    )

    if not decision.allowed:
        if decision.decision == "approval_required":
            # Create approval request and return 202
            raise HTTPException(202, detail={"approval_required": True, "reason": decision.reason})
        raise HTTPException(403, detail=decision.reason)

    # ... business logic (unchanged) ...
```

### 9.2 Decorator / Middleware Approach

> **🔵 DECISION POINT 6: Integration pattern**
>
> | Option | Description | Code Change |
> |--------|-------------|-------------|
> | **A) Explicit** | Each route calls `policy_engine.evaluate()` explicitly | Most control, most boilerplate |
> | **B) Decorator** | `@require_policy("cost_centre.create")` decorator wraps routes | Less boilerplate, but resource extraction needs conventions |
> | **C) Middleware** | FastAPI middleware intercepts all requests, auto-evaluates | Least code change, but hardest to customize per-route |
> | **D) Dependency** | `policy_ctx = Depends(evaluate_policy("cost_centre.create", ...))` | FastAPI-native, composable with existing patterns |
>
> **Recommendation**: Option D — aligns with existing `Depends(check_user_authorization(...))` pattern. Example:
>
> ```python
> @router.post("/cost-centres", status_code=201)
> async def create_cost_centre(
>     req: CostCentreRequest,
>     db: Session = Depends(get_db),
>     ctx = Depends(check_user_authorization("cost_centre.create")),       # Gate 1
>     policy = Depends(require_policy("cost_centre.create", resource_from="body"))  # Gate 2
> ):
>     # If we reach here, both gates passed
>     ...
> ```

---

## 10. Approval Workflow Integration

When the Policy Engine returns `require_approval`, the system needs an approval workflow:

```
 Policy Engine returns: {decision: "require_approval", approval_chain_id: "..."}
       │
       ▼
 ┌─────────────────────────────────┐
 │ Create ApprovalRequest          │
 │  - requester_user_id            │
 │  - action (order.create)        │
 │  - resource (order details)     │
 │  - approval_chain_id            │
 │  - status: "pending"            │
 └──────────────┬──────────────────┘
                │
                ▼
 ┌─────────────────────────────────┐
 │ Route to Approver(s)            │
 │  Based on:                      │
 │  - UserApprover table           │
 │  - approval_limit_minor         │
 │  - org_unit hierarchy           │
 │  - cost_centre assignment       │
 └──────────────┬──────────────────┘
                │
                ▼
 ┌─────────────────────────────────┐
 │ Approver receives notification  │
 │ Reviews and responds:           │
 │  - APPROVE → original action    │
 │    is executed                   │
 │  - REJECT → requester notified  │
 │  - ESCALATE → next approver     │
 └─────────────────────────────────┘
```

> **🔵 DECISION POINT 7: Approval workflow scope for Phase 1**
>
> | Option | Description |
> |--------|-------------|
> | **A) Full workflow** | Approval chains, multi-step, escalation, delegation, expiry |
> | **B) Simple approval** | Single approver per action, approve/reject only |
> | **C) Deferred** | Policy Engine returns `require_approval` but we don't build the workflow yet — just block the action |
>
> **Recommendation**: Option B for Phase 1 — single approver routing via `UserApprover` table (already added to Models.py). Build full chains later.

---

## 11. Performance Considerations

### 11.1 Latency Budget

| Component | Target | Strategy |
|-----------|--------|----------|
| RBAC (Gate 1) | < 5ms | JWT validation + single DB query (already fast) |
| Policy evaluation (Gate 2) | < 10ms | Redis cache for policies + in-process evaluator |
| Context enrichment | < 5ms | Redis cache for user context (TTL: 60s) |
| Decision logging | < 2ms | Async write (fire-and-forget to outbox) |
| **Total overhead** | **< 20ms** | Acceptable for API calls |

### 11.2 Caching Strategy

```
Redis Cache:
  "policies:{tenant_id}:{action}" → applicable policy IDs    (TTL: 5 min)
  "policy_rules:{policy_id}"      → current version rules     (TTL: 5 min)
  "user_context:{user_id}"        → enriched subject data     (TTL: 60s)
  "approved_products:{org_unit}"  → product ID set            (TTL: 5 min)

Cache invalidation:
  - Policy CRUD → invalidate "policies:*" and "policy_rules:{id}"
  - User role change → invalidate "user_context:{user_id}"
  - Approved range change → invalidate "approved_products:{org_unit}"
  - Outbox events trigger invalidation via worker
```

---

## 12. Implementation Phases

### Phase 1: Core Engine (est. 5-7 days)
- [ ] Policy models (Policy, PolicyVersion, PolicyRule, PolicyAssignment, PolicyDecisionLog, PolicyActionType)
- [ ] Safe expression parser (port from old code)
- [ ] Policy evaluator (port from old code)
- [ ] Context enricher (port + extend for approved ranges)
- [ ] Decision logger
- [ ] `require_policy` FastAPI dependency
- [ ] Seed default policies
- [ ] Wire into 3-5 critical endpoints (order.create, cost_centre.create, product.search)

### Phase 2: Approved Range (est. 3-4 days)
- [ ] ApprovedRange model + ApprovedRangeProduct model
- [ ] CRUD endpoints for approved ranges
- [ ] Context enricher: fetch user's approved product IDs
- [ ] Product search filtering by approved range
- [ ] Outbox events for range changes

### Phase 3: Policy Admin (est. 3-4 days)
- [ ] Policy CRUD API (internal routes)
- [ ] Policy versioning (create new version on edit)
- [ ] Policy assignment management
- [ ] Redis cache integration + invalidation
- [ ] Policy dry-run / test endpoint

### Phase 4: Approval Workflow (est. 4-5 days)
- [ ] ApprovalRequest model
- [ ] Approver routing logic (UserApprover table)
- [ ] Approve / Reject endpoints
- [ ] Notification on approval events
- [ ] Wire `require_approval` decisions to workflow

### Phase 5: Full Rollout (est. 3-4 days)
- [ ] Wire Policy Engine to ALL write endpoints
- [ ] Migrate hardcoded `check_feature_limit` to entitlement policies
- [ ] Add tenant-specific policy override capability
- [ ] Policy decision analytics / dashboard data

---

## 13. Summary of Decision Points for Team

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Deployment topology | Embedded / Separate service / Hybrid | **Hybrid** — in-process evaluator, separate admin API |
| 2 | Approved Range assignment level | OrgUnit only / Multi-level / Via PolicyAssignment | **Multi-level** (tenant + org_unit + user) |
| 3 | Approved Range filtering mechanism | Query-time / Per-product eval / Materialized view / Hybrid | **Hybrid** — query filter for search, per-product for orders |
| 4 | Should RBAC go through Policy Engine? | Separate / Unified / RBAC first + policy enriches | **RBAC first, policy enriches** (sequential gates) |
| 5 | Policy management access | System-only / Tenant-configurable / Tiered | **Tiered** — system defaults + tenant overrides as premium |
| 6 | Integration pattern | Explicit / Decorator / Middleware / Dependency | **FastAPI Dependency** — `Depends(require_policy(...))` |
| 7 | Approval workflow scope | Full / Simple / Deferred | **Simple** for Phase 1 (single approver) |

---

## 14. Open Questions

1. **Policy Engine database**: Should policy tables live in the same Postgres database as the provisioning service, or a separate database? (Same DB is simpler; separate DB is more isolated.)

2. **Decision log retention**: How long do we keep policy decision logs? (Compliance may require 1-7 years. Could be millions of rows per month.)

3. **Default-deny vs default-allow**: When no policies match an action, should we allow or deny? (Old code defaults to allow. Stricter governance would default to deny.)

4. **Approved Range inheritance**: If a parent org unit has approved ranges, do child org units inherit them? Or must each org unit have its own explicit ranges?

5. **Real-time vs eventual consistency**: When a policy changes, should it take effect immediately (cache invalidation) or on next cache refresh (TTL-based)?

6. **Policy conflict resolution**: If a global policy says "allow" but a tenant policy says "deny" for the same action, which wins? (Typically: deny wins, or more specific scope wins.)
