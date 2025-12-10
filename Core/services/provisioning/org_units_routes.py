import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Models import OrgUnit, User, UserOrgAssignment, UserCostCentre, CostCentre, OrgUnitCostCentre
from Schemas import OrgUnitRequest, OrgUnitAssignmentRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from core.user_auth import invalidate_user_context
from utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["org_units"])


@router.post("/departments", status_code=201)
async def create_org_unit(
    req: OrgUnitRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.manage"))
):
    check_tenant_access(ctx, uuid.UUID(req.tenant_id))
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

    cc_uuid = None
    if req.cost_centre_id:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        cc_uuid = cc.cost_centre_id

    org_unit = OrgUnit(
        org_unit_id=uuid.uuid4(),
        tenant_id=uuid.UUID(req.tenant_id),
        name=req.name,
        type=req.type,
        parent_org_unit_id=parent_uuid,
        cost_centre_id=cc_uuid,
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
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.manage"))
):
    org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
    if not org_unit:
        raise HTTPException(status_code=404, detail="Org unit not found")
    check_tenant_access(ctx, org_unit.tenant_id)

    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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

    if not req.role_id:
        raise HTTPException(status_code=400, detail="role_id is required for org unit assignment")

    assignment = UserOrgAssignment(
        assignment_id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        org_unit_id=uuid.UUID(org_unit_id),
        assigned_by=uuid.UUID(req.assigned_by) if req.assigned_by else uuid.UUID(ctx.user_id),
        role_id=uuid.UUID(req.role_id),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    # if the org unit has a cost centre, auto-link user to that cost centre
    if org_unit.cost_centre_id:
        cc_link = (
            db.query(UserCostCentre)
            .filter(
                UserCostCentre.user_id == uuid.UUID(user_id),
                UserCostCentre.cost_centre_id == org_unit.cost_centre_id,
            )
            .first()
        )
        if not cc_link:
            db.add(UserCostCentre(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                cost_centre_id=org_unit.cost_centre_id,
                allocated_budget_minor=0,
                spent_minor=0,
                currency_code="GBP",
            ))
            db.commit()

    invalidate_user_context(str(user.user_id), str(user.tenant_id))

    logger.info(f"✅ Assigned user {user_id} to org unit {org_unit_id}")
    return {
        "assignment_id": str(assignment.assignment_id),
        "user_id": user_id,
        "org_unit_id": org_unit_id,
        "assigned_at": assignment.assigned_at.isoformat(),
    }


@router.post("/org-units/{org_unit_id}/cost-centres/{cost_centre_id}", status_code=201)
async def link_org_unit_cost_centre(org_unit_id: str, cost_centre_id: str, db: Session = Depends(get_db)):
    org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
    if not org_unit:
        raise HTTPException(status_code=404, detail="Org unit not found")
    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")

    existing = (
        db.query(OrgUnitCostCentre)
        .filter(
            OrgUnitCostCentre.org_unit_id == org_unit.org_unit_id,
            OrgUnitCostCentre.cost_centre_id == cc.cost_centre_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Mapping already exists")

    link = OrgUnitCostCentre(
        id=uuid.uuid4(),
        org_unit_id=org_unit.org_unit_id,
        cost_centre_id=cc.cost_centre_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {
        "mapping_id": str(link.id),
        "org_unit_id": org_unit_id,
        "cost_centre_id": cost_centre_id,
        "created_at": link.created_at.isoformat(),
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

