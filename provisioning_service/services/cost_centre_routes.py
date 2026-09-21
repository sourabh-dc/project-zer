"""
Cost Centres API — CC CRUD, hierarchy, scope, users, overview, history.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import (
    Tenant, User, UserIdentity, OrgUnit, Site, Store, CostCentre, UserCostCentre,
    CostCenterBudget, CostCentreAuditEvent,
)
from provisioning_service.Schemas import CostCentreRequest, CostCentreUpdateRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage
from provisioning_service.core.helpers.resource_loaders import cost_centre_quota_resource
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Cost Centres"])


# ── Cost centre helpers ───────────────────────────────────────────

def _record_cc_event(db: Session, tenant_id, cost_centre_id, actor_user_id, action: str, lines):
    """Append one audit event for a cost centre. ``lines`` = human-readable changes."""
    if isinstance(lines, str):
        lines = [lines]
    db.add(CostCentreAuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        cost_centre_id=cost_centre_id,
        actor_user_id=actor_user_id,
        action=action,
        detail="\n".join(lines) if lines else None,
    ))


def _validate_org_unit(db: Session, org_unit_id, tenant_id):
    if not org_unit_id:
        return None
    ou = db.query(OrgUnit).filter(
        OrgUnit.org_unit_id == uuid.UUID(org_unit_id),
        OrgUnit.tenant_id == tenant_id,
    ).first()
    if not ou:
        raise HTTPException(status_code=404, detail="Department (org unit) not found")
    return ou.org_unit_id


def _validate_site(db: Session, site_id):
    if not site_id:
        return None
    site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site.site_id


def _validate_store(db: Session, store_id, tenant_id):
    if not store_id:
        return None
    store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store.store_id


def _cc_scope_names(db: Session, ccs) -> dict:
    """Batch-resolve department/site/store names for a list of cost centres."""
    dept_ids = {c.department_id for c in ccs if c.department_id}
    site_ids = {c.site_id for c in ccs if c.site_id}
    store_ids = {c.store_id for c in ccs if c.store_id}
    depts = {ou.org_unit_id: ou.name for ou in db.query(OrgUnit).filter(OrgUnit.org_unit_id.in_(dept_ids)).all()} if dept_ids else {}
    sites = {s.site_id: s.name for s in db.query(Site).filter(Site.site_id.in_(site_ids)).all()} if site_ids else {}
    stores = {s.store_id: s.name for s in db.query(Store).filter(Store.store_id.in_(store_ids)).all()} if store_ids else {}
    return {"departments": depts, "sites": sites, "stores": stores}


def _cc_history_payload(db: Session, cost_centre_id, limit: int = 50) -> list:
    """Per-CC audit feed: actor, action, details, timestamp — newest first."""
    rows = (
        db.query(CostCentreAuditEvent, User)
        .outerjoin(User, CostCentreAuditEvent.actor_user_id == User.user_id)
        .filter(CostCentreAuditEvent.cost_centre_id == cost_centre_id)
        .order_by(CostCentreAuditEvent.created_at.desc())
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


def _cc_would_cycle(db: Session, cost_centre_id, new_parent_id) -> bool:
    """True if setting new_parent_id would create a cycle in the CC tree."""
    seen = {cost_centre_id}
    current = new_parent_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        parent = db.query(CostCentre.parent_cost_centre_id).filter(
            CostCentre.cost_centre_id == current
        ).first()
        current = parent[0] if parent else None
    return False


@router.post("/cost-centres", status_code=201)
async def create_cost_centre(
        req: CostCentreRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("costcentre.manage")),
        policy=Depends(require_policy("cost_centre.create", resource_loader=cost_centre_quota_resource)),
):
    """Create a new cost centre (with optional parent + scope)"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify manager user exists (if provided)
        owner_user_id = None
        if req.owner_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.owner_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            owner_user_id = uuid.UUID(req.owner_user_id)

        tenant_uuid = uuid.UUID(req.tenant_id)

        # Validate parent (same tenant, exists, active)
        parent_id = None
        if req.parent_cost_centre_id:
            parent = db.query(CostCentre).filter(
                CostCentre.cost_centre_id == uuid.UUID(req.parent_cost_centre_id),
                CostCentre.tenant_id == tenant_uuid,
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent cost centre not found")
            parent_id = parent.cost_centre_id

        # Validate scope targets (same tenant)
        department_id = _validate_org_unit(db, req.department_id, tenant_uuid)
        site_id = _validate_site(db, req.site_id)
        store_id = _validate_store(db, req.store_id, tenant_uuid)

        # Create a cost centre
        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            code=req.code,
            name=req.name,
            description=getattr(req, "description", None),
            owner_user_id=owner_user_id,
            parent_cost_centre_id=parent_id,
            department_id=department_id,
            site_id=site_id,
            store_id=store_id,
            is_active=bool(getattr(req, "is_active", getattr(req, "active", True)))
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)

        cc_budget = None
        if req.budget_amount_minor is not None and req.fiscal_year is not None:
            cc_budget = CostCenterBudget(budget_id=uuid.uuid4(), cost_centre_id=cc.cost_centre_id,
                                         tenant_id=req.tenant_id, budget_amount_minor=req.budget_amount_minor,
                                         fiscal_year=req.fiscal_year, period_start=req.period_start, allocated_to_users_minor=0,
                                         period_end=req.period_end, period_type=req.period_type, period_number=req.period_number,
                                         remaining_to_allocate_minor=req.budget_amount_minor,status="active",
                                         created_by=req.created_by)
            db.add(cc_budget)
            db.commit()
            db.refresh(cc_budget)

        # Versioned budget (preferred path when the wizard sends year_id)
        cc_version = None
        if req.budget_amount_minor is not None and req.year_id:
            from provisioning_service.Models import CostCentreBudgetVersion
            cc_version = CostCentreBudgetVersion(
                version_id=uuid.uuid4(),
                cost_centre_id=cc.cost_centre_id,
                year_id=uuid.UUID(req.year_id),
                period_id=None,
                tenant_id=tenant_uuid,
                currency="GBP",
                budget_minor=req.budget_amount_minor,
                status="active",
                created_by=uuid.UUID(req.created_by) if req.created_by else None,
            )
            db.add(cc_version)
            if req.distribution_mode:
                cc.period_granularity = {
                    "monthly": "month", "quarterly": "quarter",
                    "yearly": "year", "one_time": "year",
                }.get(req.distribution_mode, cc.period_granularity)
            db.commit()
            db.refresh(cc_version)

        # Audit event
        _record_cc_event(db, tenant_uuid, cc.cost_centre_id,
                         uuid.UUID(req.created_by) if req.created_by else None,
                         "created", [f"Created cost centre {cc.name} ({cc.code})"])
        db.commit()

        # Record feature usage
        record_feature_usage(db, req.tenant_id, "cost.centres", count=1)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "cost_centre.created",
                {
                    "cost_centre_id": str(cc.cost_centre_id),
                    "name": cc.name,
                    "budget_minor": cc_budget.budget_amount_minor if cc_budget else None,
                    "tenant_id": req.tenant_id,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.created: {_oe}")

        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created cost centre: {cc.cost_centre_id} ({cc.name})")

        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "parent_cost_centre_id": str(cc.parent_cost_centre_id) if cc.parent_cost_centre_id else None,
            "department_id": str(cc.department_id) if cc.department_id else None,
            "site_id": str(cc.site_id) if cc.site_id else None,
            "store_id": str(cc.store_id) if cc.store_id else None,
            "budget_minor": cc_budget.budget_amount_minor if cc_budget else None,
            "budget_version_id": str(cc_version.version_id) if cc_version else None,
            "manager_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
            "status": "Active" if cc.is_active else "Inactive",
            "created_at": cc.created_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cost-centres")
async def list_cost_centres(
        tenant_id: Optional[str] = Query(None),
        search: Optional[str] = Query(None, description="Search code, name, description"),
        status: Optional[str] = Query(None, description="active | archived | all (default: all)"),
        department_id: Optional[str] = Query(None),
        site_id: Optional[str] = Query(None),
        store_id: Optional[str] = Query(None),
        year_id: Optional[str] = Query(None, description="Financial year UUID — adds budget/used/available for that year"),
        sort: str = Query("created_at", description="name | code | created_at | budget"),
        order: str = Query("desc", description="asc | desc"),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List cost centres — search, status, scope filters, sort, per-FY budget."""
    q = db.query(CostCentre)

    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))
    if status == "active":
        q = q.filter(CostCentre.is_active == True)
    elif status in ("archived", "inactive"):
        q = q.filter(CostCentre.is_active == False)
    # default "all" — no status filter
    if search:
        like = f"%{search}%"
        q = q.filter(
            (CostCentre.name.ilike(like)) |
            (CostCentre.code.ilike(like)) |
            (CostCentre.description.ilike(like))
        )
    if department_id:
        q = q.filter(CostCentre.department_id == uuid.UUID(department_id))
    if site_id:
        q = q.filter(CostCentre.site_id == uuid.UUID(site_id))
    if store_id:
        q = q.filter(CostCentre.store_id == uuid.UUID(store_id))

    total = q.count()

    sort_col = {
        "name": CostCentre.name,
        "code": CostCentre.code,
        "created_at": CostCentre.created_at,
    }.get(sort, CostCentre.created_at)
    q = q.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    ccs = q.offset(offset).limit(limit).all()

    # Resolve scope + parent names in batch
    names = _cc_scope_names(db, ccs)
    parent_ids = {c.parent_cost_centre_id for c in ccs if c.parent_cost_centre_id}
    parents = {
        c.cost_centre_id: c.name
        for c in db.query(CostCentre).filter(CostCentre.cost_centre_id.in_(parent_ids)).all()
    } if parent_ids else {}

    # Per-FY budget from versioned budgets (when year selected)
    budget_map: dict = {}
    if year_id and ccs:
        from provisioning_service.Models import CostCentreBudgetVersion
        versions = db.query(CostCentreBudgetVersion).filter(
            CostCentreBudgetVersion.year_id == uuid.UUID(year_id),
            CostCentreBudgetVersion.cost_centre_id.in_([c.cost_centre_id for c in ccs]),
            CostCentreBudgetVersion.period_id.is_(None),
        ).all()
        for v in versions:
            budget_map[v.cost_centre_id] = {
                "budget_minor": v.budget_minor,
                "used_minor": (v.spent_minor or 0) + (v.committed_minor or 0),
                "available_minor": v.budget_minor + (v.carry_forward_minor or 0)
                                   - (v.committed_minor or 0) - (v.spent_minor or 0),
                "status": v.status,
            }

    items = []
    for cc in ccs:
        items.append({
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "description": cc.description,
            "parent_cost_centre_id": str(cc.parent_cost_centre_id) if cc.parent_cost_centre_id else None,
            "parent_name": parents.get(cc.parent_cost_centre_id),
            "department_id": str(cc.department_id) if cc.department_id else None,
            "department": names["departments"].get(cc.department_id),
            "site_id": str(cc.site_id) if cc.site_id else None,
            "site": names["sites"].get(cc.site_id),
            "store_id": str(cc.store_id) if cc.store_id else None,
            "store": names["stores"].get(cc.store_id),
            "owner_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
            "is_active": bool(cc.is_active),
            "status": "Active" if cc.is_active else "Archived",
            "budget": budget_map.get(cc.cost_centre_id),
            "created_at": cc.created_at.isoformat()
        })

    # budget sort needs the assembled list
    if sort == "budget" and year_id:
        items.sort(key=lambda x: (x["budget"] or {}).get("budget_minor", 0), reverse=(order != "asc"))

    return {
        "cost_centres": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/cost-centres/{cost_centre_id}")
async def get_cost_centre(cost_centre_id: str, db: Session = Depends(get_db)):
    """Get a single cost centre by ID"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "description": cc.description,
            "owner_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
            "is_active": bool(cc.is_active),
            "created_at": cc.created_at.isoformat(),
            "updated_at": cc.updated_at.isoformat() if cc.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cost centre ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/cost-centres/{cost_centre_id}")
async def update_cost_centre(
    cost_centre_id: str,
    req: CostCentreUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
    policy=Depends(require_policy("cost_centre.update")),
):
    """Update an existing cost centre"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        # Parent change — validate + cycle guard
        if "parent_cost_centre_id" in update_data:
            new_parent = update_data["parent_cost_centre_id"]
            if new_parent:
                parent_uuid = uuid.UUID(new_parent)
                if parent_uuid == cc.cost_centre_id:
                    raise HTTPException(status_code=400, detail="Cost centre cannot be its own parent")
                parent = db.query(CostCentre).filter(
                    CostCentre.cost_centre_id == parent_uuid,
                    CostCentre.tenant_id == cc.tenant_id,
                ).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent cost centre not found")
                if _cc_would_cycle(db, cc.cost_centre_id, parent_uuid):
                    raise HTTPException(status_code=400, detail="Parent change would create a cycle")
                update_data["parent_cost_centre_id"] = parent_uuid

        # Scope changes — validate targets
        if update_data.get("department_id"):
            update_data["department_id"] = _validate_org_unit(db, update_data["department_id"], cc.tenant_id)
        if update_data.get("site_id"):
            update_data["site_id"] = _validate_site(db, update_data["site_id"])
        if update_data.get("store_id"):
            update_data["store_id"] = _validate_store(db, update_data["store_id"], cc.tenant_id)

        changes = []
        for key, value in update_data.items():
            old = getattr(cc, key)
            if key == "owner_user_id" and value is not None:
                value = uuid.UUID(value)
            if old != value:
                setattr(cc, key, value)
                changes.append(f"Changed {key} from '{old or '—'}' to '{value or '—'}'")

        cc.updated_at = datetime.now(timezone.utc)
        if changes:
            actor = ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None)
            _record_cc_event(db, cc.tenant_id, cc.cost_centre_id,
                             uuid.UUID(str(actor)) if actor else None, "updated", changes)
        db.commit()
        db.refresh(cc)

        # Outbox audit event
        try:
            create_outbox_event(
                db, cc.tenant_id, "cost_centre.updated",
                {"cost_centre_id": str(cc.cost_centre_id), "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.updated: {_oe}")

        logger.info(f"✅ Updated cost centre: {cc.cost_centre_id}")
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "is_active": bool(cc.is_active),
            "updated_at": cc.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/cost-centres/{cost_centre_id}", status_code=204)
async def delete_cost_centre(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
    policy=Depends(require_policy("cost_centre.delete", resource_from="none")),
):
    """Soft-delete a cost centre (deactivate)"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        # Check if users are still assigned
        assigned_count = db.query(UserCostCentre).filter(
            UserCostCentre.cost_centre_id == cc.cost_centre_id,
            UserCostCentre.is_blocked == False,
        ).count()
        if assigned_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete cost centre — {assigned_count} active user assignment(s) remain",
            )

        cc.is_active = False
        cc.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, cc.tenant_id, "cost_centre.deleted", {"cost_centre_id": cost_centre_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted cost centre: {cost_centre_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cost centre ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cost-centres/{cost_centre_id}/reactivate")
async def reactivate_cost_centre(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
    policy=Depends(require_policy("cost_centre.update")),
):
    """Reactivate an archived cost centre."""
    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")
    if cc.is_active:
        return {"cost_centre_id": cost_centre_id, "status": "Active"}

    cc.is_active = True
    cc.updated_at = datetime.now(timezone.utc)
    actor = ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None)
    _record_cc_event(db, cc.tenant_id, cc.cost_centre_id,
                     uuid.UUID(str(actor)) if actor else None, "status.changed",
                     ["Reactivated cost centre"])
    db.commit()
    try:
        create_outbox_event(db, cc.tenant_id, "cost_centre.reactivated", {"cost_centre_id": cost_centre_id})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for cost_centre.reactivated: {_oe}")
    return {"cost_centre_id": cost_centre_id, "status": "Active"}


def _cc_users_payload(db: Session, cost_centre_id, tenant_id) -> list:
    """Enriched assigned-user rows: identity + budget/used/available/reset."""
    rows = (
        db.query(UserCostCentre, User)
        .join(User, UserCostCentre.user_id == User.user_id)
        .filter(UserCostCentre.cost_centre_id == cost_centre_id)
        .all()
    )
    user_ids = [u.user_id for _, u in rows]
    identities = {
        i.user_id: i
        for i in db.query(UserIdentity).filter(UserIdentity.user_id.in_(user_ids)).all()
    } if user_ids else {}
    dept_names = {
        ou.org_unit_id: ou.name
        for ou in db.query(OrgUnit).filter(
            OrgUnit.org_unit_id.in_({u.home_org_unit_id for _, u in rows if u.home_org_unit_id})
        ).all()
    } if any(u.home_org_unit_id for _, u in rows) else {}
    return [
        {
            "user_id": str(u.user_id),
            "display_name": u.display_name,
            "email": identities[u.user_id].email if u.user_id in identities else None,
            "avatar": u.profile_image,
            "job_title": u.display_job_title,
            "department": dept_names.get(u.home_org_unit_id),
            "assigned_at": uc.created_at.isoformat() if uc.created_at else None,
            "budget_minor": uc.allocated_minor,
            "used_minor": uc.spent_minor,
            "available_minor": uc.available_minor,
            "reset_period": uc.recurring_period,
            "is_blocked": uc.is_blocked,
        }
        for uc, u in rows
    ]


@router.get("/cost-centres/{cost_centre_id}/users")
async def list_cost_centre_users(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
):
    """Enriched user list for a cost centre (nested view 'Assigned users')."""
    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")
    users = _cc_users_payload(db, cc.cost_centre_id, cc.tenant_id)
    return {"cost_centre_id": cost_centre_id, "users": users, "total": len(users)}


@router.get("/cost-centres/{cost_centre_id}/overview")
async def get_cost_centre_overview(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
):
    """One aggregate call for the nested view: scope, users, budgets by FY,
    change requests, history."""
    from provisioning_service.Models import CostCentreBudgetVersion, FinancialYear, BudgetChangeRequest

    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")

    names = _cc_scope_names(db, [cc])
    parent_name = None
    if cc.parent_cost_centre_id:
        parent = db.query(CostCentre).filter(CostCentre.cost_centre_id == cc.parent_cost_centre_id).first()
        parent_name = parent.name if parent else None

    users = _cc_users_payload(db, cc.cost_centre_id, cc.tenant_id)

    # Budgets by financial year (annual versions only)
    versions = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cc.cost_centre_id,
        CostCentreBudgetVersion.period_id.is_(None),
    ).all()
    year_ids = {v.year_id for v in versions}
    years = {y.year_id: y for y in db.query(FinancialYear).filter(FinancialYear.year_id.in_(year_ids)).all()} if year_ids else {}
    budgets = []
    for v in versions:
        y = years.get(v.year_id)
        budgets.append({
            "version_id": str(v.version_id),
            "year_id": str(v.year_id),
            "year_label": getattr(y, "label", None) or (f"FY {y.start_date.year}" if y else None),
            "budget_minor": v.budget_minor,
            "used_minor": (v.spent_minor or 0) + (v.committed_minor or 0),
            "available_minor": v.budget_minor + (v.carry_forward_minor or 0)
                               - (v.committed_minor or 0) - (v.spent_minor or 0),
            "status": v.status,
        })
    budgets.sort(key=lambda b: b["year_label"] or "", reverse=True)

    # Budget change requests for this CC
    requests = (
        db.query(BudgetChangeRequest, User)
        .outerjoin(User, BudgetChangeRequest.requester_id == User.user_id)
        .filter(BudgetChangeRequest.cost_centre_id == cc.cost_centre_id)
        .order_by(BudgetChangeRequest.created_at.desc())
        .limit(20)
        .all()
    )
    change_requests = [
        {
            "change_req_id": str(r.change_req_id),
            "requested_by": u.display_name if u else None,
            "type": r.request_type,
            "amount_minor": r.amount_minor,
            "currency": r.currency,
            "status": r.status,
            "date": r.created_at.isoformat() if r.created_at else None,
        }
        for r, u in requests
    ]

    history = _cc_history_payload(db, cc.cost_centre_id)

    return {
        "cost_centre_id": str(cc.cost_centre_id),
        "code": cc.code,
        "name": cc.name,
        "description": cc.description,
        "status": "Active" if cc.is_active else "Archived",
        "parent_cost_centre_id": str(cc.parent_cost_centre_id) if cc.parent_cost_centre_id else None,
        "parent_name": parent_name,
        "department": names["departments"].get(cc.department_id),
        "site": names["sites"].get(cc.site_id),
        "store": names["stores"].get(cc.store_id),
        "users": users,
        "budgets": budgets,
        "change_requests": change_requests,
        "history": history,
        "created_at": cc.created_at.isoformat() if cc.created_at else None,
        "updated_at": cc.updated_at.isoformat() if cc.updated_at else None,
    }


@router.get("/cost-centres/{cost_centre_id}/history")
async def get_cost_centre_history(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
):
    """Per-CC audit feed, newest first."""
    cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
    if not cc:
        raise HTTPException(status_code=404, detail="Cost centre not found")
    return {"cost_centre_id": cost_centre_id,
            "history": _cc_history_payload(db, cc.cost_centre_id)}
