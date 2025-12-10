import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Models import OrgUnit, User, Role, UserOrgAssignment
from Schemas import OrgUnitRequest, OrgUnitAssignmentRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from core.user_auth import invalidate_user_context
from utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["org_units"])


@router.post("/departments", status_code=201)
async def create_org_unit(req: OrgUnitRequest, db: Session = Depends(get_db)):
    tenant = db.query(OrgUnit).filter(OrgUnit.tenant_id == uuid.UUID(req.tenant_id)).first()
    # tenant existence implied by FK; skip explicit check

    parent_uuid = None
    if req.parent_org_unit_id:
        parent = (
            db.query(OrgUnit)
            .filter(OrgUnit.org_unit_id == uuid.UUID(req.parent_org_unit_id))
            .first()
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent org unit not found")
        parent_uuid = uuid.UUID(req.parent_org_unit_id)

    org_unit = OrgUnit(
        org_unit_id=uuid.uuid4(),
        tenant_id=uuid.UUID(req.tenant_id),
        name=req.name,
        type=req.type,
        parent_org_unit_id=parent_uuid,
    )
    db.add(org_unit)
    db.commit()
    db.refresh(org_unit)

    logger.info(f"✅ Created org unit: {org_unit.org_unit_id} ({org_unit.name})")
    return {
        "org_unit_id": str(org_unit.org_unit_id),
        "tenant_id": str(org_unit.tenant_id),
        "name": org_unit.name,
        "type": org_unit.type,
        "parent_org_unit_id": str(org_unit.parent_org_unit_id) if org_unit.parent_org_unit_id else None,
        "created_at": org_unit.created_at.isoformat(),
    }


@router.get("/departments")
async def list_org_units(
    tenant_id: Optional[str] = Query(None),
    parent_org_unit_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(OrgUnit)
    if tenant_id:
        q = q.filter(OrgUnit.tenant_id == uuid.UUID(tenant_id))
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
                "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
                "created_at": ou.created_at.isoformat(),
            }
            for ou in org_units
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/org-units/{org_unit_id}/users/{user_id}", status_code=201)
async def assign_user_to_org_unit(
    org_unit_id: str,
    user_id: str,
    req: OrgUnitAssignmentRequest,
    current_user_id: str,
    db: Session = Depends(get_db),
):
    org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
    if not org_unit:
        raise HTTPException(status_code=404, detail="Org unit not found")

    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    existing = (
        db.query(UserOrgAssignment)
        .filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id),
            UserOrgAssignment.org_unit_id == uuid.UUID(org_unit_id),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already assigned to this org unit")

    assignment = UserOrgAssignment(
        assignment_id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        org_unit_id=uuid.UUID(org_unit_id),
        role_id=uuid.UUID(req.role_id),
        assigned_by=uuid.UUID(current_user_id),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    invalidate_user_context(str(user.user_id), str(user.tenant_id))

    logger.info(f"✅ Assigned user {user_id} to org unit {org_unit_id}")
    return {
        "assignment_id": str(assignment.assignment_id),
        "user_id": user_id,
        "org_unit_id": org_unit_id,
        "role_id": req.role_id,
        "assigned_at": assignment.assigned_at.isoformat(),
    }


@router.delete("/v1/org-units/{org_unit_id}/users/{user_id}")
async def remove_user_from_org_unit(
    org_unit_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.assign")),
):
    assignment = (
        db.query(UserOrgAssignment)
        .filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id),
            UserOrgAssignment.org_unit_id == uuid.UUID(org_unit_id),
        )
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == assignment.org_unit_id).first()
    if org_unit:
        check_tenant_access(ctx, org_unit.tenant_id)

    db.delete(assignment)
    db.commit()

    invalidate_user_context(user_id, str(ctx.tenant_id))

    logger.info(f"✅ Removed user {user_id} from org unit {org_unit_id}")
    return {}

