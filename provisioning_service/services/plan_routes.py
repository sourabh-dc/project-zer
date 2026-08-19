from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import SubscriptionPlan, PlanFeature, Feature, PlanPrice
from provisioning_service.core.db_config import get_db
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/plans", tags=["Plan Management"])


@router.get("/", status_code=200)
async def get_plans(
    include_private: bool = Query(False, description="Include sales-only (non-public) plans"),
    db: Session = Depends(get_db),
):
    """
    Get all active subscription plans with their features and pricing.
    Returns both monthly and yearly prices for each plan.

    Phase D4: by default only publicly-listed plans are returned;
    pass ``include_private=true`` to also see sales-only plans.
    """
    try:
        query = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.is_active == True
        )
        if not include_private:
            query = query.filter(SubscriptionPlan.is_public == True)

        plans = query.all()

        if not plans:
            return {"plans": []}

        result = []
        for plan in plans:
            # Get all features for this plan
            plan_pricing = db.query(PlanPrice).filter(PlanPrice.plan_code == plan.code).first()
            plan_features = db.query(Feature, PlanFeature).join(
                PlanFeature, Feature.code == PlanFeature.feature_code
            ).filter(
                PlanFeature.plan_code == plan.code,
                PlanFeature.enabled == True,
                Feature.active == True
            ).all()

            # Format features
            features_list = []
            for feature, plan_feature in plan_features:
                # limit precedence: plan_feature.limits.max_value > feature.max_unit
                limit = None
                if plan_feature.limits and isinstance(plan_feature.limits, dict):
                    mv = plan_feature.limits.get("max_value")
                    if mv is not None:
                        try:
                            limit = int(mv)
                        except ValueError:
                            limit = None
                if limit is None and feature.max_unit:
                    limit = feature.max_unit

                features_list.append({
                    "code": feature.code,
                    "name": feature.name,
                    "description": feature.description,
                    "cluster": feature.cluster,
                    "usage_type": feature.usage_type,
                    "max_unit": limit,
                    "reset_period": feature.reset_period,
                    "enabled": plan_feature.enabled
                })

            # Build plan response
            monthly_minor = int(plan_pricing.price_monthly_minor or 0)
            yearly_minor = int(plan_pricing.price_yearly_minor or 0)
            implementation_fee = int(plan_pricing.implementation_fee_minor or 0)
            plan_data = {
                "id": plan.plan_id,
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "currency": plan_pricing.currency,
                "is_public": plan.is_public if plan.is_public is not None else True,
                "pricing": {
                    "monthly": {
                        "amount_minor": plan_pricing.price_monthly_minor,
                        "amount": plan_pricing.price_monthly_minor  if plan_pricing.price_monthly_minor else None,
                        "available": True
                    },
                    "quarterly": {
                        "amount_minor": plan_pricing.price_quarterly_minor,
                        "amount": plan_pricing.price_quarterly_minor if plan_pricing.price_quarterly_minor else None,
                        "available": True
                    },
                    "yearly": {
                        "amount_minor": plan_pricing.price_yearly_minor,
                        "amount": plan_pricing.price_yearly_minor,
                        "available": True,
                        # Phase D1 — "two months free" annual anchor
                        "anchor": "two_months_free",
                        "savings_minor": max(0, monthly_minor * 12 - yearly_minor),
                    }
                },
                # Phase D3 — one-time implementation fee guardrail
                "implementation_fee_minor": implementation_fee,
                # Phase D2 — additional-user block pricing
                "seat_block": {
                    "block_size": int(plan_pricing.seat_block_size or 5),
                    "price_monthly_minor": int(plan_pricing.seat_block_price_minor or 0),
                    "available": bool(int(plan_pricing.seat_block_price_minor or 0) > 0),
                },
                "features": features_list,
                "active": plan.is_active,
                "created_at": plan.created_at.isoformat() if plan.created_at else None
            }

            result.append(plan_data)

        logger.info(f"Retrieved {len(result)} active plans")
        return {"plans": result}

    except Exception as e:
        logger.error(f"Failed to retrieve plans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve plans")
