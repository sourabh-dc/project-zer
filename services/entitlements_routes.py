# services/core/routes/entitlements.py
"""
Entitlement Service
- Check if tenant can use a feature
- Record feature usage with concurrency safety
- Proper billing cycle anchoring (not calendar-based)
- Support for daily, weekly, monthly, yearly reset periods
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dateutil.relativedelta import relativedelta

from Models import (
    TenantSubscription, PlanFeature, Feature, SubscriptionUsage
)
from Schemas import CheckEntitlementRequest, RecordUsageRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger

router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])


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
        return relativedelta(months=1)  # Proper month handling (28/29/30/31 days)
    elif reset_period == "yearly":
        return relativedelta(years=1)  # Proper year handling (leap years)
    else:
        return relativedelta(months=1)  # Default to monthly


def get_current_period_start(sub: TenantSubscription, reset_period: str) -> datetime:
    """
    Calculate current period start anchored to billing cycle, NOT calendar.
    
    This ensures:
    - Monthly resets happen on the same day each month (e.g., 15th)
    - Yearly resets happen on the anniversary date
    - No drift due to Feb having 28 days
    """
    if not sub.current_period_start:
        # Fallback to now if no billing anchor
        return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    anchor = sub.current_period_start
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    
    if reset_period == "daily":
        # Daily: start of current day
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "weekly":
        # Weekly: align to billing anchor's weekday
        anchor_weekday = anchor.weekday()
        current_weekday = now.weekday()
        days_since_anchor_weekday = (current_weekday - anchor_weekday) % 7
        period_start = now - timedelta(days=days_since_anchor_weekday)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "monthly":
        # Monthly: same day of month as billing start
        anchor_day = min(anchor.day, 28)  # Handle months with fewer days
        
        # Calculate months since anchor
        months_diff = (now.year - anchor.year) * 12 + (now.month - anchor.month)
        
        # If we haven't reached the anchor day this month, we're in the previous period
        if now.day < anchor_day:
            months_diff -= 1
        
        period_start = anchor + relativedelta(months=months_diff)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif reset_period == "yearly":
        # Yearly: anniversary of billing start
        years_diff = now.year - anchor.year
        
        # If we haven't reached the anniversary this year, we're in the previous period
        anchor_this_year = anchor.replace(year=now.year)
        if now < anchor_this_year:
            years_diff -= 1
        
        period_start = anchor + relativedelta(years=years_diff)
        return period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    else:
        # Default to monthly
        return get_current_period_start(sub, "monthly")


def is_subscription_active(sub: TenantSubscription) -> bool:
    """Check if subscription is currently active (including trial)"""
    if not sub:
        return False
    
    now = datetime.now(timezone.utc)
    
    # Check status
    if sub.status not in ["active", "trialing"]:
        return False
    
    # Check if trial expired
    if sub.status == "trialing" and sub.trial_ends_at:
        if sub.trial_ends_at.tzinfo is None:
            trial_end = sub.trial_ends_at.replace(tzinfo=timezone.utc)
        else:
            trial_end = sub.trial_ends_at
        if trial_end < now:
            return False
    
    # Check if subscription ended (after cancellation)
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
    
    Returns:
    - allowed: bool - whether the operation is permitted
    - reason: str - why it's not allowed (if applicable)
    - usage/limit/remaining: current usage stats (if metered)
    """
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Access denied to other tenant's entitlements")

    # Get subscription with status check
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not is_subscription_active(sub):
        return {
            "allowed": False,
            "reason": "no_active_subscription",
            "message": "No active subscription found. Please subscribe to a plan."
        }

    # Check if feature is in plan
    pf = db.query(PlanFeature).filter_by(
        plan_code=sub.plan_code,
        feature_code=req.feature_code,
        enabled=True
    ).first()
    
    if not pf:
        return {
            "allowed": False,
            "reason": "feature_not_in_plan",
            "message": f"Feature '{req.feature_code}' is not included in your current plan."
        }

    # Check limits
    limit = (pf.limits or {}).get("max_value")
    warn_at = (pf.limits or {}).get("warn_at")
    
    if not limit:
        # Unlimited feature
        return {
            "allowed": True,
            "unlimited": True,
            "message": "Feature has no usage limits."
        }

    # Get feature details for reset period
    feature = db.query(Feature).filter_by(code=req.feature_code).first()
    if not feature:
        return {
            "allowed": False,
            "reason": "feature_not_found",
            "message": "Feature configuration not found."
        }

    # Calculate period (anchored to billing cycle)
    period_start = get_current_period_start(sub, feature.reset_period)
    period_end = period_start + get_reset_delta(feature.reset_period)
    
    # Get current usage
    usage = db.query(SubscriptionUsage).filter_by(
        tenant_id=ctx.tenant_id,
        feature_code=req.feature_code,
        period_start=period_start
    ).first()

    used = usage.usage_count if usage else 0
    requested = req.requested_count or 1
    
    # Check if request would exceed limit
    would_exceed = (used + requested) > limit
    
    response = {
        "allowed": not would_exceed,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "requested": requested,
        "resets_at": period_end.isoformat(),
        "period_start": period_start.isoformat()
    }
    
    if would_exceed:
        response["reason"] = "limit_exceeded"
        response["message"] = f"Would exceed limit. Used {used}/{limit}, requested {requested}."
    
    if warn_at and used >= warn_at and not would_exceed:
        response["warning"] = f"Approaching limit: {used}/{limit} used ({(used/limit)*100:.0f}%)"
    
    return response


