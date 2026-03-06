# ============================================================================
# Policy Engine — Test Payloads
# ============================================================================
# Policy Engine runs on: http://localhost:8004
# Provisioning Service runs on: http://localhost:8001
#
# STEP 1: Seed default policies (optional — creates global policies)
# STEP 2: Create action-specific policies that match provisioning endpoints
# STEP 3: Create assignments so policies are picked up during evaluation
# STEP 4: Test /evaluate directly
# STEP 5: Test through provisioning endpoints (Gate 2 fires automatically)
# ============================================================================


# ============================================================================
# STEP 1: SEED DEFAULT POLICIES
# ============================================================================
# POST http://localhost:8004/policies/seed
# No body required — creates 8 global policies (idempotent)
# Response: { "seeded": 8, "skipped": 0, "details": [...] }


# ============================================================================
# STEP 2: CREATE POLICIES (one per provisioning action)
# ============================================================================

# --- 2a. Budget check for order creation ---
# POST http://localhost:8004/policies
{
    "code": "order.budget.enforcement",
    "name": "Order Budget Enforcement",
    "description": "Deny order if user budget is insufficient",
    "policy_type": "budget",
    "priority": 10,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "Budget Insufficient",
            "condition_expression": "subject.budget_remaining < resource.order_total",
            "effect": "deny",
            "denial_reason": "Insufficient budget. Remaining: {budget_remaining}, Order: {order_total}"
        }
    ],
    "change_reason": "Initial creation"
}


# --- 2b. Subscription required for site creation ---
# POST http://localhost:8004/policies
{
    "code": "site.subscription.required",
    "name": "Active Subscription Required for Sites",
    "description": "Deny site creation if tenant has no active subscription",
    "policy_type": "entitlement",
    "priority": 5,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "No Active Subscription",
            "condition_expression": "subject.subscription_active == False",
            "effect": "deny",
            "denial_reason": "An active subscription is required to create a site"
        }
    ],
    "change_reason": "Enforce subscription for site creation"
}


# --- 2c. Cross-tenant prevention for all actions ---
# POST http://localhost:8004/policies
{
    "code": "cross.tenant.block",
    "name": "Cross-Tenant Access Prevention",
    "description": "Block any request where subject tenant != resource tenant",
    "policy_type": "access",
    "priority": 0,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "Tenant Mismatch",
            "condition_expression": "subject.tenant_id != resource.tenant_id",
            "effect": "deny",
            "denial_reason": "Cross-tenant access is not allowed"
        }
    ],
    "change_reason": "Security: prevent cross-tenant operations"
}


# --- 2d. Large order requires approval ---
# POST http://localhost:8004/policies
{
    "code": "order.large.approval",
    "name": "Large Order Approval Required",
    "description": "Orders exceeding user limit require manager approval",
    "policy_type": "approval",
    "priority": 20,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "Order Exceeds Limit",
            "condition_expression": "resource.order_total > subject.max_order_limit_minor",
            "effect": "require_approval",
            "denial_reason": "Order total exceeds your limit of {max_order_limit_minor}"
        }
    ],
    "change_reason": "Approval workflow for large orders"
}


# --- 2e. User creation — subscription check ---
# POST http://localhost:8004/policies
{
    "code": "user.create.subscription",
    "name": "Subscription Required for User Creation",
    "description": "Deny user creation without active subscription",
    "policy_type": "entitlement",
    "priority": 5,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "No Subscription for User Create",
            "condition_expression": "subject.subscription_active == False",
            "effect": "deny",
            "denial_reason": "Active subscription required to create users"
        }
    ],
    "change_reason": "Entitlement check for user creation"
}


# --- 2f. Vendor creation — always allow (passthrough policy) ---
# POST http://localhost:8004/policies
{
    "code": "vendor.create.allow",
    "name": "Allow Vendor Creation",
    "description": "Explicitly allow vendor creation when subscription is active",
    "policy_type": "entitlement",
    "priority": 50,
    "is_active": true,
    "status": "active",
    "rules": [
        {
            "rule_order": 0,
            "name": "Allow if subscribed",
            "condition_expression": "subject.subscription_active == True",
            "effect": "allow"
        }
    ],
    "change_reason": "Allow vendor creation for subscribed tenants"
}


# ============================================================================
# STEP 3: CREATE ASSIGNMENTS (link policies to actions)
# ============================================================================
# Use the policy_id from the responses above.
# Replace <POLICY_ID> with the actual UUID returned.

# --- 3a. Assign order.budget.enforcement to action "order.create" ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "order.create",
    "is_active": true
}

# --- 3b. Assign site.subscription.required to action "site.create" ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "site.create",
    "is_active": true
}

# --- 3c. Assign cross.tenant.block to all actions ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "*",
    "is_active": true
}

