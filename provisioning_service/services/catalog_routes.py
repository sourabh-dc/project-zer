import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from uuid import UUID

from provisioning_service.Models import (
    Tenant, Category, Product, Variant, StoreProduct, Store, Vendor
)
from provisioning_service.Schemas import (
    CategoryRequest, ProductRequest, VariantRequest, StoreProductRequest,
    UserContext
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.helpers.aifi_services import cv_create_product
from provisioning_service.core.permission_check_helpers import require_permission
from provisioning_service.core.entitlement_helpers import check_feature_limit, record_feature_usage
from provisioning_service.utils.logger import logger


router = APIRouter(prefix="/catalog", tags=["Catalog"])

# =============================================================================
# CATEGORY ENDPOINTS
# =============================================================================

@router.post("/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
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
        Category.tenant_id == ctx.tenant_id,
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
        tenant_id=ctx.tenant_id,
        name=req.name.strip(),
        code=req.code.strip(),
        description=req.description,
        parent_category_id=parent_id,
        active=True
    )
    db.add(category)
    try:
        db.commit()
        db.refresh(category)
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "categories", count=1)
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
    ctx: UserContext = Depends(require_permission("catalog.categories.view"))
):
    q = db.query(Category).filter(
        Category.tenant_id == ctx.tenant_id,
        Category.active == True
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
                    Category.active == True
                ).count() > 0
            }
            for c in items
        ]
    }


# =============================================================================
# PRODUCT ENDPOINTS
# =============================================================================

@router.post("/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Tenant mismatch")
    
    # Check entitlement limit
    check_feature_limit(db, req.tenant_id, "products", count=1)

    # SKU must be unique per tenant
    if db.query(Product).filter(
        Product.tenant_id == ctx.tenant_id,
        Product.sku == req.sku,
        Product.active == True
    ).first():
        raise HTTPException(409, "SKU already exists in your catalog")

    category_id = None
    if req.category_id:
        try:
            category_id = UUID(req.category_id)
        except ValueError:
            raise HTTPException(400, "Invalid category_id")
        if not db.query(Category).filter(
            Category.category_id == category_id,
            Category.tenant_id == ctx.tenant_id,
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
            Vendor.tenant_id == ctx.tenant_id
        ).first():
            raise HTTPException(404, "Vendor not found")

    product = Product(
        product_id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        vendor_id=vendor_id,
        category_id=category_id,
        sku=req.sku.strip(),
        barcode=req.barcode.strip(),
        name=req.name.strip(),
        description=req.description,
        brand=req.brand,
        base_price_minor=req.base_price_minor,
        currency=req.currency or "GBP",
        tax_rate=req.tax_rate or 0.0,
        weight=req.weight or 0.0,
        product_type=req.product_type or "physical",
        product_metadata=req.product_metadata or {},
        active=True
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
        try:
            aifi_product = await cv_create_product({
                "externalId": product.product_id,
                "name": product.name,
                "barcode": product.barcode,
                "price": product.base_price_minor,
                "weight": str(product.weight),
                "thumbnail": ""
            })
            product.aifi_product_id = aifi_product.get("id")
            db.commit()
        except Exception as e:
            logger.warning(f"❌ AiFi product sync failed, continuing: {e}")
            db.rollback()
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "products", count=1)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "SKU or data conflict")

    return {
        "product_id": str(product.product_id),
        "sku": product.sku,
        "name": product.name,
        "base_price_minor": product.base_price_minor,
        "active": True
    }


@router.get("/products")
async def list_products(
    category_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    q = db.query(Product).filter(
        Product.tenant_id == ctx.tenant_id,
        Product.active == True
    )

    if category_id:
        q = q.filter(Product.category_id == UUID(category_id))
    if vendor_id:
        q = q.filter(Product.vendor_id == UUID(vendor_id))
    if active is not None:
        q = q.filter(Product.active == active)
    if search:
        q = q.filter(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
                Product.brand.ilike(f"%{search}%")
            )
        )

    total = q.count()
    items = q.order_by(Product.name).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [
            {
                "product_id": str(p.product_id),
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "base_price_minor": p.base_price_minor,
                "currency": p.currency,
                "category_id": str(p.category_id) if p.category_id else None,
                "active": p.active
            }
            for p in items
        ]
    }


# =============================================================================
# VARIANT ENDPOINTS
# =============================================================================

@router.post("/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.variants.manage"))
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
        price_minor=req.price_minor or product.base_price_minor,
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

@router.post("/v1/store-products", status_code=201)
async def add_product_to_store(
    req: StoreProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.products.manage"))
):
    # Check entitlement limit
    check_feature_limit(db, str(ctx.tenant_id), "store_products", count=1)
    
    try:
        store_id = UUID(req.store_id)
        product_id = UUID(req.product_id)
    except ValueError:
        raise HTTPException(400, "Invalid store_id or product_id")

    store = db.query(Store).filter(
        Store.store_id == store_id,
        Store.tenant_id == ctx.tenant_id
    ).first()
    if not store:
        raise HTTPException(404, "Store not found")

    product = db.query(Product).filter(
        Product.product_id == product_id,
        Product.tenant_id == ctx.tenant_id,
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
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        price_minor=req.price_minor or product.base_price_minor,
        currency=req.currency or "GBP",
        is_available=True,
        stock_quantity=req.stock_quantity or 0
    )
    db.add(sp)
    db.commit()
    
    # Record feature usage
    record_feature_usage(db, str(ctx.tenant_id), "store_products", count=1)

    return {
        "store_product_id": str(sp.id),
        "product_id": str(product_id),
        "store_id": str(store_id),
        "price_minor": sp.price_minor,
        "is_available": True
    }


@router.get("/v1/store-products")
async def list_store_products_all(
    store_id: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.products.view"))
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

@router.get("/v1/stores/{store_id}/products")
async def list_store_products(
    store_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.products.view"))
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