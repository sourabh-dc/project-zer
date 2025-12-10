import uuid
from typing import Dict
from fastapi import Depends, APIRouter
from sqlalchemy.orm import Session

from Models import Budget, UserCostCentre
from Schemas import BudgetRequest
from core.db_config import get_db

app = APIRouter(prefix="/v1/budget", tags=["budget"])


@app.post("/create", status_code=200)
async def update_costcentre_amount(
    req: BudgetRequest,
    db: Session = Depends(get_db),
):
    budget = Budget(
        budget_id=uuid.uuid4(),
        cost_centre_id=req.cost_centre_id,
        tenant_id=req.tenant_id,
        budget_year=req.budget_year,
        budget_month=req.budget_month,
        budget_amount_minor=req.budget_amount_minor,
        spent_amount_minor=0,
        available_amount_minor=req.budget_amount_minor,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)

@app.post("/create-user-budget", status_code=200)
async def create_user_budget(
    req: Dict,
    db: Session = Depends(get_db),
):
    user_budget = UserCostCentre(
        id=uuid.uuid4(),
        user_id=req["user_id"],
        cost_centre_id=req["cost_centre_id"],
        allocated_budget_minor=req["allocated_budget_minor"],
        spent_minor=0,
        currency_code=req["currency_code"]
    )
    db.add(user_budget)
    db.commit()

@app.get("/get-remaining-costcenter", status_code=200)
async def get_remaining_budget(
    cost_centre_id: str,
    db: Session = Depends(get_db),
):
    budget = db.query(Budget).filter(Budget.cost_centre_id == cost_centre_id).first()
    remaining = budget.available_amount_minor
    return remaining

@app.get("/get-remaining-user-budget", status_code=200)
async def get_remaining_user_budget(user_id, db: Session = Depends(get_db)):
    user_budget = db.query(UserCostCentre).filter(UserCostCentre.user_id == user_id).first()
    remaining = user_budget.allocated_budget_minor - user_budget.spent_minor
    return remaining
