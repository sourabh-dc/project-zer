"""
policy_engine.local_evaluator
------------------------------
In-process Python re-implementation of the Rego policies for local
development and testing (no OPA binary required).

The rules here mirror the .rego files in policies/ exactly.
When POLICY_MODE=local this module is used instead of the OPA sidecar.
"""
from typing import Any, Dict, List


ROLE_RANK = {
    "org_admin":   40,
    "org_manager": 30,
    "org_member":  20,
    "org_viewer":  10,
}


def _max_rank(roles: List[str]) -> int:
    return max((ROLE_RANK.get(r, 0) for r in roles), default=0)


def _is_admin(roles: List[str]) -> bool:
    return "org_admin" in roles


def _is_manager(roles: List[str]) -> bool:
    return _max_rank(roles) >= ROLE_RANK["org_manager"]


def _is_member(roles: List[str]) -> bool:
    return _max_rank(roles) >= ROLE_RANK["org_member"]


def _is_viewer(roles: List[str]) -> bool:
    return _max_rank(roles) >= ROLE_RANK["org_viewer"]


def _same_tenant(user: Dict, resource: Dict) -> bool:
    u_org = user.get("org_id", "")
    r_org = resource.get("org_id", "")
    return bool(u_org) and u_org == r_org


def _eval_users(action: str, user: Dict, resource: Dict) -> Dict[str, Any]:
    roles = user.get("roles", [])
    reasons: List[str] = []

    if not _same_tenant(user, resource):
        return {"allow": False, "reasons": ["tenant mismatch: user org does not match resource org"]}

    if _is_admin(roles):
        return {"allow": True, "reasons": []}

    if _is_manager(roles) and action != "delete":
        return {"allow": True, "reasons": []}

    if _is_member(roles) and action == "read":
        return {"allow": True, "reasons": []}

    if resource.get("user_id") == user.get("user_id") and action in ("read", "update"):
        return {"allow": True, "reasons": []}

    if action == "delete" and not _is_admin(roles):
        reasons.append("only org_admin can delete users")
    elif not _is_viewer(roles):
        reasons.append("insufficient role: at least org_viewer required")
    else:
        reasons.append(f"role insufficient for action '{action}' on users")

    return {"allow": False, "reasons": reasons}


_EVALUATORS = {
    "user": _eval_users,
    "role": _eval_users,
}


def evaluate(
    resource_type: str,
    action: str,
    inp: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a policy decision locally (mirrors OPA Rego output)."""
    evaluator = _EVALUATORS.get(resource_type)
    if evaluator is None:
        return {"allow": False, "reasons": [f"no policy defined for resource type '{resource_type}'"]}

    return evaluator(action, inp["user"], inp["resource"])
