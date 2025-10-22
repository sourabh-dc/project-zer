import uuid
from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.catalog.models import ProductBundleV2, BundleComponentV2
from services.catalog.schemas import ProductBundleRequest, BundleComponentRequest


def create_bundle_record(req: ProductBundleRequest, db: Session, bundle_id:uuid.UUID, uctx: Dict) -> ProductBundleV2:
    bundle = ProductBundleV2(
        bundle_id=bundle_id,
        tenant_id=uuid.UUID(uctx["tenant_id"]),
        name=req.name,
        description=req.description,
        bundle_sku=req.bundle_sku,
        bundle_type=req.bundle_type,
        base_price_minor=req.base_price_minor,
        currency=req.currency
    )
    db.add(bundle)
    db.commit()
    db.refresh(bundle)
    return bundle

def create_bundle_components(components: List[BundleComponentRequest], db: Session, bundle_id: uuid.UUID):
    for i, component_req in enumerate(components):
        component = BundleComponentV2(
            bundle_id=bundle_id,
            product_id=uuid.UUID(component_req.product_id),
            variant_id=uuid.UUID(component_req.variant_id) if component_req.variant_id else None,
            quantity=component_req.quantity,
            price_override_minor=component_req.price_override_minor,
            is_required=component_req.is_required,
            sort_order=component_req.sort_order or i
        )
        db.add(component)
    db.commit()

def get_all_bundles(db: Session, tenant_id: str, bundle_type: str = None, limit: int = 100, offset: int = 0) -> Dict:
    query = db.query(ProductBundleV2).filter(
        ProductBundleV2.tenant_id == uuid.UUID(tenant_id),
        ProductBundleV2.is_active == True
    )

    if bundle_type:
        query = query.filter(ProductBundleV2.bundle_type == bundle_type)

    bundles = query.offset(offset).limit(limit).all()

    return {
        "bundles": [
            {
                "bundle_id": str(bundle.bundle_id),
                "name": bundle.name,
                "bundle_sku": bundle.bundle_sku,
                "bundle_type": bundle.bundle_type,
                "base_price_minor": bundle.base_price_minor,
                "currency": bundle.currency,
                "created_at": bundle.created_at.isoformat()
            }
            for bundle in bundles
        ],
        "total": len(bundles),
        "limit": limit,
        "offset": offset
    }

async def get_bundle_by_id(db: Session, bundle_id: str) -> Dict:
    # Get bundle
    bundle = db.query(ProductBundleV2).filter(
        ProductBundleV2.bundle_id == uuid.UUID(bundle_id)
    ).first()

    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    # Get components
    components = db.query(BundleComponentV2).filter(
        BundleComponentV2.bundle_id == uuid.UUID(bundle_id)
    ).order_by(BundleComponentV2.sort_order).all()

    return {
        "bundle_id": str(bundle.bundle_id),
        "name": bundle.name,
        "description": bundle.description,
        "bundle_sku": bundle.bundle_sku,
        "bundle_type": bundle.bundle_type,
        "base_price_minor": bundle.base_price_minor,
        "currency": bundle.currency,
        "is_active": bundle.is_active,
        "components": [
            {
                "component_id": str(component.component_id),
                "product_id": str(component.product_id),
                "variant_id": str(component.variant_id) if component.variant_id else None,
                "quantity": component.quantity,
                "price_override_minor": component.price_override_minor,
                "is_required": component.is_required,
                "sort_order": component.sort_order
            }
            for component in components
        ],
        "created_at": bundle.created_at.isoformat(),
        "updated_at": bundle.updated_at.isoformat()
    }

async def search_product_db(req, db: Session) -> List[dict]:
    query = "SELECT * FROM products_v2 WHERE 1=1"
    params = {"limit": req.limit, "offset": req.offset}

    if req.query:
        query += " AND (name ILIKE :query OR description ILIKE :query OR sku ILIKE :query)"
        params["query"] = f"%{req.query}%"

    if req.category_id:
        query += " AND category_id = :category_id"
        params["category_id"] = req.category_id

    if req.vendor_id:
        query += " AND vendor_id = :vendor_id"
        params["vendor_id"] = req.vendor_id

    if req.min_price:
        query += " AND base_price_minor >= :min_price"
        params["min_price"] = req.min_price

    if req.max_price:
        query += " AND base_price_minor <= :max_price"
        params["max_price"] = req.max_price

    query += " AND is_active = true ORDER BY created_at DESC LIMIT :limit OFFSET :offset"

    products = db.execute(text(query), params).fetchall()

    return [dict(product._mapping) for product in products]