# ------------------------------------------------------------------
# shared/opa_policies/zeroque/sod.rego
# ------------------------------------------------------------------
# Segregation of Duties enforcement — Phase 4
#
# Enforces:
#   1. Self-approval prevention — requester cannot approve own request
#   2. Strict SoD — tenant-level toggle, blocks delegation bypass,
#      blocks if no valid approver exists
#
# Action namespaces:
#   sod.check  — called before any approval decision
#
# Resource context expected:
#   resource.tenant_id
#   resource.requester_user_id
#   resource.approver_user_id
#   resource.strict_sod_enabled     (bool — from Tenant.strict_sod_enabled)
#   resource.is_delegated           (bool — whether this approval comes via delegation)
#   resource.delegator_user_id      (nullable — original delegator, if delegated)
# ------------------------------------------------------------------
package zeroque.sod

import rego.v1
import data.zeroque.common

# ── defaults ──────────────────────────────────────────────────────
default allow                 := true    # permit unless a rule blocks it
default decision              := "allow"
default reason                := ""
default requires_platform_ops := false

# ──────────────────────────────────────────────────────────────────
# BLOCK: self-approval — requester cannot approve their own request
# ──────────────────────────────────────────────────────────────────

block_self_approval if {
    input.resource.requester_user_id == input.resource.approver_user_id
}

deny_self_approval if {
    block_self_approval
    reason := "Self-approval is not permitted — the requester cannot approve their own request"
    decision := "block"
}

# ──────────────────────────────────────────────────────────────────
# BLOCK: delegation bypass under Strict SoD
# Under Strict SoD, a delegated approval cannot approve a request
# created by the original delegator (delegator → delegate → delegator's request)
# ──────────────────────────────────────────────────────────────────

block_delegation_sod_bypass if {
    input.resource.strict_sod_enabled == true
    input.resource.is_delegated == true
    input.resource.requester_user_id == input.resource.delegator_user_id
}

deny_delegation_sod_bypass if {
    block_delegation_sod_bypass
    reason := "Strict SoD: delegated authority cannot be used to approve the delegator's own request"
    decision := "block"
}

# ──────────────────────────────────────────────────────────────────
# BLOCK: strict SoD — if no valid approver route exists
# ──────────────────────────────────────────────────────────────────

block_no_valid_approver if {
    input.resource.strict_sod_enabled == true
    input.resource.valid_approver_count == 0
}

deny_no_valid_approver if {
    block_no_valid_approver
    reason := "Strict SoD: no valid approver exists for this request. An administrator must configure an approval route."
    decision := "block"
    requires_platform_ops := false
}

# ──────────────────────────────────────────────────────────────────
# WARN: strict SoD — only one valid approver (single point of failure)
# ──────────────────────────────────────────────────────────────────

warn_single_approver if {
    input.resource.strict_sod_enabled == true
    input.resource.valid_approver_count == 1
    reason := "Strict SoD warning: only one valid approver exists. Consider adding a fallback."
    decision := "warn"
}

# ──────────────────────────────────────────────────────────────────
# Final decision resolution
# ──────────────────────────────────────────────────────────────────

allow = false if {
    deny_self_approval
}

allow = false if {
    deny_delegation_sod_bypass
}

allow = false if {
    deny_no_valid_approver
}

decision = "block" if { deny_self_approval }
decision = "block" if { deny_delegation_sod_bypass }
decision = "block" if { deny_no_valid_approver }
decision = "warn"  if { warn_single_approver }
