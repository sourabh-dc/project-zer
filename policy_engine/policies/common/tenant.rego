package common.tenant

# ---------------------------------------------------------------------------
# Shared tenant-isolation helpers — imported by every domain policy.
# ---------------------------------------------------------------------------

# True when the caller's org matches the target resource's org.
same_tenant {
    input.user.org_id == input.resource.org_id
}

# Convenience: check that org_id is present at all.
has_org {
    input.user.org_id != ""
}
