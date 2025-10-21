import uuid
from typing import Dict, List

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