"""
Suppliers API (S0) — legal organisations + supplier org CRUD + lifecycle.

Suppliers are independent organisations (tenant_type='supplier'), not
vendor rows inside a buyer tenant. Only 'approved' suppliers are
discoverable to buyers (enforced by discovery APIs in S2).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, LegalOrganisation, SupplierProfile
from provisioning_service.Schemas import (
    LegalOrgCreate, LegalOrgUpdate,
    SupplierCreate, SupplierUpdate, SupplierLifecycleRequest,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Suppliers"])

SCREENING_STATUSES = ("pending", "clear", "flagged")
LIFECYCLE_STATUSES = SupplierProfile.LIFECYCLE_STATUSES

# action → (allowed current statuses, target status)
LIFECYCLE_TRANSITIONS = {
    "submit": (("draft",), "submitted"),
    "approve": (("submitted",), "approved"),
    "suspend": (("approved",), "suspended"),
    "reject": (("submitted",), "draft"),
}


# ────────────────────────────────────────────────────────────────────
# Serialisers
# ────────────────────────────────────────────────────────────────────

def _legal_org_dict(lo: LegalOrganisation) -> dict:
    return {
        "legal_org_id": str(lo.legal_org_id),
        "legal_name": lo.legal_name,
        "registration_number": lo.registration_number,
        "registration_authority": lo.registration_authority,
        "country_code": lo.country_code,
        "screening_status": lo.screening_status,
        "screening_facts": lo.screening_facts,
        "created_at": lo.created_at.isoformat() if lo.created_at else None,
        "updated_at": lo.updated_at.isoformat() if lo.updated_at else None,
    }


def _supplier_dict(tenant: Tenant, profile: SupplierProfile) -> dict:
    return {
        "tenant_id": str(tenant.tenant_id),
        "tenant_name": tenant.tenant_name,
        "tenant_type": tenant.tenant_type,
        "active": tenant.active,
        "supplier_profile_id": str(profile.supplier_profile_id),
        "legal_org_id": str(profile.legal_org_id) if profile.legal_org_id else None,
        "trading_name": profile.trading_name,
        "lifecycle_status": profile.lifecycle_status,
        "contact_email": profile.contact_email,
        "connectivity": profile.connectivity,
        "submitted_at": profile.submitted_at.isoformat() if profile.submitted_at else None,
        "approved_at": profile.approved_at.isoformat() if profile.approved_at else None,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _audit(db: Session, ctx: dict, event_type: str, event_data: dict) -> None:
    """Outbox audit event scoped to the caller's tenant (legal orgs are
    platform-scoped, so the actor's tenant owns the audit trail)."""
    try:
        caller_tenant = (ctx or {}).get("tenant_id")
        if not caller_tenant:
            logger.warning(f"Outbox skipped for {event_type}: no tenant in claims")
            return
        create_outbox_event(db, caller_tenant, event_type, event_data)
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for {event_type}: {_oe}")


def _get_supplier(db: Session, tenant_id: str):
    """Load (tenant, profile) pair for a supplier org or 404."""
    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid supplier ID format")
    tenant = db.query(Tenant).filter(
        Tenant.tenant_id == tid, Tenant.tenant_type == "supplier"
    ).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Supplier not found")
    profile = db.query(SupplierProfile).filter(SupplierProfile.tenant_id == tid).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Supplier profile not found")
    return tenant, profile


# ────────────────────────────────────────────────────────────────────
# Legal organisations (platform ops)
# ────────────────────────────────────────────────────────────────────

