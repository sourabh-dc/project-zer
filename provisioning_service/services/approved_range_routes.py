import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func

from provisioning_service.Models import (
    ApprovedRange, ApprovedRangeOrgUnit, ApprovedRangeCategory,
    OrgUnit, Category, User,
)
from provisioning_service.Schemas import (
    ApprovedRangeCreateRequest, ApprovedRangeUpdateRequest,
    ApprovedRangeOrgUnitRequest,
    ApprovedRangeCategoryRequest,
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
        category_count = db.query(ApprovedRangeCategory).filter(
            ApprovedRangeCategory.approved_range_id == ar.approved_range_id
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
            "category_count": category_count,
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

    category_count = db.query(ApprovedRangeCategory).filter(
        ApprovedRangeCategory.approved_range_id == ar.approved_range_id
    ).count()

    return {
        "approved_range_id": str(ar.approved_range_id),
        "name": ar.name,
        "description": ar.description,
        "is_universal": ar.is_universal,
        "status": ar.status,
        "category_count": category_count,
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
# CATEGORY MEMBERSHIP (PRIMARY GOVERNANCE PATH)
# =============================================================================

@router.post("/{approved_range_id}/categories", status_code=201)
async def add_categories_to_range(
    approved_range_id: str,
    req: ApprovedRangeCategoryRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.add_categories")),
):
    """Add one or more categories to an approved range (PRIMARY governance path).

    All products in those categories (and optionally subcategories)
    become approved for org units governed by this range.
    """
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

    for cid_str in req.category_ids:
        cid = uuid.UUID(cid_str)
        category = db.query(Category).filter(
            Category.category_id == cid,
            Category.status != "deleted",
        ).first()
        if not category:
            skipped.append({"category_id": cid_str, "reason": "Category not found"})
            continue

        exists = db.query(ApprovedRangeCategory).filter(
            ApprovedRangeCategory.approved_range_id == ar.approved_range_id,
            ApprovedRangeCategory.category_id == cid,
        ).first()
        if exists:
            skipped.append({"category_id": cid_str, "reason": "Already in range"})
            continue

        mapping = ApprovedRangeCategory(
            id=uuid.uuid4(),
            approved_range_id=ar.approved_range_id,
            category_id=cid,
            added_by=uuid.UUID(user_id) if user_id else None,
            include_subcategories=req.include_subcategories,
        )
        db.add(mapping)
        added.append(cid_str)

    if added:
        outbox = append_outbox_event(
            db,
            tenant_id=tenant_id,
            aggregate_type="approved_range",
            aggregate_id=ar.approved_range_id,
            event_type="approved_range.categories_added",
            payload={
                "approved_range_id": str(ar.approved_range_id),
                "category_ids": added,
                "include_subcategories": req.include_subcategories,
                "added_by": str(user_id) if user_id else None,
            },
        )
        db.commit()
        await notify_outbox(str(outbox.id))
    else:
        db.commit()

    return {"added": added, "skipped": skipped}


@router.delete("/{approved_range_id}/categories/{category_id}", status_code=204)
async def remove_category_from_range(
    approved_range_id: str,
    category_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("approved_range.remove_category", resource_from="none")),
):
    """Remove a category from an approved range."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    mapping = db.query(ApprovedRangeCategory).filter(
        ApprovedRangeCategory.approved_range_id == ar.approved_range_id,
        ApprovedRangeCategory.category_id == uuid.UUID(category_id),
    ).first()
    if not mapping:
        raise HTTPException(404, "Category not in this range")

    db.delete(mapping)

    outbox = append_outbox_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="approved_range",
        aggregate_id=ar.approved_range_id,
        event_type="approved_range.category_removed",
        payload={
            "approved_range_id": str(ar.approved_range_id),
            "category_id": category_id,
        },
    )
    db.commit()
    await notify_outbox(str(outbox.id))
    return None


@router.get("/{approved_range_id}/categories")
async def list_range_categories(
    approved_range_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """List categories included in an approved range (from Postgres)."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id

    ar = db.query(ApprovedRange).filter(
        ApprovedRange.approved_range_id == uuid.UUID(approved_range_id),
        ApprovedRange.tenant_id == tenant_id,
        ApprovedRange.status != "deleted",
    ).first()
    if not ar:
        raise HTTPException(404, "Approved range not found")

    rows = (
        db.query(Category, ApprovedRangeCategory.include_subcategories)
        .join(ApprovedRangeCategory, ApprovedRangeCategory.category_id == Category.category_id)
        .filter(
            ApprovedRangeCategory.approved_range_id == ar.approved_range_id,
            Category.status != "deleted",
        )
        .order_by(Category.name)
        .all()
    )

    return {
        "approved_range_id": approved_range_id,
        "categories": [
            {
                "category_id": str(cat.category_id),
                "name": cat.name,
                "code": cat.code,
                "status": cat.status,
                "include_subcategories": include_sub,
            }
            for cat, include_sub in rows
        ],
    }
