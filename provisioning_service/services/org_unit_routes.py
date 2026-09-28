"""
Org Units API — organisational unit CRUD, activate/deactivate, user assignments.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import (
    Tenant, User, UserIdentity, OrgUnit, UserOrgAssignment, Role, TenantRoleScope, ApprovedRangeOrgUnit,
    CostCentre, OrgUnitAuditEvent,
)
from provisioning_service.Schemas import OrgUnitRequest, OrgUnitAssignmentRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["Org Units"])


# ── Org unit history helpers ──────────────────────────────────────

def _ctx_user_id(ctx) -> Optional[uuid.UUID]:
    """Best-effort actor user id from auth context."""
    try:
        sub = ctx.get("sub") if isinstance(ctx, dict) else getattr(ctx, "sub", None)
        return uuid.UUID(str(sub)) if sub else None
    except Exception:
        return None


def _record_ou_event(db: Session, tenant_id, org_unit_id, actor_user_id, action: str, lines):
    """Append one audit event for an org unit. ``lines`` = human-readable changes."""
    if isinstance(lines, str):
        lines = [lines]
    db.add(OrgUnitAuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        org_unit_id=org_unit_id,
        actor_user_id=actor_user_id,
        action=action,
        detail="\n".join(lines) if lines else None,
    ))


def _ou_history_payload(db: Session, org_unit_id, limit: int = 50) -> list:
    """Per-org-unit audit feed: actor, action, details, timestamp — newest first."""
    rows = (
        db.query(OrgUnitAuditEvent, User)
        .outerjoin(User, OrgUnitAuditEvent.actor_user_id == User.user_id)
        .filter(OrgUnitAuditEvent.org_unit_id == org_unit_id)
        .order_by(OrgUnitAuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "actor": u.display_name if u else None,
            "action": e.action,
            "details": e.detail.split("\n") if e.detail else [],
            "timestamp": e.created_at.isoformat() if e.created_at else None,
        }
        for e, u in rows
    ]

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

@router.get("/departments")
async def list_departments(
    tenant_id: str = Query(...),
    search: Optional[str] = Query(None, description="Search department name or code"),
    status: Optional[str] = Query(None, description="active | archived"),
    type: Optional[str] = Query(None, description="Department type filter"),
    cost_centre_id: Optional[str] = Query(None, description="Only departments linked to this cost centre"),
    users: Optional[str] = Query(None, description="has_users | no_users"),
    sort: str = Query("name", description="name | users | status | created_at"),
    order: str = Query("asc", description="asc | desc"),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Departments sidebar list.

    Each row: department name + code, type, linked cost centre (name + code),
    status, approver (manager name + email), user count.
    """
    try:
        tid = uuid.UUID(tenant_id)

        # Users-count subquery — powers the Users filter + Users sort at SQL level
        uc = (
            db.query(
                UserOrgAssignment.org_unit_id.label("org_unit_id"),
                func.count(UserOrgAssignment.assignment_id).label("users_count"),
            )
            .group_by(UserOrgAssignment.org_unit_id)
            .subquery()
        )
        users_count_col = func.coalesce(uc.c.users_count, 0)

        q = (
            db.query(OrgUnit, users_count_col.label("users_count"))
            .outerjoin(uc, uc.c.org_unit_id == OrgUnit.org_unit_id)
            .filter(OrgUnit.tenant_id == tid)
        )

        if status:
            q = q.filter(OrgUnit.status == status)
        if type:
            q = q.filter(OrgUnit.type == type)
        if search:
            like = f"%{search}%"
            q = q.filter((OrgUnit.name.ilike(like)) | (OrgUnit.code.ilike(like)))
        if users == "has_users":
            q = q.filter(users_count_col > 0)
        elif users == "no_users":
            q = q.filter(users_count_col == 0)
        if cost_centre_id:
            cc_id = uuid.UUID(cost_centre_id)
            q = q.filter(OrgUnit.org_unit_id.in_(
                db.query(CostCentre.department_id).filter(
                    CostCentre.cost_centre_id == cc_id,
                    CostCentre.department_id.isnot(None),
                )
            ))

        total = q.count()

        sort_col = {
            "name": OrgUnit.name,
            "status": OrgUnit.status,
            "users": users_count_col,
            "created_at": OrgUnit.created_at,
        }.get(sort, OrgUnit.name)
        q = q.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
        rows = q.limit(limit).offset(offset).all()

        departments_rows = [r for r, _cnt in rows]
        count_map = {r.org_unit_id: cnt for r, cnt in rows}

        # Batch-load linked cost centres (CostCentre.department_id -> org unit)
        ou_ids = [r.org_unit_id for r in departments_rows]
        cc_map = {}
        if ou_ids:
            ccs = db.query(CostCentre).filter(CostCentre.department_id.in_(ou_ids)).all()
            for cc in ccs:
                cc_map[cc.department_id] = cc

        # Batch-load approvers (manager -> user identity)
        mgr_ids = [r.manager_user_id for r in departments_rows if r.manager_user_id]
        approver_map = {}
        if mgr_ids:
            idents = db.query(UserIdentity).filter(UserIdentity.user_id.in_(mgr_ids)).all()
            for ident in idents:
                name = f"{ident.first_name or ''} {ident.last_name or ''}".strip() or ident.email
                approver_map[ident.user_id] = {
                    "user_id": str(ident.user_id),
                    "name": name,
                    "email": ident.email,
                }

        departments = []
        for r in departments_rows:
            cc = cc_map.get(r.org_unit_id)
            departments.append({
                "org_unit_id": str(r.org_unit_id),
                "parent_org_unit_id": str(r.parent_org_unit_id) if r.parent_org_unit_id else None,
                "name": r.name,
                "code": r.code,
                "type": r.type,
                "status": r.status,
                "description": r.description,
                "cost_centre": {
                    "cost_centre_id": str(cc.cost_centre_id),
                    "name": cc.name,
                    "code": cc.code,
                } if cc else None,
                "approver": approver_map.get(r.manager_user_id),
                "user_count": count_map.get(r.org_unit_id, 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })

        return {
            "departments": departments,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except Exception as e:
        logger.error(f"❌ List departments failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/departments/{org_unit_id}")
async def get_department_detail(org_unit_id: str, db: Session = Depends(get_db)):
    """Department detail for the right sidebar.

    Full department info + linked cost centre + approver + assigned users.
    """
    try:
        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Department not found")

        # Linked cost centre
        cc = db.query(CostCentre).filter(CostCentre.department_id == ou.org_unit_id).first()

        # Approver (manager -> identity)
        approver = None
        if ou.manager_user_id:
            ident = db.query(UserIdentity).filter(UserIdentity.user_id == ou.manager_user_id).first()
            if ident:
                name = f"{ident.first_name or ''} {ident.last_name or ''}".strip() or ident.email
                approver = {"user_id": str(ident.user_id), "name": name, "email": ident.email}

        # Parent unit
        parent = None
        if ou.parent_org_unit_id:
            p = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou.parent_org_unit_id).first()
            if p:
                parent = {"org_unit_id": str(p.org_unit_id), "name": p.name, "code": p.code}

        # Assigned users (with role + identity)
        assignments = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.org_unit_id == ou.org_unit_id
        ).all()
        user_ids = [a.user_id for a in assignments]
        role_ids = [a.role_id for a in assignments]
        ident_map = {}
        if user_ids:
            for ident in db.query(UserIdentity).filter(UserIdentity.user_id.in_(user_ids)).all():
                name = f"{ident.first_name or ''} {ident.last_name or ''}".strip() or ident.email
                ident_map[ident.user_id] = {"name": name, "email": ident.email}
        role_map = {}
        if role_ids:
            role_map = {r.role_id: r.code for r in db.query(Role).filter(Role.role_id.in_(role_ids)).all()}

        users = [
            {
                "user_id": str(a.user_id),
                "name": ident_map.get(a.user_id, {}).get("name"),
                "email": ident_map.get(a.user_id, {}).get("email"),
                "role": role_map.get(a.role_id),
                "assignment_id": str(a.assignment_id),
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            }
            for a in assignments
        ]

        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "code": ou.code,
            "type": ou.type,
            "status": ou.status,
            "description": ou.description,
            "external_id": ou.external_id,
            "parent": parent,
            "cost_centre": {
                "cost_centre_id": str(cc.cost_centre_id),
                "name": cc.name,
                "code": cc.code,
            } if cc else None,
            "approver": approver,
            "users": users,
            "user_count": len(users),
            "history": _ou_history_payload(db, ou.org_unit_id),
            "created_at": ou.created_at.isoformat() if ou.created_at else None,
            "updated_at": ou.updated_at.isoformat() if ou.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid department ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get department detail failed: {e}")
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

        # Audit history event
        try:
            _record_ou_event(db, ou.tenant_id, ou.org_unit_id, _ctx_user_id(ctx),
                             "created", f"Created {ou.type} '{ou.name}'" + (f" ({ou.code})" if ou.code else ""))
            db.commit()
        except Exception as _he:
            logger.warning(f"History event failed for org_unit.created: {_he}")

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

        # Snapshot old values for history diff
        old = {
            "name": ou.name, "type": ou.type, "status": ou.status,
            "code": ou.code, "description": ou.description,
            "manager_user_id": ou.manager_user_id, "parent_org_unit_id": ou.parent_org_unit_id,
        }

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

        # Audit history event with human-readable diff
        try:
            changes = []
            if old["name"] != ou.name:
                changes.append(f"Name: {old['name']} → {ou.name}")
            if old["type"] != ou.type:
                changes.append(f"Type: {old['type']} → {ou.type}")
            if old["status"] != ou.status:
                changes.append(f"Status: {old['status']} → {ou.status}")
            if old["code"] != ou.code:
                changes.append(f"Code: {old['code']} → {ou.code}")
            if old["description"] != ou.description:
                changes.append("Description updated")
            if old["manager_user_id"] != ou.manager_user_id:
                changes.append("Approver changed")
            if old["parent_org_unit_id"] != ou.parent_org_unit_id:
                changes.append("Parent unit changed")
            if changes:
                _record_ou_event(db, ou.tenant_id, ou.org_unit_id, _ctx_user_id(ctx), "updated", changes)
                db.commit()
        except Exception as _he:
            logger.warning(f"History event failed for org_unit.updated: {_he}")

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
        _record_ou_event(db, ou.tenant_id, ou_id, _ctx_user_id(ctx), "deactivated",
                         f"Archived ({affected_users} user assignments kept)")
        db.commit()
    except Exception as _he:
        logger.warning(f"History event failed for org_unit.deactivated: {_he}")

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
        _record_ou_event(db, ou.tenant_id, ou_id, _ctx_user_id(ctx), "activated", "Reactivated")
        db.commit()
    except Exception as _he:
        logger.warning(f"History event failed for org_unit.activated: {_he}")

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

        # Audit history event
        try:
            ident = db.query(UserIdentity).filter(UserIdentity.user_id == user_uuid).first()
            _record_ou_event(db, user.tenant_id, org_unit_uuid, _ctx_user_id(ctx),
                             "user.assigned", f"User {ident.email if ident else user_uuid} assigned with role '{role.code}'")
            db.commit()
        except Exception as _he:
            logger.warning(f"History event failed for org_unit_assignment.created: {_he}")

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

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == org_unit_id).first()

        db.delete(assignment)
        db.commit()

        try:
            if ou:
                ident = db.query(UserIdentity).filter(UserIdentity.user_id == user_id).first()
                _record_ou_event(db, ou.tenant_id, org_unit_id, _ctx_user_id(ctx),
                                 "user.removed", f"User {ident.email if ident else user_id} removed")
                db.commit()
        except Exception as _he:
            logger.warning(f"History event failed for org_unit_assignment.removed: {_he}")

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
