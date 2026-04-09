package invoices.manage

import data.common.tenant.same_tenant

default allow = false
default reasons = ["invoice policy denied"]

allow {
    same_tenant
    input.action == "create"
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
