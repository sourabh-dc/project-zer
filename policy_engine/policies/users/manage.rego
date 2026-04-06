package users.manage

import data.common.tenant
import data.rbac.roles

default allow = false

# Org admins can perform any user action within their tenant.
allow {
    tenant.same_tenant
    roles.is_admin
}

# Org managers can create/read users in their tenant (not delete).
allow {
    tenant.same_tenant
    roles.is_manager
    input.action != "delete"
}

# Any member can read users in their own org.
allow {
    tenant.same_tenant
    roles.is_member
    input.action == "read"
}

# Users can always read/update their own profile.
allow {
    tenant.same_tenant
    input.resource.user_id == input.user.user_id
    input.action in {"read", "update"}
}

# Deny reason helpers (optional — for structured denial messages).
reasons[msg] {
    not tenant.same_tenant
    msg := "tenant mismatch: user org does not match resource org"
}

reasons[msg] {
    tenant.same_tenant
    not roles.is_viewer
    msg := "insufficient role: at least org_viewer required"
}

reasons[msg] {
    tenant.same_tenant
    input.action == "delete"
    not roles.is_admin
    msg := "only org_admin can delete users"
}
