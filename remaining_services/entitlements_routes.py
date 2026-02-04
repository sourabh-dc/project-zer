# services/core/routes/entitlements.py
"""
Entitlement Service - With Policy Engine Integration

Policies enforced:
1. entitlement.access - Cross-tenant access, subscription status, feature in plan, usage limits
2. entitlement.usage.warning - Warnings when approaching limits

Features:
- Check if tenant can use a feature
- Record feature usage with concurrency safety
- Proper billing cycle anchoring (not calendar-based)
- Support for daily, weekly, monthly, yearly reset periods
"""
import uuid
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dateutil.relativedelta import relativedelta
import httpx

from Models import (
    TenantSubscription, PlanFeature, Feature, SubscriptionUsage
)
from Schemas import CheckEntitlementRequest, RecordUsageRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger

router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])

POLICY_ENGINE_URL = os.getenv("POLICY_ENGINE_URL", "http://localhost:8004")


async def evaluate_policy(action: str, subject: dict, resource: dict, context: dict = None) -> dict:
    """Evaluate a policy against the Policy Engine."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{POLICY_ENGINE_URL}/v1/policy-engine/evaluate",
                json={
                    "action": action,
                    "subject": subject,
                    "resource": resource,
                    "context": context or {}
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Policy Engine error: {response.status_code} - {response.text}")
                return {"allowed": True, "effect": "allow", "reason": "Policy Engine unavailable"}
    except Exception as e:
        logger.error(f"Policy Engine connection error: {e}")
        return {"allowed": True, "effect": "allow", "reason": f"Policy Engine unavailable: {e}"}


# ============================================================================
# Helper Functions - Proper Calendar Logic
# ============================================================================

def get_reset_delta(reset_period: str) -> relativedelta:
    """Get the delta for a reset period using proper calendar math"""
    if reset_period == "daily":
        return relativedelta(days=1)
    elif reset_period == "weekly":
        return relativedelta(weeks=1)
    elif reset_period == "monthly":
        return relativedelta(months=1)
    elif reset_period == "yearly":
        return relativedelta(years=1)
    else:
        return relativedelta(months=1)


def get_current_period_start(sub: TenantSubscription, reset_period: str) -> datetime:
    """
    Calculate current period start anchored to billing cycle, NOT calendar.
    """
    if not sub.current_period_start:
        return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    anchor = sub.current_period_start
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    
    if reset_period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "weekly":
        anchor_weekday = anchor.weekday()
        current_weekday = now.weekday()
        days_since_anchor_weekday = (current_weekday - anchor_weekday) % 7
        period_start = now - timedelta(days=days_since_anchor_weekday)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "monthly":
        anchor_day = min(anchor.day, 28)
        months_diff = (now.year - anchor.year) * 12 + (now.month - anchor.month)
        if now.day < anchor_day:
            months_diff -= 1
        period_start = anchor + relativedelta(months=months_diff)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "yearly":
        years_diff = now.year - anchor.year
        anchor_this_year = anchor.replace(year=now.year)
        if now < anchor_this_year:
            years_diff -= 1
        period_start = anchor + relativedelta(years=years_diff)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    else:
        return get_current_period_start(sub, "monthly")


def is_subscription_active(sub: TenantSubscription) -> bool:
    """Check if subscription is currently active (including trial)"""
    if not sub:
        return False
    
    now = datetime.now(timezone.utc)
    
    if sub.status not in ["active", "trialing"]:
        return False
    
    if sub.status == "trialing" and sub.trial_ends_at:
        if sub.trial_ends_at.tzinfo is None:
            trial_end = sub.trial_ends_at.replace(tzinfo=timezone.utc)
        else:
            trial_end = sub.trial_ends_at
        if trial_end < now:
            return False
    
    if sub.ends_at:
        if sub.ends_at.tzinfo is None:
            ends = sub.ends_at.replace(tzinfo=timezone.utc)
        else:
            ends = sub.ends_at
        if ends < now:
            return False
    
    return True


# ============================================================================
# Entitlement Endpoints
# ============================================================================

@router.post("/check")
async def check_entitlement(
    req: CheckEntitlementRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("entitlements.check"))
):
    """
    Check if tenant is entitled to use a feature.
    
    Policy Engine validates:
    - Cross-tenant access denied
    - Subscription must be active
    - Feature must be in plan
    - Usage limit not exceeded
    
    Returns:
    - allowed: bool - whether the operation is permitted
    - reason: str - why it's not allowed (if applicable)
    - usage/limit/remaining: current usage stats (if metered)
    - warning: str - if approaching limit
    """
    # Get subscription
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    subscription_active = is_subscription_active(sub)
    
    # Check if feature is in plan
    pf = None
    feature_in_plan = False
    if sub:
        pf = db.query(PlanFeature).filter_by(
            plan_code=sub.plan_code,
            feature_code=req.feature_code,
            enabled=True
        ).first()
        feature_in_plan = pf is not None
    
    # Get feature details
    feature = db.query(Feature).filter_by(code=req.feature_code).first()
    
    # Calculate usage info
    limit = (pf.limits or {}).get("max_value") if pf else None
    warn_at = (pf.limits or {}).get("warn_at") if pf else None
    used = 0
    period_start = None
    period_end = None
    
    if sub and feature and limit:
        period_start = get_current_period_start(sub, feature.reset_period)
        period_end = period_start + get_reset_delta(feature.reset_period)
        
        usage = db.query(SubscriptionUsage).filter_by(
            tenant_id=ctx.tenant_id,
            feature_code=req.feature_code,
            period_start=period_start
        ).first()
        used = usage.usage_count if usage else 0
    
    requested = req.requested_count or 1
    would_exceed = limit and (used + requested) > limit
    usage_percentage = (used / limit * 100) if limit and limit > 0 else 0
    
    # Build context for Policy Engine
    subject = {
        "user_id": ctx.user_id,
        "tenant_id": str(ctx.tenant_id),
        "subscription_active": subscription_active,
        "plan_features": [pf.feature_code] if pf else []
    }
    
    resource = {
        "tenant_id": req.tenant_id,
        "feature_code": req.feature_code,
        "feature_in_plan": feature_in_plan,
        "current_usage": used,
        "requested_count": requested,
        "usage_limit": limit,
        "would_exceed_limit": would_exceed,
        "usage_percentage": usage_percentage
    }
    
    # Evaluate policy
    policy_result = await evaluate_policy(
        action="entitlement.check",
        subject=subject,
        resource=resource
    )
    
    # Build response
    if not policy_result.get("allowed", True):
        reason = policy_result.get("reason", "Access denied")
        
        # Map to specific error codes
        if "tenant" in reason.lower():
            return {"allowed": False, "reason": "cross_tenant_access", "message": reason}
        elif "subscription" in reason.lower():
            return {"allowed": False, "reason": "no_active_subscription", "message": reason}
        elif "plan" in reason.lower():
            return {"allowed": False, "reason": "feature_not_in_plan", "message": reason}
        elif "limit" in reason.lower() or "exceeded" in reason.lower():
            return {
                "allowed": False,
                "reason": "limit_exceeded",
                "message": reason,
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used) if limit else None,
                "requested": requested
            }
        else:
            return {"allowed": False, "reason": "policy_denied", "message": reason}
    
    # Allowed - build success response
    response = {
        "allowed": True,
        "feature_code": req.feature_code
    }
    
    if limit:
        response.update({
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "requested": requested,
            "resets_at": period_end.isoformat() if period_end else None,
            "period_start": period_start.isoformat() if period_start else None
        })
        
        # Add warning if approaching limit
        if warn_at and used >= warn_at:
            response["warning"] = f"Approaching limit: {used}/{limit} used ({usage_percentage:.0f}%)"
    else:
        response["unlimited"] = True
        response["message"] = "Feature has no usage limits."
    
    return response


@router.post("/usage/record", status_code=201)
async def record_usage(
    req: RecordUsageRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("entitlements.usage.record"))
):
    """
    Record feature usage with concurrency safety.
    
    Policy Engine validates access before recording.
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    # Get subscription
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    subscription_active = is_subscription_active(sub)
    
    # Check if feature is in plan
    pf = None
    feature_in_plan = False
    if sub:
        pf = db.query(PlanFeature).filter_by(
            plan_code=sub.plan_code,
            feature_code=req.feature_code,
            enabled=True
        ).first()
        feature_in_plan = pf is not None
    
    # Get feature details
    feature = db.query(Feature).filter_by(code=req.feature_code).first()
    
    # Calculate usage info
    limit = (pf.limits or {}).get("max_value") if pf else None
    period_start = None
    period_end = None
    used = 0
    
    if sub and feature:
        period_start = get_current_period_start(sub, feature.reset_period)
        period_end = period_start + get_reset_delta(feature.reset_period)
        
        # Get current usage (without lock for policy check)
        usage_check = db.query(SubscriptionUsage).filter_by(
            tenant_id=ctx.tenant_id,
            feature_code=req.feature_code,
            period_start=period_start
        ).first()
        used = usage_check.usage_count if usage_check else 0
    
    would_exceed = limit and (used + req.count) > limit
    usage_percentage = (used / limit * 100) if limit and limit > 0 else 0
    
    # Evaluate policy
    policy_result = await evaluate_policy(
        action="entitlement.use",
        subject={
            "user_id": ctx.user_id,
            "tenant_id": str(ctx.tenant_id),
            "subscription_active": subscription_active
        },
        resource={
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "feature_in_plan": feature_in_plan,
            "current_usage": used,
            "requested_count": req.count,
            "usage_limit": limit,
            "would_exceed_limit": would_exceed,
            "usage_percentage": usage_percentage
        }
    )
    
    if not policy_result.get("allowed", True):
        reason = policy_result.get("reason", "Access denied")
        
        if "tenant" in reason.lower():
            raise HTTPException(403, "Access denied to other tenant's usage")
        elif "subscription" in reason.lower():
            raise HTTPException(403, "No active subscription")
        elif "plan" in reason.lower():
            raise HTTPException(403, f"Feature '{req.feature_code}' not in your plan")
        elif "limit" in reason.lower() or "exceeded" in reason.lower():
            raise HTTPException(429, f"Usage limit exceeded. Current: {used}/{limit}, requested: {req.count}")
        else:
            raise HTTPException(403, reason)
    
    # Now record usage with lock
    if not feature:
        raise HTTPException(404, "Feature configuration not found")
    
    # CRITICAL: Use with_for_update() for concurrency safety
    usage = db.query(SubscriptionUsage).filter_by(
        tenant_id=ctx.tenant_id,
        feature_code=req.feature_code,
        period_start=period_start
    ).with_for_update().first()

    if usage:
        # Double-check limit with lock
        if limit and (usage.usage_count + req.count) > limit:
            raise HTTPException(
                429,
                f"Usage limit exceeded. Current: {usage.usage_count}/{limit}, requested: {req.count}"
            )
        
        usage.usage_count += req.count
        usage.updated_at = datetime.now(timezone.utc)
    else:
        if limit and req.count > limit:
            raise HTTPException(
                429,
                f"Usage limit exceeded. Limit: {limit}, requested: {req.count}"
            )
        
        usage = SubscriptionUsage(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant_id,
            feature_code=req.feature_code,
            usage_type=req.usage_type or feature.usage_type or "count",
            usage_count=req.count,
            period_start=period_start,
            period_end=period_end
        )
        db.add(usage)

    db.commit()
    
    logger.info(f"✅ Recorded usage for tenant {ctx.tenant_id}: {req.feature_code} +{req.count} (total: {usage.usage_count})")
    
    # Build response with optional warning
    response = {
        "recorded": req.count,
        "total": usage.usage_count,
        "limit": limit,
        "remaining": (limit - usage.usage_count) if limit else None,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None
    }
    
    # Add warning if approaching limit (80%+)
    if limit and usage.usage_count >= (limit * 0.8):
        response["warning"] = f"Approaching limit: {usage.usage_count}/{limit} used ({(usage.usage_count/limit)*100:.0f}%)"
    
    return response


