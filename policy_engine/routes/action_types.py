"""
Action Types API Routes
Catalog of known action types for documentation and validation.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from policy_engine.core.db_config import get_db
from policy_engine.Models import PolicyActionType
from policy_engine.Schemas import ActionTypeCreate, ActionTypeResponse
from policy_engine.utils.logger import logger


router = APIRouter(prefix="/v1/action-types", tags=["Action Types"])


@router.post("", response_model=ActionTypeResponse, status_code=201)
async def create_action_type(
    action_type_data: ActionTypeCreate,
    db: Session = Depends(get_db)
):
    """
    Register a new action type.
    
    Action types document what actions can be evaluated by the policy engine
    and what context they expect.
    """
    # Check for duplicate
    existing = db.query(PolicyActionType).filter(
        PolicyActionType.code == action_type_data.code
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Action type '{action_type_data.code}' already exists"
        )
    
    action_type = PolicyActionType(
        action_type_id=uuid.uuid4(),
        code=action_type_data.code,
        name=action_type_data.name,
        description=action_type_data.description,
        category=action_type_data.category,
        subject_schema=action_type_data.subject_schema,
        resource_schema=action_type_data.resource_schema,
        context_schema=action_type_data.context_schema
    )
    
    db.add(action_type)
    db.commit()
    db.refresh(action_type)
    
    logger.info(f"Created action type: {action_type.code}")
    
    return action_type


@router.get("", response_model=list[ActionTypeResponse])
async def list_action_types(
    category: Optional[str] = Query(None, description="Filter by category"),
    is_active: bool = Query(True, description="Filter by active status"),
    db: Session = Depends(get_db)
):
    """List all registered action types."""
    query = db.query(PolicyActionType).filter(
        PolicyActionType.is_active == is_active
    )
    
    if category:
        query = query.filter(PolicyActionType.category == category)
    
    action_types = query.order_by(PolicyActionType.category, PolicyActionType.code).all()
    
    return [ActionTypeResponse.model_validate(at) for at in action_types]


@router.get("/{code}", response_model=ActionTypeResponse)
async def get_action_type(
    code: str,
    db: Session = Depends(get_db)
):
    """Get an action type by code."""
    action_type = db.query(PolicyActionType).filter(
        PolicyActionType.code == code
    ).first()
    
    if not action_type:
        raise HTTPException(status_code=404, detail="Action type not found")
    
    return ActionTypeResponse.model_validate(action_type)


@router.delete("/{code}", status_code=204)
async def delete_action_type(
    code: str,
    db: Session = Depends(get_db)
):
    """Deactivate an action type."""
    action_type = db.query(PolicyActionType).filter(
        PolicyActionType.code == code
    ).first()
    
    if not action_type:
        raise HTTPException(status_code=404, detail="Action type not found")
    
    action_type.is_active = False
    db.commit()
    
    logger.info(f"Deactivated action type: {code}")
