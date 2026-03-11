import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func

from provisioning_service.Models import (
    ApprovedRange, ApprovedRangeOrgUnit, ApprovedRangeProduct,
    OrgUnit, Product, User,
)
from provisioning_service.Schemas import (
    ApprovedRangeCreateRequest, ApprovedRangeUpdateRequest,
    ApprovedRangeOrgUnitRequest, ApprovedRangeProductRequest,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox import append_outbox_event, notify_outbox
from provisioning_service.utils.logger import logger


router = APIRouter(prefix="/approved-ranges", tags=["Approved Ranges"])



# =============================================================================
# APPROVED RANGE CRUD
# =============================================================================

@router.post("", status_code=201)
async def create_approved_range(
    req: ApprovedRangeCreateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.create")),
):
    """Create a new approved range for the tenant."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    user_id = ctx.get("user_id") if isinstance(ctx, dict) else ctx.user_id

    existing = db.query(ApprovedRange).filter(
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.name == req.name,
        ApprovedRange.status != "deleted",
    ).first()
    if existing:
        raise HTTPException(409, "An approved range with this name already exists")

    ar = ApprovedRange(
        approved_range_id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        is_universal=req.is_universal,
        status="active",
        created_by=user_id,
    )
    db.add(ar)

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.created",
        payload={
            "approved_range_id": str(ar.approved_range_id),
            "name": ar.name,
            "is_universal": ar.is_universal,
        },
    )
    db.commit()
    await notify_outbox(str(outbox.id))

    logger.info(f"Created approved range: {ar.name} (universal={ar.is_universal})")

    return {
        "approved_range_id": str(ar.approved_range_id),
        "name": ar.name,
        "description": ar.description,
        "is_universal": ar.is_universal,
        "status": ar.status,
        "created_at": ar.created_at.isoformat() if ar.created_at else None,
    }


@router.get("")
async def list_approved_ranges(
    is_universal: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """List approved ranges for the tenant."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    q = db.query(ApprovedRange).filter(
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    )
    if is_universal is not None:
        q = q.filter(ApprovedRange.is_universal == is_universal)

    total = q.count()
    items = q.order_by(ApprovedRange.name).offset(offset).limit(limit).all()

    results = []
    for ar in items:
        product_count = db.query(ApprovedRangeProduct).filter(
            ApprovedRangeProduct.approved_range_id == ar.approved_range_id
        ).count()
        org_unit_count = db.query(ApprovedRangeOrgUnit).filter(
            ApprovedRangeOrgUnit.approved_range_id == ar.approved_range_id
        ).count()
        results.append({
            "approved_range_id": str(ar.approved_range_id),
            "name": ar.name,
            "description": ar.description,
            "is_universal": ar.is_universal,
            "status": ar.status,
            "product_count": product_count,
            "org_unit_count": org_unit_count,
            "created_at": ar.created_at.isoformat() if ar.created_at else None,
        })

    return {"total": total, "limit": limit, "offset": offset, "approved_ranges": results}


@router.get("/{approved_range_id}")
async def get_approved_range(
    approved_range_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Get approved range details including mapped org units and product count."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    org_units = (
        db.query(OrgUnit.org_unit_id, OrgUnit.name)
        .join(ApprovedRangeOrgUnit, ApprovedRangeOrgUnit.org_unit_id == OrgUnit.org_unit_id)
        .filter(ApprovedRangeOrgUnit.approved_range_id == ar.approved_range_id)
        .all()
    )

    product_count = db.query(ApprovedRangeProduct).filter(
        ApprovedRangeProduct.approved_range_id == ar.approved_range_id
    ).count()

    return {
        "approved_range_id": str(ar.approved_range_id),
        "name": ar.name,
        "description": ar.description,
        "is_universal": ar.is_universal,
        "status": ar.status,
        "product_count": product_count,
        "org_units": [{"org_unit_id": str(ou[0]), "name": ou[1]} for ou in org_units],
        "created_by": str(ar.created_by) if ar.created_by else None,
        "created_at": ar.created_at.isoformat() if ar.created_at else None,
        "updated_at": ar.updated_at.isoformat() if ar.updated_at else None,
    }


