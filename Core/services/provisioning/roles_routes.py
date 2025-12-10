import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import Role, RolePermission, Permission
from Schemas import RoleRequest
from core.db_config import get_db
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["roles"])


@router.post("/roles", status_code=201)
async def create_role(req: RoleRequest, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="create_role", status="start").inc()

        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(status_code=409, detail="Role code already exists")

        role = Role(role_id=uuid.uuid4(), code=req.code, name=req.name or req.code, description=req.description or "")
        db.add(role)
        db.commit()
        db.refresh(role)

        req_total.labels(operation="create_role", status="success").inc()
        req_duration.labels(operation="create_role").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Created role: {role.role_id} ({role.code})")
        return {
            "role_id": str(role.role_id),
            "name": role.name or role.code,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat(),
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
    offset: int = Query(0, ge=0),
):
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "roles": [
            {
                "role_id": str(r.role_id),
                "name": r.name or r.code,
                "code": r.code,
                "description": r.description,
                "created_at": r.created_at.isoformat(),
            }
            for r in roles
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    exists = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == uuid.UUID(role_id), RolePermission.permission_id == uuid.UUID(permission_id))
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Permission already assigned to role")

    rp = RolePermission(role_permission_id=uuid.uuid4(), role_id=uuid.UUID(role_id), permission_id=uuid.UUID(permission_id))
    db.add(rp)
    db.commit()
    return {"message": "Permission added to role"}


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204)
async def remove_permission_from_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    assignment = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == uuid.UUID(role_id), RolePermission.permission_id == uuid.UUID(permission_id))
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Permission not assigned to role")
    db.delete(assignment)
    db.commit()
    return {}


@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(role_id: str, db: Session = Depends(get_db)):
    role_perms = (
        db.query(RolePermission, Permission)
        .join(Permission, RolePermission.permission_id == Permission.permission_id)
        .filter(RolePermission.role_id == uuid.UUID(role_id))
        .all()
    )
    return {
        "role_id": role_id,
        "permissions": [
            {
                "permission_id": str(p.permission_id),
                "code": p.code,
                "description": p.description,
            }
            for rp, p in role_perms
        ],
    }

