import uuid
import io
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from uuid import UUID
import pandas as pd

from provisioning_service.Models import (
    Tenant, Category, Product, Variant, StoreProduct, Store, Vendor,
    Colour, Size, Fit, UosLabel,
    ApprovedRange, ApprovedRangeOrgUnit, ApprovedRangeProduct, User,
)
from provisioning_service.Schemas import (
    CategoryRequest, ProductRequest, VariantRequest, StoreProductRequest,
    UserContext
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.helpers.aifi_services import cv_create_product
from provisioning_service.core.entitlement_helpers import check_feature_limit, record_feature_usage
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox import append_outbox_event, notify_outbox
from provisioning_service.utils.logger import logger


router = APIRouter(prefix="/catalog", tags=["Catalog"])

# =============================================================================
# CATEGORY ENDPOINTS
# =============================================================================

@router.post("/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("category.create")),
):
    try:
        tenant_id = ctx.tenant_id if hasattr(ctx, 'tenant_id') else ctx.get('tenant_id')
        if str(tenant_id) != req.tenant_id:
            raise HTTPException(403, "Tenant mismatch")
        
        # Check entitlement limit
        check_feature_limit(db, req.tenant_id, "categories", count=1)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_category setup: {type(e).__name__}: {e}")
        raise HTTPException(500, f"Setup error: {str(e)}")

    # Enforce tenant-scoped unique code
    exists = db.query(Category).filter(
        Category.tenant_id == req.tenant_id,
        Category.code == req.code,
        Category.active == True
    ).first()
    if exists:
        raise HTTPException(409, "Category code already exists")

    parent_id = None
    if req.parent_category_id:
        try:
            parent_id = UUID(req.parent_category_id)
        except ValueError:
            raise HTTPException(400, "Invalid parent_category_id format")

        parent = db.query(Category).filter(
            Category.category_id == parent_id,
            Category.tenant_id == ctx.tenant_id,
            Category.active == True
        ).first()
        if not parent:
            raise HTTPException(404, "Parent category not found")

    category = Category(
        category_id=uuid.uuid4(),
        tenant_id=req.tenant_id,
        name=req.name.strip(),
        code=req.code.strip(),
        description=req.description,
        parent_category_id=parent_id,
        active=True
    )
    db.add(category)

    outbox = append_outbox_event(
        db,
        tenant_id=uuid.UUID(req.tenant_id),
        aggregate_type="category",
        aggregate_id=category.category_id,
        event_type="category.created",
        payload={
            "category_id": str(category.category_id),
            "name": category.name,
            "code": category.code,
            "tenant_id": req.tenant_id,
        },
    )
    try:
        db.commit()
        db.refresh(category)
        record_feature_usage(db, req.tenant_id, "categories", count=1)
        await notify_outbox(str(outbox.id))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Category code conflict")

    return {
        "category_id": str(category.category_id),
        "name": category.name,
        "code": category.code,
        "parent_category_id": str(parent_id) if parent_id else None,
        "active": True
    }


@router.get("/categories")
async def list_categories(
    active: Optional[bool] = Query(None),
    parent_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage"))
):
    q = db.query(Category).filter(
        Category.tenant_id == ctx["tenant_id"],
        Category.status != "deleted"
    )

    if active is not None:
        q = q.filter(Category.active == active)
    if parent_id:
        q = q.filter(Category.parent_category_id == UUID(parent_id))

    total = q.count()
    items = q.order_by(Category.name).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "categories": [
            {
                "category_id": str(c.category_id),
                "name": c.name,
                "code": c.code,
                "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                "active": c.active,
                "has_children": db.query(Category).filter(
                    Category.parent_category_id == c.category_id,
                    Category.status != "deleted"
                ).count() > 0
            }
            for c in items
        ]
    }


