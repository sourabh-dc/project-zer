package purchase_orders.manage

import data.common.tenant.same_tenant

default allow = false
default reasons = ["purchase order policy denied"]

allow {
    same_tenant
    input.action == "read"
    input.user.roles[_] == "vendor"
}

allow {
    same_tenant
    input.action == "acknowledge"
    input.user.roles[_] == "vendor"
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
