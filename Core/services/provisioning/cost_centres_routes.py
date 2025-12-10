import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import CostCentre, User, UserCostCentre, UserBudget
from Schemas import CostCentreRequest, UserBudgetRequest, UserContext
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

        creator = db.query(User).filter(User.user_id == uuid.UUID(req.created_by)).first()
        if not creator:
            raise HTTPException(status_code=404, detail="Creator user not found")

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
            created_by=uuid.UUID(req.created_by),
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


@router.post("/cost-centres/{cost_centre_id}/manager", status_code=200)
async def set_cost_centre_manager(
    cost_centre_id: str,
    manager_user_id: str = Query(..., description="Manager user ID"),
    db: Session = Depends(get_db),
):
    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")

    manager = db.query(User).filter(User.user_id == uuid.UUID(manager_user_id)).first()
    if not manager:
        raise HTTPException(status_code=404, detail="Manager user not found")

    cc.manager_user_id = manager.user_id
    db.commit()
    db.refresh(cc)

    logger.info(f"✅ Set manager {manager_user_id} for cost centre {cost_centre_id}")
    return {
        "cost_centre_id": str(cc.cost_centre_id),
        "manager_user_id": str(cc.manager_user_id),
    }

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
        allocated_budget_minor=req.allocated_budget_minor if hasattr(req, "allocated_budget_minor") else 0,
        spent_minor=req.spent_minor if hasattr(req, "spent_minor") else 0,
        currency_code=req.currency if hasattr(req, "currency") else "GBP",
    )
    db.add(user_cc)
    db.commit()
    db.refresh(user_cc)

    logger.info(f"✅ Assigned user {user_id} to cost centre {cost_centre_id}")
    return {
        "id": str(user_cc.id),
        "user_id": user_id,
        "cost_centre_id": cost_centre_id,
    }


@router.post("/users/{user_id}/budget", status_code=201)
async def set_user_budget(
    user_id: str,
    req: UserBudgetRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")

    existing_budget = db.query(UserBudget).filter(UserBudget.user_id == uuid.UUID(user_id)).first()
    if existing_budget:
        existing_budget.allocated_budget_minor = req.allocated_budget_minor
        existing_budget.spent_minor = req.spent_minor
        existing_budget.currency_code = req.currency_code
        existing_budget.recurring_budget_minor = req.recurring_budget_minor
        existing_budget.recurring_period = req.recurring_period
        db.commit()
        db.refresh(existing_budget)
        budget_row = existing_budget
    else:
        budget_row = UserBudget(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            allocated_budget_minor=req.allocated_budget_minor,
            spent_minor=req.spent_minor,
            currency_code=req.currency_code,
            recurring_budget_minor=req.recurring_budget_minor,
            recurring_period=req.recurring_period,
        )
        db.add(budget_row)
        db.commit()
        db.refresh(budget_row)

    # ensure user is linked to cost centre
    link = (
        db.query(UserCostCentre)
        .filter(UserCostCentre.user_id == uuid.UUID(user_id), UserCostCentre.cost_centre_id == cc.cost_centre_id)
        .first()
    )
    if not link:
        db.add(UserCostCentre(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            cost_centre_id=cc.cost_centre_id,
            allocated_budget_minor=0,
            spent_minor=0,
            currency_code=req.currency_code or "GBP",
        ))
        db.commit()

    logger.info(f"✅ Set budget for user {user_id} on cost centre {req.cost_centre_id}")
    return {
        "user_id": user_id,
        "cost_centre_id": req.cost_centre_id,
        "allocated_budget_minor": budget_row.allocated_budget_minor,
        "spent_minor": budget_row.spent_minor,
        "currency_code": budget_row.currency_code,
        "recurring_budget_minor": budget_row.recurring_budget_minor,
        "recurring_period": budget_row.recurring_period,
    }

