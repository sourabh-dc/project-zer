# ------------------------------------------------------------------
# shared/opa_policies/zeroque/provisioning.rego
# ------------------------------------------------------------------
# Policies for provisioning_service mutating endpoints.
# Evaluated via: POST /v1/data/zeroque/provisioning/allow
# ------------------------------------------------------------------
package zeroque.provisioning

import rego.v1
import data.zeroque.common

# ── default deny ──────────────────────────────────────────────────
default allow := false
default decision := "deny"
default reason := "Access denied by default policy"

# ── ALLOW rules ───────────────────────────────────────────────────

# Tenant admins with a valid subscription can perform any mutation.
allow if {
    common.is_authenticated
    common.same_tenant
    common.is_tenant_admin
    common.subscription_valid
}

# Non-admin users with the specific permission and valid subscription.
allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission(input.action)
}

# ── DENY overrides (evaluated before allow in decision) ───────────

# Block cross-tenant mutations.
deny_cross_tenant if {
    common.is_authenticated
    not common.same_tenant
}

# Block if subscription is not active/trialing.
deny_no_subscription if {
    common.is_authenticated
    not common.subscription_valid
}

# ── site.create ───────────────────────────────────────────────────
deny_site_limit if {
    input.action == "site.create"
    input.resource.current_site_count >= input.resource.site_limit
}

# ── user.create ───────────────────────────────────────────────────
deny_user_limit if {
    input.action == "user.create"
    input.resource.current_user_count >= input.resource.user_limit
}

# ── order.create (budget check) ──────────────────────────────────
deny_budget_exceeded if {
    input.action == "order.create"
    input.resource.amount_minor > 0
    not common.budget_sufficient
}

require_approval_large_order if {
    input.action == "order.create"
    input.resource.amount_minor > input.subject.max_order_limit_minor
}

# ── composite decision ────────────────────────────────────────────
decision := "deny" if {
    deny_cross_tenant
    reason := "Cross-tenant access is forbidden"
}

decision := "deny" if {
    deny_no_subscription
    reason := "Active subscription required"
}

decision := "deny" if {
    deny_site_limit
    reason := "Site limit reached for current plan"
}

decision := "deny" if {
    deny_user_limit
    reason := "User limit reached for current plan"
}

decision := "deny" if {
    deny_budget_exceeded
    reason := "Insufficient budget"
}

decision := "require_approval" if {
    require_approval_large_order
    reason := "Order exceeds user limit — approval required"
}

decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
    not deny_site_limit
    not deny_user_limit
    not deny_budget_exceeded
}

reason := "Cross-tenant access is forbidden" if deny_cross_tenant
reason := "Active subscription required" if deny_no_subscription
reason := "Site limit reached for current plan" if deny_site_limit
reason := "User limit reached for current plan" if deny_user_limit
reason := "Insufficient budget" if deny_budget_exceeded
reason := "Order exceeds user limit — approval required" if require_approval_large_order
reason := "Allowed" if allow
