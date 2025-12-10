import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import CostCentre, User, UserCostCentre
from Schemas import CostCentreRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["cost_centres"])


@router.post("/cost-centres", status_code=201)
async def create_cost_centre(req: CostCentreRequest, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()

        tenant = db.query(CostCentre).filter(CostCentre.tenant_id == uuid.UUID(req.tenant_id)).first()
        # tenant existence implied; skip explicit fetch

        manager_user_uuid = None
        if req.manager_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.manager_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            manager_user_uuid = uuid.UUID(req.manager_user_id)

        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            manager_user_id=manager_user_uuid,
            budget_minor=req.budget_minor,
            spent_minor=0,
            currency_code=req.currency,
            status="active",
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)

        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Created cost centre: {cc.cost_centre_id} ({cc.name})")

        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "name": cc.name,
            "budget_minor": cc.budget_minor,
            "spent_minor": cc.spent_minor,
            "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
            "status": cc.status,
            "created_at": cc.created_at.isoformat(),
        }
    except HTTPException:
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cost-centres")
async def list_cost_centres(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("cost_centres.manage", None)),
):
    q = db.query(CostCentre).filter(CostCentre.status == "active")

    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(CostCentre.tenant_id == ctx.tenant_id)

    total = q.count()
    ccs = q.order_by(CostCentre.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "cost_centres": [
            {
                "cost_centre_id": str(cc.cost_centre_id),
                "tenant_id": str(cc.tenant_id),
                "name": cc.name,
                "budget_minor": cc.budget_minor,
                "spent_minor": cc.spent_minor,
                "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
                "status": cc.status,
                "created_at": cc.created_at.isoformat(),
            }
            for cc in ccs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/users/{user_id}/cost-centres", status_code=201)
async def assign_user_to_cost_centre(
    user_id: str,
    cost_centre_id: str = Query(..., description="Cost centre ID"),
    allocated_budget_minor: int = Query(0, description="Initial allocated budget in minor units"),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")

    existing = (
        db.query(UserCostCentre)
        .filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already assigned to this cost centre")

    user_cc = UserCostCentre(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        cost_centre_id=uuid.UUID(cost_centre_id),
        allocated_budget_minor=allocated_budget_minor,
        spent_minor=0,
        currency_code=cc.currency_code,
    )
    db.add(user_cc)
    db.commit()
    db.refresh(user_cc)

    logger.info(f"✅ Assigned user {user_id} to cost centre {cost_centre_id} with budget {allocated_budget_minor}")
    return {
        "id": str(user_cc.id),
        "user_id": user_id,
        "cost_centre_id": cost_centre_id,
        "allocated_budget_minor": allocated_budget_minor,
        "spent_minor": 0,
        "available_minor": allocated_budget_minor,
        "currency_code": cc.currency_code,
    }

