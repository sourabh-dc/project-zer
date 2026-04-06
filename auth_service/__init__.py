"""
auth_service — Multi-tenant authentication using Auth0 Organizations.

Each tenant = one Auth0 Organization. Users belong to organizations
and receive org-scoped roles. JWTs carry the org_id claim for
tenant-level data isolation in every API call.
"""
