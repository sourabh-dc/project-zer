import uuid
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from internal_api.db import get_db
from internal_api.models import Role, Permission, RolePermission, SubscriptionPlan, Feature, PlanFeature, PlanPrice, PlanCatalog, PlanPriceCatalog
from internal_api.schemas import (
    RoleCreateRequest,
    PermissionCreateRequest,
    PlanCreateRequest,
    FeatureCreateRequest,
    PlanFeatureMapRequest,
    PlanPriceRequest,
)
from internal_api.logger import logger

router = APIRouter(prefix="/internal", tags=["internal"])


# Plans (catalog) -----------------------------------------------------------------------
@router.post("/plans", status_code=201)
async def create_plan(req: PlanCreateRequest, db: Session = Depends(get_db)):
    """Create a catalog plan with code/name/description."""
    code_norm = req.code.lower()
    if db.query(PlanCatalog).filter_by(code=code_norm).first():
        raise HTTPException(409, "Plan code already exists")

    plan = PlanCatalog(
        plan_id=req.plan_id,
        code=code_norm,
        name=req.name,
        description=req.description or "",
        meta=req.meta,
        created_by=req.created_by or "zeroque_admin",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    logger.info(f"✅ Created catalog plan: {plan.code} ({plan.name})")
    return {
        "plan_id": plan.plan_id,
        "plan_code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "metadata": plan.meta,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


@router.get("/plans")
async def list_plans(db: Session = Depends(get_db)):
    plans = db.query(PlanCatalog).order_by(PlanCatalog.plan_id).all()
    return {
        "plans": [
            {
                "plan_id": p.plan_id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "metadata": p.meta,
                "created_by": p.created_by,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in plans
        ],
        "total": len(plans),
    }


@router.get("/plans/{plan_code}")
async def get_plan(plan_code: str, db: Session = Depends(get_db)):
    plan = db.query(PlanCatalog).filter_by(code=plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {
        "plan_id": plan.plan_id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "metadata": plan.meta,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


@router.delete("/plans/{plan_code}", status_code=204)
async def delete_plan(plan_code: str, db: Session = Depends(get_db)):
    plan = db.query(PlanCatalog).filter_by(code=plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.delete(plan)
    db.commit()
    logger.info(f"🗑️ Deleted catalog plan {plan_code}")
    return Response(status_code=204)


def _calculate_prices(monthly_minor: int, quarterly_discount_pct: float, yearly_discount_pct: float):
    quarterly_minor = int(monthly_minor * 3 * (100 - quarterly_discount_pct) / 100)
    yearly_minor = int(monthly_minor * 12 * (100 - yearly_discount_pct) / 100)
    return quarterly_minor, yearly_minor


@router.post("/plan-price", status_code=201)
async def set_plan_price(req: PlanPriceRequest, db: Session = Depends(get_db)):
    plan = db.query(PlanCatalog).filter_by(code=req.plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    quarterly_minor, yearly_minor = _calculate_prices(
        req.price_monthly_minor, req.quarterly_discount_pct, req.yearly_discount_pct
    )

    price = db.query(PlanPriceCatalog).filter_by(plan_code=plan.code).first()
    if price:
        price.price_monthly_minor = req.price_monthly_minor
        price.currency = req.currency
        price.quarterly_discount_pct = req.quarterly_discount_pct
        price.yearly_discount_pct = req.yearly_discount_pct
        price.price_quarterly_minor = quarterly_minor
        price.price_yearly_minor = yearly_minor
    else:
        price = PlanPriceCatalog(
            plan_code=plan.code,
            currency=req.currency,
            price_monthly_minor=req.price_monthly_minor,
            quarterly_discount_pct=req.quarterly_discount_pct,
            yearly_discount_pct=req.yearly_discount_pct,
            price_quarterly_minor=quarterly_minor,
            price_yearly_minor=yearly_minor,
        )
        db.add(price)

    db.commit()
    db.refresh(price)
    return {
        "plan_code": plan.code,
        "monthly_minor": price.price_monthly_minor,
        "quarterly_minor": price.price_quarterly_minor,
        "yearly_minor": price.price_yearly_minor,
        "currency": price.currency,
        "discounts": {
            "quarterly_pct": float(price.quarterly_discount_pct),
            "yearly_pct": float(price.yearly_discount_pct)
        }
    }


@router.put("/plan-price/{plan_code}", status_code=200)
async def update_plan_price(plan_code: str, req: PlanPriceRequest, db: Session = Depends(get_db)):
    # ensure body code matches path if provided
    if req.plan_code.lower() != plan_code.lower():
        raise HTTPException(400, "plan_code in path and body must match")
    return await set_plan_price(req, db)  # reuse logic


@router.post("/plan-price/calculate", status_code=200)
async def calculate_plan_price(
    plan_code: str,
    quarterly_discount_pct: float = 5.0,
    yearly_discount_pct: float = 10.0,
    db: Session = Depends(get_db)
):
    plan = db.query(PlanCatalog).filter_by(code=plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    price = db.query(PlanPriceCatalog).filter_by(plan_code=plan.code).first()
    if not price or not price.price_monthly_minor:
        raise HTTPException(400, "Monthly price not set for this plan")

    monthly = price.price_monthly_minor
    quarterly_minor, yearly_minor = _calculate_prices(monthly, quarterly_discount_pct, yearly_discount_pct)

    price.quarterly_discount_pct = quarterly_discount_pct
    price.yearly_discount_pct = yearly_discount_pct
    price.price_quarterly_minor = quarterly_minor
    price.price_yearly_minor = yearly_minor

    db.commit()
    db.refresh(price)
    return {
        "plan_code": plan.code,
        "monthly_minor": monthly,
        "quarterly_minor": quarterly_minor,
        "yearly_minor": yearly_minor,
        "currency": price.currency,
        "discounts": {
            "quarterly_pct": quarterly_discount_pct,
            "yearly_pct": yearly_discount_pct
        }
    }


@router.get("/plan-price")
async def get_plan_prices(db: Session = Depends(get_db)):
    plans = db.query(PlanCatalog).all()
    prices = {p.plan_code: p for p in db.query(PlanPriceCatalog).all()}
    result = []
    for plan in plans:
        price = prices.get(plan.code)
        if price:
            result.append({
                "plan_code": plan.code,
                "plan_name": plan.name,
                "monthly_minor": price.price_monthly_minor,
                "quarterly_minor": price.price_quarterly_minor,
                "yearly_minor": price.price_yearly_minor,
                "currency": price.currency,
                "discounts": {
                    "quarterly_pct": float(price.quarterly_discount_pct),
                    "yearly_pct": float(price.yearly_discount_pct),
                },
            })
        else:
            result.append({
                "plan_code": plan.code,
                "plan_name": plan.name,
                "monthly_minor": None,
                "quarterly_minor": None,
                "yearly_minor": None,
                "currency": None,
                "discounts": None,
            })
    return {"plans": result}


@router.get("/plan-price/{plan_code}")
async def get_plan_price(plan_code: str, db: Session = Depends(get_db)):
    plan = db.query(PlanCatalog).filter_by(code=plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    price = db.query(PlanPriceCatalog).filter_by(plan_code=plan.code).first()
    if not price:
        return {
            "plan_code": plan.code,
            "plan_name": plan.name,
            "monthly_minor": None,
            "quarterly_minor": None,
            "yearly_minor": None,
            "currency": None,
            "discounts": None,
        }
    return {
        "plan_code": plan.code,
        "plan_name": plan.name,
        "monthly_minor": price.price_monthly_minor,
        "quarterly_minor": price.price_quarterly_minor,
        "yearly_minor": price.price_yearly_minor,
        "currency": price.currency,
        "discounts": {
            "quarterly_pct": float(price.quarterly_discount_pct),
            "yearly_pct": float(price.yearly_discount_pct),
        },
    }


@router.delete("/plan-price/{plan_code}", status_code=204)
async def delete_plan_price(plan_code: str, db: Session = Depends(get_db)):
    plan = db.query(PlanCatalog).filter_by(code=plan_code.lower()).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.query(PlanPriceCatalog).filter_by(plan_code=plan.code).delete()
    db.commit()
    logger.info(f"🗑️ Deleted plan price for {plan_code}")
    return Response(status_code=204)


# Features --------------------------------------------------------------------
@router.post("/features", status_code=201)
async def create_feature(req: FeatureCreateRequest, db: Session = Depends(get_db)):
    if db.query(Feature).filter_by(code=req.code).first():
        raise HTTPException(409, "Feature code already exists")

    f = Feature(
        id=uuid.uuid4(),
        code=req.code,
        name=req.name,
        description=req.description or "",
        cluster=req.cluster or "general",
        usage_type=getattr(req, "usage_type", None) or "count",
        max_unit=getattr(req, "max_unit", None),
        reset_period=getattr(req, "reset_period", None) or "monthly",
        active=True
    )
    db.add(f)
    db.commit()
    logger.info(f"✅ Created feature: {f.code} ({f.name})")
    return {
        "feature_code": f.code,
        "name": f.name,
        "usage_type": f.usage_type,
        "reset_period": f.reset_period
    }


@router.get("/features")
async def list_features(
        active: Optional[bool] = None,
        cluster: Optional[str] = None,
        db: Session = Depends(get_db)
):
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if cluster:
        q = q.filter(Feature.cluster == cluster)
    features = q.order_by(Feature.cluster, Feature.name).all()
    return {
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "cluster": f.cluster,
                "usage_type": f.usage_type,
                "reset_period": f.reset_period,
                "active": f.active
            }
            for f in features
        ],
        "total": len(features)
    }


@router.delete("/features/{feature_code}", status_code=204)
async def delete_feature(feature_code: str, db: Session = Depends(get_db)):
    f = db.query(Feature).filter_by(code=feature_code).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    # cascade disable mappings first
    db.query(PlanFeature).filter_by(feature_code=feature_code).delete()
    db.delete(f)
    db.commit()
    logger.info(f"🗑️ Deleted feature {feature_code}")
    return Response(status_code=204)


@router.put("/map-feature")
async def upsert_plan_feature(req: PlanFeatureMapRequest, db: Session = Depends(get_db)):
    if not db.query(SubscriptionPlan).filter_by(code=req.plan_code).first():
        raise HTTPException(404, "Plan not found")
    if not db.query(Feature).filter_by(code=req.feature_code).first():
        raise HTTPException(404, "Feature not found")

    pf = db.query(PlanFeature).filter_by(
        plan_code=req.plan_code,
        feature_code=req.feature_code
    ).first()

    if pf:
        pf.enabled = True
        pf.limits = req.limits or {}
    else:
        pf = PlanFeature(
            id=uuid.uuid4(),
            plan_code=req.plan_code,
            feature_code=req.feature_code,
            enabled=True,
            limits=req.limits or {}
        )
        db.add(pf)
    db.commit()
    logger.info(f"✅ Updated feature {req.feature_code} in plan {req.plan_code}")
    return {"plan_code": req.plan_code, "feature_code": req.feature_code, "enabled": True, "limits": pf.limits}


@router.delete("/plans/{plan_code}/features/{feature_code}", status_code=204)
async def remove_feature_from_plan(plan_code: str, feature_code: str, db: Session = Depends(get_db)):
    pf = db.query(PlanFeature).filter_by(plan_code=plan_code, feature_code=feature_code).first()
    if pf:
        db.delete(pf)
        db.commit()
        logger.info(f"🗑️ Removed feature {feature_code} from plan {plan_code}")
    return Response(status_code=204)


# Roles -----------------------------------------------------------------------
@router.post("/roles", status_code=201)
async def create_role(req: RoleCreateRequest, db: Session = Depends(get_db)):
    try:
        if req.code and db.query(Role).filter(Role.code == req.code).first():
            raise HTTPException(status_code=409, detail="Role code already exists")
        role = Role(role_id=uuid.uuid4(), code=req.code, description=req.description or "")
        db.add(role)
        db.commit()
        db.refresh(role)
        logger.info(f"✅ Created role: {role.role_id} ({role.code})")
        return {
            "role_id": str(role.role_id),
            "name": role.code,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Role code already exists")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Role creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles")
async def list_roles(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()
    return {
        "roles": [
            {
                "role_id": str(r.role_id),
                "name": r.code,
                "code": r.code,
                "description": r.description,
                "created_at": r.created_at.isoformat()
            }
            for r in roles
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: str, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.role_id == uuid.UUID(role_id)).first()
    if not role:
        raise HTTPException(404, "Role not found")
    # remove mappings first
    db.query(RolePermission).filter(RolePermission.role_id == role.role_id).delete()
    db.delete(role)
    db.commit()
    logger.info(f"🗑️ Deleted role {role_id}")
    return Response(status_code=204)


# Permissions ------------------------------------------------------------------
@router.post("/permissions", status_code=201)
async def create_permission(code: str, description: str, db: Session = Depends(get_db)):
    try:
        if db.query(Permission).filter(Permission.code == code).first():
            raise HTTPException(status_code=409, detail="Permission already exists")
        perm = Permission(permission_id=uuid.uuid4(), code=code, description=description)
        db.add(perm)
        db.commit()
        db.refresh(perm)
        return {"permission_id": str(perm.permission_id), "code": perm.code, "description": perm.description}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Permission creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/permissions")
async def list_permissions(db: Session = Depends(get_db)):
    permissions = db.query(Permission).all()
    return {
        "permissions": [
            {"permission_id": str(p.permission_id), "code": p.code, "description": p.description}
            for p in permissions
        ]
    }


@router.delete("/permissions/{permission_id}", status_code=204)
async def delete_permission(permission_id: str, db: Session = Depends(get_db)):
    perm = db.query(Permission).filter(Permission.permission_id == uuid.UUID(permission_id)).first()
    if not perm:
        raise HTTPException(404, "Permission not found")
    db.query(RolePermission).filter(RolePermission.permission_id == perm.permission_id).delete()
    db.delete(perm)
    db.commit()
    logger.info(f"🗑️ Deleted permission {permission_id}")
    return Response(status_code=204)


# Role-Permission mapping ------------------------------------------------------
@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    try:
        exists = db.query(RolePermission).filter(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id)
        ).first()
        if exists:
            raise HTTPException(status_code=409, detail="Permission already assigned to role")

        rp = RolePermission(id=uuid.uuid4(), role_id=uuid.UUID(role_id), permission_id=uuid.UUID(permission_id))
        db.add(rp)
        db.commit()
        return {"message": "Permission added to role"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add permission to role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204)
async def remove_permission_from_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    assignment = db.query(RolePermission).filter(
        RolePermission.role_id == uuid.UUID(role_id),
        RolePermission.permission_id == uuid.UUID(permission_id)
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Permission not assigned to role")
    db.delete(assignment)
    db.commit()
    return Response(status_code=204)


@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(role_id: str, db: Session = Depends(get_db)):
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_id == Permission.permission_id
    ).filter(RolePermission.role_id == uuid.UUID(role_id)).all()
    return {
        "role_id": role_id,
        "permissions": [
            {
                "permission_id": str(p.permission_id),
                "code": p.code,
                "description": p.description
            }
            for rp, p in role_perms
        ]
    }

