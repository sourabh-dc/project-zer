"""
Tenant Roles API — custom per-tenant roles: CRUD, permissions, scope, status, history.

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
    User, UserIdentity, OrgUnit, CostCentre, Permission,
    TenantRole, TenantRolePermission, TenantUserRole, TenantRoleScope, RoleAuditEvent,
)
from provisioning_service.Schemas import (
    TenantRoleRequest, TenantRolePermissionRequest, TenantRoleAssignRequest,
    TenantRoleUpdateRequest, TenantRolePermissionsReplaceRequest, TenantRoleScopeRequest,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["Tenant Roles"])


# Tenant-scoped roles (custom per tenant; permissions remain global)
# ── Role helpers ──────────────────────────────────────────────────

def _ctx_ids(ctx):
    """Extract (tenant_id, user_id) UUIDs from the auth context."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    user_id = ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context")
    return uuid.UUID(str(tenant_id)), (uuid.UUID(str(user_id)) if user_id else None)


def _record_role_event(db: Session, tenant_id, role_id, actor_user_id, action: str, lines):
    """Append one audit event for a role. ``lines`` = human-readable changes."""
    if isinstance(lines, str):
        lines = [lines]
    db.add(RoleAuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role_id=role_id,
        actor_user_id=actor_user_id,
        action=action,
        detail="\n".join(lines) if lines else None,
    ))


def _role_scope_payload(db: Session, role_id) -> dict:
    """Role scope resolved to names: {"departments": [...], "cost_centres": [...]}."""
    rows = db.query(TenantRoleScope).filter(TenantRoleScope.tenant_role_id == role_id).all()
    dept_ids = [s.scope_id for s in rows if s.scope_type == "department"]
    cc_ids = [s.scope_id for s in rows if s.scope_type == "cost_centre"]
    dept_names = {
        ou.org_unit_id: ou.name
        for ou in db.query(OrgUnit).filter(OrgUnit.org_unit_id.in_(dept_ids)).all()
    } if dept_ids else {}
    cc_names = {
        c.cost_centre_id: c.name
        for c in db.query(CostCentre).filter(CostCentre.cost_centre_id.in_(cc_ids)).all()
    } if cc_ids else {}
    payload = {"departments": [], "cost_centres": []}
    for s in rows:
        if s.scope_type == "department":
            payload["departments"].append({"id": str(s.scope_id), "name": dept_names.get(s.scope_id)})
        elif s.scope_type == "cost_centre":
            payload["cost_centres"].append({"id": str(s.scope_id), "name": cc_names.get(s.scope_id)})
    return payload


def _role_history_payload(db: Session, role_id, limit: int = 50) -> list:
    """Per-role audit feed: actor, action, details, timestamp — newest first."""
    rows = (
        db.query(RoleAuditEvent, User)
        .outerjoin(User, RoleAuditEvent.actor_user_id == User.user_id)
        .filter(RoleAuditEvent.role_id == role_id)
        .order_by(RoleAuditEvent.created_at.desc())
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


@router.post("/tenant-roles", status_code=201)
async def create_tenant_role(
    req: TenantRoleRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.create")),
):
    tenant_id, actor_id = _ctx_ids(ctx)
    existing = db.query(TenantRole).filter(
        TenantRole.tenant_id == tenant_id,
        TenantRole.code == req.code
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Role code already exists for this tenant")

    # Validate permission codes up-front — fail before creating anything
    perm_codes = list(dict.fromkeys(req.permissions or []))  # dedupe, keep order
    if perm_codes:
        found = {
            p.code for p in db.query(Permission).filter(Permission.code.in_(perm_codes)).all()
        }
        unknown = [c for c in perm_codes if c not in found]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown permission code(s): {', '.join(unknown)}",
            )

    role = TenantRole(
        role_id=uuid.uuid4(),
        tenant_id=tenant_id,
        code=req.code,
        name=req.name or req.code,
        description=req.description,
        category=req.category,
        status="active",
        updated_by=actor_id,
    )
    db.add(role)
    for pc in perm_codes:
        db.add(TenantRolePermission(
            id=uuid.uuid4(),
            tenant_role_id=role.role_id,
            permission_code=pc,
        ))
    _record_role_event(db, tenant_id, role.role_id, actor_id, "created",
                       [f"Created role {role.name} ({role.code})"])
    db.commit()
    db.refresh(role)
    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "category": role.category,
        "status": role.status,
        "is_custom": True,
        "permissions": perm_codes,
    }


