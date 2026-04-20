# ------------------------------------------------------------------
# shared/opa_policies/zeroque/procurement.rego
# ------------------------------------------------------------------
# Policies for purchase requests and approval policy CRUD.
# Evaluated via: POST /evaluate  (action namespace: purchase_request.* | approval_policy.*)
#
# Resource context expected per action (populated by resource_loaders.py):
#
#   purchase_request.create:
#     resource.tenant_id, resource.amount_minor, resource.cost_centre_id,
#     resource.cc_headroom_minor, resource.company_cap_headroom_minor,
#     resource.is_blocked, resource.block_reason,
#     resource.can_self_approve, resource.needs_approval
#
#   purchase_request.decide:
#     resource.tenant_id, resource.task_id,
#     resource.requester_id, resource.sox_sod_enforced
#
#   purchase_request.issue_po:
#     resource.tenant_id  (body / none)
#
#   approval_policy.create | approval_policy.delete:
#     resource.tenant_id  (body / none)
# ------------------------------------------------------------------
package zeroque.procurement

import rego.v1
import data.zeroque.common

# ── defaults ──────────────────────────────────────────────────────
default allow    := false
default decision := "deny"
default reason   := "Access denied by policy"

# ──────────────────────────────────────────────────────────────────
# SHARED: cross-cutting denials (evaluated for every action)
# ──────────────────────────────────────────────────────────────────

deny_cross_tenant if {
    common.is_authenticated
    not common.same_tenant
}

deny_no_subscription if {
    common.is_authenticated
    not common.subscription_valid
}

# ──────────────────────────────────────────────────────────────────
# purchase_request.create
# ──────────────────────────────────────────────────────────────────

# Deny: budget is hard-blocked (CC insufficient or company hard cap exceeded).
deny_budget_blocked if {
    input.action == "purchase_request.create"
    input.resource.is_blocked == true
}

# Require approval: user's window limits are breached — route to workflow.
require_approval_workflow if {
    input.action == "purchase_request.create"
    input.resource.is_blocked == false
    input.resource.needs_approval == true
}

# Allow: all limits within range — self-approve path.
allow_self_approve if {
    input.action == "purchase_request.create"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("orders.place")
    input.resource.is_blocked == false
    input.resource.can_self_approve == true
}

# ──────────────────────────────────────────────────────────────────
# purchase_request.decide  (approve / reject / escalate a task)
# ──────────────────────────────────────────────────────────────────

# Deny: SOX Segregation-of-Duties — requester cannot approve own request.
deny_sox_sod if {
    input.action == "purchase_request.decide"
    input.resource.sox_sod_enforced == true
    input.subject.user_id == input.resource.requester_id
}

allow_decide if {
    input.action == "purchase_request.decide"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("orders.approve")
    not deny_sox_sod
}

# ──────────────────────────────────────────────────────────────────
# purchase_request.issue_po
# ──────────────────────────────────────────────────────────────────

allow_issue_po if {
    input.action == "purchase_request.issue_po"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("orders.manage")
}

# ──────────────────────────────────────────────────────────────────
# approval_policy.create | approval_policy.delete
# ──────────────────────────────────────────────────────────────────

allow_approval_policy if {
    input.action in {"approval_policy.create", "approval_policy.delete"}
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("budget.manage")
}

# ──────────────────────────────────────────────────────────────────
# Composite allow (OR of all action-specific allows)
# ──────────────────────────────────────────────────────────────────

allow if allow_self_approve
allow if allow_decide
allow if allow_issue_po
allow if allow_approval_policy

# Tenant admins bypass action-specific permission checks.
allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.is_tenant_admin
    not deny_budget_blocked
    not deny_sox_sod
}

# ──────────────────────────────────────────────────────────────────
# Composite decision  (deny > require_approval > allow)
# ──────────────────────────────────────────────────────────────────

decision := "deny" if {
    deny_cross_tenant
}

decision := "deny" if {
    deny_no_subscription
}

decision := "deny" if {
    deny_budget_blocked
}

decision := "deny" if {
    deny_sox_sod
}

decision := "require_approval" if {
    require_approval_workflow
    not deny_cross_tenant
    not deny_no_subscription
}

decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
    not deny_budget_blocked
    not deny_sox_sod
}

# ──────────────────────────────────────────────────────────────────
# Reason strings
# ──────────────────────────────────────────────────────────────────

reason := "Cross-tenant access is forbidden"                                if deny_cross_tenant
reason := "Active subscription required"                                    if deny_no_subscription
reason := input.resource.block_reason                                       if { deny_budget_blocked; input.resource.block_reason != "" }
reason := "Budget is blocked"                                               if { deny_budget_blocked; not input.resource.block_reason }
reason := "SOX Segregation-of-Duties: requester cannot approve own request" if deny_sox_sod
reason := "Budget limits exceeded — routed for approval"                    if require_approval_workflow
reason := "Allowed"                                                         if allow