@router.put("/{approved_range_id}")
async def update_approved_range(
    approved_range_id: str,
    req: ApprovedRangeUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.update")),
):
    """Update an approved range's name, description, or universal flag."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    if req.name is not None:
        dupe = db.query(ApprovedRange).filter(
            ApprovedRange.tenant_id == tenant_id,
            ApprovedRange.name == req.name,
            ApprovedRange.approved_range_id != ar.approved_range_id,
            ApprovedRange.status != "deleted",
        ).first()
        if dupe:
            raise HTTPException(409, "Another approved range with this name already exists")
        ar.name = req.name
    if req.description is not None:
        ar.description = req.description
    if req.is_universal is not None:
        ar.is_universal = req.is_universal

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.updated",
        payload={
            "approved_range_id": str(ar.approved_range_id),
            "name": ar.name,
            "is_universal": ar.is_universal,
        },
    )
    db.commit()
    await notify_outbox(str(outbox.id))

    return {
        "approved_range_id": str(ar.approved_range_id),
        "name": ar.name,
        "description": ar.description,
        "is_universal": ar.is_universal,
        "status": ar.status,
    }


@router.delete("/{approved_range_id}", status_code=204)
async def delete_approved_range(
    approved_range_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.delete", resource_from="none")),
):
    """Soft-delete an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    ar.status = "deleted"

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.deleted",
        payload={"approved_range_id": str(ar.approved_range_id)},
    )
    db.commit()
    await notify_outbox(str(outbox.id))

    logger.info(f"Soft-deleted approved range: {approved_range_id}")
    return None


# =============================================================================
# ORG UNIT MAPPING
# =============================================================================

@router.post("/{approved_range_id}/org-units", status_code=201)
async def map_org_units_to_range(
    approved_range_id: str,
    req: ApprovedRangeOrgUnitRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.map_org_unit")),
):
    """Map one or more org units to an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    added = []
    skipped = []

    for ou_id_str in req.org_unit_ids:
        ou_id = uuid.UUID(ou_id_str)
        ou = db.query(OrgUnit).filter(
            OrgUnit.org_unit_id == ou_id,
            OrgUnit.tenant_id == tenant_id,
            OrgUnit.status != "deleted",
        ).first()
        if not ou:
            skipped.append({"org_unit_id": ou_id_str, "reason": "Org unit not found"})
            continue

        exists = db.query(ApprovedRangeOrgUnit).filter(
            ApprovedRangeOrgUnit.approved_range_id == ar.approved_range_id,
            ApprovedRangeOrgUnit.org_unit_id == ou_id,
        ).first()
        if exists:
            skipped.append({"org_unit_id": ou_id_str, "reason": "Already mapped"})
            continue

        mapping = ApprovedRangeOrgUnit(
            id=uuid.uuid4(),
            approved_range_id=ar.approved_range_id,
            org_unit_id=ou_id,
        )
        db.add(mapping)
        added.append(ou_id_str)

    if added:
        outbox = append_outbox_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="approved_range",
            aggregate_id=ar.approved_range_id,
            event_type="approved_range.org_units_added",
            payload={
                "approved_range_id": str(ar.approved_range_id),
                "org_unit_ids": added,
            },
        )
        db.commit()
        await notify_outbox(str(outbox.id))
    else:
        db.commit()

    return {"added": added, "skipped": skipped}


@router.delete("/{approved_range_id}/org-units/{org_unit_id}", status_code=204)
async def remove_org_unit_from_range(
    approved_range_id: str,
    org_unit_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.unmap_org_unit", resource_from="none")),
):
    """Remove an org unit mapping from an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    mapping = db.query(ApprovedRangeOrgUnit).filter(
        ApprovedRangeOrgUnit.approved_range_id == ar.approved_range_id,
        ApprovedRangeOrgUnit.org_unit_id == uuid.UUID(org_unit_id),
    ).first()
    if not mapping:
        raise HTTPException(404, "Org unit not mapped to this range")

    db.delete(mapping)

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.org_unit_removed",
        payload={
            "approved_range_id": str(ar.approved_range_id),
            "org_unit_id": org_unit_id,
        },
    )
    db.commit()
    await notify_outbox(str(outbox.id))
    return None


