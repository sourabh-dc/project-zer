"""
Review queue API (deck slice 3).

Low-confidence records land here instead of being silently merged.
Humans approve (accept the proposed canonical match) or reject (keep as
a distinct identity). Approving a supplier match records the source name
as an alias on the canonical record — evidence, not erasure.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from provisioning_service import Models
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization

router = APIRouter(prefix="/v1", tags=["Review Queue"])

REVIEW_PERMISSION = "catalog.manage"


class ReviewItemOut(BaseModel):
    review_id: str
    object_type: str
    source_record: dict
    proposed_match_id: Optional[str] = None
    proposed_match_name: Optional[str] = None
    confidence: int
    reason: Optional[str] = None
    status: str
    created_at: Optional[str] = None


def _check_tenant(ctx, tenant_id: str) -> None:
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")


def _out(i: Models.ReviewQueueItem) -> ReviewItemOut:
    return ReviewItemOut(
        review_id=str(i.review_id),
        object_type=i.object_type,
        source_record=i.source_record or {},
        proposed_match_id=str(i.proposed_match_id) if i.proposed_match_id else None,
        proposed_match_name=i.proposed_match_name,
        confidence=i.confidence,
        reason=i.reason,
        status=i.status,
        created_at=i.created_at.isoformat() if i.created_at else None,
    )


@router.get("/tenants/{tenant_id}/review-queue", response_model=List[ReviewItemOut])
def list_review_queue(
    tenant_id: str,
    status_filter: str = Query("pending", description="pending|approved|rejected|all"),
    object_type: Optional[str] = Query(None, description="supplier|product"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REVIEW_PERMISSION)),
):
    _check_tenant(ctx, tenant_id)
    query = db.query(Models.ReviewQueueItem).filter(Models.ReviewQueueItem.tenant_id == tenant_id)
    if status_filter != "all":
        query = query.filter(Models.ReviewQueueItem.status == status_filter)
    if object_type:
        query = query.filter(Models.ReviewQueueItem.object_type == object_type)
    items = query.order_by(Models.ReviewQueueItem.created_at.desc()).limit(200).all()
    return [_out(i) for i in items]


@router.post("/tenants/{tenant_id}/review-queue/{review_id}/approve", response_model=ReviewItemOut)
def approve_review_item(
    tenant_id: str,
    review_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REVIEW_PERMISSION)),
):
    """Accept the proposed match — source name becomes a canonical alias."""
    _check_tenant(ctx, tenant_id)
    item = db.query(Models.ReviewQueueItem).filter(
        Models.ReviewQueueItem.review_id == review_id,
        Models.ReviewQueueItem.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {item.status}")

    if item.object_type == "supplier" and item.proposed_match_id:
        canonical = db.query(Models.CanonicalSupplier).filter(
            Models.CanonicalSupplier.canonical_supplier_id == item.proposed_match_id,
        ).first()
        if canonical:
            aliases = set(canonical.aliases or [])
            source_name = (item.source_record or {}).get("name")
            if source_name:
                aliases.add(source_name)
                canonical.aliases = sorted(aliases)

    item.status = "approved"
    item.reviewer_user_id = uuid.UUID(ctx["user_id"]) if ctx.get("user_id") else None
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return _out(item)


@router.post("/tenants/{tenant_id}/review-queue/{review_id}/reject", response_model=ReviewItemOut)
def reject_review_item(
    tenant_id: str,
    review_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REVIEW_PERMISSION)),
):
    """Reject the proposed match — the source record is a distinct identity."""
    _check_tenant(ctx, tenant_id)
    item = db.query(Models.ReviewQueueItem).filter(
        Models.ReviewQueueItem.review_id == review_id,
        Models.ReviewQueueItem.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {item.status}")

    if item.object_type == "supplier":
        source_name = (item.source_record or {}).get("name")
        norm = (item.source_record or {}).get("normalized")
        if source_name and norm:
            exists = db.query(Models.CanonicalSupplier).filter(
                Models.CanonicalSupplier.tenant_id == tenant_id,
                Models.CanonicalSupplier.normalized_name == norm,
            ).first()
            if not exists:
                db.add(Models.CanonicalSupplier(
                    canonical_supplier_id=uuid.uuid4(),
                    tenant_id=uuid.UUID(tenant_id),
                    display_name=source_name[:255],
                    normalized_name=norm[:255],
                    aliases=[source_name],
                ))

    item.status = "rejected"
    item.reviewer_user_id = uuid.UUID(ctx["user_id"]) if ctx.get("user_id") else None
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return _out(item)
