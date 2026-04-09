package ops.manage

import data.common.tenant.same_tenant

default allow = false
default reasons = ["ops policy denied"]

allow {
    same_tenant
    input.user.roles[_] == "ops"
}

allow {
    same_tenant
    input.user.roles[_] == "admin"
}

allow {
    same_tenant
    input.user.permissions[_] == "*"
}

reasons = [] {
    allow
}

reasons = ["ops role required"] {
    not allow
}
