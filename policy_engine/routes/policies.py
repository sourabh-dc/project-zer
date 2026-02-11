"""
Policy Management API Routes
CRUD operations for policies, versions, and rules.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from policy_engine.core.db_config import get_db
from policy_engine.core.redis_client import PolicyCache, get_cache
from policy_engine.Models import Policy, PolicyVersion, PolicyRule, PolicyAssignment
from policy_engine.Schemas import (
    PolicyCreate, PolicyUpdate, PolicyResponse, PolicyDetailResponse, PolicyListResponse,
    PolicyVersionCreate, PolicyVersionResponse, PolicyVersionDetailResponse,
    PolicyRuleResponse, PolicyAssignmentCreate, PolicyAssignmentResponse
)
from policy_engine.utils.logger import logger


router = APIRouter(prefix="/v1/policies", tags=["Policies"])


# =============================================================================
# Policy CRUD
# =============================================================================

@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    policy_data: PolicyCreate,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """
    Create a new policy.
    
    If rules are provided, creates the first version automatically.
    """
    # Check for duplicate code within tenant
    existing = db.query(Policy).filter(
        Policy.tenant_id == policy_data.tenant_id,
        Policy.code == policy_data.code
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Policy with code '{policy_data.code}' already exists"
        )
    
    # Create policy
    policy = Policy(
        policy_id=uuid.uuid4(),
        tenant_id=policy_data.tenant_id,
        code=policy_data.code,
        name=policy_data.name,
        description=policy_data.description,
        policy_type=policy_data.policy_type,
        priority=policy_data.priority,
        is_active=policy_data.is_active,
    )
    
    db.add(policy)
    
    # Create initial version if rules provided
    if policy_data.rules:
        version = PolicyVersion(
            version_id=uuid.uuid4(),
            policy_id=policy.policy_id,
            version_number=1,
            rules_json=[r.model_dump() for r in policy_data.rules],
            effective_from=datetime.now(timezone.utc),
            change_reason="Initial version"
        )
        db.add(version)
        
        # Create rule records
        for i, rule_data in enumerate(policy_data.rules):
            rule = PolicyRule(
                rule_id=uuid.uuid4(),
                version_id=version.version_id,
                rule_order=rule_data.rule_order or i,
                name=rule_data.name,
                description=rule_data.description,
                condition_expression=rule_data.condition_expression,
                effect=rule_data.effect,
                denial_reason=rule_data.denial_reason,
                approval_chain_id=rule_data.approval_chain_id,
                actions=rule_data.actions,
                is_active=rule_data.is_active
            )
            db.add(rule)
    
    db.commit()
    db.refresh(policy)
    
    # Invalidate cache
    if cache.is_connected:
        await cache.invalidate_tenant_policies(str(policy_data.tenant_id) if policy_data.tenant_id else "global")
    
    logger.info(f"Created policy: {policy.code} ({policy.policy_id})")
    
    return policy


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    policy_type: Optional[str] = Query(None, description="Filter by type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List policies with optional filters."""
    query = db.query(Policy)
    
    if tenant_id:
        query = query.filter(Policy.tenant_id == uuid.UUID(tenant_id))
    
    if policy_type:
        query = query.filter(Policy.policy_type == policy_type)
    
    if is_active is not None:
        query = query.filter(Policy.is_active == is_active)
    
    total = query.count()
    policies = query.order_by(Policy.priority, Policy.code).offset(offset).limit(limit).all()
    
    return PolicyListResponse(
        policies=[PolicyResponse.model_validate(p) for p in policies],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{policy_id}", response_model=PolicyDetailResponse)
async def get_policy(
    policy_id: str,
    db: Session = Depends(get_db)
):
    """Get a policy by ID with its current version and rules."""
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Get current version
    current_version = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy.policy_id,
        PolicyVersion.effective_until == None
    ).first()
    
    # Get version count
    version_count = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy.policy_id
    ).count()
    
    response = PolicyDetailResponse.model_validate(policy)
    response.version_count = version_count
    
    if current_version:
        # Get rules for current version
        rules = db.query(PolicyRule).filter(
            PolicyRule.version_id == current_version.version_id
        ).order_by(PolicyRule.rule_order).all()
        
        version_response = PolicyVersionDetailResponse.model_validate(current_version)
        version_response.rules = [PolicyRuleResponse.model_validate(r) for r in rules]
        response.current_version = version_response
    
    return response


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: str,
    policy_update: PolicyUpdate,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """Update policy metadata (not rules - use versions for that)."""
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Update fields
    update_data = policy_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)
    
    policy.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(policy)
    
    # Invalidate cache
    if cache.is_connected:
        await cache.invalidate_policy(policy_id, str(policy.tenant_id) if policy.tenant_id else None)
    
    logger.info(f"Updated policy: {policy.code} ({policy_id})")
    
    return policy


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """Delete a policy (soft delete by deactivating)."""
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Soft delete
    policy.is_active = False
    policy.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Invalidate cache
    if cache.is_connected:
        await cache.invalidate_policy(policy_id, str(policy.tenant_id) if policy.tenant_id else None)
    
    logger.info(f"Deleted (deactivated) policy: {policy.code} ({policy_id})")


# =============================================================================
# Policy Versions
# =============================================================================

