"""
Policy Evaluator — the core evaluation endpoint.

POST /evaluate          — evaluate policies for an action and log the decision
POST /evaluate/dry-run  — same logic but does NOT log the decision
"""
import time
import uuid
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from policy_service.Models import (
    Policy, PolicyVersion, PolicyAssignment, PolicyDecisionLog,
)
from policy_service.Schemas import EvaluateRequest, EvaluateResponse
from policy_service.core.db_config import get_db
from policy_service.core.expression_parser import evaluate_condition, PolicyEvaluationError
from policy_service.core.context_enricher import enrich_subject
from policy_service.utils.logger import logger

router = APIRouter(prefix="/evaluate", tags=["Policy Evaluation"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_applicable_policies(
    db: Session,
    action: str,
    tenant_id: uuid.UUID,
) -> List[dict]:
    """Fetch active policies whose assignments match the given action and tenant.

    Returns a list of dicts:
      { "policy": <Policy>, "version": <PolicyVersion>, "rules": [<PolicyRule>], "priority": int }
    sorted by effective priority (lower first).
    """
    now = datetime.now(timezone.utc)

    # 1. Load all active assignments that are currently valid
    assignments = (
        db.query(PolicyAssignment)
        .join(Policy, PolicyAssignment.policy_id == Policy.policy_id)
        .filter(
            Policy.is_active == True,
            Policy.status == "active",
            PolicyAssignment.is_active == True,
        )
        .all()
    )

    # 2. Filter in-memory: action pattern match, scope, validity window
    matched_policy_ids: Dict[uuid.UUID, int] = {}  # policy_id → effective priority

    for assgn in assignments:
        # Action pattern match (fnmatch supports wildcards like "order.*")
        if not fnmatch(action, assgn.action_pattern):
            continue

        # Scope: global policies always apply; tenant-scoped must match tenant_id
        policy = assgn.policy
        if policy.tenant_id is not None and policy.tenant_id != tenant_id:
            continue

        # Validity window
        if assgn.valid_from and assgn.valid_from > now:
            continue
        if assgn.valid_until and assgn.valid_until < now:
            continue

        # Effective priority: use assignment override if present, else policy priority
        eff_priority = assgn.priority_override if assgn.priority_override is not None else policy.priority

        # Keep lowest priority per policy (in case multiple assignments match)
        if policy.policy_id not in matched_policy_ids or eff_priority < matched_policy_ids[policy.policy_id]:
            matched_policy_ids[policy.policy_id] = eff_priority

    if not matched_policy_ids:
        return []

    # 3. Load matched policies with current version + rules
    policies = (
        db.query(Policy)
        .options(joinedload(Policy.versions).joinedload(PolicyVersion.rules))
        .filter(Policy.policy_id.in_(list(matched_policy_ids.keys())))
        .all()
    )

    result = []
    for policy in policies:
        # Find current version (effective_until IS NULL)
        current_ver = None
        for v in policy.versions:
            if v.effective_until is None:
                current_ver = v
                break
        if not current_ver:
            continue

        active_rules = [r for r in current_ver.rules if r.is_active]
        if not active_rules:
            continue

        result.append({
            "policy": policy,
            "version": current_ver,
            "rules": sorted(active_rules, key=lambda r: r.rule_order),
            "priority": matched_policy_ids[policy.policy_id],
        })

    # Sort by priority (lower first)
    result.sort(key=lambda x: x["priority"])
    return result


def _evaluate_policies(
    applicable: List[dict],
    context: Dict[str, Any],
) -> dict:
    """Run rule evaluation across all applicable policies.

    Returns:
        {"decision": str, "reason": str, "matched": [{"code":..., "rule":..., "effect":...}]}

    Logic (deny-first):
      - For each policy (priority order), for each rule (rule_order):
        - Evaluate condition against context
        - If condition True:
          - "deny" → immediately return deny
          - "require_approval" → accumulate (will return if no deny found)
          - "allow" → note but keep going
      - If any require_approval accumulated → return require_approval
      - Otherwise → allow (default)
    """
    matched = []
    require_approval_reasons = []
    require_approval_info = []

    for entry in applicable:
        policy = entry["policy"]
        for rule in entry["rules"]:
            try:
                condition_met = evaluate_condition(rule.condition_expression, context)
            except PolicyEvaluationError as exc:
                logger.warning(f"Expression error in policy {policy.code}, rule {rule.name}: {exc}")
                continue

            if not condition_met:
                continue

            # Condition matched
            match_info = {
                "policy_code": policy.code,
                "policy_name": policy.name,
                "rule_name": rule.name,
                "effect": rule.effect,
            }

            if rule.effect == "deny":
                reason = rule.denial_reason or f"Denied by policy {policy.code}: {rule.name}"
                # Interpolate context values into reason string
                try:
                    reason = reason.format(**context.get("subject", {}), **context.get("resource", {}))
                except (KeyError, IndexError, ValueError):
                    pass
                matched.append(match_info)
                return {"decision": "deny", "reason": reason, "matched": matched}

            elif rule.effect == "require_approval":
                reason = rule.denial_reason or f"Approval required by policy {policy.code}: {rule.name}"
                try:
                    reason = reason.format(**context.get("subject", {}), **context.get("resource", {}))
                except (KeyError, IndexError, ValueError):
                    pass
                require_approval_reasons.append(reason)
                require_approval_info.append(match_info)

            elif rule.effect == "allow":
                matched.append(match_info)
                # continue evaluating other policies

    if require_approval_info:
        matched.extend(require_approval_info)
        return {
            "decision": "require_approval",
            "reason": "; ".join(require_approval_reasons),
            "matched": matched,
        }

    return {"decision": "allow", "reason": "All policies passed", "matched": matched}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=EvaluateResponse)
async def evaluate_policy(req: EvaluateRequest, db: Session = Depends(get_db)):
    """Evaluate all applicable policies for an action and log the decision."""
    return await _do_evaluate(req, db, dry_run=False)


@router.post("/dry-run", response_model=EvaluateResponse)
async def evaluate_policy_dry_run(req: EvaluateRequest, db: Session = Depends(get_db)):
    """Dry-run evaluation — same logic but does NOT log the decision."""
    return await _do_evaluate(req, db, dry_run=True)


async def _do_evaluate(req: EvaluateRequest, db: Session, dry_run: bool) -> dict:
    start = time.perf_counter()

    try:
        # 1. Enrich subject context from DB
        user_id = req.subject.get("user_id")
        if user_id:
            enriched = enrich_subject(db, user_id, str(req.tenant_id))
            # merge: request subject values override enriched (caller can override)
            merged_subject = {**enriched, **req.subject}
        else:
            merged_subject = req.subject

        context = {
            "subject": merged_subject,
            "resource": req.resource,
        }

        # 2. Fetch applicable policies
        applicable = _fetch_applicable_policies(db, req.action, req.tenant_id)

        # 3. Evaluate
        if not applicable:
            result = {"decision": "allow", "reason": "No applicable policies found", "matched": []}
        else:
            result = _evaluate_policies(applicable, context)

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # 4. Log decision (unless dry-run)
        if not dry_run:
            log_entry = PolicyDecisionLog(
                decision_id=uuid.uuid4(),
                tenant_id=req.tenant_id,
                user_id=uuid.UUID(user_id) if user_id else None,
                action=req.action,
                subject=merged_subject,
                resource=req.resource,
                decision=result["decision"],
                matched_policies=result["matched"],
                reason=result.get("reason"),
                evaluation_ms=elapsed_ms,
                correlation_id=req.correlation_id,
            )
            db.add(log_entry)
            db.commit()

        return {
            "decision": result["decision"],
            "allowed": result["decision"] == "allow",
            "reason": result.get("reason"),
            "matched_policies": result["matched"],
            "evaluation_ms": elapsed_ms,
            "correlation_id": req.correlation_id,
            "dry_run": dry_run,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Policy evaluation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Policy evaluation error: {str(exc)}")