@router.put("/categories/{category_id}")
async def update_category(
    category_id: str,
    name: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    parent_category_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("category.update")),
):
    try:
        tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id

        category = db.query(Category).filter(
            Category.category_id == UUID(category_id),
            Category.tenant_id == tenant_id,
            Category.status != "deleted"
        ).first()
        if not category:
            raise HTTPException(404, "Category not found")

        if name is not None:
            category.name = name.strip()
        if code is not None:
            existing = db.query(Category).filter(
                Category.tenant_id == tenant_id,
                Category.code == code.strip(),
                Category.category_id != category.category_id,
                Category.active == True
            ).first()
            if existing:
                raise HTTPException(409, "Category code already exists")
            category.code = code.strip()
        if description is not None:
            category.description = description
        if parent_category_id is not None:
            if parent_category_id == "":
                category.parent_category_id = None
            else:
                try:
                    pid = UUID(parent_category_id)
                except ValueError:
                    raise HTTPException(400, "Invalid parent_category_id format")
                parent = db.query(Category).filter(
                    Category.category_id == pid,
                    Category.tenant_id == tenant_id,
                    Category.active == True
                ).first()
                if not parent:
                    raise HTTPException(404, "Parent category not found")
                category.parent_category_id = pid

        outbox = append_outbox_event(
            db,
            tenant_id=uuid.UUID(str(tenant_id)),
            aggregate_type="category",
            aggregate_id=category.category_id,
            event_type="category.updated",
            payload={
                "category_id": str(category.category_id),
                "name": category.name,
                "code": category.code,
                "tenant_id": str(tenant_id),
            },
        )
        db.commit()
        db.refresh(category)
        await notify_outbox(str(outbox.id))

        return {
            "category_id": str(category.category_id),
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "active": category.active,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Update category failed: {e}")
        raise HTTPException(500, f"Internal server error")


@router.delete("/categories/{category_id}", status_code=200)
async def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("category.delete", resource_from="none")),
):
    try:
        tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id

        category = db.query(Category).filter(
            Category.category_id == UUID(category_id),
            Category.tenant_id == tenant_id,
            Category.status != "deleted"
        ).first()
        if not category:
            raise HTTPException(404, "Category not found")

        category.status = "deleted"
        category.active = False

        outbox = append_outbox_event(
            db,
            tenant_id=uuid.UUID(str(tenant_id)),
            aggregate_type="category",
            aggregate_id=category.category_id,
            event_type="category.deleted",
            payload={"category_id": str(category.category_id), "tenant_id": str(tenant_id)},
        )
        db.commit()
        await notify_outbox(str(outbox.id))

        return {"deleted": True, "category_id": category_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Delete category failed: {e}")
        raise HTTPException(500, "Internal server error")


# =============================================================================
# PRODUCT ENDPOINTS
# =============================================================================

@router.post("/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("product.create")),
):
    if str(ctx["tenant_id"]) != req.tenant_id:
        raise HTTPException(403, "Tenant mismatch")
    
    # Check entitlement limit
    check_feature_limit(db, req.tenant_id, "products", count=1)

    # SKU must be unique per tenant
    if db.query(Product).filter(
        Product.tenant_id == req.tenant_id,
        Product.sku == req.sku,
        Product.active == True
    ).first():
        raise HTTPException(409, "SKU already exists in your catalog")

    # EAN must be unique per tenant if provided
    if req.ean and db.query(Product).filter(
        Product.tenant_id == req.tenant_id,
        Product.ean == req.ean,
        Product.active == True
    ).first():
        raise HTTPException(409, "EAN already exists in your catalog")

    category_id = None
    if req.category_id:
        try:
            category_id = UUID(req.category_id)
        except ValueError:
            raise HTTPException(400, "Invalid category_id")
        if not db.query(Category).filter(
            Category.category_id == category_id,
            Category.tenant_id == req.tenant_id,
            Category.active == True
        ).first():
            raise HTTPException(404, "Category not found")

    vendor_id = None
    if req.vendor_id:
        try:
            vendor_id = UUID(req.vendor_id)
        except ValueError:
            raise HTTPException(400, "Invalid vendor_id")
        if not db.query(Vendor).filter(
            Vendor.vendor_id == vendor_id,
            Vendor.tenant_id == req.tenant_id
        ).first():
            raise HTTPException(404, "Vendor not found")

    brand_id = None
    if req.brand_id:
        try:
            brand_id = UUID(req.brand_id)
        except ValueError:
            raise HTTPException(400, "Invalid brand_id")

    # Validate matrix parent if this is a child product
    matrix_parent_id = None
    if req.matrix_parent_id:
        try:
            matrix_parent_id = UUID(req.matrix_parent_id)
        except ValueError:
            raise HTTPException(400, "Invalid matrix_parent_id")
        parent = db.query(Product).filter(
            Product.product_id == matrix_parent_id,
            Product.tenant_id == req.tenant_id,
            Product.active == True
        ).first()
        if not parent:
            raise HTTPException(404, "Matrix parent product not found")
        if parent.matrix_type != "parent":
            raise HTTPException(400, "matrix_parent_id must reference a parent product")

    # Validate colour_id
    colour_id = None
    if req.colour_id:
        try:
            colour_id = UUID(req.colour_id)
        except ValueError:
            raise HTTPException(400, "Invalid colour_id")
        if not db.query(Colour).filter(Colour.colour_id == colour_id).first():
            raise HTTPException(404, "Colour not found")

    # Validate size_id
    size_id = None
    if req.size_id:
        try:
            size_id = UUID(req.size_id)
        except ValueError:
            raise HTTPException(400, "Invalid size_id")
        if not db.query(Size).filter(Size.size_id == size_id).first():
            raise HTTPException(404, "Size not found")

    # Validate fit_id
    fit_id = None
    if req.fit_id:
        try:
            fit_id = UUID(req.fit_id)
        except ValueError:
            raise HTTPException(400, "Invalid fit_id")
        if not db.query(Fit).filter(Fit.fit_id == fit_id, Fit.status != "deleted").first():
            raise HTTPException(404, "Fit not found")

    # Validate UOS labels
    if req.outer_label_id:
        if not db.query(UosLabel).filter(UosLabel.label_id == req.outer_label_id).first():
            raise HTTPException(404, "Outer UOS label not found")
    if req.inner_label_id:
        if not db.query(UosLabel).filter(UosLabel.label_id == req.inner_label_id).first():
            raise HTTPException(404, "Inner UOS label not found")

    product = Product(
        product_id=uuid.uuid4(),
        tenant_id=req.tenant_id,
        external_id=req.external_id,
        sku=req.sku.strip(),
        ean=req.ean.strip() if req.ean else None,
        mpn=req.mpn,
        vendor_id=vendor_id,
        category_id=category_id,
        brand_id=brand_id,
        manufacturer=req.manufacturer,
        is_matrix_item=req.is_matrix_item,
        matrix_type=req.matrix_type or "standalone",
        matrix_parent_id=matrix_parent_id,
        colour_id=colour_id,
        size_id=size_id,
        fit_id=fit_id,
        item_option=req.item_option,
        display_name=req.display_name.strip(),
        web_display_name=req.web_display_name,
        sales_description=req.sales_description,
        purchase_description=req.purchase_description,
        packing_slip_description=req.packing_slip_description,
        detailed_description=req.detailed_description,
        additional_description=req.additional_description,
        weight=req.weight,
        weight_unit=req.weight_unit,
        width=req.width,
        depth=req.depth,
        height=req.height,
        outer_quantity=req.outer_quantity,
        outer_label_id=req.outer_label_id,
        inner_quantity=req.inner_quantity,
        inner_label_id=req.inner_label_id,
        reorder_multiple=req.reorder_multiple,
        purchase_price_minor=req.purchase_price_minor,
        currency=req.currency or "GBP",
        tax_rate=req.tax_rate or 0,
        manufacturer_country=req.manufacturer_country,
        commodity_code=req.commodity_code,
        product_type=req.product_type,
        colour_filter=req.colour_filter,
        size_filter=req.size_filter,
        search_keywords=req.search_keywords,
        is_dangerous_goods=req.is_dangerous_goods,
        cas_number=req.cas_number,
        un_number=req.un_number,
        proper_shipping_name=req.proper_shipping_name,
        transport_hazard_class=req.transport_hazard_class,
        packing_group=req.packing_group,
        adr_classification_code=req.adr_classification_code,
        adr_tunnel_restriction_code=req.adr_tunnel_restriction_code,
        adr_hazard_id_number=req.adr_hazard_id_number,
        tax_code=req.tax_code,
        restricted=req.restricted,
        product_metadata=req.product_metadata or {},
        comments=req.comments,
        active=True
    )
    db.add(product)

    outbox = append_outbox_event(
        db,
        tenant_id=uuid.UUID(req.tenant_id),
        aggregate_type="product",
        aggregate_id=product.product_id,
        event_type="product.created",
        payload={
            "product_id": str(product.product_id),
            "sku": product.sku,
            "display_name": product.display_name,
            "tenant_id": req.tenant_id,
        },
    )
    try:
        db.commit()
        db.refresh(product)
        try:
            aifi_product = await cv_create_product({
                "externalId": str(product.product_id),
                "name": product.display_name,
                "barcode": product.ean or product.sku,
                "price": product.purchase_price_minor,
                "weight": str(product.weight) if product.weight else "0",
                "thumbnail": ""
            })
            product.aifi_product_id = aifi_product.get("id")
            db.commit()
        except Exception as e:
            logger.warning(f"AiFi product sync failed, continuing: {e}")
            db.rollback()
        record_feature_usage(db, req.tenant_id, "products", count=1)
        await notify_outbox(str(outbox.id))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "SKU or EAN conflict")

    return {
        "product_id": str(product.product_id),
        "sku": product.sku,
        "ean": product.ean,
        "display_name": product.display_name,
        "matrix_type": product.matrix_type,
        "purchase_price_minor": product.purchase_price_minor,
        "active": True
    }