@router.post("/legal-organisations", status_code=201)
async def create_legal_org(
    req: LegalOrgCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("legal_orgs.manage")),
    policy=Depends(require_policy("legal_org.create")),
):
    """Create a platform-scoped legal organisation."""
    start = datetime.now()
    try:
        req_total.labels(operation="create_legal_org", status="start").inc()

        lo = LegalOrganisation(
            legal_org_id=uuid.uuid4(),
            legal_name=req.legal_name,
            registration_number=req.registration_number,
            registration_authority=req.registration_authority,
            country_code=req.country_code,
            screening_facts=req.screening_facts,
        )
        db.add(lo)
        db.commit()
        db.refresh(lo)

        _audit(db, ctx, "legal_org.created",
               {"legal_org_id": str(lo.legal_org_id), "legal_name": lo.legal_name})

        req_total.labels(operation="create_legal_org", status="success").inc()
        req_duration.labels(operation="create_legal_org").observe(
            (datetime.now() - start).total_seconds()
        )
        logger.info(f"Created legal organisation: {lo.legal_org_id} ({lo.legal_name})")
        return _legal_org_dict(lo)
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_legal_org", status="error").inc()
        raise HTTPException(
            status_code=409,
            detail="Legal organisation with this registration number already exists",
        )
    except HTTPException:
        req_total.labels(operation="create_legal_org", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_legal_org", status="error").inc()
        logger.error(f"❌ Legal org creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/legal-organisations")
async def list_legal_orgs(
    screening_status: Optional[str] = Query(None),
    country_code: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List legal organisations with optional filters."""
    q = db.query(LegalOrganisation)
    if screening_status:
        q = q.filter(LegalOrganisation.screening_status == screening_status)
    if country_code:
        q = q.filter(LegalOrganisation.country_code == country_code)

    total = q.count()
    items = q.order_by(LegalOrganisation.created_at.desc()).limit(limit).offset(offset).all()
    return {
        "legal_organisations": [_legal_org_dict(lo) for lo in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/legal-organisations/{legal_org_id}")
async def get_legal_org(legal_org_id: str, db: Session = Depends(get_db)):
    """Get a single legal organisation."""
    try:
        lo = db.query(LegalOrganisation).filter(
            LegalOrganisation.legal_org_id == uuid.UUID(legal_org_id)
        ).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid legal org ID format")
    if not lo:
        raise HTTPException(status_code=404, detail="Legal organisation not found")
    return _legal_org_dict(lo)


@router.put("/legal-organisations/{legal_org_id}")
async def update_legal_org(
    legal_org_id: str,
    req: LegalOrgUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("legal_orgs.manage")),
    policy=Depends(require_policy("legal_org.update", resource_from="none")),
):
    """Update a legal organisation (incl. screening status/facts)."""
    try:
        lo = db.query(LegalOrganisation).filter(
            LegalOrganisation.legal_org_id == uuid.UUID(legal_org_id)
        ).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid legal org ID format")
    if not lo:
        raise HTTPException(status_code=404, detail="Legal organisation not found")

    update_data = req.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    if "screening_status" in update_data and update_data["screening_status"] not in SCREENING_STATUSES:
        raise HTTPException(status_code=400, detail=f"screening_status must be one of {SCREENING_STATUSES}")

    for key, value in update_data.items():
        setattr(lo, key, value)
    lo.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(lo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Legal organisation with this registration number already exists",
        )

    _audit(db, ctx, "legal_org.updated",
           {"legal_org_id": str(lo.legal_org_id), "updated_fields": list(update_data.keys())})

    logger.info(f"✅ Updated legal organisation: {legal_org_id}")
    return _legal_org_dict(lo)


@router.delete("/legal-organisations/{legal_org_id}", status_code=204)
async def delete_legal_org(
    legal_org_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("legal_orgs.manage")),
    policy=Depends(require_policy("legal_org.delete", resource_from="none")),
):
    """Delete a legal organisation — blocked while linked to a supplier."""
    try:
        loid = uuid.UUID(legal_org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid legal org ID format")
    lo = db.query(LegalOrganisation).filter(LegalOrganisation.legal_org_id == loid).first()
    if not lo:
        raise HTTPException(status_code=404, detail="Legal organisation not found")

    linked = db.query(SupplierProfile).filter(SupplierProfile.legal_org_id == loid).count()
    if linked:
        raise HTTPException(
            status_code=409,
            detail=f"Legal organisation is linked to {linked} supplier profile(s)",
        )

    db.delete(lo)
    db.commit()
    _audit(db, ctx, "legal_org.deleted", {"legal_org_id": legal_org_id})

    logger.info(f"✅ Deleted legal organisation: {legal_org_id}")
    return Response(status_code=204)


# ────────────────────────────────────────────────────────────────────
# Suppliers (platform ops create/manage; lifecycle gated separately)
# ────────────────────────────────────────────────────────────────────

@router.post("/suppliers", status_code=201)
async def create_supplier(
    req: SupplierCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("suppliers.manage")),
    policy=Depends(require_policy("supplier.create")),
):
    """Create a supplier org: tenant (type=supplier) + profile (+ legal org) atomically."""
    start = datetime.now()
    try:
        req_total.labels(operation="create_supplier", status="start").inc()

        # Resolve legal organisation
        legal_org_id = None
        if req.legal_org_id:
            try:
                legal_org_id = uuid.UUID(req.legal_org_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid legal_org_id format")
            lo = db.query(LegalOrganisation).filter(
                LegalOrganisation.legal_org_id == legal_org_id
            ).first()
            if not lo:
                raise HTTPException(status_code=404, detail="Legal organisation not found")
        elif req.legal_org:
            lo = LegalOrganisation(
                legal_org_id=uuid.uuid4(),
                legal_name=req.legal_org.legal_name,
                registration_number=req.legal_org.registration_number,
                registration_authority=req.legal_org.registration_authority,
                country_code=req.legal_org.country_code,
                screening_facts=req.legal_org.screening_facts,
            )
            db.add(lo)
            db.flush()
            legal_org_id = lo.legal_org_id

        # Create supplier tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            tenant_name=req.tenant_name,
            tenant_type="supplier",
            email=str(req.email),
            legal_org_id=legal_org_id,
        )
        db.add(tenant)
        db.flush()

        # Create supplier profile (lifecycle starts at draft)
        profile = SupplierProfile(
            supplier_profile_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            legal_org_id=legal_org_id,
            trading_name=req.trading_name,
            contact_email=str(req.contact_email) if req.contact_email else None,
            connectivity=req.connectivity,
            lifecycle_status="draft",
        )
        db.add(profile)
        db.commit()
        db.refresh(tenant)
        db.refresh(profile)

        try:
            create_outbox_event(
                db, str(tenant.tenant_id), "supplier.created",
                {
                    "tenant_id": str(tenant.tenant_id),
                    "tenant_name": tenant.tenant_name,
                    "legal_org_id": str(legal_org_id) if legal_org_id else None,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for supplier.created: {_oe}")

        req_total.labels(operation="create_supplier", status="success").inc()
        req_duration.labels(operation="create_supplier").observe(
            (datetime.now() - start).total_seconds()
        )
        logger.info(f"Created supplier org: {tenant.tenant_id} ({tenant.tenant_name})")
        return _supplier_dict(tenant, profile)
    except HTTPException:
        db.rollback()
        req_total.labels(operation="create_supplier", status="error").inc()
        raise
    except IntegrityError as e:
        db.rollback()
        req_total.labels(operation="create_supplier", status="error").inc()
        logger.error(f"❌ Supplier creation integrity error: {e}")
        raise HTTPException(status_code=409, detail="Conflicting supplier or legal organisation data")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_supplier", status="error").inc()
        logger.error(f"❌ Supplier creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/suppliers")
async def list_suppliers(
    lifecycle_status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List supplier orgs, optionally filtered by lifecycle status."""
    q = (
        db.query(Tenant, SupplierProfile)
        .join(SupplierProfile, SupplierProfile.tenant_id == Tenant.tenant_id)
        .filter(Tenant.tenant_type == "supplier")
    )
    if lifecycle_status:
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise HTTPException(status_code=400, detail=f"lifecycle_status must be one of {LIFECYCLE_STATUSES}")
        q = q.filter(SupplierProfile.lifecycle_status == lifecycle_status)

    total = q.count()
    rows = q.order_by(SupplierProfile.created_at.desc()).limit(limit).offset(offset).all()
    return {
        "suppliers": [_supplier_dict(t, p) for t, p in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/suppliers/{tenant_id}")
async def get_supplier(tenant_id: str, db: Session = Depends(get_db)):
    """Get a single supplier org with its profile."""
    tenant, profile = _get_supplier(db, tenant_id)
    return _supplier_dict(tenant, profile)


@router.put("/suppliers/{tenant_id}")
async def update_supplier(
    tenant_id: str,
    req: SupplierUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("suppliers.manage")),
    policy=Depends(require_policy("supplier.update", resource_from="none")),
):
    """Update supplier profile fields (trading name, contact, connectivity, legal org link)."""
    tenant, profile = _get_supplier(db, tenant_id)

    update_data = req.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    if "legal_org_id" in update_data:
        if update_data["legal_org_id"] is None:
            profile.legal_org_id = None
        else:
            try:
                loid = uuid.UUID(update_data["legal_org_id"])
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid legal_org_id format")
            lo = db.query(LegalOrganisation).filter(LegalOrganisation.legal_org_id == loid).first()
            if not lo:
                raise HTTPException(status_code=404, detail="Legal organisation not found")
            profile.legal_org_id = loid
        update_data.pop("legal_org_id")

    for key, value in update_data.items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)

    try:
        create_outbox_event(
            db, str(tenant.tenant_id), "supplier.updated",
            {"tenant_id": str(tenant.tenant_id), "updated_fields": list(req.model_dump(exclude_unset=True).keys())},
        )
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for supplier.updated: {_oe}")

    logger.info(f"✅ Updated supplier: {tenant_id}")
    return _supplier_dict(tenant, profile)


@router.delete("/suppliers/{tenant_id}", status_code=204)
async def delete_supplier(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("suppliers.manage")),
    policy=Depends(require_policy("supplier.delete", resource_from="none")),
):
    """Soft-delete a supplier: profile suspended + tenant deactivated."""
    tenant, profile = _get_supplier(db, tenant_id)

    profile.lifecycle_status = "suspended"
    profile.updated_at = datetime.now(timezone.utc)
    tenant.active = False
    db.commit()

    try:
        create_outbox_event(db, str(tenant.tenant_id), "supplier.deleted", {"tenant_id": tenant_id})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for supplier.deleted: {_oe}")

    logger.info(f"✅ Soft-deleted supplier: {tenant_id}")
    return Response(status_code=204)


@router.post("/suppliers/{tenant_id}/lifecycle")
async def supplier_lifecycle(
    tenant_id: str,
    req: SupplierLifecycleRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("suppliers.approve")),
    policy=Depends(require_policy("supplier.lifecycle", resource_from="none")),
):
    """Transition supplier lifecycle: submit | approve | suspend | reject.

    draft → submitted → approved → suspended (reject returns submitted → draft).
    Only 'approved' suppliers are discoverable to buyers.
    """
    tenant, profile = _get_supplier(db, tenant_id)

    action = req.action.lower()
    if action not in LIFECYCLE_TRANSITIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {list(LIFECYCLE_TRANSITIONS)}")

    allowed_from, target = LIFECYCLE_TRANSITIONS[action]
    if profile.lifecycle_status not in allowed_from:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} supplier in status '{profile.lifecycle_status}'",
        )

    now = datetime.now(timezone.utc)
    previous = profile.lifecycle_status
    profile.lifecycle_status = target
    profile.updated_at = now
    if action == "submit":
        profile.submitted_at = now
    elif action == "approve":
        profile.approved_at = now
        if ctx.get("user_id"):
            try:
                profile.approved_by = uuid.UUID(ctx["user_id"])
            except (ValueError, TypeError):
                pass
    db.commit()
    db.refresh(profile)

    try:
        event_name = {
            "submit": "supplier.submitted",
            "approve": "supplier.approved",
            "suspend": "supplier.suspended",
            "reject": "supplier.rejected",
        }[action]
        create_outbox_event(
            db, str(tenant.tenant_id), event_name,
            {
                "tenant_id": str(tenant.tenant_id),
                "from": previous,
                "to": target,
                "reason": req.reason,
            },
        )
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for supplier lifecycle: {_oe}")

    logger.info(f"✅ Supplier {tenant_id}: {previous} → {target}")
    return _supplier_dict(tenant, profile)
