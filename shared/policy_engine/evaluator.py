"""
shared/policy_engine/evaluator.py
-----------------------------------
Core in-process policy evaluation.

Flow for every request:
  1. Enrich subject from shared DB (roles, budget, subscription, approved ranges)
  2. Resolve the OPA Rego package from the action code
  3. POST input document to OPA sidecar
  4. Write decision to policy_decisions audit table (best-effort)
  5. Return normalised result dict

OPA sidecar is configured via environment:
  OPA_URL     — default: http://localhost:8181
  OPA_TIMEOUT — default: 3.0 seconds
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .cache import cache_get, cache_set, USER_CONTEXT_TTL
from .context_enricher import enrich_subject

logger = logging.getLogger("policy_engine.evaluator")

OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
OPA_TIMEOUT = float(os.getenv("OPA_TIMEOUT", "3.0"))


# ---------------------------------------------------------------------------
# Action → OPA package mapping
# Exact matches are checked first; prefix rules are the fallback.
# ---------------------------------------------------------------------------

_EXACT_ACTION_PACKAGE: Dict[str, str] = {
    "vendor.update":             "zeroque/vendor_integration",
    "vendor.read":               "zeroque/vendor_integration",
    "vendor.fulfillment_update": "zeroque/vendor_integration",
    "order.dispatch":            "zeroque/vendor_integration",
}

_PREFIX_PACKAGE: List[Tuple[str, str]] = [
    ("purchase_request.",  "zeroque/procurement"),
    ("approval_policy.",   "zeroque/procurement"),
    ("order.",             "zeroque/orders"),
    ("budget.",            "zeroque/budget"),
    ("budget_change.",     "zeroque/budget"),
    ("user_budget.",       "zeroque/budget"),
    ("site.",              "zeroque/provisioning"),
    ("store.",             "zeroque/provisioning"),
    ("user.",              "zeroque/provisioning"),
    ("vendor.",            "zeroque/provisioning"),
    ("cost_centre.",       "zeroque/provisioning"),
    ("tenant.",            "zeroque/provisioning"),
]


def _resolve_package(action: str) -> str:
    """Return the OPA Rego package path for the given action code."""
    if action in _EXACT_ACTION_PACKAGE:
        return _EXACT_ACTION_PACKAGE[action]
    for prefix, package in _PREFIX_PACKAGE:
        if action.startswith(prefix):
            return package
    return "zeroque/provisioning"


# ---------------------------------------------------------------------------
# OPA call
# ---------------------------------------------------------------------------

async def _call_opa(
    package_path: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    action: str,
) -> Dict[str, Any]:
    url = f"{OPA_URL.rstrip('/')}/v1/data/{package_path}"
    payload = {
        "input": {
            "subject": subject,
            "resource": resource,
            "action": action,
            "current_time": datetime.now(timezone.utc).isoformat(),
        }
    }
    try:
        async with httpx.AsyncClient(timeout=OPA_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"OPA returned HTTP {resp.status_code}: {resp.text}")
        return resp.json().get("result", {})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="OPA policy evaluation timed out")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OPA unreachable: {str(exc)}")


# ---------------------------------------------------------------------------
# Decision log — best-effort write to policy_decisions table
# ---------------------------------------------------------------------------

def _write_decision_log(
    db: Session,
    *,
    tenant_id: str,
    user_id: Optional[str],
    action: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    decision: str,
    reason: Optional[str],
    package_path: str,
    correlation_id: Optional[str],
    evaluation_ms: int,
) -> None:
    try:
        db.execute(
            text("""
                INSERT INTO policy_decisions (
                    decision_id, tenant_id, user_id, action,
                    subject, resource, decision, matched_policies,
                    reason, evaluation_ms, correlation_id, evaluated_at
                ) VALUES (
                    :id, :tid, :uid, :action,
                    CAST(:subject AS jsonb), CAST(:resource AS jsonb),
                    :decision, CAST(:matched AS jsonb),
                    :reason, :ms, :corr, NOW()
                )
            """),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "uid": user_id,
                "action": action,
                "subject": json.dumps(subject, default=str),
                "resource": json.dumps(resource, default=str),
                "decision": decision,
                "matched": json.dumps([{"opa_package": package_path}]),
                "reason": reason,
                "ms": evaluation_ms,
                "corr": correlation_id,
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"Failed to write policy decision log: {exc}")
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def evaluate(
    db: Session,
    action: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    tenant_id: str,
    *,
    correlation_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Evaluate a policy action via OPA and return the decision.

    Parameters
    ----------
    db          : SQLAlchemy session connected to the shared PostgreSQL DB.
    action      : Action code, e.g. ``"order.create"``, ``"vendor.update"``.
    subject     : Caller identity from JWT / UserContext (merged with DB enrichment).
    resource    : Resource context (request body fields, pre-loaded quota data, etc.).
    tenant_id   : Tenant scope string (UUID).
    correlation_id : Optional tracing ID written to the decision log.
    dry_run     : When True, skips writing to the decision log.

    Returns
    -------
    dict with keys: decision, allowed, reason, matched_policies, evaluation_ms,
                    correlation_id.

    Raises
    ------
    HTTPException 502 — OPA unreachable.
    HTTPException 504 — OPA timed out.
    """
    start = time.perf_counter()

    # 1. Enrich subject with DB context (cached)
    user_id = subject.get("user_id")
    if user_id:
        cache_key = f"user_context:{user_id}"
        enriched = cache_get(cache_key)
        if enriched is None:
            enriched = enrich_subject(db, str(user_id), str(tenant_id))
            cache_set(cache_key, enriched, ttl=USER_CONTEXT_TTL)
        merged_subject = {**enriched, **subject}
    else:
        merged_subject = subject

    # 2. Resolve OPA package and evaluate
    package_path = _resolve_package(action)
    result = await _call_opa(package_path, merged_subject, resource, action)

    # 3. Normalise result
    decision = result.get("decision", "allow" if result.get("allow") else "deny")
    reason = result.get("reason", "Allowed" if decision == "allow" else "Denied by policy")
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    logger.debug(
        f"Policy [{action}] package={package_path} "
        f"decision={decision} ({elapsed_ms}ms)"
    )

    # 4. Audit log (best-effort)
    if not dry_run:
        _write_decision_log(
            db,
            tenant_id=str(tenant_id),
            user_id=str(user_id) if user_id else None,
            action=action,
            subject=merged_subject,
            resource=resource,
            decision=decision,
            reason=reason,
            package_path=package_path,
            correlation_id=correlation_id,
            evaluation_ms=elapsed_ms,
        )

    return {
        "decision": decision,
        "allowed": decision == "allow",
        "reason": reason,
        "matched_policies": [{"opa_package": package_path}],
        "evaluation_ms": elapsed_ms,
        "correlation_id": correlation_id,
    }