@router.post("/{policy_id}/versions", response_model=PolicyVersionResponse, status_code=201)
async def create_policy_version(
    policy_id: str,
    version_data: PolicyVersionCreate,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """
    Create a new version of a policy with updated rules.
    
    The previous version is automatically marked as superseded.
    """
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    now = datetime.now(timezone.utc)
    
    # Mark current version as superseded
    current_version = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy.policy_id,
        PolicyVersion.effective_until == None
    ).first()
    
    next_version_number = 1
    if current_version:
        current_version.effective_until = now
        next_version_number = current_version.version_number + 1
    
    # Create new version
    new_version = PolicyVersion(
        version_id=uuid.uuid4(),
        policy_id=policy.policy_id,
        version_number=next_version_number,
        rules_json=[r.model_dump() for r in version_data.rules],
        effective_from=now,
        change_reason=version_data.change_reason
    )
    db.add(new_version)
    
    # Create rule records
    for i, rule_data in enumerate(version_data.rules):
        rule = PolicyRule(
            rule_id=uuid.uuid4(),
            version_id=new_version.version_id,
            rule_order=rule_data.rule_order or i,
            name=rule_data.name,
            description=rule_data.description,
            condition_expression=rule_data.condition_expression,
            effect=rule_data.effect,
            denial_reason=rule_data.denial_reason,
            approval_chain_id=rule_data.approval_chain_id,
            actions=rule_data.actions,
            is_active=rule_data.is_active
        )
        db.add(rule)
    
    policy.updated_at = now
    
    db.commit()
    db.refresh(new_version)
    
    # Invalidate cache
    if cache.is_connected:
        await cache.invalidate_policy(policy_id, str(policy.tenant_id) if policy.tenant_id else None)
    
    logger.info(f"Created version {next_version_number} for policy: {policy.code}")
    
    return new_version


@router.get("/{policy_id}/versions", response_model=List[PolicyVersionResponse])
async def list_policy_versions(
    policy_id: str,
    db: Session = Depends(get_db)
):
    """List all versions of a policy."""
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    versions = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy.policy_id
    ).order_by(PolicyVersion.version_number.desc()).all()
    
    return [PolicyVersionResponse.model_validate(v) for v in versions]


@router.get("/{policy_id}/versions/{version_number}", response_model=PolicyVersionDetailResponse)
async def get_policy_version(
    policy_id: str,
    version_number: int,
    db: Session = Depends(get_db)
):
    """Get a specific version of a policy with its rules."""
    version = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == uuid.UUID(policy_id),
        PolicyVersion.version_number == version_number
    ).first()
    
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    rules = db.query(PolicyRule).filter(
        PolicyRule.version_id == version.version_id
    ).order_by(PolicyRule.rule_order).all()
    
    response = PolicyVersionDetailResponse.model_validate(version)
    response.rules = [PolicyRuleResponse.model_validate(r) for r in rules]
    
    return response


# =============================================================================
# Policy Assignments
# =============================================================================

@router.post("/{policy_id}/assignments", response_model=PolicyAssignmentResponse, status_code=201)
async def create_policy_assignment(
    policy_id: str,
    assignment_data: PolicyAssignmentCreate,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """
    Assign a policy to a specific scope.
    
    This determines where/when the policy applies.
    """
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    assignment = PolicyAssignment(
        assignment_id=uuid.uuid4(),
        policy_id=policy.policy_id,
        scope_type=assignment_data.scope_type,
        scope_id=assignment_data.scope_id,
        action_pattern=assignment_data.action_pattern,
        priority_override=assignment_data.priority_override,
        valid_from=assignment_data.valid_from,
        valid_until=assignment_data.valid_until,
        is_active=assignment_data.is_active
    )
    
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    
    # Invalidate cache
    if cache.is_connected:
        await cache.invalidate_policy(policy_id, str(policy.tenant_id) if policy.tenant_id else None)
    
    logger.info(f"Created assignment for policy {policy.code}: {assignment_data.scope_type}:{assignment_data.action_pattern}")
    
    return assignment


@router.get("/{policy_id}/assignments", response_model=List[PolicyAssignmentResponse])
async def list_policy_assignments(
    policy_id: str,
    db: Session = Depends(get_db)
):
    """List all assignments for a policy."""
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    assignments = db.query(PolicyAssignment).filter(
        PolicyAssignment.policy_id == policy.policy_id
    ).all()
    
    return [PolicyAssignmentResponse.model_validate(a) for a in assignments]


@router.delete("/{policy_id}/assignments/{assignment_id}", status_code=204)
async def delete_policy_assignment(
    policy_id: str,
    assignment_id: str,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """Delete a policy assignment."""
    assignment = db.query(PolicyAssignment).filter(
        PolicyAssignment.assignment_id == uuid.UUID(assignment_id),
        PolicyAssignment.policy_id == uuid.UUID(policy_id)
    ).first()
    
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    policy = db.query(Policy).filter(
        Policy.policy_id == uuid.UUID(policy_id)
    ).first()
    
    db.delete(assignment)
    db.commit()
    
    # Invalidate cache
    if cache.is_connected and policy:
        await cache.invalidate_policy(policy_id, str(policy.tenant_id) if policy.tenant_id else None)
    
    logger.info(f"Deleted assignment {assignment_id}")
