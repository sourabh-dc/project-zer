"""
Internal API routes for managing system configuration.
Used by developers/admins to manage plans, features, roles, and permissions.
"""
import uuid
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from provisioning_service.Models import Role, Permission, RolePermission, SubscriptionPlan, Feature, PlanFeature, PlanPrice
from provisioning_service.Schemas import RoleRequest, SubscriptionPlanRequest, FeatureRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/internal", tags=["internal"])

# System-level tenant UUID for internal/admin audit events
_SYSTEM_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _internal_outbox(db, event_type: str, data: dict):
    """Write an outbox event for internal/system operations."""
    try:
        create_outbox_event(db, _SYSTEM_TENANT, event_type, data)
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for {event_type}: {e}")


# Request schemas for endpoints that were using query params
class PermissionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)


class RolePermissionRequest(BaseModel):
    role_code: str
    permission_code: str


# ---------------------------------------------------------------------------
# Subscription Plans
# ---------------------------------------------------------------------------

@router.post("/plans", status_code=201)
async def create_plan(req: SubscriptionPlanRequest, db: Session = Depends(get_db)):
    """Create a new subscription plan with pricing."""
    if db.query(SubscriptionPlan).filter_by(code=req.code).first():
        raise HTTPException(409, "Plan code already exists")

    plan = SubscriptionPlan(
        plan_id=uuid.uuid4(),
        code=req.code,
        name=req.name,
        description=req.description,
        created_by=req.created_by,
        is_active=True
    )
    db.add(plan)
    db.commit()

    # calculate discounted prices
    price_yearly = int((req.price_monthly_minor * 12) * (1 - req.yearly_discount_pct / 100))
    price_quarterly = int((req.price_monthly_minor * 3) * (1 - req.quarterly_discount_pct / 100))

    pricing = PlanPrice(
        plan_code=req.code,
        price_monthly_minor=req.price_monthly_minor,
        currency=req.currency,
        quarterly_discount_pct=req.quarterly_discount_pct,
        yearly_discount_pct=req.yearly_discount_pct,
        price_yearly_minor=price_yearly,
        price_quarterly_minor=price_quarterly
    )
    db.add(pricing)
    db.commit()

    _internal_outbox(db, "plan.created", {"plan_code": plan.code, "name": plan.name})

    logger.info(f"Created plan: {plan.code}")
    return {
        "plan_code": plan.code,
        "name": plan.name,
        "price_monthly_minor": pricing.price_monthly_minor,
        "currency": pricing.currency
    }


@router.get("/plans")
async def list_plans(active: Optional[bool] = None, db: Session = Depends(get_db)):
    """List all subscription plans with pricing."""
    q = db.query(SubscriptionPlan, PlanPrice).outerjoin(
        PlanPrice, PlanPrice.plan_code == SubscriptionPlan.code
    )
    if active is not None:
        q = q.filter(SubscriptionPlan.is_active == active)

    rows = q.order_by(SubscriptionPlan.name).all()

    plans = []
    for plan, pricing in rows:
        plans.append({
            "code": plan.code,
            "name": plan.name,
            "description": plan.description,
            "price_monthly_minor": getattr(pricing, "price_monthly_minor", None),
            "price_quarterly_minor": getattr(pricing, "price_quarterly_minor", None),
            "price_yearly_minor": getattr(pricing, "price_yearly_minor", None),
            "currency": getattr(pricing, "currency", None),
            "active": plan.is_active
        })

    return {"plans": plans, "total": len(plans)}


@router.get("/plans/{plan_code}")
async def get_plan(plan_code: str, db: Session = Depends(get_db)):
    """Get a specific plan with its pricing and features."""
    row = db.query(SubscriptionPlan, PlanPrice).outerjoin(
        PlanPrice, PlanPrice.plan_code == SubscriptionPlan.code
    ).filter(SubscriptionPlan.code == plan_code).first()

    if not row:
        raise HTTPException(404, "Plan not found")

    plan, pricing = row

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
        "price_monthly_minor": getattr(pricing, "price_monthly_minor", None),
        "price_quarterly_minor": getattr(pricing, "price_quarterly_minor", None),
        "price_yearly_minor": getattr(pricing, "price_yearly_minor", None),
        "currency": getattr(pricing, "currency", None),
        "active": plan.is_active,
        "features": [{"code": f.code, "name": f.name} for pf, f in features]
    }


