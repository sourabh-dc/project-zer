"""
Users API — user CRUD + unified team list.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import (
    User, UserIdentity, Invitation, OrgUnit, CostCentre, UserCostCentre,
    Role, UserRole, TenantRole, TenantUserRole, UserOrgAssignment,
    CostCenterBudget, SpendingEvent,
)
from provisioning_service.Schemas import UserContext, UserUpdateRequest, AssignRoleRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Users"])


def compute_next_reset(period: str, from_date: Optional[date] = None) -> Optional[date]:
    """Compute the next reset date based on a recurring period."""
    if not from_date:
        from_date = date.today()
    period = (period or "none").lower()
    if period == "daily":
        return from_date + timedelta(days=1)
    if period == "weekly":
        return from_date + timedelta(days=7)
    if period == "monthly":
        return from_date + timedelta(days=30)
    if period == "yearly":
        return from_date + timedelta(days=365)
    return None


@router.get("/users")
async def list_users(
        tenant_id: Optional[str] = Query(None),
        include_invited: bool = Query(False, description="Merge pending invitations as status=Invited rows"),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin'))
):
    """List users — email, roles, departments, cost centres per row.
    Optionally merges pending invitations (unified team list)."""
    try:
        ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
        effective_tenant = uuid.UUID(tenant_id) if tenant_id else uuid.UUID(str(ctx_tenant))
        q = db.query(User).filter(User.is_active == True, User.tenant_id == effective_tenant)

        total = q.count()
        users = q.order_by(User.created_at.desc()).limit(limit).offset(offset).all()
        user_ids = [u.user_id for u in users]

        # ── Emails from UserIdentity (email does NOT live on users) ──
        identities = {
            i.user_id: i
            for i in db.query(UserIdentity).filter(UserIdentity.user_id.in_(user_ids)).all()
        } if user_ids else {}

        # ── Roles per user (global + tenant) ─────────────────────
        roles_map: dict = {uid: [] for uid in user_ids}
        if user_ids:
            for role_code, uid in (
                db.query(Role.code, UserRole.user_id)
                .join(UserRole, Role.role_id == UserRole.role_id)
                .filter(UserRole.user_id.in_(user_ids)).all()
            ):
                roles_map[uid].append(role_code)
            for role_name, uid in (
                db.query(func.coalesce(TenantRole.name, TenantRole.code), TenantUserRole.user_id)
                .join(TenantUserRole, TenantRole.role_id == TenantUserRole.tenant_role_id)
                .filter(TenantUserRole.user_id.in_(user_ids)).all()
            ):
                roles_map[uid].append(role_name)

        # ── Departments per user ─────────────────────────────────
        depts_map: dict = {uid: [] for uid in user_ids}
        if user_ids:
            for uid, dept_name in (
                db.query(UserOrgAssignment.user_id, OrgUnit.name)
                .join(OrgUnit, UserOrgAssignment.org_unit_id == OrgUnit.org_unit_id)
                .filter(UserOrgAssignment.user_id.in_(user_ids)).all()
            ):
                depts_map[uid].append(dept_name)

        # ── Cost centres per user ────────────────────────────────
        ccs_map: dict = {uid: [] for uid in user_ids}
        if user_ids:
            for uid, cc_name in (
                db.query(UserCostCentre.user_id, CostCentre.name)
                .join(CostCentre, UserCostCentre.cost_centre_id == CostCentre.cost_centre_id)
                .filter(UserCostCentre.user_id.in_(user_ids)).all()
            ):
                ccs_map[uid].append(cc_name)

        items = [
            {
                "user_id": str(u.user_id),
                "tenant_id": str(u.tenant_id),
                "email": identities[u.user_id].email if u.user_id in identities else None,
                "display_name": u.display_name,
                "job_title": u.display_job_title,
                "avatar": u.profile_image,
                "status": "Active",
                "roles": roles_map.get(u.user_id, []),
                "departments": depts_map.get(u.user_id, []),
                "cost_centres": ccs_map.get(u.user_id, []),
                "created_at": u.created_at.isoformat()
            }
            for u in users
        ]

        # ── Unified list: merge pending invitations ──────────────
        if include_invited and offset == 0:
            pending = db.query(Invitation).filter(
                Invitation.tenant_id == effective_tenant,
                Invitation.status == "pending",
            ).all()
            for inv in pending:
                items.append({
                    "user_id": None,
                    "invitation_id": str(inv.invitation_id),
                    "tenant_id": str(inv.tenant_id),
                    "email": inv.email,
                    "display_name": None,
                    "job_title": inv.display_job_title,
                    "avatar": None,
                    "status": "Invited",
                    "roles": [inv.role_code] if inv.role_code else [],
                    "departments": [],
                    "cost_centres": [],
                    "created_at": inv.created_at.isoformat() if inv.created_at else None,
                })

        return {
            "users": items,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}")
async def get_user(user_id: str, db: Session = Depends(get_db)):
    """Get a single user by ID"""
    from provisioning_service.Models import UserIdentity
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == uuid.UUID(user_id)).first()
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": identity.email if identity else None,
            "first_name": identity.first_name if identity else None,
            "last_name": identity.last_name if identity else None,
            "display_name": user.display_name,
            "phone": user.phone,
            "position": user.position,
            "profile_image": user.profile_image,
            "home_site_id": str(user.home_site_id) if user.home_site_id else None,
            "home_store_id": str(user.home_store_id) if user.home_store_id else None,
            "home_org_unit_id": str(user.home_org_unit_id) if user.home_org_unit_id else None,
            "all_locations": user.all_locations,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user.update")),
):
    """Update an existing user"""
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        for key, value in update_data.items():
            if key in ("home_site_id", "home_store_id", "home_org_unit_id") and value is not None:
                setattr(user, key, uuid.UUID(value))
            else:
                setattr(user, key, value)

        # Update display_name if first/last name changed
        from provisioning_service.Models import UserIdentity
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
        if "first_name" in update_data or "last_name" in update_data:
            if identity:
                if "first_name" in update_data:
                    identity.first_name = update_data["first_name"]
                if "last_name" in update_data:
                    identity.last_name = update_data["last_name"]
                user.display_name = f"{identity.first_name} {identity.last_name}".strip()

        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "user.updated",
                {"user_id": str(user.user_id), "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user.updated: {_oe}")

        logger.info(f"Updated user: {user.user_id}")
        email = identity.email if identity else ""
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": email,
            "display_name": user.display_name,
            "is_active": user.is_active,
            "updated_at": user.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user.delete", resource_from="none")),
):
    """Soft-delete a user (deactivate)"""
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, user.tenant_id, "user.deleted", {"user_id": user_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted user: {user_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# USER BUDGET ENDPOINTS - Cost Centre Assignments & Budget Info
# ==================================================================================

@router.post("/users/{user_id}/cost-centres", status_code=201)
async def assign_user_to_cost_centre(
    user_id: str,
    cost_centre_id: str = Query(..., description="Cost centre ID"),
    allocated_budget_minor: int = Query(0, description="Initial allocated budget in minor units"),
    recurring_budget_minor: int = Query(0, description="Recurring budget amount for resets"),
    recurring_period: str = Query("none", description="Recurring period: none/daily/weekly/monthly/yearly"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budgets.manage")),
    policy=Depends(require_policy("user_budget.assign", resource_from="none")),
):
    """Assign a user to a cost centre with optional budget allocation (enforces remaining CC budget)"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()

        cc_budget = db.query(CostCenterBudget).filter(CostCenterBudget.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        if not cc_budget:
            raise HTTPException(status_code=404, detail="Cost centre budget not found; create budget first")

        # Check if the assignment already exists
        existing = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id)
        ).first()

        # If already mapped, allow increasing allocation (idempotent update with remaining-budget check)
        if existing:
            current_alloc = existing.allocated_minor or 0
            current_recurring = existing.recurring_amount_minor or 0
            # Update recurring config if provided
            if recurring_budget_minor:
                existing.recurring_amount_minor = recurring_budget_minor
            if recurring_period:
                existing.recurring_period = recurring_period.lower()
                existing.next_recurring_at = compute_next_reset(recurring_period)
            if allocated_budget_minor <= current_alloc:
                db.commit()
                db.refresh(existing)
                return {
                    "user_budget_id": str(existing.user_budget_id),
                    "user_id": user_id,
                    "cost_centre_id": cost_centre_id,
                    "allocated_minor": existing.allocated_minor,
                    "spent_minor": existing.spent_minor,
                    "available_minor": (existing.available_minor if existing.available_minor is not None else (existing.allocated_minor - existing.spent_minor)),
                    "recurring_amount_minor": existing.recurring_amount_minor,
                    "recurring_period": existing.recurring_period,
                    "next_recurring_at": str(existing.next_recurring_at) if existing.next_recurring_at else None
                }
            delta = allocated_budget_minor - current_alloc
            # Remaining = total budget - already allocated to users - total spent
            remaining_cc = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            if delta > remaining_cc:
                raise HTTPException(status_code=400, detail="Insufficient cost centre remaining budget")
            # Update budget allocations
            cc_budget.allocated_to_users_minor = (cc_budget.allocated_to_users_minor or 0) + delta
            cc_budget.remaining_to_allocate_minor = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            existing.allocated_minor = allocated_budget_minor
            if not existing.next_recurring_at:
                existing.next_recurring_at = compute_next_reset(existing.recurring_period)
            db.commit()
            db.refresh(existing)
            logger.info(f"✅ Updated allocation for user {user_id} in cost centre {cost_centre_id} by {delta}")
            return {
                "user_budget_id": str(existing.user_budget_id),
                "user_id": user_id,
                "cost_centre_id": cost_centre_id,
                "allocated_minor": existing.allocated_minor,
                "spent_minor": existing.spent_minor,
                "available_minor": (existing.available_minor if existing.available_minor is not None else (existing.allocated_minor - existing.spent_minor)),
                "recurring_amount_minor": existing.recurring_amount_minor,
                "recurring_period": existing.recurring_period,
                "next_recurring_at": str(existing.next_recurring_at) if existing.next_recurring_at else None
            }

        # Enforce remaining budget if allocating
        if allocated_budget_minor and allocated_budget_minor > 0:
            # Remaining = total budget - already allocated - total spent
            remaining_cc = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            if allocated_budget_minor > remaining_cc:
                raise HTTPException(status_code=400, detail="Insufficient cost centre remaining budget")
            # Increase allocated_to_users (not total_spent) when assigning to a user
            cc_budget.allocated_to_users_minor = (cc_budget.allocated_to_users_minor or 0) + allocated_budget_minor
            cc_budget.remaining_to_allocate_minor = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))

        # Create assignment
        user_cc = UserCostCentre(
            cc_budget_id=cc_budget.budget_id,
            user_budget_id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            cost_centre_id=uuid.UUID(cost_centre_id),
            allocated_minor=allocated_budget_minor,
            spent_minor=0,
            available_minor=allocated_budget_minor,
            max_budget_minor=allocated_budget_minor,
            recurring_amount_minor=recurring_budget_minor or allocated_budget_minor,
            recurring_period=recurring_period.lower() if recurring_period else "none",
            next_recurring_at=compute_next_reset(recurring_period)
        )
        db.add(user_cc)
        # Persist both the user assignment and the updated budget
        db.add(cc_budget)
        db.commit()
        db.refresh(user_cc)
        db.refresh(cc_budget)

        # Outbox audit event
        try:
            user_obj = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
            _tid = user_obj.tenant_id if user_obj else uuid.uuid4()
            create_outbox_event(
                db, _tid, "user_cost_centre.assigned",
                {
                    "user_id": user_id,
                    "cost_centre_id": cost_centre_id,
                    "allocated_minor": allocated_budget_minor,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_cost_centre.assigned: {_oe}")

        logger.info(f"✅ Assigned user {user_id} to cost centre {cost_centre_id} with budget {allocated_budget_minor}")

        return {
            "user_budget_id": str(user_cc.user_budget_id),
            "user_id": user_id,
            "cost_centre_id": cost_centre_id,
            "allocated_minor": allocated_budget_minor,
            "spent_minor": 0,
            "available_minor": allocated_budget_minor,
            "cost_centre_allocated_to_users_minor": cc_budget.allocated_to_users_minor,
            "cost_centre_remaining_to_allocate_minor": cc_budget.remaining_to_allocate_minor
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to assign user to cost centre: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/budget")
async def get_user_budget(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get user's budget information"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get cost centre assignment
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id)
        ).first()

        if not user_cc:
            return {
                "user_id": user_id,
                "has_budget": False,
                "message": "User not assigned to any cost centre"
            }

        # Get cost centre info and budget summary
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).first()
        cc_budget = db.query(CostCenterBudget).filter(CostCenterBudget.cost_centre_id == user_cc.cost_centre_id).first()

        available = (user_cc.allocated_minor or 0) - (user_cc.spent_minor or 0)

        return {
            "user_id": user_id,
            "has_budget": True,
            "cost_centre_id": str(user_cc.cost_centre_id),
            "cost_centre_name": cc.name if cc else "Unknown",
            "allocated_minor": user_cc.allocated_minor,
            "spent_minor": user_cc.spent_minor,
            "available_minor": available,
            "recurring_amount_minor": user_cc.recurring_amount_minor,
            "recurring_period": user_cc.recurring_period,
            "next_recurring_at": str(user_cc.next_recurring_at) if user_cc.next_recurring_at else None,
            "cost_centre_budget_amount_minor": cc_budget.budget_amount_minor if cc_budget else 0,
            "cost_centre_total_spent_minor": cc_budget.total_spent_minor if cc_budget else 0,
            "cost_centre_available_minor": ((cc_budget.budget_amount_minor or 0) - (cc_budget.total_spent_minor or 0)) if cc_budget else 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/budgets/renew", status_code=200)
async def renew_budgets(
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("budgets.manage")),
    policy=Depends(require_policy("budget.renew", resource_from="none")),
):
    """Renew cost centre and user budgets that are due based on recurring settings."""
    today = date.today()
    renewed_cc = 0
    renewed_users = 0
    try:
        # Renew user-level recurring budgets (UserCostCentre)
        ucs = db.query(UserCostCentre).filter(
            UserCostCentre.recurring_period != None,
            UserCostCentre.recurring_period != "none",
            ((UserCostCentre.next_recurring_at == None) | (UserCostCentre.next_recurring_at <= today))
        ).all()

        for uc in ucs:
            # Determine renewal amount: prefer configured recurring_amount_minor, fall back to allocated_minor
            base = (uc.recurring_amount_minor if uc.recurring_amount_minor is not None else uc.allocated_minor) or 0
            uc.allocated_minor = base
            uc.spent_minor = 0
            # update last/next
            try:
                uc.last_reset_date = today
            except Exception:
                # field may not exist on model; ignore if so
                pass
            uc.next_recurring_at = compute_next_reset(uc.recurring_period, today)

            # Emit a spending event for audit
            try:
                db.add(SpendingEvent(
                    event_id=uuid.uuid4(),
                    event_type="budget_renewal",
                    user_id=uc.user_id,
                    cost_centre_id=uc.cost_centre_id,
                    order_id=None,
                    approval_request_id=None,
                    amount_minor=base,
                    currency_code=None,
                    event_metadata={"recurring_period": uc.recurring_period}
                ))
            except Exception:
                # best-effort; don't fail renewal if event model differs
                logger.debug("SpendingEvent add skipped due to model differences")

            renewed_users += 1

        db.commit()
        return {"renewed_cost_centres": 0, "renewed_users": renewed_users, "date": str(today)}
    except Exception as e:
        db.rollback()
        logger.error(f"Budget renewal failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/spending-history")
async def get_user_spending_history(
    user_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get a user's spending history"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get spending events
        events = db.query(SpendingEvent).filter(
            SpendingEvent.user_id == uuid.UUID(user_id)
        ).order_by(SpendingEvent.created_at.desc()).limit(limit).offset(offset).all()

        total = db.query(func.count(SpendingEvent.event_id)).filter(
            SpendingEvent.user_id == uuid.UUID(user_id)
        ).scalar()

        return {
            "user_id": user_id,
            "events": [
                {
                    "event_id": str(e.event_id),
                    "event_type": e.event_type,
                    "amount_minor": e.amount_minor,
                    "currency_code": e.currency_code,
                    "cost_centre_id": str(e.cost_centre_id),
                    "order_id": str(e.order_id) if e.order_id else None,
                    "approval_request_id": str(e.approval_request_id) if e.approval_request_id else None,
                    "metadata": e.event_metadata,
                    "created_at": e.created_at.isoformat()
                }
                for e in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get spending history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

'''to fix the below endpoint, get subordinates from cost center'''
@router.get("/users/{user_id}/subordinates")
async def get_user_subordinates(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get a list of users who report to this user"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get manager's org unit assignments
        manager_assignments = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id)
        ).all()

        if not manager_assignments:
            return {
                "user_id": user_id,
                "subordinates": [],
                "total": 0
            }

        # Get org unit IDs where this user is assigned
        org_unit_ids = [assignment.org_unit_id for assignment in manager_assignments]

        # Get all users assigned to these org units (excluding the manager)
        subordinate_assignments = db.query(UserOrgAssignment, User).join(
             User, UserOrgAssignment.user_id == User.user_id
         ).filter(
             UserOrgAssignment.org_unit_id.in_(org_unit_ids),
             UserOrgAssignment.user_id != uuid.UUID(user_id),
             User.is_active == True
         ).all()

        # Deduplicate subordinates
        seen_users = set()
        subordinates = []

        for assignment, subordinate in subordinate_assignments:
            if subordinate.user_id not in seen_users:
                seen_users.add(subordinate.user_id)
                subordinates.append({
                    "user_id": str(subordinate.user_id),
                    "email": subordinate.email,
                    "display_name": subordinate.display_name,
                    "org_unit_id": str(assignment.org_unit_id)
                })

        return {
            "user_id": user_id,
            "subordinates": subordinates,
            "total": len(subordinates)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subordinates: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# USER ROLE ASSIGNMENTS
# ==================================================================================

@router.post("/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(
        user_id: str,
        req: AssignRoleRequest,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.assign")),
        policy=Depends(require_policy("user_role.assign")),
):
    """Assign a role to a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="assign_role", status="start").inc()

        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify role exists
        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Check if the assignment already exists (idempotent)
        existing = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(req.role_id),
            UserRole.tenant_id == user.tenant_id
        ).first()

        if existing:
            return {"status": "ok", "message": "Role already assigned", "user_id": user_id, "role_id": str(existing.role_id)}

        # Create assignment with tenant_id from user
        user_role = UserRole(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=uuid.UUID(user_id),
            role_id=uuid.UUID(req.role_id)
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "user_role.assigned",
                {"user_id": user_id, "role_id": req.role_id, "role_code": role.code},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_role.assigned: {_oe}")

        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe(
            (datetime.now() - start).total_seconds()
        )

        return {
            "user_id": user_id,
            "role_id": req.role_id,
            "role_name": role.code,
            "assigned": True,
            "created_at": user_role.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="assign_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        return {"status": "ok", "message": "Role already assigned (integrity)", "user_id": user_id, "role_id": str(req.role_code)}
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/users/{user_id}/roles")
async def get_user_roles(
        user_id: str,
        db: Session = Depends(get_db)
):
    """Get all roles assigned to a user"""
    from provisioning_service.Models import UserIdentity
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get identity for email
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == uuid.UUID(user_id)).first()

        # Get global roles
        global_roles = (
            db.query(UserRole, Role)
            .join(Role, UserRole.role_id == Role.role_id)
            .filter(UserRole.user_id == uuid.UUID(user_id))
            .all()
        )

        # Get tenant-scoped custom roles
        tenant_roles = (
            db.query(TenantUserRole, TenantRole)
            .join(TenantRole, TenantUserRole.tenant_role_id == TenantRole.role_id)
            .filter(TenantUserRole.user_id == uuid.UUID(user_id))
            .all()
        )

        roles_list = []
        for ur, r in global_roles:
            roles_list.append({
                "role_id": str(r.role_id),
                "role_code": r.code,
                "role_name": r.code,
                "type": "global",
                "assigned_at": ur.created_at.isoformat()
            })
        for tur, tr in tenant_roles:
            roles_list.append({
                "role_id": str(tr.role_id),
                "role_code": tr.code,
                "role_name": tr.code,
                "type": "tenant",
                "assigned_at": tur.created_at.isoformat()
            })

        return {
            "user_id": user_id,
            "email": identity.email if identity else None,
            "display_name": user.display_name,
            "roles": roles_list,
            "total": len(roles_list)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user roles failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
        user_id: str,
        role_id: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.assign")),
        policy=Depends(require_policy("user_role.remove", resource_from="none")),
):
    """Remove a role from a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_role", status="start").inc()

        # Find user role assignment (check both global and tenant roles)
        user_role = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id)
        ).first()

        tenant_user_role = None
        if not user_role:
            tenant_user_role = db.query(TenantUserRole).filter(
                TenantUserRole.user_id == uuid.UUID(user_id),
                TenantUserRole.tenant_role_id == uuid.UUID(role_id)
            ).first()

        if not user_role and not tenant_user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")

        if user_role:
            user = db.query(User).filter(User.user_id == user_role.user_id).first()
            db.delete(user_role)
        else:
            user = db.query(User).filter(User.user_id == tenant_user_role.user_id).first()
            db.delete(tenant_user_role)
        db.commit()

        # Outbox audit event
        try:
            _tid = user.tenant_id if user else uuid.uuid4()
            create_outbox_event(db, _tid, "user_role.removed", {"user_id": user_id, "role_id": role_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_role.removed: {_oe}")

        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Removed role {role_id} from user {user_id}")

        return {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True
        }
    except ValueError:
        req_total.labels(operation="remove_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="remove_role", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_role", status="error").inc()
        logger.error(f"❌ Remove role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
