"""
Entitlement Helpers - Feature usage limit enforcement

Provides:
- check_feature_limit(): Raises 429 if limit exceeded
- record_feature_usage(): Records usage after successful operation
- load_tenant_features(): Loads all features with usage for a tenant
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from provisioning_service.Models import (
    Tenant, TenantSubscription, PlanFeature, Feature, SubscriptionUsage, SubscriptionPlan, User,
    TenantIntegrationPack, IntegrationPackFeature, TenantSeatBlock
)
from provisioning_service.Schemas import FeatureUsage
from provisioning_service.utils.logger import logger


def get_reset_period_delta(reset_period: str) -> timedelta:
    """Get timedelta for reset period"""
    if reset_period == "daily":
        return timedelta(days=1)
    elif reset_period == "weekly":
        return timedelta(weeks=1)
    elif reset_period == "monthly":
        return timedelta(days=30)  # Approximate
    elif reset_period == "yearly":
        return timedelta(days=365)
    else:
        return timedelta(days=36500)  # ~100 years for 'none'


def get_period_boundaries(
    subscription_start: Optional[datetime],
    reset_period: str
) -> tuple[datetime, datetime]:
    """
    Calculate current period start and end based on subscription start and reset period.
    Anchors to subscription start date to maintain consistency.
    """
    now = datetime.now(timezone.utc)
    
    if not subscription_start:
        subscription_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if subscription_start.tzinfo is None:
        subscription_start = subscription_start.replace(tzinfo=timezone.utc)
    
    if reset_period == "none":
        # No reset - use far future
        return subscription_start, subscription_start + timedelta(days=36500)
    
    delta = get_reset_period_delta(reset_period)
    
    # Calculate how many periods have passed since subscription start
    elapsed = now - subscription_start
    periods_elapsed = int(elapsed.total_seconds() / delta.total_seconds())
    
    period_start = subscription_start + (delta * periods_elapsed)
    period_end = period_start + delta
    
    return period_start, period_end


def load_tenant_features(db: Session, tenant_id: str) -> tuple[bool, Optional[str], Optional[str], Dict[str, FeatureUsage]]:
    """
    Load all features with usage for a tenant, including from integration packs.
    
    Returns:
        (subscription_active, plan_code, plan_name, features_dict)
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        return False, None, None, {}
    
    # Get active subscription
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_uuid,
        TenantSubscription.is_active == True
    ).first()
    
    if not sub:
        return False, None, None, {}
    
    # Get plan info
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.code == sub.plan_code
    ).first()
    
    plan_name = plan.name if plan else sub.plan_code
    
    # Get all features in the base plan
    plan_features_query = db.query(PlanFeature, Feature).join(
        Feature, PlanFeature.feature_code == Feature.code
    ).filter(
        PlanFeature.plan_code == sub.plan_code,
        PlanFeature.enabled == True,
        Feature.active == True
    )
    
    # Get all features from active integration packs
    integration_pack_features_query = db.query(IntegrationPackFeature, Feature).join(
        Feature, IntegrationPackFeature.feature_code == Feature.code
    ).join(
        TenantIntegrationPack, and_(
            TenantIntegrationPack.pack_code == IntegrationPackFeature.pack_code,
            TenantIntegrationPack.tenant_id == tenant_uuid,
            TenantIntegrationPack.status == 'active'
        )
    )

    # Phase C4 — shared integration hub: inherit the parent tenant's
    # packs that are flagged shared_with_subtenants.
    shared_pack_features = []
    tenant_row = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    if tenant_row is not None and tenant_row.parent_tenant_id is not None:
        shared_pack_features = db.query(IntegrationPackFeature, Feature).join(
            Feature, IntegrationPackFeature.feature_code == Feature.code
        ).join(
            TenantIntegrationPack, and_(
                TenantIntegrationPack.pack_code == IntegrationPackFeature.pack_code,
                TenantIntegrationPack.tenant_id == tenant_row.parent_tenant_id,
                TenantIntegrationPack.status == 'active',
                TenantIntegrationPack.shared_with_subtenants == True,
            )
        ).all()

    # Combine plan features and integration pack features
    # For integration pack features, we create a "dummy" PlanFeature object
    # as the processing loop expects it for accessing limits.
    all_features = [
        (pf, feature) for pf, feature in plan_features_query.all()
    ]
    for ipf, feature in integration_pack_features_query.all() + shared_pack_features:
        # Avoid adding duplicates if a feature is somehow in both
        if not any(f.code == feature.code for _, f in all_features):
            mock_plan_feature = PlanFeature(enabled=True, limits={})
            all_features.append((mock_plan_feature, feature))

    features: Dict[str, FeatureUsage] = {}
    
    for pf, feature in all_features:
        # Calculate period boundaries
        period_start, period_end = get_period_boundaries(
            sub.current_period_start,
            feature.reset_period or "none"
        )
        
        # Get current usage for this period
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == tenant_uuid,
            SubscriptionUsage.feature_code == feature.code,
            SubscriptionUsage.period_start == period_start
        ).first()
        
        used = usage.usage_count if usage else 0
        
        # Limit precedence: plan_feature.limits.max_value > feature.max_unit
        limit = None
        if pf.limits and isinstance(pf.limits, dict):
            mv = pf.limits.get("max_value")
            if mv is not None:
                try:
                    limit = int(mv)
                except ValueError:
                    limit = None
        if limit is None and feature.max_unit:
            try:
                limit = int(feature.max_unit)
            except ValueError:
                limit = None  # Not a number, treat as unlimited
        
        remaining = None
        if limit is not None:
            remaining = max(0, limit - used)
        
        features[feature.code] = FeatureUsage(
            code=feature.code,
            name=feature.name,
            limit=limit,
            used=used,
            remaining=remaining,
            reset_period=feature.reset_period or "none",
            resets_at=period_end if feature.reset_period and feature.reset_period != "none" else None,
            usage_type=feature.usage_type or "count"
        )
    
    return True, sub.plan_code, plan_name, features


