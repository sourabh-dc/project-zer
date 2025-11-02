from typing import Dict

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.entitlements.repositories.database_ops import audit_log, get_current_usage
from services.entitlements.repositories.usage_record_saga import UsageRecordSaga
from services.entitlements.schemas import CheckEntitlementRequest, RecordUsageRequest
from services.entitlements.utils.entitlements_logger import logger
from services.entitlements.utils.user_auth import check_permission


async def check_entitlement(req: CheckEntitlementRequest, user_context: Dict, db: Session):
    """Check if tenant has access to feature and within limits"""
    if not check_permission("entitlements.check", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Get tenant's subscription from subscriptions service
        subscription = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://localhost:8212/subscriptions/v2/subscriptions/{req.tenant_id}")
                if response.status_code == 200:
                    sub_data = response.json()
                    subscription = sub_data
        except Exception as e:
            logger.warning(f"Could not fetch subscription for tenant {req.tenant_id}: {e}")

        if not subscription:
            # No subscription found, deny access
            audit_log(db, req.tenant_id, user_context["user_id"], "CHECK_ENTITLEMENT", "entitlement", req.feature_code, {"result": "denied", "reason": "no_subscription"})
            return {"allowed": False, "reason": "No active subscription found"}

        # Check if feature is enabled for the plan
        plan_features = []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://localhost:8212/subscriptions/v2/plans/{subscription['plan_code']}/features")
                if response.status_code == 200:
                    plan_features = response.json()
        except Exception as e:
            logger.warning(f"Could not fetch plan features: {e}")

        # Find the feature in the plan
        feature_limit = None
        for pf in plan_features:
            if pf.get("feature_code") == req.feature_code and pf.get("enabled"):
                feature_limit = pf.get("limits", {})
                break

        if not feature_limit:
            # Feature not found in plan or not enabled
            audit_log(db, req.tenant_id, user_context["user_id"], "CHECK_ENTITLEMENT", "entitlement", req.feature_code, {"result": "denied", "reason": "feature_not_in_plan"})
            return {"allowed": False, "reason": "Feature not available in subscription plan"}

        # Check current usage against limits
        current_usage = get_current_usage(db, req)

        usage_count = current_usage.usage_count if current_usage else 0
        limit_value = feature_limit.get("rate_limit", float('inf'))

        if usage_count >= limit_value:
            # Usage limit exceeded
            audit_log(db, req.tenant_id, user_context["user_id"], "CHECK_ENTITLEMENT", "entitlement", req.feature_code, {"result": "denied", "reason": "limit_exceeded", "usage": usage_count, "limit": limit_value})
            return {"allowed": False, "reason": "Usage limit exceeded", "usage": usage_count, "limit": limit_value}

        # Access allowed
        audit_log(db, req.tenant_id, user_context["user_id"], "CHECK_ENTITLEMENT", "entitlement", req.feature_code, {"result": "allowed", "usage": usage_count, "limit": limit_value})
        return {"allowed": True, "usage": usage_count, "limit": limit_value, "remaining": limit_value - usage_count}

    except Exception as e:
        logger.error(f"Error checking entitlement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def create_usage(payload: RecordUsageRequest, user_context: Dict, db: Session):
    if not check_permission("entitlements.record_usage", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    saga = UsageRecordSaga(db)
    result = await saga.execute(payload, user_context)
    return result