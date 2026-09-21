"""
Roles Admin API — global role CRUD + role↔permission mapping + permission catalogue.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Role, RolePermission, Permission, TenantRole, TenantRolePermission
from provisioning_service.Schemas import RoleRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Roles Admin"])


@router.post("/roles", status_code=201)
async def create_role(
        req: RoleRequest,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.create")),
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

        # Outbox audit event (system-level: no tenant scope → use role_id as surrogate)
        try:
            create_outbox_event(
                db, uuid.uuid4(), "role.created",
                {"role_id": str(role.role_id), "code": role.code},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for role.created: {_oe}")

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

@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role(
        role_code: str,
        permission_code: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.map_permission", resource_from="none")),
):
    """Add permission to a role"""
    try:
        # Check if already exists
        existing = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == permission_code
        ).first()

        if existing:
            raise HTTPException(status_code=409, detail="Permission already assigned to role")

        rp = RolePermission(
            id=uuid.uuid4(),
            role_code=role_code,
            permission_code=permission_code
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
        role_code: str,
        permission_code: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.unmap_permission", resource_from="none")),
):
    """Remove permission from a role"""
    try:
        assignment = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == permission_code
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

@router.get("/permissions")
async def get_all_permissions(
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(100, ge=1, le=500, description="Maximum number of records to return"),
        search: Optional[str] = Query(None, description="Search by code or description"),
        db: Session = Depends(get_db)
):
    """
    Get all permissions in the system.

    Returns a paginated list of all available permissions.
    """
    try:
        query = db.query(Permission)

        # Apply search filter if provided
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (Permission.code.ilike(search_pattern)) |
                (Permission.description.ilike(search_pattern))
            )

        # Get total count
        total = query.count()

        # Apply pagination and ordering
        permissions = query.order_by(Permission.code).offset(skip).limit(limit).all()

        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "permissions": [
                {
                    "permission_id": str(p.permission_id),
                    "code": p.code,
                    "description": p.description,
                    "created_at": p.created_at.isoformat() if p.created_at else None
                }
                for p in permissions
            ]
        }
    except Exception as e:
        logger.error(f"Get permissions failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles/{role_code}/permissions")
async def get_role_permissions(
        role_code: str,
        db: Session = Depends(get_db)
):
    """Get all permissions for a role (global or tenant-scoped).

    - If ``role_code`` is a UUID, it's treated as a tenant-role ``role_id``.
    - Otherwise it's treated as a global role ``code``.
    """
    # Try to parse as UUID -> tenant role lookup
    try:
        role_id = uuid.UUID(role_code)
        role = db.query(TenantRole).filter(TenantRole.role_id == role_id).first()
        if role:
            perms = db.query(TenantRolePermission, Permission).join(
                Permission, TenantRolePermission.permission_code == Permission.code
            ).filter(
                TenantRolePermission.tenant_role_id == role_id
            ).all()
            return {
                "role_code": role_code,
                "role_type": "tenant",
                "permissions": [
                    {
                        "permission_code": trp.permission_code,
                        "code": p.code,
                        "description": p.description
                    }
                    for trp, p in perms
                ]
            }
    except ValueError:
        pass  # Not a UUID, treat as global role code

    # Global role lookup
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_code == Permission.code
    ).filter(
        RolePermission.role_code == role_code
    ).all()

    return {
        "role_code": role_code,
        "role_type": "global",
        "permissions": [
            {
                "permission_code": str(rp.permission_code),
                "code": p.code,
                "description": p.description
            }
            for rp, p in role_perms
        ]
    }
