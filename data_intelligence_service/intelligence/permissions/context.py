"""
Permission Context — build and cache user context for agent permission checks.

WHY reuse graph/queries/user_governance instead of shared/policy_engine?
  The shared/policy_engine.evaluate() requires:
    1. A SQLAlchemy session to the shared DB (for context enrichment)
    2. An OPA sidecar running (HTTP round-trip)
  
  The DIS already has all user governance data in the Neo4j graph
  (roles, permissions, org units, approved ranges). `get_user_context()` 
  in graph/queries/user_governance.py performs a single Cypher traversal 
  that is faster and doesn't need a second DB connection or OPA sidecar.

  For the intelligence query permission specifically, the check is:
    "Does this user's roles include ANY permission with code intelligence.query?"
  This is a simple graph lookup — no OPA policy logic needed.

  If the user has NO graph record (anonymous API key usage), we fall back 
  to a tenant-scoped context (no user-specific product filter).

WHY cache?
  get_user_context() hits Neo4j (network I/O). For multi-turn conversations,
  the same user will ask multiple questions in the same session. Caching for
  60 seconds avoids repeated graph traversals within a session.
"""
import time
from typing import Any, Dict, Optional, Union, List

from data_intelligence_service.core.logger import logger

# In-memory cache: {cache_key: (context_dict, expires_at)}
_cache: Dict[str, tuple] = {}
_TTL = 60  # seconds — same as shared/policy_engine/cache.py USER_CONTEXT_TTL


def _cache_get(key: str) -> Optional[Dict]:
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: str, value: Dict) -> None:
    _cache[key] = (value, time.monotonic() + _TTL)


def build_user_permission_context(
    user_id: Optional[str],
    tenant_id: str,
) -> Dict[str, Any]:
    """Return a permission context dict for the given user.

    Fetches from Neo4j graph (user governance) + approved product IDs.
    Cached for 60s per user.

    Returns a dict with:
      user_id           : str | None
      tenant_id         : str
      roles             : list of {role_id, code, name}
      permissions       : list of permission code strings
      org_units         : list of {org_unit_id, name, code}
      cost_centres      : list of {cost_centre_id, name, code}
      policies          : list of {policy_id, code, name}
      approved_ids      : "__all__" | list[str]  — product IDs the user may see
      is_admin          : bool  — True if user has tenant_admin role or "*" permission
    """
    if not user_id:
        # No user ID — API key-only call. No product filter, tenant-scoped only.
        return {
            "user_id":    None,
            "tenant_id":  tenant_id,
            "roles":      [],
            "permissions": [],
            "org_units":  [],
            "cost_centres": [],
            "policies":   [],
            "approved_ids": "__all__",
            "is_admin":   False,
        }

    cache_key = f"user_ctx:{tenant_id}:{user_id}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(f"[Permissions] Cache hit for user {user_id}")
        return cached

    ctx: Dict[str, Any] = {
        "user_id":         user_id,
        "tenant_id":       tenant_id,
        "roles":           [],
        "permissions":     [],
        "org_units":       [],
        "cost_centres":    [],
        "policies":        [],
        "approved_ids":    "__all__",
        "is_admin":        False,
        "graph_available": False,   # set True only when graph traversal succeeds
    }

    try:
        from data_intelligence_service.graph.queries.user_governance import get_user_context
        graph_ctx = get_user_context(user_id, tenant_id)
        ctx.update({
            "roles":           graph_ctx.get("roles", []),
            "permissions":     graph_ctx.get("permissions", []),
            "org_units":       graph_ctx.get("org_units", []),
            "cost_centres":    graph_ctx.get("cost_centres", []),
            "policies":        graph_ctx.get("policies", []),
            "graph_available": True,
        })
        # Admin check: tenant_admin role code OR wildcard "*" permission
        role_codes = {r.get("code", "") for r in ctx["roles"]}
        perms      = set(ctx["permissions"])
        ctx["is_admin"] = "tenant_admin" in role_codes or "*" in perms
    except Exception as exc:
        logger.warning(f"[Permissions] get_user_context failed (graph unavailable — fail-open): {exc}")
        # graph_available stays False — has_permission will fail-open

    try:
        from data_intelligence_service.graph.queries.approved_universe import get_approved_product_ids
        approved = get_approved_product_ids(
            tenant_id=tenant_id,
            user_id=user_id,
            is_admin=ctx["is_admin"],
        )
        ctx["approved_ids"] = approved
    except Exception as exc:
        logger.warning(f"[Permissions] get_approved_product_ids failed: {exc}")
        # Fail open — no product filter applied
        ctx["approved_ids"] = "__all__"

    _cache_set(cache_key, ctx)
    logger.info(
        f"[Permissions] user_ctx built: user={user_id} admin={ctx['is_admin']} "
        f"roles={len(ctx['roles'])} perms={len(ctx['permissions'])} "
        f"approved_ids={'__all__' if ctx['approved_ids'] == '__all__' else len(ctx['approved_ids'])}"
    )
    return ctx


def has_permission(ctx: Dict[str, Any], permission_code: str) -> bool:
    """Check if the context has a specific permission.

    WHY check against graph permissions?
      The graph already has role→permission edges (HAS_ROLE→GRANTS).
      get_user_context() traverses these and returns permission codes.
      No separate OPA call needed for simple permission checks.

    Admin users bypass all permission checks (wildcard "*").
    Anonymous users (no user_id) are allowed — API key is sufficient gate.

    WHY fail-open when graph is unavailable?
      The API key at middleware level is the primary auth gate. Graph-based
      permission checks are a bonus enforcement layer. If Neo4j is down, we
      cannot know whether the user lacks the permission — denying would block
      legitimate users unfairly. Log and allow; monitor via metrics.
    """
    if ctx.get("is_admin"):
        return True
    if ctx.get("user_id") is None:
        # Anonymous/API-key-only call — API key is sufficient gate
        return True
    if not ctx.get("graph_available"):
        # Graph was unavailable when context was built — can't enforce permissions
        # Fail-open: allow the query, log the gap for monitoring
        logger.warning(
            f"[Permissions] Graph unavailable for user {ctx.get('user_id')} — "
            f"failing open for '{permission_code}'"
        )
        return True
    return permission_code in set(ctx.get("permissions", []))


def get_approved_ids(ctx: Dict[str, Any]) -> Union[str, List[str]]:
    """Extract approved product IDs from context.

    Returns '__all__' for admins or when no restrictions apply.
    Returns [] if graph was unavailable and no fallback.
    """
    return ctx.get("approved_ids", "__all__")