@router.post("/tenant-roles/{role_id}/permissions", status_code=201)
async def add_permission_to_tenant_role(
    role_id: str,
    req: TenantRolePermissionRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.add_permission", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    perm = db.query(Permission).filter(Permission.code == req.permission_code).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    existing = db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id,
        TenantRolePermission.permission_code == req.permission_code
    ).first()
    if existing:
        return {"role_id": str(role.role_id), "permission_code": req.permission_code, "assigned": True}
    trp = TenantRolePermission(
        id=uuid.uuid4(),
        tenant_role_id=role.role_id,
        permission_code=req.permission_code
    )
    db.add(trp)
    db.commit()
    return {"role_id": str(role.role_id), "permission_code": req.permission_code, "assigned": True}


@router.put("/tenant-roles/{role_id}")
async def update_tenant_role(
    role_id: str,
    req: TenantRoleUpdateRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Update role details (name / description / category) with audit trail."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    changes = []
    update_data = req.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    for field in ("name", "description", "category"):
        if field in update_data:
            old = getattr(role, field)
            new = update_data[field]
            if old != new:
                setattr(role, field, new)
                changes.append(f"Changed {field} from '{old or '—'}' to '{new or '—'}'")

    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    if changes:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "updated", changes)
    db.commit()
    db.refresh(role)
    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "category": role.category,
        "status": role.status,
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
    }


@router.put("/tenant-roles/{role_id}/permissions")
async def replace_tenant_role_permissions(
    role_id: str,
    req: TenantRolePermissionsReplaceRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Replace the full permission set (wizard save). Diffs recorded to history."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    new_codes = list(dict.fromkeys(req.permissions or []))
    found = {
        p.code for p in db.query(Permission).filter(Permission.code.in_(new_codes)).all()
    } if new_codes else set()
    unknown = [c for c in new_codes if c not in found]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown permission code(s): {', '.join(unknown)}")

    old_codes = {
        trp.permission_code
        for trp in db.query(TenantRolePermission).filter(
            TenantRolePermission.tenant_role_id == role.role_id
        ).all()
    }
    new_set = set(new_codes)
    added = sorted(new_set - old_codes)
    removed = sorted(old_codes - new_set)

    db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id
    ).delete()
    for pc in new_codes:
        db.add(TenantRolePermission(
            id=uuid.uuid4(), tenant_role_id=role.role_id, permission_code=pc,
        ))

    lines = [f"Added {c}" for c in added] + [f"Removed {c}" for c in removed]
    if lines:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "permissions.updated", lines)
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "permissions": new_codes,
            "added": added, "removed": removed}


@router.delete("/tenant-roles/{role_id}/permissions/{permission_code}", status_code=200)
async def remove_tenant_role_permission(
    role_id: str,
    permission_code: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Remove a single permission from a tenant role."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    deleted = db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id,
        TenantRolePermission.permission_code == permission_code,
    ).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Permission not assigned to this role")
    _record_role_event(db, tenant_id, role.role_id, actor_id, "permissions.updated",
                       [f"Removed {permission_code}"])
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "removed": permission_code}