def check_feature_limit(
    db: Session,
    tenant_id: str,
    feature_code: str,
    count: int = 1,
    features: Optional[Dict[str, FeatureUsage]] = None
) -> None:
    """
    Check if tenant can use a feature. Raises HTTPException if not allowed.
    
    Args:
        db: Database session
        tenant_id: Tenant UUID string
        feature_code: Feature code to check
        count: Number of units to consume (default 1)
        features: Pre-loaded features dict (optional, for efficiency)
    
    Raises:
        HTTPException 403: No active subscription or feature not in plan
        HTTPException 429: Limit exceeded
    """
    if features is None:
        active, plan_code, _, features = load_tenant_features(db, tenant_id)
        if not active:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "no_subscription",
                    "message": "No active subscription. Please subscribe to a plan."
                }
            )
    
    if feature_code not in features:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "feature_not_in_plan",
                "feature": feature_code,
                "message": f"Feature '{feature_code}' is not available in your current plan. Upgrade to access this feature."
            }
        )
    
    feature = features[feature_code]
    
    # Unlimited features always pass
    if feature.limit is None:
        return
    
    # Check if we have enough remaining
    if (feature.remaining or 0) < count:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "limit_exceeded",
                "feature": feature_code,
                "feature_name": feature.name,
                "limit": feature.limit,
                "used": feature.used,
                "remaining": feature.remaining,
                "requested": count,
                "reset_period": feature.reset_period,
                "resets_at": feature.resets_at.isoformat() if feature.resets_at else None,
                "message": f"You've reached your {feature.name} limit ({feature.used}/{feature.limit}). Upgrade your plan for more."
            }
        )