@router.put("/plans/{plan_code}")
async def update_plan(plan_code: str, req: SubscriptionPlanRequest, db: Session = Depends(get_db)):
    """Update an existing plan and its pricing."""
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    pricing = db.query(PlanPrice).filter_by(plan_code=plan_code).first()

    plan.name = req.name
    plan.description = req.description

    if pricing:
        pricing.price_monthly_minor = req.price_monthly_minor
        pricing.currency = req.currency
        pricing.quarterly_discount_pct = req.quarterly_discount_pct
        pricing.yearly_discount_pct = req.yearly_discount_pct
        pricing.price_yearly_minor = int((req.price_monthly_minor * 12) * (1 - req.yearly_discount_pct / 100))
        pricing.price_quarterly_minor = int((req.price_monthly_minor * 3) * (1 - req.quarterly_discount_pct / 100))

    db.commit()
    _internal_outbox(db, "plan.updated", {"plan_code": plan.code, "name": plan.name})
    logger.info(f"Updated plan: {plan.code}")

    return {
        "plan_code": plan.code,
        "name": plan.name,
        "price_monthly_minor": pricing.price_monthly_minor if pricing else None,
        "currency": pricing.currency if pricing else None
    }


@router.delete("/plans/{plan_code}", status_code=204)
async def delete_plan(plan_code: str, db: Session = Depends(get_db)):
    """Deactivate a plan (soft delete)."""
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    plan.is_active = False
    db.commit()
    _internal_outbox(db, "plan.deactivated", {"plan_code": plan_code})
    logger.info(f"Deactivated plan: {plan_code}")
    return None


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

