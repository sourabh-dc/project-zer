"""
policy_engine
=============
Centralised OPA-based authorization for multi-tenant B2B SaaS.

Architecture:
  - Rego policies live in ``policies/`` (single source of truth, Git-managed)
  - Each service runs an **OPA sidecar** that loads these policies
  - FastAPI middleware queries the local sidecar at http://localhost:8181

Usage in any service::

    from policy_engine.middleware import require_policy

    @router.post("/sites")
    async def create_site(
        body: SiteCreate,
        user: UserContext = Depends(require_policy("create", "site")),
    ):
        ...

Two modes (controlled by ``POLICY_MODE`` env var):
  - ``opa``   — production; queries the OPA REST API
  - ``local`` — development/tests; evaluates rules in-process
"""

from policy_engine.client import check_policy  # noqa: F401