def record_feature_usage(
    db: Session,
    tenant_id: str,
    feature_code: str,
    count: int = 1
) -> Dict[str, Any]:
    """
    Record feature usage after successful operation.
    Uses upsert to handle concurrent requests safely.
    
    Args:
        db: Database session
        tenant_id: Tenant UUID string
        feature_code: Feature code
        count: Number of units to record (default 1)
    
    Returns:
        Dict with updated usage info
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        logger.error(f"Invalid tenant_id: {tenant_id}")
        return {"error": "invalid_tenant_id"}
    
    # Get subscription for period calculation
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_uuid,
        TenantSubscription.is_active == True
    ).first()
    
    if not sub:
        logger.warning(f"No active subscription for tenant {tenant_id}")
        return {"error": "no_subscription"}
    
    # Get feature for reset period
    feature = db.query(Feature).filter(Feature.code == feature_code).first()
    if not feature:
        logger.warning(f"Feature not found: {feature_code}")
        return {"error": "feature_not_found"}
    
    # Calculate period
    period_start, period_end = get_period_boundaries(
        sub.current_period_start,
        feature.reset_period or "none"
    )
    
    # Try to update existing usage record, or create new one
    usage = db.query(SubscriptionUsage).filter(
        SubscriptionUsage.tenant_id == tenant_uuid,
        SubscriptionUsage.feature_code == feature_code,
        SubscriptionUsage.period_start == period_start
    ).with_for_update().first()
    
    if usage:
        usage.usage_count += count
        usage.updated_at = datetime.now(timezone.utc)
    else:
        usage = SubscriptionUsage(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            feature_code=feature_code,
            usage_type=feature.usage_type or "count",
            usage_count=count,
            period_start=period_start,
            period_end=period_end
        )
        db.add(usage)
    
    db.commit()
    
    # Get limit for response
    limit = None
    if feature.max_unit:
        try:
            limit = int(feature.max_unit)
        except ValueError:
            pass
    
    logger.info(f"Recorded usage: tenant={tenant_id}, feature={feature_code}, count={count}, total={usage.usage_count}")
    
    return {
        "feature_code": feature_code,
        "recorded": count,
        "total": usage.usage_count,
        "limit": limit,
        "remaining": (limit - usage.usage_count) if limit else None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat()
    }


def decrement_feature_usage(
    db: Session,
    tenant_id: str,
    feature_code: str,
    count: int = 1
) -> Dict[str, Any]:
    """
    Decrement feature usage (for rollback/delete operations).
    
    Args:
        db: Database session
        tenant_id: Tenant UUID string
        feature_code: Feature code
        count: Number of units to decrement (default 1)
    
    Returns:
        Dict with updated usage info
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        return {"error": "invalid_tenant_id"}
    
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_uuid,
        TenantSubscription.is_active == True
    ).first()
    
    if not sub:
        return {"error": "no_subscription"}
    
    feature = db.query(Feature).filter(Feature.code == feature_code).first()
    if not feature:
        return {"error": "feature_not_found"}
    
    period_start, _ = get_period_boundaries(
        sub.current_period_start,
        feature.reset_period or "none"
    )
    
    usage = db.query(SubscriptionUsage).filter(
        SubscriptionUsage.tenant_id == tenant_uuid,
        SubscriptionUsage.feature_code == feature_code,
        SubscriptionUsage.period_start == period_start
    ).with_for_update().first()
    
    if usage and usage.usage_count >= count:
        usage.usage_count -= count
        usage.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Decremented usage: tenant={tenant_id}, feature={feature_code}, count={count}, total={usage.usage_count}")
        return {"decremented": count, "total": usage.usage_count}
    
    return {"decremented": 0, "total": usage.usage_count if usage else 0}


def enforce_active_user_limit(
    db: Session,
    tenant_id: str,
    adding: int = 1
) -> Dict[str, Any]:
    """
    Enforce the per-plan 'active.users' seat limit at user-creation time.

    Unlike `check_feature_limit` (which reads SubscriptionUsage counters),
    this counts ACTUAL active user rows for the tenant. This keeps seat
    enforcement authoritative even if usage counters drift, and it correctly
    reflects deactivations.

    Raises:
        HTTPException 403: no active subscription or 'active.users' not in plan
        HTTPException 429: seat limit would be exceeded

    Returns:
        Dict with current, limit, remaining (for logging/response context)
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.error(f"enforce_active_user_limit: invalid tenant_id {tenant_id!r}")
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    # Count existing active users in the tenant
    current_count = db.query(User).filter(
        User.tenant_id == tenant_uuid,
        User.is_active == True
    ).count()

    # Resolve the plan's configured seat limit for 'active.users'
    active, _plan_code, _plan_name, features_dict = load_tenant_features(db, tenant_id)

    if not active:
        raise HTTPException(status_code=403, detail="No active subscription")

    active_users = features_dict.get("active.users")
    if active_users is None:
        # Feature not mapped into the plan -> treat as not entitled
        raise HTTPException(status_code=403, detail="User seats are not enabled on your plan")

    limit = active_users.limit
    if limit is None:
        # No numeric limit configured -> unlimited (enterprise/distributor)
        return {
            "current": current_count,
            "limit": None,
            "remaining": None,
            "exceeded": False,
        }

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        logger.warning(f"active.users limit is not numeric: {limit!r}; treating as unlimited")
        return {"current": current_count, "limit": None, "remaining": None, "exceeded": False}

    # Phase D2 — additional-user blocks raise the effective seat limit
    extra_seats = 0
    try:
        blocks = db.query(TenantSeatBlock).filter(
            TenantSeatBlock.tenant_id == tenant_uuid,
            TenantSeatBlock.status == "active",
        ).all()
        extra_seats = sum(b.quantity * b.block_size for b in blocks)
    except Exception as _e:
        logger.warning(f"Seat block lookup failed for tenant {tenant_id}: {_e}")
    effective_limit = limit + extra_seats

    if current_count + adding > effective_limit:
        logger.warning(
            f"Seat limit exceeded for tenant {tenant_id}: "
            f"current={current_count}, adding={adding}, limit={effective_limit} "
            f"(plan={limit} + blocks={extra_seats})"
        )
        raise HTTPException(
            status_code=429,
            detail=f"User seat limit reached ({effective_limit}). Upgrade your plan or buy additional-user blocks to add more users."
        )

    return {
        "current": current_count,
        "limit": effective_limit,
        "remaining": effective_limit - (current_count + adding),
        "exceeded": False,
    }