@router.put("/tenant-roles/{role_id}/scope")
async def set_tenant_role_scope(
    role_id: str,
    req: TenantRoleScopeRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Replace role scope (departments / cost centres). Empty items = All."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Validate targets exist and belong to this tenant
    dept_ids = [uuid.UUID(i.scope_id) for i in req.items if i.scope_type == "department"]
    cc_ids = [uuid.UUID(i.scope_id) for i in req.items if i.scope_type == "cost_centre"]
    bad_types = [i.scope_type for i in req.items if i.scope_type not in ("department", "cost_centre")]
    if bad_types:
        raise HTTPException(status_code=400, detail=f"Unknown scope_type(s): {', '.join(sorted(set(bad_types)))}")
    dept_names = {
        ou.org_unit_id: ou.name
        for ou in db.query(OrgUnit).filter(
            OrgUnit.org_unit_id.in_(dept_ids), OrgUnit.tenant_id == tenant_id,
        ).all()
    } if dept_ids else {}
    cc_names = {
        c.cost_centre_id: c.name
        for c in db.query(CostCentre).filter(
            CostCentre.cost_centre_id.in_(cc_ids), CostCentre.tenant_id == tenant_id,
        ).all()
    } if cc_ids else {}
    missing = [str(d) for d in dept_ids if d not in dept_names] + \
              [str(c) for c in cc_ids if c not in cc_names]
    if missing:
        raise HTTPException(status_code=404, detail=f"Scope target(s) not found: {', '.join(missing)}")

    old_rows = db.query(TenantRoleScope).filter(
        TenantRoleScope.tenant_role_id == role.role_id
    ).all()
    old_set = {(s.scope_type, str(s.scope_id)) for s in old_rows}
    new_set = {(i.scope_type, i.scope_id) for i in req.items}

    db.query(TenantRoleScope).filter(TenantRoleScope.tenant_role_id == role.role_id).delete()
    for i in req.items:
        db.add(TenantRoleScope(
            id=uuid.uuid4(), tenant_role_id=role.role_id,
            scope_type=i.scope_type, scope_id=uuid.UUID(i.scope_id),
        ))

    def _label(stype, sid):
        if stype == "department":
            return dept_names.get(uuid.UUID(sid)) or sid
        return cc_names.get(uuid.UUID(sid)) or sid

    lines = [f"Added {_label(t, s)} to {t}" for t, s in sorted(new_set - old_set)] + \
            [f"Removed {_label(t, s)} from {t}" for t, s in sorted(old_set - new_set)]
    if lines:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "scope.updated", lines)
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "scope": _role_scope_payload(db, role.role_id)}


@router.post("/tenant-roles/{role_id}/deactivate")
async def deactivate_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Set role status to inactive (keeps assignments, blocks new ones)."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    if role.status == "inactive":
        return {"role_id": str(role.role_id), "status": "inactive"}
    role.status = "inactive"
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    _record_role_event(db, tenant_id, role.role_id, actor_id, "status.changed",
                       ["Deactivated role"])
    db.commit()
    return {"role_id": str(role.role_id), "status": "inactive"}


@router.post("/tenant-roles/{role_id}/activate")
async def activate_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Restore an inactive role to active."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    if role.status == "active":
        return {"role_id": str(role.role_id), "status": "active"}
    role.status = "active"
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    _record_role_event(db, tenant_id, role.role_id, actor_id, "status.changed",
                       ["Restored role"])
    db.commit()
    return {"role_id": str(role.role_id), "status": "active"}


@router.get("/tenant-roles/{role_id}/history")
async def get_tenant_role_history(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
):
    """Per-role audit feed, newest first."""
    tenant_id, _ = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    return {"role_id": str(role.role_id), "history": _role_history_payload(db, role.role_id)}


