# ------------------------------------------------------------------
# shared/opa_policies/zeroque/budget.rego
# ------------------------------------------------------------------
# Policies for all budget management, change requests, and user
# budget limit actions.
# Evaluated via: POST /evaluate
#
# Action namespaces:
#   budget.*              — company caps, CC versions, reallocation
#   budget_change.*       — mid-period change requests (bring-forward / top-up / realloc)
#   user_budget.*         — user→cost-centre assignments and spend limits
#
# Resource context expected per action (populated by resource_loaders.py):
#
#   budget.create_cap / budget.update_version / budget.create_version (base):
#     resource.tenant_id
#
#   budget.update_cap:
#     resource.tenant_id, resource.new_total_budget_minor,
#     resource.current_allocated, resource.hard_cap,
#     resource.would_underfund, resource.override_reason
#
#   budget.create_version:
#     resource.tenant_id, resource.budget_minor,
#     resource.cap_total_budget_minor (null if no cap),
#     resource.hard_cap, resource.would_exceed_cap,
#     resource.override_reason
#
#   budget.reallocate:
#     resource.tenant_id, resource.amount_minor,
#     resource.source_version_id (null = additive top-up),
#     resource.source_available_minor (null if no source)
#
#   budget_change.bring_forward:
#     resource.tenant_id, resource.amount_minor,
#     resource.from_available_minor
#
#   All others (create_cap, top_up, reallocation, decide,
#               user_budget.*):
#     resource.tenant_id
# ------------------------------------------------------------------
package zeroque.budget

import rego.v1
import data.zeroque.common

# ── defaults ──────────────────────────────────────────────────────
default allow    := false
default decision := "deny"
default reason   := "Access denied by policy"

# ──────────────────────────────────────────────────────────────────
# SHARED cross-cutting denials
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
# budget.update_cap  — new total must not fall below current allocated
# (hard cap: deny outright; soft cap: require override_reason)
# ──────────────────────────────────────────────────────────────────

deny_cap_would_underfund if {
    input.action == "budget.update_cap"
    input.resource.would_underfund == true
    input.resource.hard_cap == true
}

deny_cap_soft_underfund_no_override if {
    input.action == "budget.update_cap"
    input.resource.would_underfund == true
    input.resource.hard_cap == false
    input.resource.override_reason == ""
}

# ──────────────────────────────────────────────────────────────────
# budget.create_version  — check company cap headroom
# ──────────────────────────────────────────────────────────────────

deny_version_hard_cap if {
    input.action == "budget.create_version"
    input.resource.cap_total_budget_minor != null
    input.resource.hard_cap == true
    input.resource.would_exceed_cap == true
}

deny_version_soft_cap_no_override if {
    input.action == "budget.create_version"
    input.resource.cap_total_budget_minor != null
    input.resource.hard_cap == false
    input.resource.would_exceed_cap == true
    input.resource.override_reason == ""
}

# ──────────────────────────────────────────────────────────────────
# budget.reallocate  — source version must have sufficient headroom
# ──────────────────────────────────────────────────────────────────

deny_reallocate_insufficient if {
    input.action == "budget.reallocate"
    input.resource.source_version_id != null
    input.resource.source_available_minor < input.resource.amount_minor
}

# ──────────────────────────────────────────────────────────────────
# budget_change.bring_forward  — future period must have headroom
# ──────────────────────────────────────────────────────────────────

deny_bring_forward_insufficient if {
    input.action == "budget_change.bring_forward"
    input.resource.from_available_minor < input.resource.amount_minor
}

# ──────────────────────────────────────────────────────────────────
# RBAC allow: all budget actions require budget.manage or budget.request
# ──────────────────────────────────────────────────────────────────

_budget_manage_actions := {
    "budget.create_cap", "budget.update_cap",
    "budget.create_version", "budget.update_version",
    "budget.reallocate",
    "budget_change.decide",
    "user_budget.create_assignment", "user_budget.delete_assignment",
    "user_budget.create_limit", "user_budget.update_limit", "user_budget.delete_limit",
}

_budget_request_actions := {
    "budget_change.bring_forward",
    "budget_change.top_up",
    "budget_change.reallocation",
}

allow if {
    input.action in _budget_manage_actions
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("budget.manage")
}

allow if {
    input.action in _budget_request_actions
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("budget.request")
}

# Tenant admins bypass permission code checks.
allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.is_tenant_admin
}

# ──────────────────────────────────────────────────────────────────
# Composite decision  (deny > allow)
# ──────────────────────────────────────────────────────────────────

decision := "deny" if deny_cross_tenant
decision := "deny" if deny_no_subscription
decision := "deny" if deny_cap_would_underfund
decision := "deny" if deny_cap_soft_underfund_no_override
decision := "deny" if deny_version_hard_cap
decision := "deny" if deny_version_soft_cap_no_override
decision := "deny" if deny_reallocate_insufficient
decision := "deny" if deny_bring_forward_insufficient

decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
    not deny_cap_would_underfund
    not deny_cap_soft_underfund_no_override
    not deny_version_hard_cap
    not deny_version_soft_cap_no_override
    not deny_reallocate_insufficient
    not deny_bring_forward_insufficient
}

# ──────────────────────────────────────────────────────────────────
# Reason strings
# ──────────────────────────────────────────────────────────────────

reason := "Cross-tenant access is forbidden"                                     if deny_cross_tenant
reason := "Active subscription required"                                         if deny_no_subscription
reason := "Cannot reduce company cap below currently allocated cost-centre total" if deny_cap_would_underfund
reason := "Company soft cap would be breached: provide override_reason to confirm" if deny_cap_soft_underfund_no_override
reason := "Company hard budget cap would be exceeded by this allocation"          if deny_version_hard_cap
reason := "Company soft cap exceeded: provide override_reason to confirm"         if deny_version_soft_cap_no_override
reason := "Insufficient available budget in source version"                       if deny_reallocate_insufficient
reason := "Future period has insufficient budget to bring forward"                if deny_bring_forward_insufficient
reason := "Allowed"                                                               if allow
