import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, update

from Models import Tenant, Feature, PlanFeature, TenantSubscription, SubscriptionUsage
from Schemas import UserContext, CheckEntitlementRequest, RecordUsageRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from utils.logger import logger
from utils.metrics import req_total, req_duration

# ==================================================================================
# ENTITLEMENTS & USAGE TRACKING ENDPOINTS
# ==================================================================================

app = APIRouter()


# ==================================================================================
# UTILITY FUNCTIONS
# ==================================================================================


def calculate_period_start_end(reset_period: str) -> tuple:
    """Calculate period start/end based on reset_period"""
    now = datetime.now(timezone.utc)
    
    if reset_period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
    elif reset_period == "weekly":
        start = now - timedelta(days=now.weekday())  # Monday
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
    elif reset_period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Calculate next month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1)
        else:
            end = start.replace(month=start.month + 1, day=1)
        end = end - timedelta(microseconds=1)
    elif reset_period == "yearly":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1) - timedelta(microseconds=1)
    else:
        raise ValueError(f"Invalid reset_period: {reset_period}")
    
    return start, end


async def check_entitlement_internal(db: Session, tenant_id: uuid.UUID, feature_code: str) -> Dict[str, Any]:
    """Internal function to check entitlement (used by record_usage)"""
    # Get tenant subscription
    subscription = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.status == "active"
    ).first()

    if not subscription:
        return {"allowed": False, "reason": "No active subscription found"}

    # Check if feature is in plan
    plan_feature = db.query(PlanFeature).filter(
        PlanFeature.plan_code == subscription.plan_code,
        PlanFeature.feature_code == feature_code,
        PlanFeature.enabled == True
    ).first()

    if not plan_feature:
        return {"allowed": False, "reason": "Feature not available in subscription plan"}

    # Check usage limits (if any)
    limits = plan_feature.limits or {}
    max_value = limits.get("max_value")
    
    if max_value:
        # Get feature metadata
        feature = db.query(Feature).filter(Feature.code == feature_code).first()
        if not feature:
            return {"allowed": False, "reason": "Feature not found"}
        
        # Calculate period
        period_start, period_end = calculate_period_start_end(feature.reset_period)
        
        # Get current usage
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == tenant_id,
            SubscriptionUsage.feature_code == feature_code,
            SubscriptionUsage.period_start == period_start
        ).first()
        
        usage_count = usage.usage_count if usage else 0
        
        if usage_count >= max_value:
            return {
                "allowed": False,
                "reason": "Usage limit exceeded",
                "usage": usage_count,
                "limit": max_value
            }

    return {"allowed": True, "limits": limits}


# ==================================================================================
# ENDPOINTS
# ==================================================================================