def _is_tenant_admin(ctx) -> bool:
    """Check if the current user is a tenant admin (bypasses approved range filtering)."""
    perms = ctx.get("permissions") if isinstance(ctx, dict) else getattr(ctx, "permissions", None)
    if isinstance(perms, list) and "*" in perms:
        return True
    roles = ctx.get("roles") if isinstance(ctx, dict) else getattr(ctx, "roles", None)
    if isinstance(roles, list) and "tenant_admin" in roles:
        return True
    return False


def _get_approved_product_ids(db: Session, tenant_id, user_id) -> Optional[set]:
    """Return the set of product IDs visible to a non-admin user via approved ranges.

    Returns None if the user has no org unit (fallback: show nothing outside universal).
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    user_org_unit_id = user.home_org_unit_id if user else None

    # Universal ranges — always included
    universal_range_ids = [
        r[0] for r in db.query(ApprovedRange.approved_range_id).filter(
            ApprovedRange.tenant_id == tenant_id,
            ApprovedRange.is_universal == True,
            ApprovedRange.status != "deleted",
        ).all()
    ]

    # Org-unit-specific ranges
    ou_range_ids = []
    if user_org_unit_id:
        ou_range_ids = [
            r[0] for r in db.query(ApprovedRangeOrgUnit.approved_range_id).filter(
                ApprovedRangeOrgUnit.org_unit_id == user_org_unit_id,
            ).join(ApprovedRange, ApprovedRange.approved_range_id == ApprovedRangeOrgUnit.approved_range_id).filter(
                ApprovedRange.tenant_id == tenant_id,
                ApprovedRange.status != "deleted",
            ).all()
        ]

    all_range_ids = set(universal_range_ids + ou_range_ids)
    if not all_range_ids:
        return set()

    product_ids = {
        r[0] for r in db.query(ApprovedRangeProduct.product_id).filter(
            ApprovedRangeProduct.approved_range_id.in_(all_range_ids)
        ).all()
    }
    return product_ids


@router.get("/products")
async def list_products(
    category_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("product.search", resource_from="none")),
):
    tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id
    user_id = ctx["user_id"] if isinstance(ctx, dict) else ctx.user_id

    q = db.query(Product).filter(
        Product.tenant_id == tenant_id,
        Product.status != "deleted"
    )

    # Approved range filtering: non-admin users only see products in their ranges
    if not _is_tenant_admin(ctx):
        has_any_ranges = db.query(ApprovedRange).filter(
            ApprovedRange.tenant_id == tenant_id,
            ApprovedRange.status != "deleted",
        ).first()
        if has_any_ranges:
            approved_ids = _get_approved_product_ids(db, tenant_id, user_id)
            if approved_ids:
                q = q.filter(Product.product_id.in_(approved_ids))
            else:
                q = q.filter(Product.product_id == None)

    if category_id:
        q = q.filter(Product.category_id == UUID(category_id))
    if vendor_id:
        q = q.filter(Product.vendor_id == UUID(vendor_id))
    if active is not None:
        q = q.filter(Product.active == active)
    if search:
        q = q.filter(
            or_(
                Product.display_name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
                Product.ean.ilike(f"%{search}%")
            )
        )

    total = q.count()
    items = q.order_by(Product.display_name).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [
            {
                "product_id": str(p.product_id),
                "sku": p.sku,
                "ean": p.ean,
                "display_name": p.display_name,
                "matrix_type": p.matrix_type,
                "purchase_price_minor": p.purchase_price_minor,
                "currency": p.currency,
                "category_id": str(p.category_id) if p.category_id else None,
                "active": p.active
            }
            for p in items
        ]
    }


@router.put("/products/{product_id}")
async def update_product(
    product_id: str,
    display_name: Optional[str] = Query(None),
    sales_description: Optional[str] = Query(None),
    purchase_description: Optional[str] = Query(None),
    purchase_price_minor: Optional[int] = Query(None),
    restricted: Optional[bool] = Query(None),
    active: Optional[bool] = Query(None),
    category_id: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    web_display_name: Optional[str] = Query(None),
    detailed_description: Optional[str] = Query(None),
    weight: Optional[float] = Query(None),
    weight_unit: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    tax_rate: Optional[int] = Query(None),
    search_keywords: Optional[str] = Query(None),
    comments: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("product.update")),
):
    try:
        tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id

        product = db.query(Product).filter(
            Product.product_id == UUID(product_id),
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()
        if not product:
            raise HTTPException(404, "Product not found")

        if display_name is not None:
            product.display_name = display_name.strip()
        if sales_description is not None:
            product.sales_description = sales_description
        if purchase_description is not None:
            product.purchase_description = purchase_description
        if purchase_price_minor is not None:
            product.purchase_price_minor = purchase_price_minor
        if restricted is not None:
            product.restricted = restricted
        if active is not None:
            product.active = active
        if category_id is not None:
            if category_id == "":
                product.category_id = None
            else:
                try:
                    cat_uuid = UUID(category_id)
                except ValueError:
                    raise HTTPException(400, "Invalid category_id")
                if not db.query(Category).filter(
                    Category.category_id == cat_uuid,
                    Category.tenant_id == tenant_id,
                    Category.active == True
                ).first():
                    raise HTTPException(404, "Category not found")
                product.category_id = cat_uuid
        if vendor_id is not None:
            if vendor_id == "":
                product.vendor_id = None
            else:
                try:
                    v_uuid = UUID(vendor_id)
                except ValueError:
                    raise HTTPException(400, "Invalid vendor_id")
                if not db.query(Vendor).filter(
                    Vendor.vendor_id == v_uuid,
                    Vendor.tenant_id == tenant_id
                ).first():
                    raise HTTPException(404, "Vendor not found")
                product.vendor_id = v_uuid
        if web_display_name is not None:
            product.web_display_name = web_display_name
        if detailed_description is not None:
            product.detailed_description = detailed_description
        if weight is not None:
            product.weight = weight
        if weight_unit is not None:
            product.weight_unit = weight_unit
        if currency is not None:
            product.currency = currency
        if tax_rate is not None:
            product.tax_rate = tax_rate
        if search_keywords is not None:
            product.search_keywords = search_keywords
        if comments is not None:
            product.comments = comments

        outbox = append_outbox_event(
            db,
            tenant_id=uuid.UUID(str(tenant_id)),
            aggregate_type="product",
            aggregate_id=product.product_id,
            event_type="product.updated",
            payload={
                "product_id": str(product.product_id),
                "sku": product.sku,
                "display_name": product.display_name,
                "tenant_id": str(tenant_id),
            },
        )
        db.commit()
        db.refresh(product)
        await notify_outbox(str(outbox.id))

        return {
            "product_id": str(product.product_id),
            "sku": product.sku,
            "ean": product.ean,
            "display_name": product.display_name,
            "purchase_price_minor": product.purchase_price_minor,
            "active": product.active,
            "category_id": str(product.category_id) if product.category_id else None,
            "vendor_id": str(product.vendor_id) if product.vendor_id else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Update product failed: {e}")
        raise HTTPException(500, "Internal server error")


@router.delete("/products/{product_id}", status_code=200)
async def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("product.delete", resource_from="none")),
):
    try:
        tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id

        product = db.query(Product).filter(
            Product.product_id == UUID(product_id),
            Product.tenant_id == tenant_id,
            Product.status != "deleted"
        ).first()
        if not product:
            raise HTTPException(404, "Product not found")

        product.status = "deleted"
        product.active = False

        outbox = append_outbox_event(
            db,
            tenant_id=uuid.UUID(str(tenant_id)),
            aggregate_type="product",
            aggregate_id=product.product_id,
            event_type="product.deleted",
            payload={"product_id": str(product.product_id), "tenant_id": str(tenant_id)},
        )
        db.commit()
        await notify_outbox(str(outbox.id))

        return {"deleted": True, "product_id": product_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Delete product failed: {e}")
        raise HTTPException(500, "Internal server error")


# =============================================================================
# VARIANT ENDPOINTS
# =============================================================================

@router.post("/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("variant.create")),
):
    # Check entitlement limit
    check_feature_limit(db, str(ctx.tenant_id), "variants", count=1)
    
    try:
        product_id = UUID(req.product_id)
    except ValueError:
        raise HTTPException(400, "Invalid product_id")

    product = db.query(Product).filter(
        Product.product_id == product_id,
        Product.tenant_id == ctx.tenant_id,
        Product.active == True
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    if db.query(Variant).filter(
        Variant.tenant_id == ctx.tenant_id,
        Variant.sku == req.sku,
        Variant.active == True
    ).first():
        raise HTTPException(409, "Variant SKU already exists")

    variant = Variant(
        variant_id=uuid.uuid4(),
        product_id=product.product_id,
        tenant_id=ctx.tenant_id,
        sku=req.sku.strip(),
        name=req.name.strip(),
        attributes=req.attributes or {},
        price_minor=req.price_minor or product.purchase_price_minor,
        currency=req.currency or "GBP",
        stock_quantity=req.stock_quantity or 0,
        active=True
    )
    db.add(variant)
    try:
        db.commit()
        # Record feature usage
        record_feature_usage(db, str(ctx.tenant_id), "variants", count=1)
        return {"variant_id": str(variant.variant_id), "sku": variant.sku}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Variant SKU conflict")


# =============================================================================
# STORE PRODUCT ENDPOINTS
# =============================================================================

@router.post("/store-products", status_code=201)
async def add_product_to_store(
    req: StoreProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("stores.manage")),
    policy=Depends(require_policy("store_product.create")),
):
    # Check entitlement limit
    check_feature_limit(db, str(ctx["tenant_id"]), "store_products", count=1)
    
    try:
        store_id = UUID(req.store_id)
        product_id = UUID(req.product_id)
    except ValueError:
        raise HTTPException(400, "Invalid store_id or product_id")

    store = db.query(Store).filter(
        Store.store_id == store_id,
        Store.tenant_id == ctx["tenant_id"]
    ).first()
    if not store:
        raise HTTPException(404, "Store not found")

    product = db.query(Product).filter(
        Product.product_id == product_id,
        Product.tenant_id == ctx["tenant_id"],
        Product.active == True
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    existing = db.query(StoreProduct).filter(
        StoreProduct.store_id == store_id,
        StoreProduct.product_id == product_id
    ).first()
    if existing:
        raise HTTPException(409, "Product already in store")

    sp = StoreProduct(
        id=uuid.uuid4(),
        store_id=store_id,
        tenant_id=ctx["tenant_id"],
        product_id=product_id,
        price_minor=req.price_minor or product.purchase_price_minor,
        currency=req.currency or "GBP",
        is_available=True,
        stock_quantity=req.stock_quantity or 0
    )
    db.add(sp)
    db.commit()
    
    # Record feature usage
    record_feature_usage(db, str(ctx["tenant_id"]), "store_products", count=1)

    return {
        "store_product_id": str(sp.id),
        "product_id": str(product_id),
        "store_id": str(store_id),
        "price_minor": sp.price_minor,
        "is_available": True
    }


@router.get("/store-products")
async def list_store_products_all(
    store_id: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("stores.manage"))
):
    """List store products for the caller's tenant, optionally filtering by store_id or product_id."""
    ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    q = db.query(StoreProduct).filter(StoreProduct.tenant_id == ctx_tenant)
    if store_id:
        try:
            q = q.filter(StoreProduct.store_id == UUID(store_id))
        except ValueError:
            raise HTTPException(400, "Invalid store_id")
    if product_id:
        try:
            q = q.filter(StoreProduct.product_id == UUID(product_id))
        except ValueError:
            raise HTTPException(400, "Invalid product_id")

    total = q.count()
    rows = q.order_by(StoreProduct.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "store_products": [
            {
                "store_product_id": str(sp.id),
                "store_id": str(sp.store_id),
                "product_id": str(sp.product_id),
                "price_minor": sp.price_minor,
                "currency": sp.currency,
                "is_available": sp.is_available,
                "stock_quantity": sp.stock_quantity,
            }
            for sp in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.get("/stores/{store_id}/products")
async def list_store_products(
    store_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("stores.products.view"))
):
    try:
        store_uuid = UUID(store_id)
    except ValueError:
        raise HTTPException(400, "Invalid store_id")

    store = db.query(Store).filter(
        Store.store_id == store_uuid,
        Store.tenant_id == ctx.tenant_id
    ).first()
    if not store:
        raise HTTPException(404, "Store not found")

    q = db.query(StoreProduct, Product, Variant).outerjoin(
        Product, StoreProduct.product_id == Product.product_id
    ).outerjoin(
        Variant, and_(Variant.product_id == Product.product_id, Variant.active == True)
    ).filter(
        StoreProduct.store_id == store_uuid,
        StoreProduct.tenant_id == ctx.tenant_id
    )

    total = q.count()
    results = q.offset(offset).limit(limit).all()

    products = []
    seen = set()
    for sp, p, v in results:
        key = str(p.product_id)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "product_id": str(p.product_id),
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand,
            "store_price_minor": sp.price_minor,
            "currency": sp.currency,
            "is_available": sp.is_available,
            "stock_quantity": sp.stock_quantity,
            "variants": []  # You can expand this later
        })

    return {
        "store_id": store_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": products
    }


