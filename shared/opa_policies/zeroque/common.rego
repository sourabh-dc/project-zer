# ------------------------------------------------------------------
# shared/opa_policies/zeroque/common.rego
# ------------------------------------------------------------------
# Shared Rego helpers consumed by all domain-specific policy files.
# Loaded into OPA as part of the "zeroque" bundle.
# ------------------------------------------------------------------
package zeroque.common

import rego.v1

# ── identity helpers ──────────────────────────────────────────────

is_authenticated if {
    input.subject.user_id != ""
}

is_tenant_admin if {
    "tenant_admin" in input.subject.roles
}

has_permission(perm) if {
    "*" in input.subject.permissions
}

has_permission(perm) if {
    perm in input.subject.permissions
}

has_role(role) if {
    role in input.subject.roles
}

# ── tenant isolation ──────────────────────────────────────────────

# True when the resource belongs to the same tenant as the caller.
same_tenant if {
    input.subject.tenant_id == input.resource.tenant_id
}

# ── subscription helpers ──────────────────────────────────────────

subscription_active if {
    input.subject.subscription_active == true
}

subscription_trialing if {
    input.subject.subscription_status == "trialing"
}

subscription_valid if {
    subscription_active
}

subscription_valid if {
    subscription_trialing
}

# ── budget helpers ────────────────────────────────────────────────

budget_sufficient if {
    input.subject.budget_remaining >= input.resource.amount_minor
}

# ── time helpers ──────────────────────────────────────────────────

# current_time is injected by the OPA client as input.current_time
# (RFC 3339 string).  OPA's time.parse_rfc3339_ns can be used for
# advanced temporal policies.