@router.post("/users/{user_id}/tenant-roles", status_code=201)
async def assign_tenant_role_to_user(
    user_id: str,
    req: TenantRoleAssignRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user_role.assign", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(req.role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user or str(user.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=404, detail="User not found in tenant")
    existing = db.query(TenantUserRole).filter(
        TenantUserRole.user_id == user.user_id,
        TenantUserRole.tenant_role_id == role.role_id
    ).first()
    if existing:
        return {"status": "ok", "message": "Role already assigned", "user_id": str(user.user_id), "role_id": str(role.role_id)}
    tur = TenantUserRole(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(str(tenant_id)),
        user_id=user.user_id,
        tenant_role_id=role.role_id
    )
    db.add(tur)
    db.commit()
    return {"status": "ok", "user_id": str(user.user_id), "role_id": str(role.role_id)}


@router.get("/tenant-roles")
async def list_tenant_roles(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # active | inactive | all (default: all)
    sort: str = Query("created_at"),      # name | code | created_at | users_count
    order: str = Query("desc"),           # asc | desc
    limit: int = Query(100, le=500, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    """List tenant roles with full card data: permissions, scope, users_count."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    tid = uuid.UUID(str(tenant_id))

    q = db.query(TenantRole).filter(TenantRole.tenant_id == tid)
    if search:
        like = f"%{search}%"
        q = q.filter((TenantRole.name.ilike(like)) | (TenantRole.code.ilike(like)))
    if category:
        q = q.filter(TenantRole.category == category)
    if status and status != "all":
        q = q.filter(TenantRole.status == status)

    total = q.count()

    sort_col = {
        "name": TenantRole.name,
        "code": TenantRole.code,
        "created_at": TenantRole.created_at,
    }.get(sort, TenantRole.created_at)
    q = q.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    roles = q.offset(offset).limit(limit).all()

    # Permissions for all listed roles in one query
    role_ids = [r.role_id for r in roles]
    permissions_map: dict = {rid: [] for rid in role_ids}
    if role_ids:
        perms = (
            db.query(TenantRolePermission, Permission)
            .join(Permission, TenantRolePermission.permission_code == Permission.code)
            .filter(TenantRolePermission.tenant_role_id.in_(role_ids))
            .all()
        )
        for trp, p in perms:
            permissions_map[trp.tenant_role_id].append({
                "code": trp.permission_code,
                "description": p.description
            })

    # Users count per role
    users_count_map: dict = {}
    if role_ids:
        counts = (
            db.query(TenantUserRole.tenant_role_id, func.count(TenantUserRole.id))
            .filter(TenantUserRole.tenant_role_id.in_(role_ids))
            .group_by(TenantUserRole.tenant_role_id)
            .all()
        )
        users_count_map = {rid: c for rid, c in counts}

    # Scope per role, resolved to names
    scope_map: dict = {rid: {"departments": [], "cost_centres": []} for rid in role_ids}
    if role_ids:
        scope_rows = db.query(TenantRoleScope).filter(
            TenantRoleScope.tenant_role_id.in_(role_ids)
        ).all()
        dept_ids = [s.scope_id for s in scope_rows if s.scope_type == "department"]
        cc_ids = [s.scope_id for s in scope_rows if s.scope_type == "cost_centre"]
        dept_names = {
            ou.org_unit_id: ou.name
            for ou in db.query(OrgUnit).filter(OrgUnit.org_unit_id.in_(dept_ids)).all()
        } if dept_ids else {}
        cc_names = {
            c.cost_centre_id: c.name
            for c in db.query(CostCentre).filter(CostCentre.cost_centre_id.in_(cc_ids)).all()
        } if cc_ids else {}
        for s in scope_rows:
            target = {"id": str(s.scope_id), "name": None}
            if s.scope_type == "department":
                target["name"] = dept_names.get(s.scope_id)
                scope_map[s.tenant_role_id]["departments"].append(target)
            elif s.scope_type == "cost_centre":
                target["name"] = cc_names.get(s.scope_id)
                scope_map[s.tenant_role_id]["cost_centres"].append(target)

    items = [
        {
            "role_id": str(r.role_id),
            "code": r.code,
            "name": r.name or r.code,
            "description": r.description,
            "category": r.category,
            "status": r.status or "active",
            "is_custom": True,
            "permissions": permissions_map.get(r.role_id, []),
            "scope": scope_map.get(r.role_id, {"departments": [], "cost_centres": []}),
            "users_count": users_count_map.get(r.role_id, 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in roles
    ]

    # users_count sort needs the assembled list
    if sort == "users_count":
        items.sort(key=lambda x: x["users_count"], reverse=(order != "asc"))

    return {"roles": items, "total": total, "limit": limit, "offset": offset}


@router.get("/tenant-roles/{role_ref}/detail")
async def get_tenant_role_detail(
    role_ref: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    """Full detail for one tenant role: permissions, assigned users (with
    scopes), and change history.

    ``role_ref`` accepts either the role UUID or its code.
    History is returned empty until role audit events are recorded.
    """
    from provisioning_service.Models import UserResponsibilityScope

    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context")
    tid = uuid.UUID(str(tenant_id))

    # Resolve by UUID, fall back to role code
    role = None
    try:
        role_uuid = uuid.UUID(role_ref)
        role = db.query(TenantRole).filter(
            TenantRole.role_id == role_uuid,
            TenantRole.tenant_id == tid,
        ).first()
    except ValueError:
        pass
    if role is None:
        role = db.query(TenantRole).filter(
            TenantRole.code == role_ref,
            TenantRole.tenant_id == tid,
        ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Permissions (with descriptions)
    perm_rows = (
        db.query(TenantRolePermission, Permission)
        .join(Permission, TenantRolePermission.permission_code == Permission.code)
        .filter(TenantRolePermission.tenant_role_id == role.role_id)
        .all()
    )
    permissions = [
        {"code": p.code, "description": p.description}
        for _, p in perm_rows
    ]

    # Assigned users (+ identity for email, + responsibility scopes)
    assignments = (
        db.query(TenantUserRole, User)
        .join(User, TenantUserRole.user_id == User.user_id)
        .filter(TenantUserRole.tenant_role_id == role.role_id)
        .all()
    )
    user_ids = [u.user_id for _, u in assignments]
    identities = {
        i.user_id: i
        for i in db.query(UserIdentity).filter(UserIdentity.user_id.in_(user_ids)).all()
    } if user_ids else {}
    scope_rows = db.query(UserResponsibilityScope).filter(
        UserResponsibilityScope.user_id.in_(user_ids),
        UserResponsibilityScope.tenant_id == tid,
    ).all() if user_ids else []
    scopes_by_user: dict = {}
    for s in scope_rows:
        scopes_by_user.setdefault(s.user_id, []).append({
            "responsibility_code": s.responsibility_code,
            "scope_type": s.scope_type,
            "scope_id": s.scope_id,
        })

    users = [
        {
            "user_id": str(u.user_id),
            "display_name": u.display_name,
            "email": identities[u.user_id].email if u.user_id in identities else None,
            "is_active": u.is_active,
            "assigned_at": tur.created_at.isoformat() if tur.created_at else None,
            "scopes": scopes_by_user.get(u.user_id, []),
        }
        for tur, u in assignments
    ]

    # Role-level scope (departments / cost centres), resolved to names
    scope = _role_scope_payload(db, role.role_id)

    # Per-role audit history
    history = _role_history_payload(db, role.role_id)

    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name or role.code,
        "description": role.description,
        "category": role.category,
        "status": role.status or "active",
        "is_custom": True,
        "created_at": role.created_at.isoformat() if role.created_at else None,
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        "permissions": permissions,
        "scope": scope,
        "users": users,
        "users_count": len(users),
        "history": history,
    }


@router.delete("/tenant-roles/{role_id}", status_code=204)
async def delete_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.delete", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Remove all permission assignments
    db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id
    ).delete()
    # Remove all user assignments
    db.query(TenantUserRole).filter(
        TenantUserRole.tenant_role_id == role.role_id
    ).delete()
    db.delete(role)
    db.commit()
    return Response(status_code=204)
