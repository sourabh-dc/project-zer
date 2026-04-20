# ------------------------------------------------------------------
# shared/opa_policies/zeroque/vendor_integration.rego
# ------------------------------------------------------------------
# Policies for vendor integration, order dispatch, and vendor portal
# endpoints in procurement_service.
# Evaluated via: POST /v1/data/zeroque/vendor_integration
#
# Action namespaces:
#   vendor.update             — configure integration, update onboarding, test webhook
#   vendor.read               — get integration config
#   vendor.fulfillment_update — vendor portal: update fulfillment status
#   order.dispatch            — dispatch a PO to a vendor
#
# Resource context expected:
#   resource.tenant_id        — always injected by the policy client
# ------------------------------------------------------------------
package zeroque.vendor_integration

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
# vendor.update — configure integration protocol, endpoints, onboarding
#   and test webhook connectivity
# ──────────────────────────────────────────────────────────────────

allow_vendor_update if {
    input.action == "vendor.update"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("vendors.manage")
}

# ──────────────────────────────────────────────────────────────────
# vendor.read — get integration config
# ──────────────────────────────────────────────────────────────────

allow_vendor_read if {
    input.action == "vendor.read"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("vendors.manage")
}

# ──────────────────────────────────────────────────────────────────
# vendor.fulfillment_update — vendor portal: shipped / acknowledged / cancelled
# ──────────────────────────────────────────────────────────────────

allow_fulfillment_update if {
    input.action == "vendor.fulfillment_update"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("vendors.portal.update")
}

# ──────────────────────────────────────────────────────────────────
# order.dispatch — transmit a PO to a vendor via configured protocol
# ──────────────────────────────────────────────────────────────────

allow_order_dispatch if {
    input.action == "order.dispatch"
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.has_permission("orders.manage")
}

# ──────────────────────────────────────────────────────────────────
# Tenant admins bypass permission code checks for all actions above.
# ──────────────────────────────────────────────────────────────────

allow_admin if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    common.is_tenant_admin
}

# ──────────────────────────────────────────────────────────────────
# Composite allow
# ──────────────────────────────────────────────────────────────────

allow if allow_vendor_update
allow if allow_vendor_read
allow if allow_fulfillment_update
allow if allow_order_dispatch
allow if allow_admin

# ──────────────────────────────────────────────────────────────────
# Composite decision  (deny > allow)
# ──────────────────────────────────────────────────────────────────

decision := "deny" if deny_cross_tenant
decision := "deny" if deny_no_subscription

decision := "allow" if {
    allow
    not deny_cross_tenant
    not deny_no_subscription
}

# ──────────────────────────────────────────────────────────────────
# Reason strings
# ──────────────────────────────────────────────────────────────────

reason := "Cross-tenant access is forbidden" if deny_cross_tenant
reason := "Active subscription required"     if deny_no_subscription
reason := "Allowed"                          if allow
