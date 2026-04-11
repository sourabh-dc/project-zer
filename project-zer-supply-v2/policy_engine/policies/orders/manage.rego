package orders.manage

import data.common.tenant.same_tenant

default allow = false
default reasons = ["order policy denied"]

allow {
    same_tenant
    input.action == "create"
    input.user.roles[_] == "customer"
}

allow {
    same_tenant
    input.action == "read"
    input.user.roles[_] == "customer"
}

allow {
    same_tenant
    input.user.roles[_] == "ops"
}

allow {
    same_tenant
    input.user.roles[_] == "admin"
}

reasons = [] {
    allow
}