@app.post("/v1/entitlements/check")
async def check_entitlement(
        req: CheckEntitlementRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("entitlements.check"))
):
    """Check if tenant has access to a feature"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))
        
        # Get tenant subscription
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id),
            TenantSubscription.status == "active"
        ).first()

        if not subscription:
            return {
                "allowed": False,
                "reason": "No active subscription found",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code
            }

        # Check if feature is in plan
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == subscription.plan_code,
            PlanFeature.feature_code == req.feature_code,
            PlanFeature.enabled == True
        ).first()

        if not plan_feature:
            return {
                "allowed": False,
                "reason": "Feature not available in subscription plan",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "plan_code": subscription.plan_code
            }

        # Check usage limits (if any)
        limits = plan_feature.limits or {}
        max_value = limits.get("max_value")
        
        if max_value:
            # Get feature metadata
            feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
            if not feature:
                return {
                    "allowed": False,
                    "reason": "Feature not found",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code
                }
            
            # Calculate period based on feature's reset_period
            period_start, period_end = calculate_period_start_end(feature.reset_period)
            
            # Get current period usage
            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
                SubscriptionUsage.feature_code == req.feature_code,
                SubscriptionUsage.period_start == period_start
            ).first()

            usage_count = usage.usage_count if usage else 0

            if usage_count >= max_value:
                return {
                    "allowed": False,
                    "reason": "Usage limit exceeded",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code,
                    "usage": usage_count,
                    "limit": max_value,
                    "remaining": 0
                }

            return {
                "allowed": True,
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "usage": usage_count,
                "limit": max_value,
                "remaining": max_value - usage_count
            }

        # No limits, access allowed
        return {
            "allowed": True,
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "limits": limits
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Check entitlement failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/check-bulk")
async def check_entitlements_bulk(
        tenant_id: str,
        feature_codes: List[str] = Query(...),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("entitlements.check"))
):
    """Bulk check entitlements for multiple features"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        results = []
        for feature_code in feature_codes:
            entitlement = await check_entitlement_internal(db, uuid.UUID(tenant_id), feature_code)
            results.append({
                "feature_code": feature_code,
                "allowed": entitlement["allowed"],
                "reason": entitlement.get("reason"),
                "usage": entitlement.get("usage"),
                "limit": entitlement.get("limit"),
                "remaining": entitlement.get("limit", 0) - entitlement.get("usage", 0) if entitlement.get("limit") else None
            })
        
        return {
            "tenant_id": tenant_id,
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Bulk check entitlements failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/record", status_code=201)
async def record_usage(
        req: RecordUsageRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("entitlements.usage.record"))
):
    """Record feature usage with limit checking and race condition protection"""
    start = datetime.now()
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))
        
        req_total.labels(operation="record_usage", status="start").inc()
        
        # Check entitlement first
        entitlement = await check_entitlement_internal(db, uuid.UUID(req.tenant_id), req.feature_code)
        if not entitlement["allowed"]:
            raise HTTPException(
                status_code=429,
                detail=f"Feature limit exceeded: {entitlement.get('reason')}"
            )
        
        # Get feature metadata
        feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Calculate period based on feature's reset_period
        period_start, period_end = calculate_period_start_end(feature.reset_period)
        
        # Use transaction with row-level locking
        usage = None
        
        # Lock the usage row for update (prevents race conditions)
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
            SubscriptionUsage.feature_code == req.feature_code,
            SubscriptionUsage.usage_type == req.usage_type,
            SubscriptionUsage.period_start == period_start
        ).with_for_update().first()
        
        if usage:
            # Check limit before incrementing
            plan_feature = db.query(PlanFeature).join(
                TenantSubscription, PlanFeature.plan_code == TenantSubscription.plan_code
            ).filter(
                TenantSubscription.tenant_id == uuid.UUID(req.tenant_id),
                PlanFeature.feature_code == req.feature_code,
                PlanFeature.enabled == True
            ).first()
            
            if plan_feature and plan_feature.limits:
                max_value = plan_feature.limits.get("max_value")
                if max_value and usage.usage_count + req.count > max_value:
                    db.rollback()
                    raise HTTPException(
                        status_code=429,
                        detail=f"Feature limit exceeded. Used: {usage.usage_count}, Requested: {req.count}, Limit: {max_value}"
                    )
            
            usage.usage_count += req.count
            usage.updated_at = datetime.now(timezone.utc)
        else:
            usage = SubscriptionUsage(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(req.tenant_id),
                feature_code=req.feature_code,
                usage_type=req.usage_type,
                usage_count=req.count,
                period_start=period_start,
                period_end=period_end
            )
            db.add(usage)
        
        db.commit()
        
        req_total.labels(operation="record_usage", status="success").inc()
        req_duration.labels(operation="record_usage").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Recorded usage: {req.count} for feature {req.feature_code}, tenant {req.tenant_id}")

        return {
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "usage_type": req.usage_type,
            "count": req.count,
            "total_usage": usage.usage_count,
            "period": {
                "start": usage.period_start.isoformat(),
                "end": usage.period_end.isoformat(),
                "reset_period": feature.reset_period
            }
        }
    except HTTPException:
        req_total.labels(operation="record_usage", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="record_usage", status="error").inc()
        logger.error(f"❌ Record usage failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/entitlements/usage/{tenant_id}")
async def get_usage_summary(
        tenant_id: str,
        feature_code: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("entitlements.usage.record"))
):
    """Get usage summary for a tenant"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Build query
        q = db.query(SubscriptionUsage).filter(SubscriptionUsage.tenant_id == uuid.UUID(tenant_id))
        if feature_code:
            q = q.filter(SubscriptionUsage.feature_code == feature_code)

        # Get current period usage
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_usage = q.filter(SubscriptionUsage.period_start >= month_start).all()

        return {
            "tenant_id": tenant_id,
            "current_period": {
                "start": month_start.isoformat(),
                "usage": [
                    {
                        "feature_code": u.feature_code,
                        "usage_type": u.usage_type,
                        "count": u.usage_count,
                        "period_start": u.period_start.isoformat(),
                        "period_end": u.period_end.isoformat()
                    }
                    for u in current_usage
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get usage summary failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/entitlements/usage/{tenant_id}/history")
async def get_usage_history(
        tenant_id: str,
        feature_code: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("entitlements.usage.record"))
):
    """Get usage history for a tenant"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))
        
        q = db.query(SubscriptionUsage).filter(SubscriptionUsage.tenant_id == uuid.UUID(tenant_id))
        if feature_code:
            q = q.filter(SubscriptionUsage.feature_code == feature_code)

        total = q.count()
        usage_records = q.order_by(SubscriptionUsage.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "tenant_id": tenant_id,
            "usage_history": [
                {
                    "id": str(u.id),
                    "feature_code": u.feature_code,
                    "usage_type": u.usage_type,
                    "usage_count": u.usage_count,
                    "period_start": u.period_start.isoformat(),
                    "period_end": u.period_end.isoformat(),
                    "created_at": u.created_at.isoformat(),
                    "updated_at": u.updated_at.isoformat() if u.updated_at else None
                }
                for u in usage_records
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get usage history failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/reset", status_code=200)
async def reset_usage(
        tenant_id: str,
        feature_code: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("admin.permissions.manage"))  # Admin only
):
    """Reset usage for a tenant feature (admin only)"""
    try:
        # SECURITY: Admin can access any tenant
        # Regular users cannot use this endpoint due to permission check
        
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(tenant_id),
            SubscriptionUsage.feature_code == feature_code
        ).all()
        
        if not usage:
            raise HTTPException(status_code=404, detail="Usage records not found")
        
        for u in usage:
            u.usage_count = 0
            u.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"✅ Reset usage for tenant {tenant_id}, feature {feature_code}")
        
        return {
            "tenant_id": tenant_id,
            "feature_code": feature_code,
            "reset": True,
            "records_reset": len(usage)
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Reset usage failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