@router.post("/features", status_code=201)
async def create_feature(req: FeatureRequest, db: Session = Depends(get_db)):
    """Create a new feature."""
    if db.query(Feature).filter_by(code=req.code).first():
        raise HTTPException(409, "Feature code already exists")

    feature = Feature(
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
    db.add(feature)
    db.commit()

    _internal_outbox(db, "feature.created", {"feature_code": feature.code, "name": feature.name})

    logger.info(f"Created feature: {feature.code}")
    return {
        "feature_code": feature.code,
        "name": feature.name,
        "usage_type": feature.usage_type,
        "reset_period": feature.reset_period
    }


@router.get("/features")
async def list_features(
    active: Optional[bool] = None,
    cluster: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all features with optional filters."""
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


@router.get("/features/{feature_code}")
async def get_feature(feature_code: str, db: Session = Depends(get_db)):
    """Get a specific feature by code."""
    feature = db.query(Feature).filter_by(code=feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature not found")

    return {
        "code": feature.code,
        "name": feature.name,
        "description": feature.description,
        "cluster": feature.cluster,
        "usage_type": feature.usage_type,
        "max_unit": feature.max_unit,
        "reset_period": feature.reset_period,
        "active": feature.active
    }


@router.put("/features/{feature_code}")
async def update_feature(feature_code: str, req: FeatureRequest, db: Session = Depends(get_db)):
    """Update an existing feature."""
    feature = db.query(Feature).filter_by(code=feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature not found")

    feature.name = req.name
    feature.description = req.description or feature.description
    feature.cluster = req.cluster or feature.cluster
    feature.usage_type = req.usage_type or feature.usage_type
    feature.max_unit = req.max_unit
    feature.reset_period = req.reset_period or feature.reset_period

    db.commit()
    _internal_outbox(db, "feature.updated", {"feature_code": feature_code})
    logger.info(f"Updated feature: {feature_code}")

    return {
        "code": feature.code,
        "name": feature.name,
        "usage_type": feature.usage_type,
        "active": feature.active
    }


@router.delete("/features/{feature_code}", status_code=204)
async def delete_feature(feature_code: str, db: Session = Depends(get_db)):
    """Deactivate a feature (soft delete)."""
    feature = db.query(Feature).filter_by(code=feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature not found")

    feature.active = False
    db.commit()
    _internal_outbox(db, "feature.deactivated", {"feature_code": feature_code})
    logger.info(f"Deactivated feature: {feature_code}")
    return None


# ---------------------------------------------------------------------------
# Plan-Feature Mapping
# ---------------------------------------------------------------------------

@router.put("/plans/{plan_code}/features/{feature_code}")
async def add_feature_to_plan(
    plan_code: str,
    feature_code: str,
    db: Session = Depends(get_db),
    req: FeatureRequest = None
):
    """
    Add or enable a feature in a plan.
    If body is provided, updates feature metadata and allows per-plan limits (limits.max_value).
    """
    plan = db.query(SubscriptionPlan).filter_by(code=plan_code).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    feature = db.query(Feature).filter_by(code=feature_code).first()
    if not feature:
        raise HTTPException(404, "Feature not found")

    limits = None
    if req:
        feature.name = req.name or feature.name
        feature.description = req.description or feature.description
        feature.cluster = req.cluster or feature.cluster
        feature.usage_type = req.usage_type or feature.usage_type
        feature.max_unit = req.max_unit or feature.max_unit
        feature.reset_period = req.reset_period or feature.reset_period
        if req.max_unit:
            try:
                limits = {"max_value": int(req.max_unit)}
            except ValueError:
                limits = None

    pf = db.query(PlanFeature).filter_by(
        plan_code=plan_code,
        feature_code=feature_code
    ).first()

    if pf:
        pf.enabled = True
        if limits is not None:
            pf.limits = limits
    else:
        pf = PlanFeature(
            id=uuid.uuid4(),
            plan_code=plan_code,
            feature_code=feature_code,
            enabled=True,
            limits=limits
        )
        db.add(pf)

    db.commit()
    _internal_outbox(db, "plan_feature.added", {"plan_code": plan_code, "feature_code": feature_code})
    logger.info(f"Added feature {feature_code} to plan {plan_code} with limits {pf.limits}")
    return {"plan_code": plan_code, "feature_code": feature_code, "enabled": True, "limits": pf.limits}


@router.delete("/plans/{plan_code}/features/{feature_code}", status_code=204)
async def remove_feature_from_plan(plan_code: str, feature_code: str, db: Session = Depends(get_db)):
    """Remove (disable) a feature from a plan."""
    pf = db.query(PlanFeature).filter_by(
        plan_code=plan_code,
        feature_code=feature_code
    ).first()

    if pf:
        pf.enabled = False
        db.commit()
        _internal_outbox(db, "plan_feature.removed", {"plan_code": plan_code, "feature_code": feature_code})
        logger.info(f"Removed feature {feature_code} from plan {plan_code}")

    return None


@router.get("/plans/{plan_code}/features")
async def list_plan_features(plan_code: str, db: Session = Depends(get_db)):
    """List all features for a plan."""
    if not db.query(SubscriptionPlan).filter_by(code=plan_code).first():
        raise HTTPException(404, "Plan not found")

    features = db.query(PlanFeature, Feature).join(
        Feature, PlanFeature.feature_code == Feature.code
    ).filter(
        PlanFeature.plan_code == plan_code,
        PlanFeature.enabled == True
    ).all()

    return {
        "plan_code": plan_code,
        "features": [
            {
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "cluster": f.cluster,
                "usage_type": f.usage_type,
                "max_unit": f.max_unit,
                "reset_period": f.reset_period,
                "limits": pf.limits,
                "enabled": pf.enabled
            }
            for pf, f in features
        ],
        "total": len(features)
    }


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@router.post("/roles", status_code=201)
async def create_role(req: RoleRequest, db: Session = Depends(get_db)):
    """Create a new role."""
    try:
        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(409, "Role code already exists")

        role = Role(
            role_id=uuid.uuid4(),
            code=req.code,
            description=req.description or ""
        )
        db.add(role)
        db.commit()
        db.refresh(role)

        _internal_outbox(db, "role.created", {"role_code": role.code})

        logger.info(f"Created role: {role.code}")
        return {
            "role_id": str(role.role_id),
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Role code already exists")
    except Exception as e:
        db.rollback()
        logger.error(f"Role creation failed: {e}")
        raise HTTPException(500, "Internal server error")


@router.get("/roles")
async def list_roles(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0)
):
    """List all roles."""
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "roles": [
            {
                "role_id": str(r.role_id),
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


# legacy endpoints - must be defined BEFORE parameterized routes to avoid conflicts
@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role_legacy(
    role_code: str = Query(...),
    permission_code: str = Query(...),
    db: Session = Depends(get_db)
):
    """Add permission to a role (legacy, use POST /roles/{role_code}/permissions instead)."""
    try:
        existing = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == permission_code
        ).first()

        if existing:
            raise HTTPException(409, "Permission already assigned to role")

        rp = RolePermission(
            id=uuid.uuid4(),
            role_code=role_code,
            permission_code=permission_code
        )
        db.add(rp)
        db.commit()

        _internal_outbox(db, "role_permission.added", {"role_code": role_code, "permission_code": permission_code})

        return {"message": "Permission added to role"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add permission to role: {e}")
        raise HTTPException(500, "Internal server error")


@router.delete("/roles/delete-permission", status_code=204)
async def remove_permission_from_role_legacy(
    role_code: str = Query(...),
    permission_code: str = Query(...),
    db: Session = Depends(get_db)
):
    """Remove permission from a role (legacy, use DELETE /roles/{role_code}/permissions/{perm} instead)."""
    assignment = db.query(RolePermission).filter(
        RolePermission.role_code == role_code,
        RolePermission.permission_code == permission_code
    ).first()

    if not assignment:
        raise HTTPException(404, "Permission not assigned to role")

    db.delete(assignment)
    db.commit()
    _internal_outbox(db, "role_permission.removed", {"role_code": role_code, "permission_code": permission_code})
    return None


# parameterized routes come after literal paths
@router.get("/roles/{role_code}")
async def get_role(role_code: str, db: Session = Depends(get_db)):
    """Get a specific role by code."""
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        raise HTTPException(404, "Role not found")

    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "description": role.description,
        "created_at": role.created_at.isoformat()
    }


@router.put("/roles/{role_code}")
async def update_role(role_code: str, req: RoleRequest, db: Session = Depends(get_db)):
    """Update an existing role."""
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        raise HTTPException(404, "Role not found")

    role.description = req.description or role.description
    db.commit()
    _internal_outbox(db, "role.updated", {"role_code": role_code})
    logger.info(f"Updated role: {role_code}")

    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "description": role.description
    }


@router.delete("/roles/{role_code}", status_code=204)
async def delete_role(role_code: str, db: Session = Depends(get_db)):
    """Delete a role. Fails if role has assigned permissions or users."""
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        raise HTTPException(404, "Role not found")

    if db.query(RolePermission).filter(RolePermission.role_code == role_code).first():
        raise HTTPException(400, "Cannot delete role with assigned permissions. Remove permissions first.")

    db.delete(role)
    db.commit()
    _internal_outbox(db, "role.deleted", {"role_code": role_code})
    logger.info(f"Deleted role: {role_code}")
    return None


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

@router.post("/permissions", status_code=201)
async def create_permission(req: PermissionRequest, db: Session = Depends(get_db)):
    """Create a new permission."""
    try:
        existing = db.query(Permission).filter(Permission.code == req.code).first()
        if existing:
            raise HTTPException(409, "Permission already exists")

        perm = Permission(
            permission_id=uuid.uuid4(),
            code=req.code,
            description=req.description or ""
        )
        db.add(perm)
        db.commit()
        db.refresh(perm)

        _internal_outbox(db, "permission.created", {"permission_code": perm.code})

        logger.info(f"Created permission: {perm.code}")
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
        raise HTTPException(500, "Internal server error")


@router.get("/permissions")
async def list_permissions(db: Session = Depends(get_db)):
    """List all permissions."""
    permissions = db.query(Permission).order_by(Permission.code).all()
    return {
        "permissions": [
            {"permission_id": str(p.permission_id), "code": p.code, "description": p.description}
            for p in permissions
        ],
        "total": len(permissions)
    }


@router.get("/permissions/{permission_code}")
async def get_permission(permission_code: str, db: Session = Depends(get_db)):
    """Get a specific permission by code."""
    perm = db.query(Permission).filter(Permission.code == permission_code).first()
    if not perm:
        raise HTTPException(404, "Permission not found")

    return {
        "permission_id": str(perm.permission_id),
        "code": perm.code,
        "description": perm.description
    }


@router.put("/permissions/{permission_code}")
async def update_permission(permission_code: str, req: PermissionRequest, db: Session = Depends(get_db)):
    """Update an existing permission."""
    perm = db.query(Permission).filter(Permission.code == permission_code).first()
    if not perm:
        raise HTTPException(404, "Permission not found")

    perm.description = req.description or perm.description
    db.commit()
    _internal_outbox(db, "permission.updated", {"permission_code": permission_code})
    logger.info(f"Updated permission: {permission_code}")

    return {
        "permission_id": str(perm.permission_id),
        "code": perm.code,
        "description": perm.description
    }


@router.delete("/permissions/{permission_code}", status_code=204)
async def delete_permission(permission_code: str, db: Session = Depends(get_db)):
    """Delete a permission. Fails if assigned to any role."""
    perm = db.query(Permission).filter(Permission.code == permission_code).first()
    if not perm:
        raise HTTPException(404, "Permission not found")

    if db.query(RolePermission).filter(RolePermission.permission_code == permission_code).first():
        raise HTTPException(400, "Cannot delete permission assigned to roles. Remove from roles first.")

    db.delete(perm)
    db.commit()
    _internal_outbox(db, "permission.deleted", {"permission_code": permission_code})
    logger.info(f"Deleted permission: {permission_code}")
    return None


# ---------------------------------------------------------------------------
# Role-Permission Mapping
# ---------------------------------------------------------------------------

@router.post("/roles/{role_code}/permissions", status_code=201)
async def add_permission_to_role(role_code: str, req: PermissionRequest, db: Session = Depends(get_db)):
    """Add a permission to a role."""
    try:
        # validate role exists
        if not db.query(Role).filter(Role.code == role_code).first():
            raise HTTPException(404, "Role not found")

        # validate permission exists
        if not db.query(Permission).filter(Permission.code == req.code).first():
            raise HTTPException(404, "Permission not found")

        existing = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == req.code
        ).first()

        if existing:
            raise HTTPException(409, "Permission already assigned to role")

        rp = RolePermission(
            id=uuid.uuid4(),
            role_code=role_code,
            permission_code=req.code
        )
        db.add(rp)
        db.commit()

        _internal_outbox(db, "role_permission.added", {"role_code": role_code, "permission_code": req.code})

        logger.info(f"Added permission {req.code} to role {role_code}")
        return {"role_code": role_code, "permission_code": req.code, "assigned": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add permission to role: {e}")
        raise HTTPException(500, "Internal server error")


@router.delete("/roles/{role_code}/permissions/{permission_code}", status_code=204)
async def remove_permission_from_role(role_code: str, permission_code: str, db: Session = Depends(get_db)):
    """Remove a permission from a role."""
    assignment = db.query(RolePermission).filter(
        RolePermission.role_code == role_code,
        RolePermission.permission_code == permission_code
    ).first()

    if not assignment:
        raise HTTPException(404, "Permission not assigned to role")

    db.delete(assignment)
    db.commit()
    _internal_outbox(db, "role_permission.removed", {"role_code": role_code, "permission_code": permission_code})
    logger.info(f"Removed permission {permission_code} from role {role_code}")
    return None


@router.get("/roles/{role_code}/permissions")
async def get_role_permissions(role_code: str, db: Session = Depends(get_db)):
    """Get all permissions for a role."""
    if not db.query(Role).filter(Role.code == role_code).first():
        raise HTTPException(404, "Role not found")

    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_code == Permission.code
    ).filter(
        RolePermission.role_code == role_code
    ).all()

    return {
        "role_code": role_code,
        "permissions": [
            {"code": p.code, "description": p.description}
            for rp, p in role_perms
        ],
        "total": len(role_perms)
    }
