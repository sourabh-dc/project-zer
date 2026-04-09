package common.tenant

same_tenant {
    input.user.tenant_id == input.resource.tenant_id
}

has_tenant {
    input.user.tenant_id != ""
}
