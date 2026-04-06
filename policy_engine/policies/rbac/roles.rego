package rbac.roles

# ---------------------------------------------------------------------------
# Role hierarchy and permission derivation.
#
# Role ladder (each level inherits all permissions below it):
#   org_admin  >  org_manager  >  org_member  >  org_viewer
# ---------------------------------------------------------------------------

import data.common.tenant

# Ordered from most to least privileged.
role_rank := {
    "org_admin":   40,
    "org_manager": 30,
    "org_member":  20,
    "org_viewer":  10,
}

# The caller's highest rank among their assigned roles.
user_max_rank := max_rank {
    ranks := [r | some role; role = input.user.roles[_]; r = role_rank[role]]
    max_rank := max(ranks)
}

user_max_rank := 0 {
    count(input.user.roles) == 0
}

is_admin {
    "org_admin" in input.user.roles
}

is_manager {
    user_max_rank >= role_rank["org_manager"]
}

is_member {
    user_max_rank >= role_rank["org_member"]
}

is_viewer {
    user_max_rank >= role_rank["org_viewer"]
}

# Derived permissions based on role.
# Services can query data.rbac.roles.effective_permissions.
effective_permissions[perm] {
    is_admin
    perm := "admin:*"
}

effective_permissions[perm] {
    is_manager
    perm := concat(":", ["manage", input.resource.type])
}

effective_permissions[perm] {
    is_member
    perm := concat(":", ["create", input.resource.type])
}

effective_permissions[perm] {
    is_member
    perm := concat(":", ["read", input.resource.type])
}

effective_permissions[perm] {
    is_viewer
    perm := concat(":", ["read", input.resource.type])
}