# --- 3d. Assign order.large.approval to "order.create" ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "order.create",
    "is_active": true
}

# --- 3e. Assign user.create.subscription to "user.create" ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "user.create",
    "is_active": true
}

# --- 3f. Assign vendor.create.allow to "vendor.create" ---
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "vendor.create",
    "is_active": true
}

# --- 3g. Assign to store.create, cost_centre.create, org_unit.create ---
# Reuse site.subscription.required policy for these too:
# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "store.create",
    "is_active": true
}

# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "cost_centre.create",
    "is_active": true
}

# POST http://localhost:8004/policies/<POLICY_ID>/assignments
{
    "scope_type": "global",
    "action_pattern": "org_unit.create",
    "is_active": true
}


# ============================================================================
# STEP 4: TEST /evaluate DIRECTLY
# ============================================================================

# --- 4a. Test: Budget sufficient → ALLOW ---
# POST http://localhost:8004/evaluate
{
    "action": "order.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["tenant_admin"],
        "budget_remaining": 500000,
        "max_order_limit_minor": 1000000,
        "subscription_active": true
    },
    "resource": {
        "order_total": 25000,
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd"
    },
    "correlation_id": "test-allow-001"
}
# Expected: { "decision": "allow", "allowed": true }


# --- 4b. Test: Budget insufficient → DENY ---
# POST http://localhost:8004/evaluate
{
    "action": "order.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["tenant_admin"],
        "budget_remaining": 1000,
        "max_order_limit_minor": 1000000,
        "subscription_active": true
    },
    "resource": {
        "order_total": 50000,
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd"
    },
    "correlation_id": "test-deny-budget-001"
}
# Expected: { "decision": "deny", "allowed": false, "reason": "Insufficient budget..." }


# --- 4c. Test: Large order → REQUIRE_APPROVAL ---
# POST http://localhost:8004/evaluate
{
    "action": "order.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "c643ada4-ebf3-4928-a867-eb956f40a52a",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["user"],
        "budget_remaining": 9999999,
        "max_order_limit_minor": 50000,
        "subscription_active": true
    },
    "resource": {
        "order_total": 100000,
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd"
    },
    "correlation_id": "test-approval-001"
}
# Expected: { "decision": "require_approval", "allowed": false }


# --- 4d. Test: No subscription → DENY ---
# POST http://localhost:8004/evaluate
{
    "action": "site.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["tenant_admin"],
        "subscription_active": false
    },
    "resource": {
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd"
    },
    "correlation_id": "test-deny-sub-001"
}
# Expected: { "decision": "deny", "allowed": false, "reason": "...active subscription required..." }


# --- 4e. Test: Cross-tenant → DENY ---
# POST http://localhost:8004/evaluate
{
    "action": "user.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["tenant_admin"],
        "subscription_active": true
    },
    "resource": {
        "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    },
    "correlation_id": "test-cross-tenant-001"
}
# Expected: { "decision": "deny", "reason": "Cross-tenant access is not allowed" }


# --- 4f. Test: Dry-run (no logging) ---
# POST http://localhost:8004/evaluate/dry-run
{
    "action": "order.create",
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "subject": {
        "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
        "roles": ["tenant_admin"],
        "budget_remaining": 500000,
        "max_order_limit_minor": 1000000,
        "subscription_active": true
    },
    "resource": {
        "order_total": 25000,
        "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd"
    }
}
# Expected: { "decision": "allow", "dry_run": true }


# ============================================================================
# STEP 5: TEST VIA PROVISIONING ENDPOINTS (Gate 2 fires automatically)
# ============================================================================
# These hit provisioning_service on :8001. The require_policy() dependency
# automatically calls policy engine :8004/evaluate before business logic runs.
#
# Authorization header required (JWT with sub, tenant_id, roles):
# Authorization: Bearer <your_jwt_token>

# --- 5a. Create Site (action: site.create) ---
# POST http://localhost:8001/provisioning/sites
# If subscription is inactive → 403 from policy engine
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "name": "Policy Test Site",
    "type": "campus"
}

# --- 5b. Create Store (action: store.create) ---
# POST http://localhost:8001/provisioning/stores
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "site_id": "f97e999f-6d00-424c-a6f7-a48e8f76c951",
    "name": "Policy Test Store",
    "store_type": "physical"
}

# --- 5c. Create User (action: user.create) ---
# POST http://localhost:8001/provisioning/users
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "email": "policytest@example.com",
    "password": "StrongP@ssw0rd!",
    "first_name": "Policy",
    "last_name": "TestUser"
}

# --- 5d. Create Vendor (action: vendor.create) ---
# POST http://localhost:8001/provisioning/vendors
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "name": "Policy Test Vendor",
    "contact_email": "vendor@policytest.com",
    "description": "Testing policy gate"
}

