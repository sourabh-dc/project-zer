"""
Policy Evaluator — proxies evaluation requests to the OPA sidecar.

All policy logic lives as Rego files in shared/opa_policies/.
This service enriches the subject context from the DB (roles, budget,
subscription, approved ranges) and then calls OPA for the decision.

POST /evaluate          — evaluate and log the decision
POST /evaluate/dry-run  — same logic, does NOT log the decision
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from policy_service.Models import PolicyDecisionLog
from policy_service.Schemas import EvaluateRequest, EvaluateResponse
from policy_service.core.config import SETTINGS
from policy_service.core.db_config import get_db
from policy_service.core.context_enricher import enrich_subject
from policy_service.core.cache import cache_get, cache_set, USER_CONTEXT_TTL
from policy_service.utils.logger import logger

router = APIRouter(prefix="/evaluate", tags=["Policy Evaluation"])


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
    """Return the OPA package path for the given action code."""
    if action in _EXACT_ACTION_PACKAGE:
        return _EXACT_ACTION_PACKAGE[action]
    for prefix, package in _PREFIX_PACKAGE:
        if action.startswith(prefix):
            return package
    return "zeroque/provisioning"  # safe fallback


# ---------------------------------------------------------------------------
# OPA call
# ---------------------------------------------------------------------------

async def _call_opa(
    package_path: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    action: str,
) -> Dict[str, Any]:
    """POST to OPA sidecar and return the result document.

    Raises HTTPException on connectivity or evaluation errors.
    """
    url = f"{SETTINGS.OPA_URL.rstrip('/')}/v1/data/{package_path}"
    payload = {
        "input": {
            "subject": subject,
            "resource": resource,
            "action": action,
            "current_time": datetime.now(timezone.utc).isoformat(),
        }
    }

    try:
        async with httpx.AsyncClient(timeout=SETTINGS.OPA_TIMEOUT) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            logger.error(f"OPA returned {resp.status_code} for {package_path}: {resp.text}")
            raise HTTPException(
                status_code=502,
                detail=f"OPA evaluation error (HTTP {resp.status_code})",
            )

        return resp.json().get("result", {})

    except httpx.TimeoutException:
        logger.error(f"OPA timeout for action={action}")
        raise HTTPException(status_code=504, detail="OPA policy evaluation timed out")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"OPA call failed: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"OPA unreachable: {str(exc)}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=EvaluateResponse)
async def evaluate_policy(req: EvaluateRequest, db: Session = Depends(get_db)):
    """Evaluate all applicable policies via OPA and log the decision."""
    return await _do_evaluate(req, db, dry_run=False)


@router.post("/dry-run", response_model=EvaluateResponse)
async def evaluate_policy_dry_run(req: EvaluateRequest, db: Session = Depends(get_db)):
    """Dry-run evaluation — same logic but does NOT log the decision."""
    return await _do_evaluate(req, db, dry_run=True)


async def _do_evaluate(req: EvaluateRequest, db: Session, dry_run: bool) -> dict:
    start = time.perf_counter()

    try:
        # 1. Enrich subject context (check cache first, then DB)
        user_id = req.subject.get("user_id")
        if user_id:
            cache_key = f"user_context:{user_id}"
            enriched = cache_get(cache_key)
            if enriched is None:
                enriched = enrich_subject(db, user_id, str(req.tenant_id))
                cache_set(cache_key, enriched, ttl=USER_CONTEXT_TTL)
            merged_subject = {**enriched, **req.subject}
        else:
            merged_subject = req.subject

        # 2. Resolve OPA package and call OPA
        package_path = _resolve_package(req.action)
        result = await _call_opa(
            package_path=package_path,
            subject=merged_subject,
            resource=req.resource,
            action=req.action,
        )

        # 3. Normalise OPA result to our standard response shape
        #    OPA Rego files export: allow (bool), decision (str), reason (str)
        decision = result.get("decision", "deny" if not result.get("allow") else "allow")
        reason = result.get("reason", "Allowed" if decision == "allow" else "Denied by policy")

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # 4. Log decision (unless dry-run)
        if not dry_run:
            try:
                log_entry = PolicyDecisionLog(
                    decision_id=uuid.uuid4(),
                    tenant_id=req.tenant_id,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    action=req.action,
                    subject=merged_subject,
                    resource=req.resource,
                    decision=decision,
                    matched_policies=[{"opa_package": package_path}],
                    reason=reason,
                    evaluation_ms=elapsed_ms,
                    correlation_id=req.correlation_id,
                )
                db.add(log_entry)
                db.commit()
            except Exception as log_exc:
                logger.warning(f"Failed to write decision log: {log_exc}")
                db.rollback()

        return {
            "decision": decision,
            "allowed": decision == "allow",
            "reason": reason,
            "matched_policies": [{"opa_package": package_path}],
            "evaluation_ms": elapsed_ms,
            "correlation_id": req.correlation_id,
            "dry_run": dry_run,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Policy evaluation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Policy evaluation error: {str(exc)}")
