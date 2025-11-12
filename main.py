"""
ZeroQue Provisioning Service - Simplified Production Version

A clean, powerful API for multi-tenant provisioning with PostgreSQL RLS.
"""

import os
from datetime import timedelta, timezone
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from prometheus_client import Counter, Histogram

from Models import *
from Schemas import *
from core.config import SETTINGS, SERVICE_NAME, SERVICE_VERSION
from core.db_config import get_db
from utils.redis_client import redis_client
from core.permission_check_helpers import require_permission, resolve_approvers_for_step

# FastAPI app
app = FastAPI(
    title="ZeroQue All in One API",
    version=SERVICE_VERSION,
    description="Simple Implementation"
)

# CORS - configure via environment
allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ==================================================================================
# CATALOG MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """Create a new product category"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_category", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify parent category if provided
        parent_category_uuid = None
        if req.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == uuid.UUID(req.parent_category_id)).first()
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
        raise HTTPException(status_code=400, detail="Invalid tenant ID or parent category ID format")
    except HTTPException:
        req_total.labels(operation="create_category", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Category code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        logger.error(f"❌ Category creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories")
async def list_categories(
    tenant_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """List categories"""
    try:
        q = db.query(Category)
        if tenant_id:
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


@app.post("/v1/catalog/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.manage",
            None
        )
    )
):
    """Create a new product"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_product", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify category if provided
        category_uuid = None
        if req.category_id:
            category = db.query(Category).filter(Category.category_id == uuid.UUID(req.category_id)).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            category_uuid = uuid.UUID(req.category_id)
        
        # Create product
        product = Product(
            product_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
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
            "category_id": str(product.category_id) if product.category_id else None,
            "sku": product.sku,
            "name": product.name,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "created_at": product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or category ID format")
    except HTTPException:
        req_total.labels(operation="create_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Product SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        logger.error(f"❌ Product creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products")
async def list_products(
    tenant_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """List products"""
    try:
        q = db.query(Product)
        if tenant_id:
            q = q.filter(Product.tenant_id == uuid.UUID(tenant_id))
        if category_id:
            q = q.filter(Product.category_id == uuid.UUID(category_id))
        if active is not None:
            q = q.filter(Product.active == active)
        
        total = q.count()
        products = q.order_by(Product.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "products": [
                {
                    "product_id": str(p.product_id),
                    "tenant_id": str(p.tenant_id),
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


@app.post("/v1/catalog/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.variants.manage",
            None
        )
    )
):
    """Create a new product variant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_variant", status="start").inc()
        
        # Verify product exists and get tenant_id
        product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Create variant
        variant = Variant(
            variant_id=uuid.uuid4(),
            product_id=uuid.UUID(req.product_id),
            tenant_id=product.tenant_id,
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
        raise HTTPException(status_code=400, detail="Variant SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        logger.error(f"❌ Variant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}")
async def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get a specific product by ID"""
    try:
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category details if exists
        category = None
        if product.category_id:
            category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/variants")
async def get_product_variants(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get all variants for a specific product"""
    try:
        # Verify product exists
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get variants
        variants = db.query(Variant).filter(
            Variant.product_id == uuid.UUID(product_id)
        ).order_by(Variant.created_at.desc()).all()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "product_sku": product.sku,
            "variants": [
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
            ],
            "total": len(variants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/category")
async def get_product_category(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get category for a specific product"""
    try:
        # Get product
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category
        if not product.category_id:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "category": None,
                "message": "No category assigned to this product"
            }
        
        category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "category": {
                "category_id": str(category.category_id),
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
                "active": category.active
            } if category else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants")
async def list_variants(
    product_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """List product variants"""
    try:
        q = db.query(Variant)
        if product_id:
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
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except Exception as e:
        logger.error(f"❌ List variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants/{variant_id}")
async def get_variant(
    variant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get a specific variant by ID"""
    try:
        variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(variant_id)).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")
        
        # Get product details
        product = db.query(Product).filter(Product.product_id == variant.product_id).first()
        
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


@app.get("/v1/catalog/categories/{category_id}")
async def get_category(
    category_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """Get a specific category by ID"""
    try:
        category = db.query(Category).filter(Category.category_id == uuid.UUID(category_id)).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Get parent category if exists
        parent = None
        if category.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == category.parent_category_id).first()
        
        # Get product count in this category
        product_count = db.query(Product).filter(Product.category_id == uuid.UUID(category_id)).count()
        
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


# ==================================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/subscriptions/plans", status_code=201)
async def create_subscription_plan(
    req: SubscriptionPlanRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Create a new subscription plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_plan", status="start").inc()
        
        # Check if plan code exists
        existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Plan code already exists")
        
        # Create plan
        plan = SubscriptionPlan(
            code=req.code,
            name=req.name,
            description=req.description,
            price_yearly_minor=req.price_yearly_minor,
            currency=req.currency,
            active=True
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        
        req_total.labels(operation="create_plan", status="success").inc()
        req_duration.labels(operation="create_plan").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription plan: {plan.id} ({plan.code})")
        
        return {
            "plan_id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "price_yearly_minor": plan.price_yearly_minor,
            "currency": plan.currency,
            "created_at": plan.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_plan", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        raise HTTPException(status_code=409, detail="Plan code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        logger.error(f"❌ Plan creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans")
async def list_subscription_plans(
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """List subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)
    
    total = q.count()
    plans = q.order_by(SubscriptionPlan.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "plans": [
            {
                "plan_id": p.id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "currency": p.currency,
                "active": p.active,
                "created_at": p.created_at.isoformat()
            }
            for p in plans
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/subscriptions/features", status_code=201)
async def create_feature(
    req: FeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """Create a new feature"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_feature", status="start").inc()
        
        # Check if feature code exists
        existing = db.query(Feature).filter(Feature.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Feature code already exists")
        
        # Create feature
        feature = Feature(
            id=uuid.uuid4(),
            code=req.code,
            name=req.name,
            description=req.description,
            category=req.category,
            active=True
        )
        db.add(feature)
        db.commit()
        db.refresh(feature)
        
        req_total.labels(operation="create_feature", status="success").inc()
        req_duration.labels(operation="create_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created feature: {feature.id} ({feature.code})")
        
        return {
            "feature_id": str(feature.id),
            "code": feature.code,
            "name": feature.name,
            "category": feature.category,
            "created_at": feature.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_feature", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        raise HTTPException(status_code=409, detail="Feature code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        logger.error(f"❌ Feature creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/features")
async def list_features(
    active: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """List features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)
    
    total = q.count()
    features = q.order_by(Feature.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "features": [
            {
                "feature_id": str(f.id),
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "active": f.active,
                "created_at": f.created_at.isoformat()
            }
            for f in features
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.put("/v1/subscriptions/plans/{plan_code}/features/{feature_code}", status_code=201)
async def add_feature_to_plan(
    plan_code: str,
    feature_code: str,
    req: PlanFeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Add a feature to a plan with optional limits"""
    start = datetime.now()
    try:
        req_total.labels(operation="add_plan_feature", status="start").inc()
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Check if association exists
        existing = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if existing:
            # Update existing
            existing.enabled = True
            existing.limits = req.limits or {}
            db.commit()
            action = "updated"
        else:
            # Create new
            plan_feature = PlanFeature(
                id=uuid.uuid4(),
                plan_code=plan_code,
                feature_code=feature_code,
                enabled=True,
                limits=req.limits or {}
            )
            db.add(plan_feature)
            db.commit()
            action = "added"
        
        req_total.labels(operation="add_plan_feature", status="success").inc()
        req_duration.labels(operation="add_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ {action.capitalize()} feature {feature_code} to plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "enabled": True,
            "limits": req.limits or {},
            "action": action
        }
    except HTTPException:
        req_total.labels(operation="add_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="add_plan_feature", status="error").inc()
        logger.error(f"❌ Add feature to plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans/{plan_code}/features")
async def get_plan_features(
    plan_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Get all features for a plan"""
    try:
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get plan features with feature details
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "plan_code": plan_code,
            "plan_name": plan.name,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "category": f.category,
                    "enabled": pf.enabled,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "total": len(features)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get plan features failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/subscriptions/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan(
    plan_code: str,
    feature_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Remove a feature from a plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_plan_feature", status="start").inc()
        
        # Find plan feature association
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if not plan_feature:
            raise HTTPException(status_code=404, detail="Feature not associated with plan")
        
        # Disable the feature
        plan_feature.enabled = False
        db.commit()
        
        req_total.labels(operation="remove_plan_feature", status="success").inc()
        req_duration.labels(operation="remove_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Removed feature {feature_code} from plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "removed": True
        }
    except HTTPException:
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        logger.error(f"❌ Remove feature from plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Create a subscription for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_subscription", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Check if subscription already exists
        existing = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Subscription already exists for tenant")
        
        # Calculate subscription periods
        now = datetime.now(timezone.utc)
        period_days = 365 if req.billing_cycle == "yearly" else 30
        
        # Create subscription
        subscription = TenantSubscription(
            tenant_id=uuid.UUID(req.tenant_id),
            plan_code=req.plan_code,
            payment_method=req.payment_method,
            status="active",
            external_id=f"sub_{req.tenant_id}_{int(now.timestamp())}",
            current_period_start=now,
            current_period_end=now + timedelta(days=period_days)
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        req_total.labels(operation="create_subscription", status="success").inc()
        req_duration.labels(operation="create_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription: {subscription.id} for tenant {req.tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_subscription", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        raise HTTPException(status_code=409, detail="Subscription already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        logger.error(f"❌ Subscription creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/subscriptions/{tenant_id}")
async def get_subscription(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Get subscription details for a tenant"""
    try:
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Get plan details
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.code == subscription.plan_code
        ).first()
        
        # Get plan features
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == subscription.plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "plan_name": plan.name if plan else None,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/renew")
async def renew_subscription(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Renew a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="renew_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Extend subscription by 1 year
        if subscription.current_period_end:
            subscription.current_period_end = subscription.current_period_end + timedelta(days=365)
        else:
            subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=365)
        
        subscription.status = "active"
        subscription.canceled_at = None
        subscription.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="renew_subscription", status="success").inc()
        req_duration.labels(operation="renew_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Renewed subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "new_period_end": subscription.current_period_end.isoformat(),
            "renewed": True
        }
    except HTTPException:
        req_total.labels(operation="renew_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="renew_subscription", status="error").inc()
        logger.error(f"❌ Renew subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/cancel")
async def cancel_subscription(
    tenant_id: str,
    cancel_at_period_end: bool = Query(True),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Cancel a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="cancel_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        now = datetime.now(timezone.utc)
        subscription.canceled_at = now
        
        if cancel_at_period_end:
            subscription.status = "canceling"  # Will be canceled at period end
        else:
            subscription.status = "canceled"
        
        subscription.updated_at = now
        db.commit()
        
        req_total.labels(operation="cancel_subscription", status="success").inc()
        req_duration.labels(operation="cancel_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Canceled subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "canceled_at": subscription.canceled_at.isoformat(),
            "canceled": True
        }
    except HTTPException:
        req_total.labels(operation="cancel_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="cancel_subscription", status="error").inc()
        logger.error(f"❌ Cancel subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# ENTITLEMENTS & USAGE TRACKING ENDPOINTS
# ==================================================================================

@app.post("/v1/entitlements/check")
async def check_entitlement(
    req: CheckEntitlementRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.check",
            None
        )
    )
):
    """Check if tenant has access to a feature"""
    try:
        # Get tenant subscription
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id),
            TenantSubscription.status == "active"
        ).first()
        
        if not subscription:
            return {
                "allowed": False,
                "reason": "No active subscription found",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code
            }
        
        # Check if feature is in plan
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == subscription.plan_code,
            PlanFeature.feature_code == req.feature_code,
            PlanFeature.enabled == True
        ).first()
        
        if not plan_feature:
            return {
                "allowed": False,
                "reason": "Feature not available in subscription plan",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "plan_code": subscription.plan_code
            }
        
        # Check usage limits (if any)
        limits = plan_feature.limits or {}
        rate_limit = limits.get("rate_limit")
        
        if rate_limit:
            # Get current period usage
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
                SubscriptionUsage.feature_code == req.feature_code,
                SubscriptionUsage.period_start >= month_start
            ).first()
            
            usage_count = usage.usage_count if usage else 0
            
            if usage_count >= rate_limit:
                return {
                    "allowed": False,
                    "reason": "Usage limit exceeded",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code,
                    "usage": usage_count,
                    "limit": rate_limit,
                    "remaining": 0
                }
            
            return {
                "allowed": True,
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "usage": usage_count,
                "limit": rate_limit,
                "remaining": rate_limit - usage_count
            }
        
        # No limits, access allowed
        return {
            "allowed": True,
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "limits": limits
        }
    except Exception as e:
        logger.error(f"❌ Check entitlement failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/record", status_code=201)
async def record_usage(
    req: RecordUsageRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.usage.record",
            None
        )
    )
):
    """Record feature usage for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="record_usage", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Calculate current period
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate month end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)
        
        # Find or create usage record
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
            SubscriptionUsage.feature_code == req.feature_code,
            SubscriptionUsage.usage_type == req.usage_type,
            SubscriptionUsage.period_start >= month_start,
            SubscriptionUsage.period_start < month_end
        ).first()
        
        if usage:
            # Update existing
            usage.usage_count += req.count
            usage.updated_at = now
        else:
            # Create new
            usage = SubscriptionUsage(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(req.tenant_id),
                feature_code=req.feature_code,
                usage_type=req.usage_type,
                usage_count=req.count,
                period_start=month_start,
                period_end=month_end
            )
            db.add(usage)
        
        db.commit()
        db.refresh(usage)
        
        req_total.labels(operation="record_usage", status="success").inc()
        req_duration.labels(operation="record_usage").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Recorded usage: {req.count} for feature {req.feature_code}, tenant {req.tenant_id}")
        
        return {
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "usage_type": req.usage_type,
            "count": req.count,
            "total_usage": usage.usage_count,
            "period_start": usage.period_start.isoformat(),
            "period_end": usage.period_end.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="record_usage", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="record_usage", status="error").inc()
        logger.error(f"❌ Record usage failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/entitlements/usage/{tenant_id}")
async def get_usage_summary(
    tenant_id: str,
    feature_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.usage.record",
            None
        )
    )
):
    """Get usage summary for a tenant"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Build query
        q = db.query(SubscriptionUsage).filter(SubscriptionUsage.tenant_id == uuid.UUID(tenant_id))
        if feature_code:
            q = q.filter(SubscriptionUsage.feature_code == feature_code)
        
        # Get current period usage
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_usage = q.filter(SubscriptionUsage.period_start >= month_start).all()
        
        return {
            "tenant_id": tenant_id,
            "current_period": {
                "start": month_start.isoformat(),
                "usage": [
                    {
                        "feature_code": u.feature_code,
                        "usage_type": u.usage_type,
                        "count": u.usage_count,
                        "period_start": u.period_start.isoformat(),
                        "period_end": u.period_end.isoformat()
                    }
                    for u in current_usage
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get usage summary failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# APPROVALS MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/approvals/chains", status_code=201)
async def create_approval_chain(
    req: ApprovalChainRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """Create a new approval chain"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_chain", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create approval chain
        chain = ApprovalChain(
            chain_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            description=req.description,
            chain_type=req.chain_type,
            is_active=req.is_active
        )
        db.add(chain)
        db.commit()
        db.refresh(chain)
        
        req_total.labels(operation="create_approval_chain", status="success").inc()
        req_duration.labels(operation="create_approval_chain").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain: {chain.chain_id} ({chain.name})")
        
        return {
            "chain_id": str(chain.chain_id),
            "tenant_id": str(chain.tenant_id),
            "name": chain.name,
            "description": chain.description,
            "chain_type": chain.chain_type,
            "is_active": chain.is_active,
            "created_at": chain.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_chain", status="error").inc()
        logger.error(f"❌ Approval chain creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains")
async def list_approval_chains(
    tenant_id: Optional[str] = Query(None),
    chain_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """List approval chains"""
    try:
        q = db.query(ApprovalChain)
        if tenant_id:
            q = q.filter(ApprovalChain.tenant_id == uuid.UUID(tenant_id))
        if chain_type:
            q = q.filter(ApprovalChain.chain_type == chain_type)
        if is_active is not None:
            q = q.filter(ApprovalChain.is_active == is_active)
        
        total = q.count()
        chains = q.order_by(ApprovalChain.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "chains": [
                {
                    "chain_id": str(c.chain_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "description": c.description,
                    "chain_type": c.chain_type,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat()
                }
                for c in chains
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List approval chains failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/chains/steps", status_code=201)
async def create_approval_chain_step(
    req: ApprovalChainStepRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """Create a new approval chain step"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_chain_step", status="start").inc()
        
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.approval_chain_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        # Create step
        step = ApprovalChainStep(
            id=uuid.uuid4(),
            approval_chain_id=uuid.UUID(req.approval_chain_id),
            step_number=req.step_number,
            approver_role=req.approver_role,
            approver_scope=req.approver_scope,
            escalation_after_hours=req.escalation_after_hours,
            is_required=req.is_required
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        
        req_total.labels(operation="create_chain_step", status="success").inc()
        req_duration.labels(operation="create_chain_step").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain step: {step.id}")
        
        return {
            "id": str(step.id),
            "approval_chain_id": str(step.approval_chain_id),
            "step_number": step.step_number,
            "approver_role": step.approver_role,
            "approver_scope": step.approver_scope,
            "escalation_after_hours": step.escalation_after_hours,
            "is_required": step.is_required,
            "created_at": step.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid approval chain ID format")
    except HTTPException:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_chain_step", status="error").inc()
        logger.error(f"❌ Chain step creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains/{chain_id}/steps")
async def list_chain_steps(
    chain_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """List steps for an approval chain"""
    try:
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "steps": [
                {
                    "id": str(s.id),
                    "step_number": s.step_number,
                    "approver_role": s.approver_role,
                    "approver_scope": s.approver_scope,
                    "escalation_after_hours": s.escalation_after_hours,
                    "is_required": s.is_required,
                    "created_at": s.created_at.isoformat()
                }
                for s in steps
            ],
            "total": len(steps)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chain ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List chain steps failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests", status_code=201)
async def create_approval_request(
    req: ApprovalRequestRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.create",
            None
        )
    )
):
    """Create a new approval request"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_request", status="start").inc()
        
        # Verify tenant, chain, and user exist
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(req.chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        user = db.query(User).filter(User.user_id == uuid.UUID(req.requested_by)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Requester user not found")
        
        # Generate request number
        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        
        # Create approval request
        approval_request = ApprovalRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            chain_id=uuid.UUID(req.chain_id),
            request_number=request_number,
            request_type=req.request_type,
            request_data=req.request_data,
            requested_by=uuid.UUID(req.requested_by),
            request_status="pending",
            current_step_number=1,
            total_amount_minor=req.total_amount_minor,
            currency=req.currency,
            due_date=req.due_date
        )
        db.add(approval_request)
        db.flush()  # Get the request_id
        
        # Get chain steps and create approver assignments
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(req.chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        for step in steps:
            approver_user_ids = resolve_approvers_for_step(
                db,
                step,
                req.tenant_id,
                req.request_data
            )
            if not approver_user_ids:
                logger.warning(
                    "No approvers resolved for step %s in chain %s; falling back to requester",
                    step.step_number,
                    req.chain_id
                )
                approver_user_ids = [req.requested_by]

            for approver_user_id in approver_user_ids:
                approver = ApprovalRequestApprover(
                    id=uuid.uuid4(),
                    request_id=approval_request.request_id,
                    approver_user_id=uuid.UUID(approver_user_id),
                    approver_role=step.approver_role,
                    step_number=step.step_number,
                    status="pending"
                )
                db.add(approver)
        
        db.commit()
        db.refresh(approval_request)
        
        req_total.labels(operation="create_approval_request", status="success").inc()
        req_duration.labels(operation="create_approval_request").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval request: {approval_request.request_id}")
        
        return {
            "request_id": str(approval_request.request_id),
            "request_number": approval_request.request_number,
            "tenant_id": str(approval_request.tenant_id),
            "chain_id": str(approval_request.chain_id),
            "request_type": approval_request.request_type,
            "requested_by": str(approval_request.requested_by),
            "request_status": approval_request.request_status,
            "total_amount_minor": approval_request.total_amount_minor,
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
            "created_at": approval_request.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_request", status="error").inc()
        logger.error(f"❌ Approval request creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests")
async def list_approval_requests(
    tenant_id: Optional[str] = Query(None),
    request_type: Optional[str] = Query(None),
    request_status: Optional[str] = Query(None),
    requested_by: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """List approval requests"""
    try:
        q = db.query(ApprovalRequest)
        if tenant_id:
            q = q.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if request_status:
            q = q.filter(ApprovalRequest.request_status == request_status)
        if requested_by:
            q = q.filter(ApprovalRequest.requested_by == uuid.UUID(requested_by))
        
        total = q.count()
        requests = q.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "requests": [
                {
                    "request_id": str(r.request_id),
                    "request_number": r.request_number,
                    "tenant_id": str(r.tenant_id),
                    "chain_id": str(r.chain_id),
                    "request_type": r.request_type,
                    "requested_by": str(r.requested_by),
                    "request_status": r.request_status,
                    "current_step_number": r.current_step_number,
                    "total_amount_minor": r.total_amount_minor,
                    "currency": r.currency,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "created_at": r.created_at.isoformat()
                }
                for r in requests
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List approval requests failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}")
async def get_approval_request(
    request_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """Get approval request details"""
    try:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers
        approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": str(request.request_id),
            "request_number": request.request_number,
            "tenant_id": str(request.tenant_id),
            "chain_id": str(request.chain_id),
            "request_type": request.request_type,
            "request_data": request.request_data,
            "requested_by": str(request.requested_by),
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "total_amount_minor": request.total_amount_minor,
            "currency": request.currency,
            "due_date": request.due_date.isoformat() if request.due_date else None,
            "completed_date": request.completed_date.isoformat() if request.completed_date else None,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None
                }
                for a in approvers
            ],
            "created_at": request.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}/approvers")
async def get_request_approvers(
    request_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """Get all approvers for an approval request"""
    try:
        # Verify request exists
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers with user details
        approvers = db.query(ApprovalRequestApprover, User).join(
            User, ApprovalRequestApprover.approver_user_id == User.user_id
        ).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": request_id,
            "request_number": request.request_number,
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_email": u.email,
                    "approver_name": u.display_name,
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None,
                    "escalation_sent": a.escalation_sent,
                    "created_at": a.created_at.isoformat()
                }
                for a, u in approvers
            ],
            "total": len(approvers)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get request approvers failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests/{request_id}/respond")
async def respond_to_approval_request(
    request_id: str,
    req: ApprovalResponseRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.respond",
            None
        )
    )
):
    """Respond to an approval request (approve or deny)"""
    start = datetime.now()
    try:
        req_total.labels(operation="respond_approval", status="start").inc()
        
        # Get the approval request
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        if str(approval_request.tenant_id) != ctx.tenant_id and "*" not in ctx.permissions:
            raise HTTPException(status_code=403, detail="Request outside of scope")
        
        if approval_request.request_status != "pending":
            raise HTTPException(status_code=400, detail=f"Request is not pending (status: {approval_request.request_status})")
        
        # Find the approver assignment
        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.step_number == approval_request.current_step_number,
            ApprovalRequestApprover.status == "pending"
        ).first()
        
        if not approver:
            raise HTTPException(status_code=404, detail="Approver assignment not found or already responded")

        if req.approver_user_id != ctx.user_id and req.approver_user_id not in ctx.manager_of:
            raise HTTPException(status_code=403, detail="Not authorized to respond for this approver")
        
        # Update approver response
        approver.status = "approved" if req.approved else "denied"
        approver.notes = req.notes
        approver.responded_at = datetime.now(timezone.utc)
        
        # Update request status
        if not req.approved:
            # Denial at any step fails the request
            approval_request.request_status = "denied"
            approval_request.completed_date = datetime.now(timezone.utc)
        else:
            # Check if there are more steps
            max_step = db.query(func.max(ApprovalChainStep.step_number)).filter(
                ApprovalChainStep.approval_chain_id == approval_request.chain_id
            ).scalar()
            
            if approval_request.current_step_number >= max_step:
                # Last step completed and approved
                approval_request.request_status = "approved"
                approval_request.completed_date = datetime.now(timezone.utc)
            else:
                # Move to next step
                approval_request.current_step_number += 1
        
        approval_request.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="respond_approval", status="success").inc()
        req_duration.labels(operation="respond_approval").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Approval request {request_id} {'approved' if req.approved else 'denied'} by {req.approver_user_id}")
        
        return {
            "request_id": request_id,
            "approver_user_id": req.approver_user_id,
            "status": approver.status,
            "notes": approver.notes,
            "responded_at": approver.responded_at.isoformat(),
            "request_status": approval_request.request_status,
            "current_step": approval_request.current_step_number,
            "completed": approval_request.request_status in ["approved", "denied"]
        }
    except ValueError:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="respond_approval", status="error").inc()
        logger.error(f"❌ Respond to approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# PRICING SERVICE - SIMPLE IMPLEMENTATION
# ==================================================================================

@app.post("/v1/pricing/pricebooks", status_code=201)
async def create_pricebook(
    req: PricebookRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a new pricebook for a store"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_pricebook", status="start").inc()
        
        # Verify store exists
        store = db.query(Store).filter(Store.store_id == uuid.UUID(req.store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # Create pricebook
        pricebook = Pricebook(
            pricebook_id=uuid.uuid4(),
            store_id=uuid.UUID(req.store_id),
            tenant_id=store.tenant_id,
            name=req.name,
            description=req.description,
            currency=req.currency,
            is_active=True
        )
        db.add(pricebook)
        db.commit()
        db.refresh(pricebook)
        
        req_total.labels(operation="create_pricebook", status="success").inc()
        req_duration.labels(operation="create_pricebook").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created pricebook: {pricebook.pricebook_id} ({pricebook.name})")
        
        return {
            "pricebook_id": str(pricebook.pricebook_id),
            "store_id": str(pricebook.store_id),
            "tenant_id": str(pricebook.tenant_id),
            "name": pricebook.name,
            "description": pricebook.description,
            "currency": pricebook.currency,
            "is_active": pricebook.is_active,
            "created_at": pricebook.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_pricebook", status="error").inc()
        logger.error(f"❌ Pricebook creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks")
async def list_pricebooks(
    store_id: Optional[str] = Query(None, description="Filter by store ID"),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List pricebooks with optional store filtering"""
    try:
        q = db.query(Pricebook).filter(Pricebook.is_active == True)
        if store_id:
            q = q.filter(Pricebook.store_id == uuid.UUID(store_id))
        
        total = q.count()
        pricebooks = q.order_by(Pricebook.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "pricebooks": [
                {
                    "pricebook_id": str(p.pricebook_id),
                    "store_id": str(p.store_id),
                    "tenant_id": str(p.tenant_id),
                    "name": p.name,
                    "description": p.description,
                    "currency": p.currency,
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat()
                }
                for p in pricebooks
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"❌ List pricebooks failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/pricebooks/{pricebook_id}/rules", status_code=201)
async def create_price_rule(
    pricebook_id: str,
    req: PriceRuleRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a price rule for a pricebook"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_price_rule", status="start").inc()
        
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        # Verify product if provided
        if req.product_id:
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
        
        # Verify variant if provided
        if req.variant_id:
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")
        
        # Create price rule
        rule = PriceRule(
            rule_id=uuid.uuid4(),
            pricebook_id=uuid.UUID(pricebook_id),
            product_id=uuid.UUID(req.product_id) if req.product_id else None,
            variant_id=uuid.UUID(req.variant_id) if req.variant_id else None,
            rule_type=req.rule_type,
            rule_value=req.rule_value,
            min_quantity=req.min_quantity,
            max_quantity=req.max_quantity,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            is_active=True
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        
        req_total.labels(operation="create_price_rule", status="success").inc()
        req_duration.labels(operation="create_price_rule").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created price rule: {rule.rule_id} for pricebook {pricebook_id}")
        
        return {
            "rule_id": str(rule.rule_id),
            "pricebook_id": str(rule.pricebook_id),
            "product_id": str(rule.product_id) if rule.product_id else None,
            "variant_id": str(rule.variant_id) if rule.variant_id else None,
            "rule_type": rule.rule_type,
            "rule_value": rule.rule_value,
            "min_quantity": rule.min_quantity,
            "max_quantity": rule.max_quantity,
            "valid_from": rule.valid_from.isoformat() if rule.valid_from else None,
            "valid_until": rule.valid_until.isoformat() if rule.valid_until else None,
            "is_active": rule.is_active,
            "created_at": rule.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_price_rule", status="error").inc()
        logger.error(f"❌ Price rule creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks/{pricebook_id}/rules")
async def list_price_rules(
    pricebook_id: str,
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List all price rules for a pricebook"""
    try:
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        q = db.query(PriceRule).filter(PriceRule.pricebook_id == uuid.UUID(pricebook_id))
        total = q.count()
        rules = q.order_by(PriceRule.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "pricebook_id": pricebook_id,
            "rules": [
                {
                    "rule_id": str(r.rule_id),
                    "product_id": str(r.product_id) if r.product_id else None,
                    "variant_id": str(r.variant_id) if r.variant_id else None,
                    "rule_type": r.rule_type,
                    "rule_value": r.rule_value,
                    "min_quantity": r.min_quantity,
                    "max_quantity": r.max_quantity,
                    "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                    "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                    "is_active": r.is_active,
                    "created_at": r.created_at.isoformat()
                }
                for r in rules
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pricebook ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List price rules failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/calculate")
async def calculate_price(
    req: PriceCalculationRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """Calculate price for a product based on pricebook rules"""
    start = datetime.now()
    try:
        req_total.labels(operation="calculate_price", status="start").inc()
        
        # Get base price from product or variant
        base_price_minor = 0
        currency = "GBP"
        product_name = ""
        
        if req.variant_id:
            # Get variant price
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")
            base_price_minor = variant.price_minor
            currency = variant.currency
            product_name = variant.name
        else:
            # Get product price
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            base_price_minor = product.base_price_minor
            currency = product.currency
            product_name = product.name
        
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(req.pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        # Get all active rules for this product in this pricebook
        now = datetime.now(timezone.utc)
        q = db.query(PriceRule).filter(
            PriceRule.pricebook_id == uuid.UUID(req.pricebook_id),
            PriceRule.is_active == True
        )
        
        # Filter by product or variant
        if req.variant_id:
            q = q.filter(
                (PriceRule.variant_id == uuid.UUID(req.variant_id)) |
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )
        else:
            q = q.filter(
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )
        
        # Filter by date validity
        q = q.filter(
            (PriceRule.valid_from == None) | (PriceRule.valid_from <= now)
        ).filter(
            (PriceRule.valid_until == None) | (PriceRule.valid_until >= now)
        )
        
        # Filter by quantity
        q = q.filter(
            (PriceRule.min_quantity == None) | (PriceRule.min_quantity <= req.quantity)
        ).filter(
            (PriceRule.max_quantity == None) | (PriceRule.max_quantity >= req.quantity)
        )
        
        # Order by specificity: variant-specific > product-specific > general
        rules = q.order_by(
            PriceRule.variant_id.desc().nullslast(),
            PriceRule.product_id.desc().nullslast(),
            PriceRule.created_at.desc()
        ).all()
        
        # Apply rules
        calculated_price_minor = base_price_minor
        applied_rules = []
        
        for rule in rules:
            old_price = calculated_price_minor
            
            if rule.rule_type == "fixed":
                # Fixed price overrides
                calculated_price_minor = rule.rule_value
            elif rule.rule_type == "percentage":
                # Percentage adjustment (rule_value in basis points, e.g., 1000 = 10%)
                adjustment = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor + adjustment
            elif rule.rule_type == "discount":
                # Discount (rule_value in basis points, e.g., 1000 = 10% off)
                discount = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor - discount
            
            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": rule.rule_value,
                "price_before": old_price,
                "price_after": calculated_price_minor
            })
        
        req_total.labels(operation="calculate_price", status="success").inc()
        req_duration.labels(operation="calculate_price").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Calculated price for product {req.product_id}: {base_price_minor} -> {calculated_price_minor}")
        
        return {
            "product_id": req.product_id,
            "variant_id": req.variant_id,
            "pricebook_id": req.pricebook_id,
            "quantity": req.quantity,
            "product_name": product_name,
            "base_price_minor": base_price_minor,
            "calculated_price_minor": calculated_price_minor,
            "currency": currency,
            "rules_applied_count": len(applied_rules),
            "applied_rules": applied_rules
        }
    except ValueError:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise
    except Exception as e:
        req_total.labels(operation="calculate_price", status="error").inc()
        logger.error(f"❌ Price calculation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"🚀 Starting {SERVICE_NAME} v{SERVICE_VERSION}")
    logger.info(f"📊 Database: {SETTINGS.DATABASE_URL.split('@')[1] if '@' in SETTINGS.DATABASE_URL else 'configured'}")
    logger.info(f"💾 Redis: {'enabled' if redis_client else 'disabled'}")
    logger.info(f"🔒 RLS: enabled for tenant isolation")
    
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.PORT)

