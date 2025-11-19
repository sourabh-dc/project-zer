import uuid
from datetime import datetime
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from starlette.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from Models import Tenant, Category, Product, Variant, StoreProduct, StoreVariant, Store, Vendor
from Schemas import UserContext, CategoryRequest, ProductRequest, VariantRequest, StoreProductRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

# ==================================================================================
# CATEGORY ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/categories", status_code=201)
async def create_category(
        req: CategoryRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
):
    """Create a new product category"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_category", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify parent category if provided
        parent_category_uuid = None
        if req.parent_category_id:
            parent = db.query(Category).filter(
                Category.category_id == uuid.UUID(req.parent_category_id),
                Category.tenant_id == ctx.tenant_id  # Security: ensure parent belongs to tenant
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent category not found")
            parent_category_uuid = uuid.UUID(req.parent_category_id)

        # Create category
        category = Category(
            category_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            code=req.code,
            description=req.description,
            parent_category_id=parent_category_uuid,
            active=True
        )
        db.add(category)
        db.commit()
        db.refresh(category)

        req_total.labels(operation="create_category", status="success").inc()
        req_duration.labels(operation="create_category").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created category: {category.category_id} ({category.name})")

        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "created_at": category.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_category", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=409, detail="Category code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        logger.error(f"❌ Category creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories")
async def list_categories(
        tenant_id: Optional[str] = Query(None),
        active: Optional[bool] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
):
    """List categories with tenant isolation"""
    try:
        q = db.query(Category).filter(Category.tenant_id == ctx.tenant_id)  # Security: tenant isolation
        
        if tenant_id:
            # Verify requested tenant matches user's tenant
            if str(ctx.tenant_id) != tenant_id:
                raise HTTPException(status_code=403, detail="Cannot access other tenant's categories")
            q = q.filter(Category.tenant_id == uuid.UUID(tenant_id))
        if active is not None:
            q = q.filter(Category.active == active)

        total = q.count()
        categories = q.order_by(Category.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "categories": [
                {
                    "category_id": str(c.category_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "code": c.code,
                    "description": c.description,
                    "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                    "active": c.active,
                    "created_at": c.created_at.isoformat()
                }
                for c in categories
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List categories failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories/{category_id}")
async def get_category(
        category_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
):
    """Get a specific category by ID"""
    try:
        category = db.query(Category).filter(
            Category.category_id == uuid.UUID(category_id),
            Category.tenant_id == ctx.tenant_id  # Security: tenant isolation
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # Get parent category if exists
        parent = None
        if category.parent_category_id:
            parent = db.query(Category).filter(
                Category.category_id == category.parent_category_id,
                Category.tenant_id == ctx.tenant_id
            ).first()

        # Get product count in this category
        product_count = db.query(Product).filter(
            Product.category_id == uuid.UUID(category_id),
            Product.tenant_id == ctx.tenant_id
        ).count()

        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "parent_category_name": parent.name if parent else None,
            "active": category.active,
            "product_count": product_count,
            "created_at": category.created_at.isoformat(),
            "updated_at": category.updated_at.isoformat() if category.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/catalog/categories/{category_id}")
async def update_category(
        category_id: str,
        name: Optional[str] = Query(None),
        active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
):
    """Update category (activate/deactivate or rename)"""
    try:
        category = db.query(Category).filter(
            Category.category_id == uuid.UUID(category_id),
            Category.tenant_id == ctx.tenant_id
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        if name:
            category.name = name
        if active is not None:
            category.active = active
        category.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(category)

        logger.info(f"✅ Updated category: {category.category_id}")

        return {
            "category_id": str(category.category_id),
            "name": category.name,
            "active": category.active,
            "updated_at": category.updated_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# PRODUCT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/products", status_code=201)
async def create_product(
        req: ProductRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a new product (vendor creates offering)"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_product", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify vendor exists (if provided)
        if req.vendor_id:
            vendor = db.query(Vendor).filter(
                Vendor.vendor_id == uuid.UUID(req.vendor_id),
                Vendor.tenant_id == ctx.tenant_id
            ).first()
            if not vendor:
                raise HTTPException(status_code=404, detail="Vendor not found")
            
            # SECURITY: Check if user is vendor owner
            if vendor.user_id:
                if str(vendor.user_id) != ctx.user_id:
                    # Check if user has vendor-specific permission
                    from core.permission_check_helpers import permissions_for_code
                    vendor_permissions = permissions_for_code(ctx, "catalog.products.vendor.create")
                    if not vendor_permissions:
                        raise HTTPException(
                            status_code=403,
                            detail="Only the vendor can create products for this vendor"
                        )
        
        # Verify category if provided
        category_uuid = None
        if req.category_id:
            category = db.query(Category).filter(
                Category.category_id == uuid.UUID(req.category_id),
                Category.tenant_id == ctx.tenant_id
            ).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            category_uuid = uuid.UUID(req.category_id)

        # Create product
        product = Product(
            product_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            vendor_id=uuid.UUID(req.vendor_id) if req.vendor_id else None,
            category_id=category_uuid,
            sku=req.sku,
            name=req.name,
            description=req.description,
            brand=req.brand,
            manufacturer=req.manufacturer,
            base_price_minor=req.base_price_minor,
            currency=req.currency,
            tax_rate=req.tax_rate,
            product_type=req.product_type,
            active=True,
            product_metadata=req.product_metadata
        )
        db.add(product)
        db.commit()
        db.refresh(product)

        req_total.labels(operation="create_product", status="success").inc()
        req_duration.labels(operation="create_product").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created product: {product.product_id} ({product.name})")

        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "vendor_id": str(product.vendor_id) if product.vendor_id else None,
            "category_id": str(product.category_id) if product.category_id else None,
            "sku": product.sku,
            "name": product.name,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "created_at": product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=409, detail="Product SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        logger.error(f"❌ Product creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products")
async def list_products(
        tenant_id: Optional[str] = Query(None),
        category_id: Optional[str] = Query(None),
        vendor_id: Optional[str] = Query(None),
        active: Optional[bool] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List products with tenant isolation"""
    try:
        q = db.query(Product).filter(Product.tenant_id == ctx.tenant_id)  # Security: tenant isolation
        
        if tenant_id:
            if str(ctx.tenant_id) != tenant_id:
                raise HTTPException(status_code=403, detail="Cannot access other tenant's products")
            q = q.filter(Product.tenant_id == uuid.UUID(tenant_id))
        if category_id:
            q = q.filter(Product.category_id == uuid.UUID(category_id))
        if vendor_id:
            q = q.filter(Product.vendor_id == uuid.UUID(vendor_id))
        if active is not None:
            q = q.filter(Product.active == active)

        total = q.count()
        products = q.order_by(Product.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "products": [
                {
                    "product_id": str(p.product_id),
                    "tenant_id": str(p.tenant_id),
                    "vendor_id": str(p.vendor_id) if p.vendor_id else None,
                    "category_id": str(p.category_id) if p.category_id else None,
                    "sku": p.sku,
                    "name": p.name,
                    "description": p.description,
                    "brand": p.brand,
                    "base_price_minor": p.base_price_minor,
                    "currency": p.currency,
                    "active": p.active,
                    "created_at": p.created_at.isoformat()
                }
                for p in products
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List products failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}")
async def get_product(
        product_id: str,
        include_variants: bool = Query(False),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """Get a specific product by ID with optional variants"""
    try:
        product = db.query(Product).filter(
            Product.product_id == uuid.UUID(product_id),
            Product.tenant_id == ctx.tenant_id  # Security: tenant isolation
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Get category details if exists
        category = None
        if product.category_id:
            category = db.query(Category).filter(
                Category.category_id == product.category_id,
                Category.tenant_id == ctx.tenant_id
            ).first()

        response = {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "vendor_id": str(product.vendor_id) if product.vendor_id else None,
            "category_id": str(product.category_id) if product.category_id else None,
            "category_name": category.name if category else None,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "tax_rate": product.tax_rate,
            "product_type": product.product_type,
            "active": product.active,
            "product_metadata": product.product_metadata,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat() if product.updated_at else None
        }

        # Include variants if requested
        if include_variants:
            variants = db.query(Variant).filter(
                Variant.product_id == uuid.UUID(product_id),
                Variant.tenant_id == ctx.tenant_id
            ).order_by(Variant.created_at.desc()).all()
            
            response["variants"] = [
                {
                    "variant_id": str(v.variant_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ]
            response["variant_count"] = len(variants)

        return response
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/catalog/products/{product_id}")
async def update_product(
        product_id: str,
        active: Optional[bool] = Query(None),
        base_price_minor: Optional[int] = Query(None, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Update product status or base price"""
    try:
        product = db.query(Product).filter(
            Product.product_id == uuid.UUID(product_id),
            Product.tenant_id == ctx.tenant_id
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        if active is not None:
            product.active = active
        if base_price_minor is not None:
            product.base_price_minor = base_price_minor
        
        product.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(product)

        logger.info(f"✅ Updated product: {product.product_id}")

        return {
            "product_id": str(product.product_id),
            "active": product.active,
            "base_price_minor": product.base_price_minor,
            "updated_at": product.updated_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# VARIANT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/variants", status_code=201)
async def create_variant(
        req: VariantRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.variants.manage"))
):
    """Create a new product variant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_variant", status="start").inc()

        # Verify product exists and belongs to tenant
        product = db.query(Product).filter(
            Product.product_id == uuid.UUID(req.product_id),
            Product.tenant_id == ctx.tenant_id
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        # Create variant
        variant = Variant(
            variant_id=uuid.uuid4(),
            product_id=uuid.UUID(req.product_id),
            tenant_id=ctx.tenant_id,
            sku=req.sku,
            name=req.name,
            attributes=req.attributes,
            price_minor=req.price_minor,
            currency=req.currency,
            stock_quantity=req.stock_quantity,
            low_stock_threshold=req.low_stock_threshold,
            active=True
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)

        req_total.labels(operation="create_variant", status="success").inc()
        req_duration.labels(operation="create_variant").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created variant: {variant.variant_id} ({variant.name})")

        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "created_at": variant.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        req_total.labels(operation="create_variant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=409, detail="Variant SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        logger.error(f"❌ Variant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants")
async def list_variants(
        product_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List variants with tenant isolation"""
    try:
        q = db.query(Variant).filter(Variant.tenant_id == ctx.tenant_id)  # Security: tenant isolation
        
        if product_id:
            # Verify product access
            product = db.query(Product).filter(
                Product.product_id == uuid.UUID(product_id),
                Product.tenant_id == ctx.tenant_id
            ).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found or access denied")
            q = q.filter(Variant.product_id == uuid.UUID(product_id))

        total = q.count()
        variants = q.order_by(Variant.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "product_id": str(v.product_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants/{variant_id}")
async def get_variant(
        variant_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """Get a specific variant by ID"""
    try:
        variant = db.query(Variant).filter(
            Variant.variant_id == uuid.UUID(variant_id),
            Variant.tenant_id == ctx.tenant_id  # Security: tenant isolation
        ).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        # Get product details
        product = db.query(Product).filter(
            Product.product_id == variant.product_id,
            Product.tenant_id == ctx.tenant_id
        ).first()

        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "product_name": product.name if product else None,
            "product_sku": product.sku if product else None,
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "low_stock_threshold": variant.low_stock_threshold,
            "active": variant.active,
            "created_at": variant.created_at.isoformat(),
            "updated_at": variant.updated_at.isoformat() if variant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid variant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get variant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/catalog/variants/{variant_id}")
async def update_variant(
        variant_id: str,
        active: Optional[bool] = Query(None),
        stock_quantity: Optional[int] = Query(None, ge=0),
        price_minor: Optional[int] = Query(None, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.variants.manage"))
):
    """Update variant status, stock, or price"""
    try:
        variant = db.query(Variant).filter(
            Variant.variant_id == uuid.UUID(variant_id),
            Variant.tenant_id == ctx.tenant_id
        ).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        if active is not None:
            variant.active = active
        if stock_quantity is not None:
            variant.stock_quantity = stock_quantity
        if price_minor is not None:
            variant.price_minor = price_minor
        
        variant.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(variant)

        logger.info(f"✅ Updated variant: {variant.variant_id}")

        return {
            "variant_id": str(variant.variant_id),
            "active": variant.active,
            "stock_quantity": variant.stock_quantity,
            "price_minor": variant.price_minor,
            "updated_at": variant.updated_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid variant ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update variant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# STORE PRODUCT SELECTION & PRICING ENDPOINTS
# ==================================================================================

@app.post("/v1/store-products", status_code=201)
async def add_product_to_store(
        req: StoreProductRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.products.manage"))
):
    """Allow a store to select a product and set store-specific price"""
    start = datetime.now()
    try:
        req_total.labels(operation="add_store_product", status="start").inc()

        # Verify store exists and belongs to user's tenant
        store = db.query(Store).filter(
            Store.store_id == uuid.UUID(req.store_id),
            Store.tenant_id == ctx.tenant_id
        ).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found or access denied")

        # Verify product exists and belongs to tenant
        product = db.query(Product).filter(
            Product.product_id == uuid.UUID(req.product_id),
            Product.tenant_id == ctx.tenant_id
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        # Check if already added to store
        existing = db.query(StoreProduct).filter(
            StoreProduct.store_id == uuid.UUID(req.store_id),
            StoreProduct.product_id == uuid.UUID(req.product_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Product already added to store")

        # Create store product assignment
        store_product = StoreProduct(
            id=uuid.uuid4(),
            store_id=uuid.UUID(req.store_id),
            tenant_id=ctx.tenant_id,
            product_id=uuid.UUID(req.product_id),
            price_minor=req.price_minor,
            currency=req.currency,
            is_available=req.is_available if hasattr(req, 'is_available') else True,
            stock_quantity=req.stock_quantity if hasattr(req, 'stock_quantity') else 0,
            low_stock_threshold=req.low_stock_threshold if hasattr(req, 'low_stock_threshold') else 10
        )
        db.add(store_product)
        db.commit()
        db.refresh(store_product)

        req_total.labels(operation="add_store_product", status="success").inc()
        req_duration.labels(operation="add_store_product").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Added product {req.product_id} to store {req.store_id}")

        return {
            "id": str(store_product.id),
            "store_id": str(store_product.store_id),
            "product_id": str(store_product.product_id),
            "price_minor": store_product.price_minor,
            "currency": store_product.currency,
            "is_available": store_product.is_available,
            "stock_quantity": store_product.stock_quantity,
            "created_at": store_product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="add_store_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="add_store_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="add_store_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid product or store reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="add_store_product", status="error").inc()
        logger.error(f"❌ Add product to store failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/stores/{store_id}/products")
async def list_store_products(
        store_id: str,
        available_only: bool = Query(False),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.products.view"))
):
    """List products available in a specific store with store-specific pricing"""
    try:
        # Verify store access
        store = db.query(Store).filter(
            Store.store_id == uuid.UUID(store_id),
            Store.tenant_id == ctx.tenant_id
        ).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found or access denied")

        q = db.query(StoreProduct, Product).join(
            Product, StoreProduct.product_id == Product.product_id
        ).filter(
            StoreProduct.store_id == uuid.UUID(store_id),
            StoreProduct.tenant_id == ctx.tenant_id
        )

        if available_only:
            q = q.filter(StoreProduct.is_available == True)

        total = q.count()
        results = q.order_by(StoreProduct.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "store_id": store_id,
            "store_name": store.name,
            "products": [
                {
                    "store_product_id": str(sp.id),
                    "product_id": str(p.product_id),
                    "sku": p.sku,
                    "name": p.name,
                    "description": p.description,
                    "brand": p.brand,
                    "store_price_minor": sp.price_minor,
                    "base_price_minor": p.base_price_minor,
                    "currency": sp.currency,
                    "is_available": sp.is_available,
                    "stock_quantity": sp.stock_quantity,
                    "low_stock_threshold": sp.low_stock_threshold,
                    "created_at": sp.created_at.isoformat()
                }
                for sp, p in results
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List store products failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/store-products/{store_product_id}")
async def update_store_product(
        store_product_id: str,
        price_minor: Optional[int] = Query(None, ge=0),
        is_available: Optional[bool] = Query(None),
        stock_quantity: Optional[int] = Query(None, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.products.manage"))
):
    """Update store-specific product pricing or availability"""
    try:
        store_product = db.query(StoreProduct).filter(
            StoreProduct.id == uuid.UUID(store_product_id),
            StoreProduct.tenant_id == ctx.tenant_id
        ).first()
        if not store_product:
            raise HTTPException(status_code=404, detail="Store product not found")

        if price_minor is not None:
            store_product.price_minor = price_minor
        if is_available is not None:
            store_product.is_available = is_available
        if stock_quantity is not None:
            store_product.stock_quantity = stock_quantity
        
        store_product.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(store_product)

        logger.info(f"✅ Updated store product: {store_product.id}")

        return {
            "store_product_id": str(store_product.id),
            "store_id": str(store_product.store_id),
            "product_id": str(store_product.product_id),
            "price_minor": store_product.price_minor,
            "is_available": store_product.is_available,
            "stock_quantity": store_product.stock_quantity,
            "updated_at": store_product.updated_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update store product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/store-products/{store_product_id}", status_code=204)
async def remove_product_from_store(
        store_product_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.products.manage"))
):
    """Remove a product from a store"""
    try:
        store_product = db.query(StoreProduct).filter(
            StoreProduct.id == uuid.UUID(store_product_id),
            StoreProduct.tenant_id == ctx.tenant_id
        ).first()
        if not store_product:
            raise HTTPException(status_code=404, detail="Store product not found")

        db.delete(store_product)
        db.commit()

        logger.info(f"✅ Removed product from store: {store_product.id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Remove store product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")