@router.get("/usage")
async def get_usage_summary(
    feature_code: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("entitlements.usage.view"))
):
    """Get usage summary for current tenant"""
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not sub:
        return {"usage": [], "message": "No subscription found"}
    
    plan_features = db.query(PlanFeature, Feature).join(
        Feature, PlanFeature.feature_code == Feature.code
    ).filter(
        PlanFeature.plan_code == sub.plan_code,
        PlanFeature.enabled == True
    )
    
    if feature_code:
        plan_features = plan_features.filter(Feature.code == feature_code)
    
    plan_features = plan_features.all()
    
    usage_data = []
    
    for pf, feature in plan_features:
        period_start = get_current_period_start(sub, feature.reset_period)
        period_end = period_start + get_reset_delta(feature.reset_period)
        
        usage = db.query(SubscriptionUsage).filter_by(
            tenant_id=ctx.tenant_id,
            feature_code=feature.code,
            period_start=period_start
        ).first()
        
        limit = (pf.limits or {}).get("max_value")
        warn_at = (pf.limits or {}).get("warn_at")
        used = usage.usage_count if usage else 0
        percentage_used = round((used / limit) * 100, 1) if limit and limit > 0 else 0
        
        item = {
            "feature_code": feature.code,
            "feature_name": feature.name,
            "category": feature.category,
            "used": used,
            "limit": limit,
            "remaining": (limit - used) if limit else None,
            "unlimited": limit is None,
            "reset_period": feature.reset_period,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "percentage_used": percentage_used
        }
        
        # Add warning if approaching limit
        if warn_at and used >= warn_at:
            item["warning"] = f"Approaching limit: {percentage_used}% used"
        
        usage_data.append(item)
    
    return {
        "tenant_id": str(ctx.tenant_id),
        "plan_code": sub.plan_code,
        "usage": usage_data,
        "total_features": len(usage_data)
    }


@router.delete("/usage/{feature_code}/reset", status_code=200)
async def reset_usage(
    feature_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("entitlements.usage.manage"))
):
    """
    Reset usage for a feature (admin only).
    Useful for support cases or billing adjustments.
    """
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    if not sub:
        raise HTTPException(404, "No subscription found")
    
    feature = db.query(Feature).filter_by(code=feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature not found")
    
    period_start = get_current_period_start(sub, feature.reset_period)
    
    usage = db.query(SubscriptionUsage).filter_by(
        tenant_id=ctx.tenant_id,
        feature_code=feature_code,
        period_start=period_start
    ).with_for_update().first()
    
    if usage:
        old_count = usage.usage_count
        usage.usage_count = 0
        usage.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"✅ Reset usage for tenant {ctx.tenant_id}, feature {feature_code}: {old_count} → 0")
        return {"reset": True, "previous_count": old_count, "feature_code": feature_code}
    
    return {"reset": False, "message": "No usage to reset", "feature_code": feature_code}