@router.get("/{approved_range_id}/org-units")
async def list_range_org_units(
    approved_range_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """List all org units mapped to an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    org_units = (
        db.query(OrgUnit.org_unit_id, OrgUnit.name, OrgUnit.type, OrgUnit.status)
        .join(ApprovedRangeOrgUnit, ApprovedRangeOrgUnit.org_unit_id == OrgUnit.org_unit_id)
        .filter(ApprovedRangeOrgUnit.approved_range_id == ar.approved_range_id)
        .all()
    )

    return {
        "approved_range_id": str(ar.approved_range_id),
        "org_units": [
            {"org_unit_id": str(ou[0]), "name": ou[1], "type": ou[2], "status": ou[3]}
            for ou in org_units
        ],
    }


# =============================================================================
# PRODUCT MEMBERSHIP
# =============================================================================

@router.post("/{approved_range_id}/products", status_code=201)
async def add_products_to_range(
    approved_range_id: str,
    req: ApprovedRangeProductRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.add_products")),
):
    """Add one or more products to an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    user_id = ctx.get("user_id") if isinstance(ctx, dict) else ctx.user_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    added = []
    skipped = []

    for pid_str in req.product_ids:
        pid = uuid.UUID(pid_str)
        product = db.query(Product).filter(
            Product.product_id == pid,
            Product.tenant_id == tenant_id,
            Product.status != "deleted",
        ).first()
        if not product:
            skipped.append({"product_id": pid_str, "reason": "Product not found"})
            continue

        exists = db.query(ApprovedRangeProduct).filter(
            ApprovedRangeProduct.approved_range_id == ar.approved_range_id,
            ApprovedRangeProduct.product_id == pid,
        ).first()
        if exists:
            skipped.append({"product_id": pid_str, "reason": "Already in range"})
            continue

        arp = ApprovedRangeProduct(
            id=uuid.uuid4(),
            approved_range_id=ar.approved_range_id,
            product_id=pid,
            added_by=user_id,
        )
        db.add(arp)
        added.append(pid_str)

    if added:
        product_details = {}
        for pid_str in added:
            p = db.query(Product).filter(Product.product_id == uuid.UUID(pid_str)).first()
            if p:
                product_details[pid_str] = {
                    "display_name": p.display_name,
                    "sku": getattr(p, "sku", ""),
                    "item_code": getattr(p, "item_code", ""),
                    "category_id": str(p.category_id) if p.category_id else None,
                }

        outbox = append_outbox_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="approved_range",
            aggregate_id=ar.approved_range_id,
            event_type="approved_range.products_added",
            payload={
                "approved_range_id": str(ar.approved_range_id),
                "product_ids": added,
                "product_details": product_details,
                "tenant_id": str(tenant_id),
            },
        )
        db.commit()
        await notify_outbox(str(outbox.id))
    else:
        db.commit()

    return {"added": added, "skipped": skipped}


@router.delete("/{approved_range_id}/products/{product_id}", status_code=204)
async def remove_product_from_range(
    approved_range_id: str,
    product_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.remove_product", resource_from="none")),
):
    """Remove a product from an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    arp = db.query(ApprovedRangeProduct).filter(
        ApprovedRangeProduct.approved_range_id == ar.approved_range_id,
        ApprovedRangeProduct.product_id == uuid.UUID(product_id),
    ).first()
    if not arp:
        raise HTTPException(404, "Product not in this range")

    db.delete(arp)

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.product_removed",
        payload={
            "approved_range_id": str(ar.approved_range_id),
            "product_id": product_id,
        },
    )
    db.commit()
    await notify_outbox(str(outbox.id))
    return None


@router.get("/{approved_range_id}/products")
async def list_range_products(
    approved_range_id: str,
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """List all products in an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    q = (
        db.query(Product)
        .join(ApprovedRangeProduct, ApprovedRangeProduct.product_id == Product.product_id)
        .filter(
            ApprovedRangeProduct.approved_range_id == ar.approved_range_id,
            Product.status != "deleted",
        )
    )

    if search:
        from sqlalchemy import or_
        q = q.filter(or_(
            Product.display_name.ilike(f"%{search}%"),
            Product.sku.ilike(f"%{search}%"),
        ))

    total = q.count()
    items = q.order_by(Product.display_name).offset(offset).limit(limit).all()

    return {
        "approved_range_id": str(ar.approved_range_id),
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [
            {
                "product_id": str(p.product_id),
                "sku": p.sku,
                "ean": p.ean,
                "display_name": p.display_name,
                "purchase_price_minor": p.purchase_price_minor,
                "currency": p.currency,
                "category_id": str(p.category_id) if p.category_id else None,
            }
            for p in items
        ],
    }
