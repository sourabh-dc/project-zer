"""
policy_engine.client
--------------------
Talks to the OPA sidecar (production) or evaluates locally (dev/test).

Usage::

    from policy_engine.client import check_policy

    result = await check_policy(
        action="create",
        resource_type="user",
        user=user_context,
        resource={"org_id": "org_abc"},
    )
    if not result["allow"]:
        raise HTTPException(403, detail=result["reasons"])
"""
import logging
from typing import Any, Dict, Optional

import httpx

from policy_engine.config import POLICY_MODE, OPA_URL, POLICY_LOG_DECISIONS

logger = logging.getLogger("policy_engine.client")


def _build_input(
    action: str,
    resource_type: str,
    user: Dict[str, Any],
    resource: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the canonical OPA input document."""
    res = resource or {}
    res.setdefault("type", resource_type)
    return {
        "user": user,
        "action": action,
        "resource": res,
    }


async def check_policy(
    action: str,
    resource_type: str,
    user: Dict[str, Any],
    resource: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a policy and return ``{"allow": bool, "reasons": [...]}``.

    Dispatches to OPA sidecar or local evaluator depending on POLICY_MODE.
    """
    inp = _build_input(action, resource_type, user, resource)

    if POLICY_MODE == "opa":
        result = await _query_opa(resource_type, inp)
    else:
        from policy_engine.local_evaluator import evaluate
        result = evaluate(resource_type, action, inp)

    if POLICY_LOG_DECISIONS:
        verdict = "ALLOW" if result["allow"] else "DENY"
        logger.info(
            "%s %s/%s org=%s user=%s reasons=%s",
            verdict, resource_type, action,
            user.get("org_id", "?"), user.get("user_id", "?"),
            result.get("reasons", []),
        )

    return result


_POLICY_PATH_MAP = {
    "user": "users/manage",
    "role": "users/manage",
}


def _opa_path(resource_type: str) -> str:
    """Map a resource type to its OPA data path."""
    pkg = _POLICY_PATH_MAP.get(resource_type, f"{resource_type}s/manage")
    return f"{OPA_URL}/v1/data/{pkg}"


async def _query_opa(resource_type: str, inp: Dict[str, Any]) -> Dict[str, Any]:
    """POST to OPA REST API and return structured result."""
    url = _opa_path(resource_type)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(url, json={"input": inp})
        resp.raise_for_status()
        body = resp.json()

    result_data = body.get("result", {})
    return {
        "allow": result_data.get("allow", False),
        "reasons": list(result_data.get("reasons", [])),
    }
