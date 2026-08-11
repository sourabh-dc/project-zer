# ------------------------------------------------------------------
# shared/opa_policies/zeroque/approval.rego
# ------------------------------------------------------------------
# Approval authority enforcement — Phase 3
#
# Validates that a user has the authority to approve a specific
# request based on their UserApprovalControl records:
#   - Scope match (organisation / site / cost_centre / department)
#   - Per-transaction limit
#   - Period limit
#   - Effective date range
#   - Active control
#
# Action namespaces:
#   approval.decide  — deciding on a specific approval request
#
# Resource context expected:
#   resource.user_id                 — the approver's user ID
#   resource.tenant_id               — tenant
#   resource.approval_scope_type     — scope type of the request
#   resource.approval_scope_id       — scope ID of the request
#   resource.transaction_amount_minor — value in minor units
#   resource.period_spent_minor       — cumulative period spend so far
#   resource.controls                — array of UserApprovalControl objects
#     [{
#       "scope_type": "...",
#       "scope_id": "...",
#       "max_transaction_minor": 500000,
#       "max_period_minor": 2000000,
#       "period_type": "monthly",
#       "period_start": "2026-01-01",
#       "period_end": null,
#       "escalation_user_id": "...",
#       "effective_from": "2026-01-01",
#       "effective_to": null,
#       "is_active": true
#     }]
# ------------------------------------------------------------------
package zeroque.approval

import rego.v1
import data.zeroque.common

# ── defaults ──────────────────────────────────────────────────────
default allow              := false
default decision           := "deny"
default reason             := "Approval authority not found or insufficient"
default escalation_user_id := ""

# ──────────────────────────────────────────────────────────────────
# ALLOW: User has a valid, active control matching the request
# ──────────────────────────────────────────────────────────────────

allow if {
    common.is_authenticated
    common.same_tenant
    common.subscription_valid
    matching_control
    within_transaction_limit
    within_period_limit
    within_effective_dates
}

# ──────────────────────────────────────────────────────────────────
# Find a matching control for this request
# ──────────────────────────────────────────────────────────────────

matching_control if {
    some ctrl in input.resource.controls
    ctrl.is_active == true
    scope_matches(ctrl)
}

# Scope matches if:
#   - control is org-wide (scope_type == "organisation"), OR
#   - control scope_type + scope_id match the request exactly
scope_matches(ctrl) if {
    ctrl.scope_type == "organisation"
}

scope_matches(ctrl) if {
    ctrl.scope_type == input.resource.approval_scope_type
    ctrl.scope_id == input.resource.approval_scope_id
}

# ──────────────────────────────────────────────────────────────────
# Within transaction limit
# ──────────────────────────────────────────────────────────────────

within_transaction_limit if {
    ctrl := best_matching_control
    ctrl.max_transaction_minor == null
}

within_transaction_limit if {
    ctrl := best_matching_control
    ctrl.max_transaction_minor != null
    input.resource.transaction_amount_minor <= ctrl.max_transaction_minor
}

# ──────────────────────────────────────────────────────────────────
# Within period limit (only enforced when both limits are set)
# ──────────────────────────────────────────────────────────────────

within_period_limit if {
    ctrl := best_matching_control
    ctrl.max_period_minor == null
}

within_period_limit if {
    ctrl := best_matching_control
    ctrl.max_period_minor != null
    input.resource.period_spent_minor + input.resource.transaction_amount_minor <= ctrl.max_period_minor
}

# ──────────────────────────────────────────────────────────────────
# Within effective dates
# ──────────────────────────────────────────────────────────────────

within_effective_dates if {
    ctrl := best_matching_control
    ctrl.effective_from == null
}

within_effective_dates if {
    ctrl := best_matching_control
    ctrl.effective_from != null
    not is_before_effective(ctrl)
}

within_effective_dates if {
    ctrl := best_matching_control
    ctrl.effective_to == null
}

within_effective_dates if {
    ctrl := best_matching_control
    ctrl.effective_to != null
    not is_after_expiry(ctrl)
}

# Pick the best matching control for limit evaluation
# Prefer the most specific scope match
best_matching_control := ctrl if {
    some ctrl in input.resource.controls
    ctrl.is_active == true
    scope_matches(ctrl)
    ctrl.scope_type != "organisation"
} else := ctrl if {
    some ctrl in input.resource.controls
    ctrl.is_active == true
    ctrl.scope_type == "organisation"
}

# ──────────────────────────────────────────────────────────────────
# DENY rules — specific reasons
# ──────────────────────────────────────────────────────────────────

deny_cross_tenant if {
    common.is_authenticated
    not common.same_tenant
}

deny_no_subscription if {
    common.is_authenticated
    not common.subscription_valid
}

deny_no_controls if {
    common.is_authenticated
    count(input.resource.controls) == 0
    reason := "No approval controls configured for this user"
    decision := "deny"
}

deny_no_matching_scope if {
    common.is_authenticated
    count(input.resource.controls) > 0
    not matching_control
    reason := "No approval control matches the requested scope"
    decision := "deny"
}

deny_exceeds_transaction_limit if {
    common.is_authenticated
    matching_control
    ctrl := best_matching_control
    ctrl.max_transaction_minor != null
    input.resource.transaction_amount_minor > ctrl.max_transaction_minor
    reason := sprintf("Transaction amount %d exceeds per-transaction limit %d",
        [input.resource.transaction_amount_minor, ctrl.max_transaction_minor])
    decision := "escalate"
    escalation_user_id = ctrl.escalation_user_id
}

deny_exceeds_period_limit if {
    common.is_authenticated
    matching_control
    ctrl := best_matching_control
    ctrl.max_period_minor != null
    input.resource.period_spent_minor + input.resource.transaction_amount_minor > ctrl.max_period_minor
    reason := sprintf("Period spend %d + this transaction %d exceeds period limit %d",
        [input.resource.period_spent_minor, input.resource.transaction_amount_minor, ctrl.max_period_minor])
    decision := "escalate"
    escalation_user_id = ctrl.escalation_user_id
}

# ──────────────────────────────────────────────────────────────────
# Decision and reason outputs
# ──────────────────────────────────────────────────────────────────

decision = "allow" if { allow }
reason   = ""       if { allow }

decision = "deny"   if { not allow }

# Helper: is the current date before effective_from?
is_before_effective(ctrl) if {
    ctrl.effective_from != null
    time.now_ns() / 1000000000 < time.parse_rfc3339_ns(sprintf("%sT00:00:00Z", [ctrl.effective_from])) / 1000000000
}

# Helper: is the current date after effective_to?
is_after_expiry(ctrl) if {
    ctrl.effective_to != null
    time.now_ns() / 1000000000 > time.parse_rfc3339_ns(sprintf("%sT23:59:59Z", [ctrl.effective_to])) / 1000000000
}
