import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from Models import Tenant, Feature, PlanFeature, TenantSubscription, SubscriptionUsage
from Schemas import UserContext, CheckEntitlementRequest, RecordUsageRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

# ==================================================================================
# ENTITLEMENTS & USAGE TRACKING ENDPOINTS
# ==================================================================================

app = APIRouter()

@app.post("/v1/entitlements/check")
async def check_entitlement(
        req: CheckEntitlementRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "entitlements.check",
                None
            )
        )
):
    """Check if tenant has access to a feature"""
    try:
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
        rate_limit = limits.get("rate_limit")

        if rate_limit:
            # Get current period usage
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
                SubscriptionUsage.feature_code == req.feature_code,
                SubscriptionUsage.period_start >= month_start
            ).first()

            usage_count = usage.usage_count if usage else 0

            if usage_count >= rate_limit:
                return {
                    "allowed": False,
                    "reason": "Usage limit exceeded",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code,
                    "usage": usage_count,
                    "limit": rate_limit,
                    "remaining": 0
                }

            return {
                "allowed": True,
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "usage": usage_count,
                "limit": rate_limit,
                "remaining": rate_limit - usage_count
            }

        # No limits, access allowed
        return {
            "allowed": True,
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "limits": limits
        }
    except Exception as e:
        logger.error(f"❌ Check entitlement failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/record", status_code=201)
async def record_usage(
        req: RecordUsageRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "entitlements.usage.record",
                None
            )
        )
):
    """Record feature usage for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="record_usage", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")

        # Calculate current period
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Calculate month end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

        # Find or create usage record
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
            SubscriptionUsage.feature_code == req.feature_code,
            SubscriptionUsage.usage_type == req.usage_type,
            SubscriptionUsage.period_start >= month_start,
            SubscriptionUsage.period_start < month_end
        ).first()

        if usage:
            # Update existing
            usage.usage_count += req.count
            usage.updated_at = now
        else:
            # Create new
            usage = SubscriptionUsage(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(req.tenant_id),
                feature_code=req.feature_code,
                usage_type=req.usage_type,
                usage_count=req.count,
                period_start=month_start,
                period_end=month_end
            )
            db.add(usage)

        db.commit()
        db.refresh(usage)

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
            "period_start": usage.period_start.isoformat(),
            "period_end": usage.period_end.isoformat()
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
        ctx: UserContext = Depends(
            require_permission(
                "entitlements.usage.record",
                None
            )
        )
):
    """Get usage summary for a tenant"""
    try:
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