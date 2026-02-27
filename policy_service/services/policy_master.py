"""
Policy Master — CRUD endpoints for policies, versions, rules, assignments.
Also includes seed and decision-log endpoints.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from policy_service.Models import (
    Policy, PolicyVersion, PolicyRule, PolicyAssignment, PolicyDecisionLog,
)
from policy_service.Schemas import (
    PolicyCreate, PolicyUpdate,
    PolicyRuleCreate, PolicyRuleUpdate,
    PolicyAssignmentCreate,
)
from policy_service.core.db_config import get_db
from policy_service.utils.logger import logger

router = APIRouter(tags=["Policy Management"])


# =====================================================================
# Helpers
# =====================================================================

def _get_current_version(db: Session, policy_id: uuid.UUID) -> Optional[PolicyVersion]:
    """Return the current (open) version for a policy (effective_until IS NULL)."""
    return (
        db.query(PolicyVersion)
        .filter(PolicyVersion.policy_id == policy_id, PolicyVersion.effective_until == None)
        .first()
    )


def _policy_to_response(policy: Policy) -> dict:
    """Serialise a Policy ORM object to a response dict."""
    current_ver = None
    for v in (policy.versions or []):
        if v.effective_until is None:
            current_ver = v
            break

    ver_resp = None
    if current_ver:
        ver_resp = {
            "version_id": current_ver.version_id,
            "policy_id": current_ver.policy_id,
            "version_number": current_ver.version_number,
            "effective_from": current_ver.effective_from,
            "effective_until": current_ver.effective_until,
            "change_reason": current_ver.change_reason,
            "created_at": current_ver.created_at,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "version_id": r.version_id,
                    "rule_order": r.rule_order,
                    "name": r.name,
                    "condition_expression": r.condition_expression,
                    "effect": r.effect,
                    "denial_reason": r.denial_reason,
                    "approval_chain_id": r.approval_chain_id,
                    "actions": r.actions,
                    "is_active": r.is_active,
                    "created_at": r.created_at,
                }
                for r in (current_ver.rules or [])
                if r.is_active
            ],
        }

    return {
        "policy_id": policy.policy_id,
        "tenant_id": policy.tenant_id,
        "code": policy.code,
        "name": policy.name,
        "description": policy.description,
        "policy_type": policy.policy_type,
        "priority": policy.priority,
        "is_active": policy.is_active,
        "status": policy.status,
        "created_by": policy.created_by,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
        "current_version": ver_resp,
    }


# =====================================================================
# POLICY CRUD
# =====================================================================

@router.post("/policies", status_code=201)
async def create_policy(req: PolicyCreate, db: Session = Depends(get_db)):
    """Create a policy with an initial version and rules."""
    try:
        # Uniqueness check (tenant_id + code)
        existing = db.query(Policy).filter(
            Policy.code == req.code,
            Policy.tenant_id == req.tenant_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Policy code '{req.code}' already exists for this tenant")

        policy = Policy(
            policy_id=uuid.uuid4(),
            tenant_id=req.tenant_id,
            code=req.code,
            name=req.name,
            description=req.description,
            policy_type=req.policy_type,
            priority=req.priority,
            is_active=req.is_active,
            status=req.status,
            created_by=req.created_by,
        )
        db.add(policy)
        db.flush()

        # Create version 1
        version = PolicyVersion(
            version_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            version_number=1,
            change_reason=req.change_reason or "Initial version",
        )
        db.add(version)
        db.flush()

        # Create rules
        rules_json = []
        for rule_req in req.rules:
            rule = PolicyRule(
                rule_id=uuid.uuid4(),
                version_id=version.version_id,
                rule_order=rule_req.rule_order,
                name=rule_req.name,
                condition_expression=rule_req.condition_expression,
                effect=rule_req.effect,
                denial_reason=rule_req.denial_reason,
                approval_chain_id=rule_req.approval_chain_id,
                actions=rule_req.actions,
                is_active=rule_req.is_active,
            )
            db.add(rule)
            rules_json.append({
                "name": rule_req.name,
                "condition": rule_req.condition_expression,
                "effect": rule_req.effect,
                "order": rule_req.rule_order,
            })

        # Store denormalised copy
        version.rules_json = rules_json

        db.commit()
        db.refresh(policy)

        logger.info(f"Created policy {policy.code} ({policy.policy_id})")
        return _policy_to_response(policy)

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Create policy failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/policies")
async def list_policies(
    tenant_id: Optional[str] = Query(None),
    policy_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List policies with optional filters."""
    q = db.query(Policy)
    if tenant_id:
        q = q.filter((Policy.tenant_id == uuid.UUID(tenant_id)) | (Policy.tenant_id == None))
    if policy_type:
        q = q.filter(Policy.policy_type == policy_type)
    if is_active is not None:
        q = q.filter(Policy.is_active == is_active)

    total = q.count()
    policies = (
        q.options(joinedload(Policy.versions).joinedload(PolicyVersion.rules))
        .order_by(Policy.priority, Policy.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # deduplicate after joinedload (SQLAlchemy may return duplicates with joined eager loads)
    seen = set()
    unique_policies = []
    for p in policies:
        if p.policy_id not in seen:
            seen.add(p.policy_id)
            unique_policies.append(p)

    return {
        "policies": [_policy_to_response(p) for p in unique_policies],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str, db: Session = Depends(get_db)):
    """Get a single policy with current version and rules."""
    policy = (
        db.query(Policy)
        .options(joinedload(Policy.versions).joinedload(PolicyVersion.rules))
        .filter(Policy.policy_id == uuid.UUID(policy_id))
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return _policy_to_response(policy)


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, req: PolicyUpdate, db: Session = Depends(get_db)):
    """Update policy metadata. If `rules` is provided, a new version is created."""
    policy = db.query(Policy).filter(Policy.policy_id == uuid.UUID(policy_id)).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Update metadata
    if req.name is not None:
        policy.name = req.name
    if req.description is not None:
        policy.description = req.description
    if req.policy_type is not None:
        policy.policy_type = req.policy_type
    if req.priority is not None:
        policy.priority = req.priority
    if req.is_active is not None:
        policy.is_active = req.is_active
    if req.status is not None:
        policy.status = req.status

    # If rules provided → new version
    if req.rules is not None:
        # close current version
        current = _get_current_version(db, policy.policy_id)
        new_version_num = 1
        if current:
            current.effective_until = datetime.now(timezone.utc)
            new_version_num = current.version_number + 1

        new_ver = PolicyVersion(
            version_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            version_number=new_version_num,
            change_reason=req.change_reason or "Updated via API",
        )
        db.add(new_ver)
        db.flush()

        rules_json = []
        for rule_req in req.rules:
            rule = PolicyRule(
                rule_id=uuid.uuid4(),
                version_id=new_ver.version_id,
                rule_order=rule_req.rule_order,
                name=rule_req.name,
                condition_expression=rule_req.condition_expression,
                effect=rule_req.effect,
                denial_reason=rule_req.denial_reason,
                approval_chain_id=rule_req.approval_chain_id,
                actions=rule_req.actions,
                is_active=rule_req.is_active,
            )
            db.add(rule)
            rules_json.append({
                "name": rule_req.name,
                "condition": rule_req.condition_expression,
                "effect": rule_req.effect,
                "order": rule_req.rule_order,
            })
        new_ver.rules_json = rules_json

    db.commit()
    db.refresh(policy)

    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}", status_code=200)
async def delete_policy(policy_id: str, db: Session = Depends(get_db)):
    """Soft-delete a policy (archive it)."""
    policy = db.query(Policy).filter(Policy.policy_id == uuid.UUID(policy_id)).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy.status = "archived"
    policy.is_active = False
    db.commit()

    logger.info(f"Archived policy {policy.code} ({policy.policy_id})")
    return {"policy_id": str(policy.policy_id), "status": "archived"}


# =====================================================================
# RULES (on current version)
# =====================================================================

@router.post("/policies/{policy_id}/rules", status_code=201)
async def add_rule(policy_id: str, req: PolicyRuleCreate, db: Session = Depends(get_db)):
    """Add a rule to the current version of a policy."""
    version = _get_current_version(db, uuid.UUID(policy_id))
    if not version:
        raise HTTPException(status_code=404, detail="No active version found for this policy")

    rule = PolicyRule(
        rule_id=uuid.uuid4(),
        version_id=version.version_id,
        rule_order=req.rule_order,
        name=req.name,
        condition_expression=req.condition_expression,
        effect=req.effect,
        denial_reason=req.denial_reason,
        approval_chain_id=req.approval_chain_id,
        actions=req.actions,
        is_active=req.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return {
        "rule_id": str(rule.rule_id),
        "version_id": str(rule.version_id),
        "name": rule.name,
        "effect": rule.effect,
        "created_at": rule.created_at.isoformat(),
    }


@router.put("/policies/{policy_id}/rules/{rule_id}")
async def update_rule(policy_id: str, rule_id: str, req: PolicyRuleUpdate, db: Session = Depends(get_db)):
    """Update a single rule."""
    rule = db.query(PolicyRule).filter(PolicyRule.rule_id == uuid.UUID(rule_id)).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)

    db.commit()
    db.refresh(rule)

    return {
        "rule_id": str(rule.rule_id),
        "name": rule.name,
        "effect": rule.effect,
        "is_active": rule.is_active,
    }


@router.delete("/policies/{policy_id}/rules/{rule_id}", status_code=200)
async def delete_rule(policy_id: str, rule_id: str, db: Session = Depends(get_db)):
    """Soft-delete a rule (deactivate it)."""
    rule = db.query(PolicyRule).filter(PolicyRule.rule_id == uuid.UUID(rule_id)).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_active = False
    db.commit()
    return {"rule_id": str(rule.rule_id), "is_active": False}


# =====================================================================
# ASSIGNMENTS
# =====================================================================

@router.post("/policies/{policy_id}/assignments", status_code=201)
async def create_assignment(policy_id: str, req: PolicyAssignmentCreate, db: Session = Depends(get_db)):
    """Create a policy assignment (scoping)."""
    policy = db.query(Policy).filter(Policy.policy_id == uuid.UUID(policy_id)).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    assignment = PolicyAssignment(
        assignment_id=uuid.uuid4(),
        policy_id=policy.policy_id,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        action_pattern=req.action_pattern,
        priority_override=req.priority_override,
        is_active=req.is_active,
        valid_from=req.valid_from,
        valid_until=req.valid_until,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "assignment_id": str(assignment.assignment_id),
        "policy_id": str(assignment.policy_id),
        "scope_type": assignment.scope_type,
        "action_pattern": assignment.action_pattern,
        "is_active": assignment.is_active,
    }


@router.get("/policies/{policy_id}/assignments")
async def list_assignments(policy_id: str, db: Session = Depends(get_db)):
    """List all assignments for a policy."""
    assignments = (
        db.query(PolicyAssignment)
        .filter(PolicyAssignment.policy_id == uuid.UUID(policy_id))
        .order_by(PolicyAssignment.created_at.desc())
        .all()
    )
    return {
        "policy_id": policy_id,
        "assignments": [
            {
                "assignment_id": str(a.assignment_id),
                "scope_type": a.scope_type,
                "scope_id": str(a.scope_id) if a.scope_id else None,
                "action_pattern": a.action_pattern,
                "priority_override": a.priority_override,
                "is_active": a.is_active,
                "valid_from": a.valid_from.isoformat() if a.valid_from else None,
                "valid_until": a.valid_until.isoformat() if a.valid_until else None,
            }
            for a in assignments
        ],
    }


@router.delete("/policies/{policy_id}/assignments/{assignment_id}", status_code=200)
async def delete_assignment(policy_id: str, assignment_id: str, db: Session = Depends(get_db)):
    """Deactivate a policy assignment."""
    assignment = db.query(PolicyAssignment).filter(
        PolicyAssignment.assignment_id == uuid.UUID(assignment_id),
        PolicyAssignment.policy_id == uuid.UUID(policy_id),
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    assignment.is_active = False
    db.commit()
    return {"assignment_id": str(assignment.assignment_id), "is_active": False}


# =====================================================================
# DECISION LOG (audit)
# =====================================================================

@router.get("/policy-decisions")
async def list_decisions(
    tenant_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List policy decision logs (audit trail) with filters."""
    q = db.query(PolicyDecisionLog)
    if tenant_id:
        q = q.filter(PolicyDecisionLog.tenant_id == uuid.UUID(tenant_id))
    if action:
        q = q.filter(PolicyDecisionLog.action == action)
    if user_id:
        q = q.filter(PolicyDecisionLog.user_id == uuid.UUID(user_id))
    if decision:
        q = q.filter(PolicyDecisionLog.decision == decision)

    total = q.count()
    logs = q.order_by(PolicyDecisionLog.evaluated_at.desc()).offset(skip).limit(limit).all()

    return {
        "decisions": [
            {
                "decision_id": str(log.decision_id),
                "tenant_id": str(log.tenant_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "decision": log.decision,
                "reason": log.reason,
                "matched_policies": log.matched_policies,
                "evaluation_ms": log.evaluation_ms,
                "correlation_id": log.correlation_id,
                "evaluated_at": log.evaluated_at.isoformat(),
            }
            for log in logs
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# =====================================================================
# SEED default policies
# =====================================================================

# Default policies from the architecture doc §8.3
_DEFAULT_POLICIES: List[Dict[str, Any]] = [
    {
        "code": "entitlement.plan_limit",
        "name": "Plan Limit Check",
        "policy_type": "entitlement",
        "priority": 1,
        "rules": [{"name": "Plan limit exceeded", "condition": "resource.would_exceed_limit == True", "effect": "deny", "reason": "Plan limit exceeded for this feature"}],
        "action_pattern": "*",
    },
    {
        "code": "entitlement.subscription_required",
        "name": "Active Subscription Required",
        "policy_type": "entitlement",
        "priority": 2,
        "rules": [{"name": "No active subscription", "condition": "subject.subscription_active == False", "effect": "deny", "reason": "An active subscription is required"}],
        "action_pattern": "*",
    },
    {
        "code": "order.budget.check",
        "name": "Budget Limit Policy",
        "policy_type": "budget",
        "priority": 10,
        "rules": [{"name": "Budget exceeded", "condition": "subject.budget_remaining < resource.order_total", "effect": "deny", "reason": "Insufficient budget. Available: {subject.budget_remaining}"}],
        "action_pattern": "order.create",
    },
    {
        "code": "order.large_order_approval",
        "name": "Large Order Approval",
        "policy_type": "approval",
        "priority": 20,
        "rules": [{"name": "Order exceeds limit", "condition": "resource.order_total > subject.max_order_limit_minor", "effect": "require_approval", "reason": "Order exceeds your limit of {subject.max_order_limit_minor}"}],
        "action_pattern": "order.create",
    },
    {
        "code": "product.restriction",
        "name": "Restricted Product Policy",
        "policy_type": "product",
        "priority": 10,
        "rules": [{"name": "Restricted product", "condition": "resource.restricted == True", "effect": "deny", "reason": "This product is restricted and requires approval"}],
        "action_pattern": "product.purchase",
    },
    {
        "code": "discount.authorization",
        "name": "Discount Authorization",
        "policy_type": "approval",
        "priority": 30,
        "rules": [{"name": "Large discount approval", "condition": "resource.discount_percent > 20", "effect": "require_approval", "reason": "Discounts over 20% require approval"}],
        "action_pattern": "order.discount.apply",
    },
    {
        "code": "order.quantity_limit",
        "name": "Order Quantity Limit",
        "policy_type": "budget",
        "priority": 15,
        "rules": [{"name": "Quantity exceeded", "condition": "resource.quantity > 100", "effect": "deny", "reason": "Single order cannot exceed 100 items"}],
        "action_pattern": "order.create",
    },
    {
        "code": "cross_tenant.prevention",
        "name": "Cross-Tenant Prevention",
        "policy_type": "access",
        "priority": 0,
        "rules": [{"name": "Cross-tenant access", "condition": "subject.tenant_id != resource.tenant_id", "effect": "deny", "reason": "Cross-tenant access is not allowed"}],
        "action_pattern": "*",
    },
]


@router.post("/policies/seed")
async def seed_default_policies(db: Session = Depends(get_db)):
    """Seed the default (global) policies. Idempotent — skips existing codes."""
    seeded = 0
    skipped = 0
    details: List[str] = []

    for defn in _DEFAULT_POLICIES:
        existing = db.query(Policy).filter(Policy.code == defn["code"], Policy.tenant_id == None).first()
        if existing:
            skipped += 1
            details.append(f"Skipped (exists): {defn['code']}")
            continue

        policy = Policy(
            policy_id=uuid.uuid4(),
            tenant_id=None,
            code=defn["code"],
            name=defn["name"],
            policy_type=defn["policy_type"],
            priority=defn["priority"],
            is_active=True,
            status="active",
        )
        db.add(policy)
        db.flush()

        version = PolicyVersion(
            version_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            version_number=1,
            change_reason="Seeded default",
        )
        db.add(version)
        db.flush()

        for idx, rule_def in enumerate(defn["rules"]):
            rule = PolicyRule(
                rule_id=uuid.uuid4(),
                version_id=version.version_id,
                rule_order=idx,
                name=rule_def["name"],
                condition_expression=rule_def["condition"],
                effect=rule_def["effect"],
                denial_reason=rule_def.get("reason"),
                is_active=True,
            )
            db.add(rule)

        version.rules_json = defn["rules"]

        # Global assignment
        assignment = PolicyAssignment(
            assignment_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            scope_type="global",
            action_pattern=defn["action_pattern"],
            is_active=True,
        )
        db.add(assignment)

        seeded += 1
        details.append(f"Seeded: {defn['code']}")

    db.commit()
    logger.info(f"Policy seed: seeded={seeded}, skipped={skipped}")
    return {"seeded": seeded, "skipped": skipped, "details": details}

