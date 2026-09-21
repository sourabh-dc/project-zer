"""
Org Units API — organisational unit CRUD, activate/deactivate, user assignments.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import (
    Tenant, User, OrgUnit, UserOrgAssignment, Role, TenantRoleScope, ApprovedRangeOrgUnit,
)
from provisioning_service.Schemas import OrgUnitRequest, OrgUnitAssignmentRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["Org Units"])


@router.get("/org_units")
async def list_org_units(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    parent_org_unit_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List organisational units with optional filters"""
    try:
        q = db.query(OrgUnit)

        if tenant_id:
            q = q.filter(OrgUnit.tenant_id == uuid.UUID(tenant_id))
        if status:
            q = q.filter(OrgUnit.status == status)
        if parent_org_unit_id:
            q = q.filter(OrgUnit.parent_org_unit_id == uuid.UUID(parent_org_unit_id))

        total = q.count()
        org_units = q.order_by(OrgUnit.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "org_units": [
                {
                    "org_unit_id": str(ou.org_unit_id),
                    "tenant_id": str(ou.tenant_id),
                    "name": ou.name,
                    "type": ou.type,
                    "status": ou.status,
                    "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
                    "code": ou.code,
                    "description": ou.description,
                    "manager_user_id": str(ou.manager_user_id) if ou.manager_user_id else None,
                    "external_id": ou.external_id,
                    "path": ou.path,
                    "depth": ou.depth,
                    "created_at": ou.created_at.isoformat(),
                    "updated_at": ou.updated_at.isoformat() if ou.updated_at else None,
                }
                for ou in org_units
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except Exception as e:
        logger.error(f"❌ List org units failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/org_units/{org_unit_id}")
async def get_org_unit(org_unit_id: str, db: Session = Depends(get_db)):
    """Get a single organisational unit by ID"""
    try:
        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")
        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
            "code": ou.code,
            "description": ou.description,
            "manager_user_id": str(ou.manager_user_id) if ou.manager_user_id else None,
            "external_id": ou.external_id,
            "path": ou.path,
            "depth": ou.depth,
            "created_at": ou.created_at.isoformat(),
            "updated_at": ou.updated_at.isoformat() if ou.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org unit ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/org_units", status_code=201)
async def create_org_unit(
        req: OrgUnitRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.create")),
):
    """Create a new organisational unit"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Optional parent validation
        parent_id = None
        if getattr(req, 'parent_org_unit_id', None):
            try:
                parent_id = uuid.UUID(req.parent_org_unit_id)
                parent = db.query(OrgUnit).filter(OrgUnit.org_unit_id == parent_id, OrgUnit.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent org unit not found for tenant")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid parent_org_unit_id format")

        manager_uuid = None
        if getattr(req, 'manager_user_id', None):
            try:
                manager_uuid = uuid.UUID(req.manager_user_id)
                manager = db.query(User).filter(User.user_id == manager_uuid, User.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not manager:
                    raise HTTPException(status_code=404, detail="Manager user not found for tenant")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid manager_user_id format")

        ou = OrgUnit(
            org_unit_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            type=req.type,
            status=getattr(req, 'status', 'active'),
            parent_org_unit_id=parent_id,
            code=getattr(req, 'code', None),
            description=getattr(req, 'description', None),
            manager_user_id=manager_uuid,
            external_id=getattr(req, 'external_id', None),
            path=getattr(req, 'path', None),
            depth=getattr(req, 'depth', None)
        )

        db.add(ou)
        db.commit()
        db.refresh(ou)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "org_unit.created",
                {"org_unit_id": str(ou.org_unit_id), "name": ou.name, "type": ou.type},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.created: {_oe}")

        logger.info(f"Created org unit: {ou.org_unit_id} ({ou.name}) for tenant: {req.tenant_id}")

        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "created_at": ou.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format in request")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Create org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/org_units/{org_unit_id}")
async def update_org_unit(
        org_unit_id: str,
        req: OrgUnitRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Update an existing organisational unit"""
    try:
        try:
            ou_id = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # Ensure tenant matches
        if str(ou.tenant_id) != req.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant mismatch")

        # Update fields
        if getattr(req, 'name', None):
            ou.name = req.name
        if getattr(req, 'type', None):
            ou.type = req.type
        if getattr(req, 'status', None):
            ou.status = req.status

        if getattr(req, 'parent_org_unit_id', None):
            try:
                parent_uuid = uuid.UUID(req.parent_org_unit_id)
                parent = db.query(OrgUnit).filter(OrgUnit.org_unit_id == parent_uuid, OrgUnit.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent org unit not found for tenant")
                ou.parent_org_unit_id = parent_uuid
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid parent_org_unit_id format")

        if getattr(req, 'manager_user_id', None):
            try:
                manager_uuid = uuid.UUID(req.manager_user_id)
                manager = db.query(User).filter(User.user_id == manager_uuid, User.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not manager:
                    raise HTTPException(status_code=404, detail="Manager user not found for tenant")
                ou.manager_user_id = manager_uuid
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid manager_user_id format")

        ou.code = getattr(req, 'code', ou.code)
        ou.description = getattr(req, 'description', ou.description)
        ou.external_id = getattr(req, 'external_id', ou.external_id)
        ou.path = getattr(req, 'path', ou.path)
        ou.depth = getattr(req, 'depth', ou.depth)

        ou.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(ou)

        # Outbox audit event
        try:
            create_outbox_event(
                db, ou.tenant_id, "org_unit.updated",
                {"org_unit_id": str(ou.org_unit_id), "name": ou.name},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.updated: {_oe}")

        logger.info(f"Updated org unit: {ou.org_unit_id}")

        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "updated_at": ou.updated_at.isoformat() if ou.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Update org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/org_units/{org_unit_id}/deactivate")
async def deactivate_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Archive an org unit. Keeps assignments + role scopes; hidden from dropdowns."""
    try:
        ou_id = uuid.UUID(org_unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

    ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
    if not ou:
        raise HTTPException(status_code=404, detail="Org unit not found")

    if ou.status == "archived":
        return {"org_unit_id": org_unit_id, "status": "archived", "affected_users": 0}

    # Count live references so the frontend can warn ("12 users will lose this department")
    affected_users = db.query(UserOrgAssignment).filter(
        UserOrgAssignment.org_unit_id == ou_id,
    ).count()

    ou.status = "archived"
    ou.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, ou.tenant_id, "org_unit.deactivated",
                            {"org_unit_id": org_unit_id, "affected_users": affected_users})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for org_unit.deactivated: {_oe}")

    logger.info(f"Archived org unit: {org_unit_id} ({affected_users} user assignments kept)")
    return {"org_unit_id": org_unit_id, "status": "archived", "affected_users": affected_users}


@router.post("/org_units/{org_unit_id}/activate")
async def activate_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Restore an archived org unit to active."""
    try:
        ou_id = uuid.UUID(org_unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

    ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
    if not ou:
        raise HTTPException(status_code=404, detail="Org unit not found")

    if ou.status == "active":
        return {"org_unit_id": org_unit_id, "status": "active"}

    ou.status = "active"
    ou.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, ou.tenant_id, "org_unit.activated", {"org_unit_id": org_unit_id})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for org_unit.activated: {_oe}")

    logger.info(f"Reactivated org unit: {org_unit_id}")
    return {"org_unit_id": org_unit_id, "status": "active"}

@router.delete("/org_units/{org_unit_id}", status_code=200)
async def delete_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.delete", resource_from="none")),
):
    """
    Soft delete by default: active units get archived (assignments + scopes kept).

    Hard delete only when the unit is already archived AND has zero references
    (no children, no user assignments, no role scopes, no range mappings).
    """
    try:
        try:
            ou_id = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # ── Soft path: archive active units ───────────────────────
        if ou.status != "archived":
            affected_users = db.query(UserOrgAssignment).filter(
                UserOrgAssignment.org_unit_id == ou_id,
            ).count()
            ou.status = "archived"
            ou.updated_at = datetime.now(timezone.utc)
            db.commit()
            try:
                create_outbox_event(db, ou.tenant_id, "org_unit.deactivated",
                                    {"org_unit_id": org_unit_id, "affected_users": affected_users, "via": "delete"})
                db.commit()
            except Exception as _oe:
                logger.warning(f"Outbox event failed for org_unit.deactivated: {_oe}")
            logger.info(f"Soft-deleted (archived) org unit: {org_unit_id}")
            return {"org_unit_id": org_unit_id, "status": "archived", "deleted": False,
                    "affected_users": affected_users}

        # ── Hard path: archived + zero references ─────────────────
        children_count = db.query(OrgUnit).filter(OrgUnit.parent_org_unit_id == ou_id).count()
        assignment_count = db.query(UserOrgAssignment).filter(UserOrgAssignment.org_unit_id == ou_id).count()
        home_count = db.query(User).filter(User.home_org_unit_id == ou_id).count()
        role_scope_count = db.query(TenantRoleScope).filter(
            TenantRoleScope.scope_type == "department",
            TenantRoleScope.scope_id == ou_id,
        ).count()
        range_count = db.query(ApprovedRangeOrgUnit).filter(
            ApprovedRangeOrgUnit.org_unit_id == ou_id,
        ).count()

        blockers = {
            "child_units": children_count,
            "user_assignments": assignment_count,
            "home_org_unit_users": home_count,
            "role_scopes": role_scope_count,
            "approved_range_mappings": range_count,
        }
        blockers = {k: v for k, v in blockers.items() if v > 0}
        if blockers:
            raise HTTPException(
                status_code=400,
                detail=f"Org unit is archived but still referenced: {blockers}. Remove references before hard delete.",
            )

        _tid = ou.tenant_id
        db.delete(ou)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, _tid, "org_unit.deleted", {"org_unit_id": org_unit_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.deleted: {_oe}")

        logger.info(f"Hard-deleted org unit: {org_unit_id}")
        return {"org_unit_id": org_unit_id, "status": "deleted", "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Delete org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# =============================================================================
# ORG UNIT - USER ASSIGNMENT ENDPOINTS
# =============================================================================

@router.post("/org_units/assignments", status_code=201)
async def assign_user_to_org_unit(
        req: OrgUnitAssignmentRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.assign_user")),
):
    """
    Assign a user to an organisational unit with a specific role.

    This creates a mapping between a user and an org unit, defining their
    role within that organisational structure.
    """
    try:
        # Validate UUIDs
        try:
            user_uuid = uuid.UUID(req.user_id)
            org_unit_uuid = uuid.UUID(req.org_unit_id)
            role_uuid = uuid.UUID(req.role_id)
            assigned_by_uuid = uuid.UUID(req.assigned_by) if req.assigned_by else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {e}")

        # Verify user exists
        user = db.query(User).filter(User.user_id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify org unit exists and belongs to same tenant
        org_unit = db.query(OrgUnit).filter(
            OrgUnit.org_unit_id == org_unit_uuid,
            OrgUnit.tenant_id == user.tenant_id
        ).first()
        if not org_unit:
            raise HTTPException(status_code=404, detail="Org unit not found or does not belong to user's tenant")

        # Verify role exists
        role = db.query(Role).filter(Role.role_id == role_uuid).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Check if assignment already exists
        existing = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == user_uuid,
            UserOrgAssignment.org_unit_id == org_unit_uuid
        ).first()

        if existing:
            # Update existing assignment with new role
            existing.role_id = role_uuid
            existing.assigned_by = assigned_by_uuid
            existing.assigned_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)

            logger.info(f"Updated user {user_uuid} assignment to org unit {org_unit_uuid} with role {role_uuid}")

            return {
                "assignment_id": str(existing.assignment_id),
                "user_id": str(existing.user_id),
                "org_unit_id": str(existing.org_unit_id),
                "role_id": str(existing.role_id),
                "role_code": role.code,
                "assigned_by": str(existing.assigned_by) if existing.assigned_by else None,
                "assigned_at": existing.assigned_at.isoformat() if existing.assigned_at else None,
                "message": "Assignment updated"
            }

        # Create new assignment
        assignment = UserOrgAssignment(
            user_id=user_uuid,
            org_unit_id=org_unit_uuid,
            role_id=role_uuid,
            assigned_by=assigned_by_uuid
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "org_unit_assignment.created",
                {
                    "user_id": req.user_id,
                    "org_unit_id": req.org_unit_id,
                    "role_id": req.role_id,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit_assignment.created: {_oe}")

        logger.info(f"Assigned user {user_uuid} to org unit {org_unit_uuid} with role {role_uuid}")

        return {
            "assignment_id": str(assignment.assignment_id),
            "user_id": str(assignment.user_id),
            "org_unit_id": str(assignment.org_unit_id),
            "role_id": str(assignment.role_id),
            "role_code": role.code,
            "assigned_by": str(assignment.assigned_by) if assignment.assigned_by else None,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
            "message": "Assignment created"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Assign user to org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/org_units/{org_unit_id}/users")
async def get_org_unit_users(
        org_unit_id: str,
        include_children: bool = Query(False, description="Include users from child org units"),
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage"))
):
    """
    Get all users assigned to an organisational unit.

    Optionally include users from child org units.
    """
    try:
        try:
            ou_uuid = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        # Verify org unit exists
        org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_uuid).first()
        if not org_unit:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # Get org unit IDs to query
        org_unit_ids = [ou_uuid]

        if include_children:
            # Get all child org units recursively
            def get_children_ids(parent_id):
                children = db.query(OrgUnit.org_unit_id).filter(
                    OrgUnit.parent_org_unit_id == parent_id
                ).all()
                child_ids = [c[0] for c in children]
                for child_id in child_ids:
                    child_ids.extend(get_children_ids(child_id))
                return child_ids

            org_unit_ids.extend(get_children_ids(ou_uuid))

        # Query assignments with user and role info
        assignments = db.query(
            UserOrgAssignment,
            User,
            Role,
            OrgUnit
        ).join(
            User, UserOrgAssignment.user_id == User.user_id
        ).join(
            Role, UserOrgAssignment.role_id == Role.role_id
        ).join(
            OrgUnit, UserOrgAssignment.org_unit_id == OrgUnit.org_unit_id
        ).filter(
            UserOrgAssignment.org_unit_id.in_(org_unit_ids)
        ).all()

        users = []
        from provisioning_service.Models import UserIdentity
        for assignment, user, role, ou in assignments:
            identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
            users.append({
                "assignment_id": str(assignment.assignment_id),
                "user_id": str(user.user_id),
                "email": identity.email if identity else None,
                "first_name": identity.first_name if identity else None,
                "last_name": identity.last_name if identity else None,
                "display_name": user.display_name,
                "position": user.position,
                "is_active": user.is_active,
                "org_unit_id": str(ou.org_unit_id),
                "org_unit_name": ou.name,
                "role_id": str(role.role_id),
                "role_code": role.code,
                "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None
            })

        return {
            "org_unit_id": str(org_unit.org_unit_id),
            "org_unit_name": org_unit.name,
            "include_children": include_children,
            "total_users": len(users),
            "users": users
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get org unit users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/org_units")
async def get_user_org_units(
        user_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage"))
):
    """
    Get all organisational units a user is assigned to.
    """
    try:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")

        # Verify user exists
        user = db.query(User).filter(User.user_id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Query assignments
        assignments = db.query(
            UserOrgAssignment,
            OrgUnit,
            Role
        ).join(
            OrgUnit, UserOrgAssignment.org_unit_id == OrgUnit.org_unit_id
        ).join(
            Role, UserOrgAssignment.role_id == Role.role_id
        ).filter(
            UserOrgAssignment.user_id == user_uuid
        ).all()

        org_units = []
        for assignment, ou, role in assignments:
            org_units.append({
                "assignment_id": str(assignment.assignment_id),
                "org_unit_id": str(ou.org_unit_id),
                "org_unit_name": ou.name,
                "org_unit_type": ou.type,
                "org_unit_status": ou.status,
                "role_id": str(role.role_id),
                "role_code": role.code,
                "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None
            })

        from provisioning_service.Models import UserIdentity
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
        return {
            "user_id": str(user.user_id),
            "email": identity.email if identity else None,
            "first_name": identity.first_name if identity else None,
            "last_name": identity.last_name if identity else None,
            "total_assignments": len(org_units),
            "org_units": org_units
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user org units failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/org_units/assignments/{assignment_id}", status_code=204)
async def remove_user_from_org_unit(
        assignment_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.remove_user", resource_from="none")),
):
    """
    Remove a user's assignment from an organisational unit.
    """
    try:
        try:
            assignment_uuid = uuid.UUID(assignment_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assignment_id format")

        assignment = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.assignment_id == assignment_uuid
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        user_id = assignment.user_id
        org_unit_id = assignment.org_unit_id

        db.delete(assignment)
        db.commit()

        logger.info(f"Removed user {user_id} from org unit {org_unit_id}")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Remove user from org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/org_units/{org_unit_id}/users/{user_id}", status_code=204)
async def remove_user_from_org_unit_by_ids(
        org_unit_id: str,
        user_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.remove_user", resource_from="none")),
):
    """
    Remove a user's assignment from an organisational unit by org_unit_id and user_id.
    """
    try:
        try:
            ou_uuid = uuid.UUID(org_unit_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID format")

        assignment = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.org_unit_id == ou_uuid,
            UserOrgAssignment.user_id == user_uuid
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        db.delete(assignment)
        db.commit()

        logger.info(f"Removed user {user_id} from org unit {org_unit_id}")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Remove user from org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
