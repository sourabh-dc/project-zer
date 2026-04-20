# ------------------------------------------------------------------
# shared/opa_policies/zeroque/provisioning.rego
# ------------------------------------------------------------------
# Policies for provisioning_service mutating endpoints.
# Evaluated via: POST /evaluate
#
# Action namespaces: tenant.* | site.* | store.* | user.* |
#                    vendor.* | cost_centre.*
#
# Resource context expected for quota-gated create actions
# (populated by entitlement_resource_loader in resource_loaders.py):
#
#   resource.tenant_id
#   resource.subscription_active   bool
#   resource.feature_code          e.g. "sites.manage"
#   resource.feature_in_plan       bool
#   resource.current_count         int  (SubscriptionUsage.usage_count)
#   resource.feature_limit         int | null  (null = unlimited)
#
# All other mutating actions only need resource.tenant_id.
# ------------------------------------------------------------------
package zeroque.provisioning

import rego.v1
import data.zeroque.common

# ── defaults ──────────────────────────────────────────────────────
default allow    := false
default decision := "deny"
default reason   := "Access denied by default policy"

# ──────────────────────────────────────────────────────────────────
# ALLOW rules
# ──────────────────────────────────────────────────────────────────

# Tenant admins with valid subscription can perform any provisioning mutation.
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

# ──────────────────────────────────────────────────────────────────
# DENY: cross-cutting
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
# DENY: quota / entitlement checks for resource-creation actions
# ──────────────────────────────────────────────────────────────────

_quota_gated_actions := {
    "site.create", "store.create", "user.create",
    "vendor.create", "cost_centre.create",
}

# Feature not included in the tenant's current plan.
deny_feature_not_in_plan if {
    input.action in _quota_gated_actions
    input.resource.feature_in_plan == false
}

# Tenant has reached their plan quota for this resource type.
deny_quota_exceeded if {
    input.action in _quota_gated_actions
    input.resource.feature_limit != null
    input.resource.current_count >= input.resource.feature_limit
}

# Convenience aliases kept for backwards compatibility with
# callers that check specific deny reasons.
deny_site_limit  if { input.action == "site.create";        deny_quota_exceeded }
deny_store_limit if { input.action == "store.create";       deny_quota_exceeded }
deny_user_limit  if { input.action == "user.create";        deny_quota_exceeded }
deny_vendor_limit       if { input.action == "vendor.create";       deny_quota_exceeded }
deny_cost_centre_limit  if { input.action == "cost_centre.create";  deny_quota_exceeded }

# ──────────────────────────────────────────────────────────────────
# Composite decision  (deny > allow)
# ──────────────────────────────────────────────────────────────────

decision := "deny" if deny_cross_tenant
decision := "deny" if deny_no_subscription
decision := "deny" if deny_feature_not_in_plan
decision := "deny" if deny_quota_exceeded

decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
    not deny_feature_not_in_plan
    not deny_quota_exceeded
}

# ──────────────────────────────────────────────────────────────────
# Reason strings
# ──────────────────────────────────────────────────────────────────

reason := "Cross-tenant access is forbidden"           if deny_cross_tenant
reason := "Active subscription required"               if deny_no_subscription
reason := "Feature not available in your current plan" if deny_feature_not_in_plan
reason := "Plan quota reached for this resource type"  if deny_quota_exceeded
reason := "Allowed"                                    if allow