# =============================================================================
# BULK UPLOAD ENDPOINT
# =============================================================================

@router.post("/products/bulk-upload", status_code=201)
async def bulk_upload_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(check_user_authorization("catalog.manage")),
    policy=Depends(require_policy("product.bulk_upload")),
):
    """
    Bulk upload products from an Excel file.
    The Excel file should have columns matching the products table fields.
    """
    tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id

    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "File must be an Excel file (.xlsx or .xls)")

    try:
        # Read file content
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
    except Exception as e:
        logger.error(f"Error reading Excel file: {e}")
        raise HTTPException(400, f"Failed to read Excel file: {str(e)}")

    # Normalize column names (lowercase and strip whitespace)
    df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

    # Required columns
    required_columns = ['sku', 'display_name', 'purchase_price_minor']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise HTTPException(400, f"Missing required columns: {', '.join(missing_columns)}")

    # Track results
    created_products = []
    errors = []

    for index, row in df.iterrows():
        row_num = index + 2  # Excel row number (1-indexed + header row)
        try:
            sku = str(row.get('sku', '')).strip()
            if not sku or pd.isna(row.get('sku')):
                errors.append({"row": row_num, "error": "SKU is required"})
                continue

            display_name = str(row.get('display_name', '')).strip()
            if not display_name or pd.isna(row.get('display_name')):
                errors.append({"row": row_num, "error": "display_name is required"})
                continue

            # Check for duplicate SKU within tenant
            existing = db.query(Product).filter(
                Product.tenant_id == tenant_id,
                Product.sku == sku,
                Product.active == True
            ).first()
            if existing:
                errors.append({"row": row_num, "error": f"SKU '{sku}' already exists"})
                continue

            # Parse optional fields with proper null handling
            def get_value(key, default=None):
                val = row.get(key)
                if pd.isna(val) or val == '' or val is None:
                    return default
                return val

            def get_uuid(key):
                val = get_value(key)
                if val:
                    try:
                        return UUID(str(val))
                    except ValueError:
                        return None
                return None

            def get_int(key, default=None):
                val = get_value(key)
                if val is not None:
                    try:
                        return int(float(val))
                    except (ValueError, TypeError):
                        return default
                return default

            def get_float(key, default=None):
                val = get_value(key)
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return default
                return default

            def get_bool(key, default=False):
                val = get_value(key)
                if val is not None:
                    if isinstance(val, bool):
                        return val
                    if isinstance(val, str):
                        return val.lower() in ('true', 'yes', '1', 't', 'y')
                    return bool(val)
                return default

            # Validate foreign key references if provided
            vendor_id = get_uuid('vendor_id')
            if vendor_id and not db.query(Vendor).filter(Vendor.vendor_id == vendor_id, Vendor.tenant_id == tenant_id).first():
                errors.append({"row": row_num, "error": f"Vendor ID not found: {vendor_id}"})
                continue

            category_id = get_uuid('category_id')
            if category_id and not db.query(Category).filter(Category.category_id == category_id, Category.tenant_id == tenant_id, Category.status != "deleted").first():
                errors.append({"row": row_num, "error": f"Category ID not found: {category_id}"})
                continue

            colour_id = get_uuid('colour_id')
            if colour_id and not db.query(Colour).filter(Colour.colour_id == colour_id).first():
                errors.append({"row": row_num, "error": f"Colour ID not found: {colour_id}"})
                continue

            size_id = get_uuid('size_id')
            if size_id and not db.query(Size).filter(Size.size_id == size_id).first():
                errors.append({"row": row_num, "error": f"Size ID not found: {size_id}"})
                continue

            fit_id = get_uuid('fit_id')
            if fit_id and not db.query(Fit).filter(Fit.fit_id == fit_id, Fit.status != "deleted").first():
                errors.append({"row": row_num, "error": f"Fit ID not found: {fit_id}"})
                continue

            # Create product object
            product = Product(
                product_id=uuid.uuid4(),
                tenant_id=tenant_id,
                external_id=get_value('external_id'),
                sku=sku,
                ean=get_value('ean'),
                mpn=get_value('mpn'),
                vendor_id=vendor_id,
                category_id=category_id,
                brand_id=get_uuid('brand_id'),
                manufacturer=get_value('manufacturer'),
                is_matrix_item=get_bool('is_matrix_item', False),
                matrix_type=get_value('matrix_type', 'standalone'),
                matrix_parent_id=get_uuid('matrix_parent_id'),
                colour_id=colour_id,
                size_id=size_id,
                fit_id=fit_id,
                item_option=get_value('item_option'),
                display_name=display_name,
                web_display_name=get_value('web_display_name'),
                sales_description=get_value('sales_description'),
                purchase_description=get_value('purchase_description'),
                packing_slip_description=get_value('packing_slip_description'),
                detailed_description=get_value('detailed_description'),
                additional_description=get_value('additional_description'),
                weight=get_float('weight'),
                weight_unit=get_value('weight_unit'),
                width=get_float('width'),
                depth=get_float('depth'),
                height=get_float('height'),
                outer_quantity=get_int('outer_quantity'),
                outer_label_id=get_int('outer_label_id'),
                inner_quantity=get_int('inner_quantity'),
                inner_label_id=get_int('inner_label_id'),
                reorder_multiple=get_int('reorder_multiple'),
                purchase_price_minor=get_int('purchase_price_minor', 0),
                currency=get_value('currency', 'GBP'),
                tax_rate=get_int('tax_rate', 0),
                manufacturer_country=get_value('manufacturer_country'),
                commodity_code=get_value('commodity_code'),
                product_type=get_value('product_type'),
                colour_filter=get_value('colour_filter'),
                size_filter=get_value('size_filter'),
                search_keywords=get_value('search_keywords'),
                is_dangerous_goods=get_bool('is_dangerous_goods', False),
                cas_number=get_value('cas_number'),
                un_number=get_value('un_number'),
                proper_shipping_name=get_value('proper_shipping_name'),
                transport_hazard_class=get_value('transport_hazard_class'),
                packing_group=get_value('packing_group'),
                adr_classification_code=get_value('adr_classification_code'),
                adr_tunnel_restriction_code=get_value('adr_tunnel_restriction_code'),
                adr_hazard_id_number=get_value('adr_hazard_id_number'),
                tax_code=get_value('tax_code'),
                restricted=get_bool('restricted', False),
                comments=get_value('comments'),
                active=True
            )

            db.add(product)

            append_outbox_event(
                db,
                tenant_id=uuid.UUID(str(tenant_id)),
                aggregate_type="product",
                aggregate_id=product.product_id,
                event_type="product.created",
                payload={
                    "product_id": str(product.product_id),
                    "sku": product.sku,
                    "display_name": product.display_name,
                    "tenant_id": str(tenant_id),
                },
            )

            created_products.append({
                "row": row_num,
                "product_id": str(product.product_id),
                "sku": product.sku,
                "display_name": product.display_name
            })

        except Exception as e:
            logger.error(f"Error processing row {row_num}: {e}")
            errors.append({"row": row_num, "error": str(e)})

    if created_products:
        try:
            db.commit()
            record_feature_usage(db, str(tenant_id), "products", count=len(created_products))
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Database error during bulk commit: {e}")
            raise HTTPException(500, f"Database error: {str(e)}")

    return {
        "message": f"Bulk upload completed. {len(created_products)} products created, {len(errors)} errors.",
        "total_rows": len(df),
        "created_count": len(created_products),
        "error_count": len(errors),
        "created_products": created_products,
        "errors": errors
    }
