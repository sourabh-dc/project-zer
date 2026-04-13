# ------------------------------------------------------------------
# shared/opa_policies/zeroque/orders.rego
# ------------------------------------------------------------------
# Policies for orders_service mutating endpoints.
# Evaluated via: POST /v1/data/zeroque/orders/allow
# ------------------------------------------------------------------
package zeroque.orders

import rego.v1
import data.zeroque.common

default allow := false
default decision := "deny"
default reason := "Access denied by default policy"

# ── ALLOW ─────────────────────────────────────────────────────────

allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission(input.action)
}

allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.is_tenant_admin
}

# ── DENY overrides ────────────────────────────────────────────────

deny_cross_tenant if {
    common.is_authenticated
    not common.same_tenant
}

deny_no_subscription if {
    common.is_authenticated
    not common.subscription_valid
}

deny_budget if {
    input.action == "order.create"
    input.resource.amount_minor > 0
    not common.budget_sufficient
}

# ── purchase request: approved products only ──────────────────────
deny_unapproved_product if {
    input.action == "purchase_request.create"
    input.resource.product_id
    not input.resource.product_id in input.subject.approved_product_ids
    input.subject.approved_product_ids != "__all__"
}

require_approval_large if {
    input.action == "order.create"
    input.resource.amount_minor > input.subject.max_order_limit_minor
}

# ── composite decision ────────────────────────────────────────────

decision := "deny" if deny_cross_tenant
decision := "deny" if deny_no_subscription
decision := "deny" if deny_budget
decision := "deny" if deny_unapproved_product
decision := "require_approval" if { require_approval_large; not deny_budget }
decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
    not deny_budget
    not deny_unapproved_product
}

reason := "Cross-tenant access is forbidden" if deny_cross_tenant
reason := "Active subscription required" if deny_no_subscription
reason := "Insufficient budget for this order" if deny_budget
reason := "Product not in approved range" if deny_unapproved_product
reason := "Order exceeds user limit — approval required" if require_approval_large
reason := "Allowed" if allow
