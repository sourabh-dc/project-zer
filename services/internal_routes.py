import uuid
from datetime import datetime
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import  Response

from Models import  Role, Permission, RolePermission, SubscriptionPlan, Feature, PlanFeature
from Schemas import RoleRequest, SubscriptionPlanRequest, FeatureRequest, PlanFeatureRequest
from core.db_config import get_db
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/internal", tags=["internal"])

@router.post("/plans", status_code=201)
async def create_plan(
        req: SubscriptionPlanRequest,
        db: Session = Depends(get_db)
):
    """Create a new subscription plan"""
    if db.query(SubscriptionPlan).filter_by(code=req.code).first():
        raise HTTPException(409, "Plan code already exists")

    plan = SubscriptionPlan(
        code=req.code,
        name=req.name,
        description=req.description or "",
        price_yearly_minor=req.price_yearly_minor,
        price_monthly_minor=req.price_monthly_minor,
        currency=req.currency or "GBP",
        active=True
    )
    db.add(plan)
    db.commit()

    logger.info(f"✅ Created plan: {plan.code} ({plan.name})")
    return {
        "plan_code": plan.code,
        "name": plan.name,
        "price_yearly_minor": plan.price_yearly_minor,
        "price_monthly_minor": plan.price_monthly_minor,
        "currency": plan.currency
    }

@router.get("/plans")
async def list_plans(
        active: Optional[bool] = None,
        db: Session = Depends(get_db)
):
    """List all subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)
    plans = q.order_by(SubscriptionPlan.name).all()
    return {
        "plans": [
            {
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "price_monthly_minor": p.price_monthly_minor,
                "currency": p.currency,
                "active": p.active
            }
            for p in plans
        ],
        "total": len(plans)
    }


@router.get("/plans/{plan_code}")
async def get_plan(
        plan_code: str,
        db: Session = Depends(get_db)
):
    """Get a specific plan with its features"""
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    # Get plan features
    features = db.query(PlanFeature, Feature).join(
        Feature, PlanFeature.feature_code == Feature.code
    ).filter(
        PlanFeature.plan_code == plan_code,
        PlanFeature.enabled == True
    ).all()

    return {
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "price_yearly_minor": plan.price_yearly_minor,
        "price_monthly_minor": plan.price_monthly_minor,
        "currency": plan.currency,
        "active": plan.active,
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "limits": pf.limits
            }
            for pf, f in features
        ]
    }


# ============================================================================
# Feature Management
# ============================================================================

@router.post("/features", status_code=201)
async def create_feature(
        req: FeatureRequest,
        db: Session = Depends(get_db)
):
    """Create a new feature"""
    if db.query(Feature).filter_by(code=req.code).first():
        raise HTTPException(409, "Feature code already exists")

    f = Feature(
        id=uuid.uuid4(),
        code=req.code,
        name=req.name,
        description=req.description or "",
        cluster=req.cluster or "general",
        usage_type=req.usage_type or "count",
        max_unit=req.max_unit,
        reset_period=req.reset_period or "monthly",
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
        category: Optional[str] = None,
        db: Session = Depends(get_db)
):
    """List all features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)
    features = q.order_by(Feature.category, Feature.name).all()
    return {
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "usage_type": f.usage_type,
                "reset_period": f.reset_period,
                "active": f.active
            }
            for f in features
        ],
        "total": len(features)
    }


@router.put("/map-feature")
async def upsert_plan_feature(
        req: PlanFeatureRequest,
        db: Session = Depends(get_db)
):
    """Add or update a feature in a plan"""
    # Verify plan and feature exist
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
            enabled=True
        )
        db.add(pf)
    db.commit()

    logger.info(f"✅ Updated feature {req.feature_code} in plan {req.plan_code}")
    return {"plan_code": req.plan_code, "feature_code": req.feature_code, "enabled": True}


@router.delete("/plans/{plan_code}/features/{feature_code}", status_code=204)
async def remove_feature_from_plan(
        plan_code: str,
        feature_code: str,
        db: Session = Depends(get_db)
):
    """Remove (disable) a feature from a plan"""
    pf = db.query(PlanFeature).filter_by(
        plan_code=plan_code,
        feature_code=feature_code
    ).first()
    if pf:
        pf.enabled = False
        db.commit()
        logger.info(f"✅ Disabled feature {feature_code} in plan {plan_code}")
    return None

# ===========================================================================
#       Roles and Permissions
# ===========================================================================

@router.post("/roles", status_code=201)
async def create_role(
        req: RoleRequest,
        db: Session = Depends(get_db)
):
    """Create a new role"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_role", status="start").inc()

        # Check if code exists (if provided)
        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(status_code=409, detail="Role code already exists")

        # Create role
        role = Role(
            role_id=uuid.uuid4(),
            code=req.code,
            description=req.description or ""
        )
        db.add(role)
        db.commit()
        db.refresh(role)

        req_total.labels(operation="create_role", status="success").inc()
        req_duration.labels(operation="create_role").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created role: {role.role_id} ({role.code})")

        return {
            "role_id": str(role.role_id),
            "name": role.code,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        logger.error(f"❌ Role creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles")
async def list_roles(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List all roles"""
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

@router.post("/permissions", status_code=201)
async def create_permission(
        code: str,
        description: str,
        db: Session = Depends(get_db)
):
    """Create a new permission"""
    try:
        # Check if exists
        existing = db.query(Permission).filter(Permission.code == code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Permission already exists")

        perm = Permission(
            permission_id=uuid.uuid4(),
            code=code,
            description=description
        )
        db.add(perm)
        db.commit()
        db.refresh(perm)

        return {
            "permission_id": str(perm.permission_id),
            "code": perm.code,
            "description": perm.description
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Permission creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/permissions")
async def list_permissions(
        db: Session = Depends(get_db)
):
    """List all permissions"""
    permissions = db.query(Permission).all()
    return {
        "permissions": [
            {"permission_id": str(p.permission_id), "code": p.code, "description": p.description}
            for p in permissions
        ]
    }


@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role(
        role_id: str,
        permission_id: str,
        db: Session = Depends(get_db)
):
    """Add permission to a role"""
    try:
        # Check if already exists
        existing = db.query(RolePermission).filter(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id)
        ).first()

        if existing:
            raise HTTPException(status_code=409, detail="Permission already assigned to role")

        rp = RolePermission(
            id=uuid.uuid4(),
            role_id=uuid.UUID(role_id),
            permission_id=uuid.UUID(permission_id)
        )
        db.add(rp)
        db.commit()

        return {"message": "Permission added to role"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add permission to role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/roles/delete-permission", status_code=204)
async def remove_permission_from_role(
        role_id: str,
        permission_id: str,
        db: Session = Depends(get_db)
):
    """Remove permission from a role"""
    try:
        assignment = db.query(RolePermission).filter(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id)
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Permission not assigned to role")

        db.delete(assignment)
        db.commit()
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role or permission ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove permission from role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(
        role_id: str,
        db: Session = Depends(get_db)
):
    """Get all permissions for a role"""
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_id == Permission.permission_id
    ).filter(
        RolePermission.role_id == uuid.UUID(role_id)
    ).all()

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