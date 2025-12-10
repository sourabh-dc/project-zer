import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import (
    Tenant,
    User,
    UserRole,
    UserOrgAssignment,
    UserCostCentre,
    UserBudget,
    CostCentre,
    SpendingEvent,
    Role,
)
from Schemas import (
    UserRequest,
    BulkUserRequest,
    UserContext,
    AssignRoleRequest,
)
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from core.user_auth import generate_api_key, invalidate_user_context
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["users"])


@router.post("/v1/users", status_code=201)
async def create_user(
    req: UserRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage"))
):
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()

        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        existing = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")

        password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        display_name = f"{req.first_name} {req.last_name}".strip()

        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            email=req.email.lower(),
            display_name=display_name or req.email,
            first_name=req.first_name,
            last_name=req.last_name,
            password_hash=password_hash,
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Created user: {user.user_id} ({user.email})")

        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }
    except ValueError:
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_user", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=409, detail="Email already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        logger.error(f"❌ User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users")
async def list_users(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage")),
):
    q = db.query(User).filter(User.active == True)  # noqa: E712
    if tenant_id:
        q = q.filter(User.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(User.tenant_id == ctx.tenant_id)

    total = q.count()
    users = q.order_by(User.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "users": [
            {
                "user_id": str(u.user_id),
                "tenant_id": str(u.tenant_id),
                "email": u.email,
                "display_name": u.display_name,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/users/bulk-import", status_code=201)
async def bulk_import_users(
    req: BulkUserRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage", None)),
):
    start = datetime.now()
    try:
        req_total.labels(operation="bulk_import_users", status="start").inc()

        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        results = {"success": [], "failed": []}
        tenant_uuid = uuid.UUID(req.tenant_id)

        for user_data in req.users:
            try:
                email = user_data.get("email")
                first_name = user_data.get("first_name", "")
                last_name = user_data.get("last_name", "")
                display_name = f"{first_name} {last_name}".strip() or email

                if not email:
                    results["failed"].append({"error": "Missing email", "data": user_data})
                    continue

                if db.query(User).filter(func.lower(User.email) == email.lower()).first():
                    results["failed"].append({"email": email, "error": "Email already exists"})
                    continue

                temp_password = f"temp_{secrets.token_urlsafe(16)}"
                password_hash = bcrypt.hashpw(temp_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

                api_key = generate_api_key()
                api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=ctx.api_key_expiry_days or 90)

                user = User(
                    user_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    email=email.lower(),
                    display_name=display_name,
                    first_name=first_name or None,
                    last_name=last_name or None,
                    password_hash=password_hash,
                    active=True,
                )
                db.add(user)
                db.flush()

                results["success"].append(
                    {
                        "user_id": str(user.user_id),
                        "email": email,
                        "api_key": api_key,
                        "temporary_password": temp_password,
                    }
                )
            except Exception as e:
                results["failed"].append({"email": user_data.get("email", "unknown"), "error": str(e)})

        db.commit()

        req_total.labels(operation="bulk_import_users", status="success").inc()
        req_duration.labels(operation="bulk_import_users").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Bulk import: {len(results['success'])}/{len(req.users)} succeeded")

        return {
            "tenant_id": req.tenant_id,
            "total_requested": len(req.users),
            "success_count": len(results["success"]),
            "failed_count": len(results["failed"]),
            "results": results,
        }
    except HTTPException:
        req_total.labels(operation="bulk_import_users", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="bulk_import_users", status="error").inc()
        logger.error(f"❌ Bulk import failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/roles")
async def get_user_roles(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_roles = (
        db.query(UserRole)
        .filter(UserRole.user_id == uuid.UUID(user_id))
        .all()
    )

    return {
        "user_id": user_id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": [
            {
                "role_id": str(r.role_id),
                "assigned_at": r.created_at.isoformat(),
            }
            for r in user_roles
        ],
        "total": len(user_roles),
    }


@router.post("/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(user_id: str, req: AssignRoleRequest, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="assign_role", status="start").inc()

        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        existing = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user.user_id,
                UserRole.role_id == role.role_id
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Role already assigned to user")

        assignment = UserRole(
            id=uuid.uuid4(),
            user_id=user.user_id,
            role_id=role.role_id,
        )
        db.add(assignment)
        db.commit()

        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe((datetime.now() - start).total_seconds())

        invalidate_user_context(str(user.user_id), str(user.tenant_id))

        logger.info(f"✅ Assigned role {role.code} to user {user.email}")
        return {
            "user_id": str(user.user_id),
            "role_id": str(role.role_id),
        }
    except HTTPException:
        req_total.labels(operation="assign_role", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(user_id: str, role_id: str, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="remove_role", status="start").inc()

        user_role = (
            db.query(UserRole)
            .filter(UserRole.user_id == uuid.UUID(user_id), UserRole.role_id == uuid.UUID(role_id))
            .first()
        )
        if not user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")

        user = db.query(User).filter(User.user_id == user_role.user_id).first()
        db.delete(user_role)
        db.commit()

        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Removed role {role_id} from user {user_id}")
        if user:
            invalidate_user_context(str(user.user_id), str(user.tenant_id))

        return {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True,
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


@router.get("/users/{user_id}/budget")
async def get_user_budget(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    link = db.query(UserCostCentre).filter(UserCostCentre.user_id == uuid.UUID(user_id)).first()
    budget = db.query(UserBudget).filter(UserBudget.user_id == uuid.UUID(user_id)).first()

    if not link or not budget:
        return {
            "user_id": user_id,
            "has_budget": False,
            "message": "No budget found for this user",
        }

    available = budget.allocated_budget_minor - budget.spent_minor
    return {
        "user_id": user_id,
        "has_budget": True,
        "cost_centre_id": str(link.cost_centre_id),
        "allocated_budget_minor": budget.allocated_budget_minor,
        "spent_minor": budget.spent_minor,
        "available_minor": available,
        "currency_code": budget.currency_code,
        "recurring_budget_minor": budget.recurring_budget_minor,
        "recurring_period": budget.recurring_period,
        "last_reset_date": budget.last_reset_date.isoformat() if budget.last_reset_date else None,
        "next_reset_date": budget.next_reset_date.isoformat() if budget.next_reset_date else None,
    }


@router.get("/users/{user_id}/spending-history")
async def get_user_spending_history(
    user_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    events = (
        db.query(SpendingEvent)
        .filter(SpendingEvent.user_id == uuid.UUID(user_id))
        .order_by(SpendingEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    total = (
        db.query(func.count(SpendingEvent.event_id))
        .filter(SpendingEvent.user_id == uuid.UUID(user_id))
        .scalar()
    )

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
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