@router.post("/usage/record", status_code=201)
async def record_usage(
    req: RecordUsageRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("entitlements.usage.record"))
):
    """
    Record feature usage with concurrency safety.
    
    Uses SELECT FOR UPDATE to prevent race conditions when multiple
    requests try to update usage simultaneously.
    """
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Access denied to other tenant's usage")

    # Get subscription with status check
    sub = db.query(TenantSubscription).filter_by(tenant_id=ctx.tenant_id).first()
    
    if not is_subscription_active(sub):
        raise HTTPException(403, "No active subscription")

    # Check if feature is in plan
    pf = db.query(PlanFeature).filter_by(
        plan_code=sub.plan_code,
        feature_code=req.feature_code,
        enabled=True
    ).first()
    
    if not pf:
        raise HTTPException(403, f"Feature '{req.feature_code}' not in your plan")

    # Get feature details
    feature = db.query(Feature).filter_by(code=req.feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature configuration not found")

    # Calculate period (anchored to billing cycle)
    period_start = get_current_period_start(sub, feature.reset_period)
    period_end = period_start + get_reset_delta(feature.reset_period)
    
    # Get limit
    limit = (pf.limits or {}).get("max_value")
    
    # CRITICAL: Use with_for_update() for concurrency safety
    # This locks the row until the transaction completes
    usage = db.query(SubscriptionUsage).filter_by(
        tenant_id=ctx.tenant_id,
        feature_code=req.feature_code,
        period_start=period_start
    ).with_for_update().first()

    if usage:
        # Check limit before incrementing
        if limit and (usage.usage_count + req.count) > limit:
            raise HTTPException(
                429,
                f"Usage limit exceeded. Current: {usage.usage_count}/{limit}, requested: {req.count}"
            )
        
        usage.usage_count += req.count
        usage.updated_at = datetime.now(timezone.utc)
    else:
        # New usage record
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
    
    return {
        "recorded": req.count,
        "total": usage.usage_count,
        "limit": limit,
        "remaining": (limit - usage.usage_count) if limit else None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat()
    }


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
    
    # Get all features in plan
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
    now = datetime.now(timezone.utc)
    
    for pf, feature in plan_features:
        period_start = get_current_period_start(sub, feature.reset_period)
        period_end = period_start + get_reset_delta(feature.reset_period)
        
        usage = db.query(SubscriptionUsage).filter_by(
            tenant_id=ctx.tenant_id,
            feature_code=feature.code,
            period_start=period_start
        ).first()
        
        limit = (pf.limits or {}).get("max_value")
        used = usage.usage_count if usage else 0
        
        usage_data.append({
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
            "percentage_used": round((used / limit) * 100, 1) if limit and limit > 0 else 0
        })
    
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