# --- 5e. Create Cost Centre (action: cost_centre.create) ---
# POST http://localhost:8001/provisioning/cost-centres
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "code": "POLICY-CC-01",
    "name": "Policy Test Cost Centre",
    "budget_amount_minor": 1000000,
    "fiscal_year": 2026,
    "period_start": "2026-01-01",
    "period_end": "2026-12-31",
    "period_type": "yearly",
    "period_number": 1,
    "created_by": "8ed16f26-80df-4028-8459-25d94f222dfb"
}

# --- 5f. Create Org Unit (action: org_unit.create) ---
# POST http://localhost:8001/provisioning/org_units
{
    "tenant_id": "532b8f16-debb-4e74-a509-e686a6bf7acd",
    "name": "Policy Test Department",
    "type": "department",
    "status": "active"
}


# ============================================================================
# STEP 6: OTHER CRUD ENDPOINTS
# ============================================================================

# --- 6a. List all policies ---
# GET http://localhost:8004/policies
# GET http://localhost:8004/policies?is_active=true
# GET http://localhost:8004/policies?policy_type=budget
# GET http://localhost:8004/policies?tenant_id=532b8f16-debb-4e74-a509-e686a6bf7acd

# --- 6b. Get single policy ---
# GET http://localhost:8004/policies/<POLICY_ID>

# --- 6c. Update policy (metadata only) ---
# PUT http://localhost:8004/policies/<POLICY_ID>
{
    "name": "Updated Budget Policy Name",
    "priority": 8
}

# --- 6d. Update policy (with new version + rules) ---
# PUT http://localhost:8004/policies/<POLICY_ID>
{
    "name": "Budget Policy v2",
    "change_reason": "Lowered threshold",
    "rules": [
        {
            "rule_order": 0,
            "name": "Budget Insufficient v2",
            "condition_expression": "subject.budget_remaining < resource.order_total",
            "effect": "deny",
            "denial_reason": "Budget too low. Available: {budget_remaining}"
        },
        {
            "rule_order": 1,
            "name": "Minimum order value",
            "condition_expression": "resource.order_total < 100",
            "effect": "deny",
            "denial_reason": "Minimum order value is 100 minor units"
        }
    ]
}

# --- 6e. Soft-delete policy ---
# DELETE http://localhost:8004/policies/<POLICY_ID>
# Response: { "policy_id": "...", "status": "archived" }

# --- 6f. Add a rule to existing policy ---
# POST http://localhost:8004/policies/<POLICY_ID>/rules
{
    "rule_order": 2,
    "name": "Block zero-amount orders",
    "condition_expression": "resource.order_total <= 0",
    "effect": "deny",
    "denial_reason": "Order total must be greater than zero"
}

# --- 6g. Update a rule ---
# PUT http://localhost:8004/policies/<POLICY_ID>/rules/<RULE_ID>
{
    "denial_reason": "Updated denial message: order total must be positive"
}

# --- 6h. Deactivate a rule ---
# DELETE http://localhost:8004/policies/<POLICY_ID>/rules/<RULE_ID>
# Response: { "rule_id": "...", "is_active": false }

# --- 6i. List assignments ---
# GET http://localhost:8004/policies/<POLICY_ID>/assignments

# --- 6j. Deactivate assignment ---
# DELETE http://localhost:8004/policies/<POLICY_ID>/assignments/<ASSIGNMENT_ID>

# --- 6k. View audit log ---
# GET http://localhost:8004/policy-decisions
# GET http://localhost:8004/policy-decisions?tenant_id=532b8f16-debb-4e74-a509-e686a6bf7acd
# GET http://localhost:8004/policy-decisions?action=order.create
# GET http://localhost:8004/policy-decisions?decision=deny
# GET http://localhost:8004/policy-decisions?user_id=8ed16f26-80df-4028-8459-25d94f222dfb


# ============================================================================
# TESTING SEQUENCE (recommended order)
# ============================================================================
# 1. Start policy engine:       python -m uvicorn policy_service.main:app --port 8004
# 2. Start provisioning service: python -m uvicorn provisioning_service.main:app --port 8001
# 3. POST /policies/seed        → seeds 8 global default policies
# 4. POST /policies             → create the 6 custom policies from Step 2
# 5. POST /policies/<id>/assignments → create assignments from Step 3
# 6. POST /evaluate             → test directly with Step 4 payloads
# 7. POST /provisioning/*       → test via provisioning endpoints (Step 5)
#    - With active subscription → should ALLOW
#    - Without subscription    → should DENY (403)
#    - Cross-tenant resource   → should DENY (403)
# 8. GET /policy-decisions      → verify audit trail logged all evaluations

