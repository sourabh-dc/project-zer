# services/subscriptions/main.py
from fastapi import FastAPI, Body, Query, HTTPException, Path, Request, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import logging, os, json, time, uuid
from datetime import datetime, timedelta
import stripe as stripe_sdk
from fastapi.responses import PlainTextResponse

# Try to import common models, fallback to local definitions
try:
    from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
    from zeroque_common.models.subscriptions import (
        SubscriptionPlan, Feature, PlanFeature, TenantSubscription, SiteBillingAccount
    )
    COMMON_MODELS_AVAILABLE = True
except ImportError:
    # Fallback local models for development
    from sqlalchemy import create_engine, Column, String, Integer, BigInteger, Boolean, ForeignKey, DateTime, func, Text, JSON
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    
    Base = declarative_base()
    
    class SubscriptionPlan(Base):
        __tablename__ = "subscription_plans"
        id = Column(Integer, primary_key=True, autoincrement=True)
        code = Column(String(50), unique=True, index=True)
        name = Column(String(100))
        description = Column(Text, nullable=True)
        price_yearly_minor = Column(BigInteger)
        currency = Column(String(3), default="GBP")
        active = Column(Boolean, default=True)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
        updated_at = Column(DateTime(timezone=True), nullable=True)
    
    class Feature(Base):
        __tablename__ = "features"
        id = Column(Integer, primary_key=True, autoincrement=True)
        code = Column(String(50), unique=True, index=True)
        name = Column(String(100))
        description = Column(Text, nullable=True)
        category = Column(String(50))
        active = Column(Boolean, default=True)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    class PlanFeature(Base):
        __tablename__ = "plan_features"
        id = Column(Integer, primary_key=True, autoincrement=True)
        plan_code = Column(String(50), ForeignKey("subscription_plans.code"))
        feature_code = Column(String(50), ForeignKey("features.code"))
        enabled = Column(Boolean, default=True)
        limits = Column(JSON)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    class TenantSubscription(Base):
        __tablename__ = "tenant_subscriptions"
        id = Column(Integer, primary_key=True, autoincrement=True)
        tenant_id = Column(String(100), unique=True, index=True)
        plan_code = Column(String(50), ForeignKey("subscription_plans.code"))
        payment_method = Column(String(20))
        status = Column(String(50), default="active")
        external_id = Column(String(100), index=True)
        current_period_start = Column(DateTime(timezone=True))
        current_period_end = Column(DateTime(timezone=True))
        trial_end = Column(DateTime(timezone=True))
        canceled_at = Column(DateTime(timezone=True))
        created_at = Column(DateTime(timezone=True), server_default=func.now())
        updated_at = Column(DateTime(timezone=True))
    
    class SiteBillingAccount(Base):
        __tablename__ = "site_billing_accounts"
        id = Column(Integer, primary_key=True, autoincrement=True)
        tenant_id = Column(String(100), index=True)
        site_id = Column(String(100), index=True)
        payment_method = Column(String(20))
        external_id = Column(String(100), index=True)
        active = Column(Boolean, default=True)
        account_metadata = Column(JSON)
        created_at = Column(DateTime(timezone=True), server_default=func.now())
        updated_at = Column(DateTime(timezone=True))
    
    def get_engine():
        return create_engine(os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5000/zeroque_dev"))
    
    def init_db():
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
    
    def check_db():
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    COMMON_MODELS_AVAILABLE = False

SERVICE_NAME = "subscriptions"
app = FastAPI(title="ZeroQue Tenant Subscriptions Service", version="2.0.0")

# Logging setup
log = logging.getLogger(SERVICE_NAME)
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    log.addHandler(handler)
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Custom Exceptions
class SubscriptionValidationError(Exception):
    """Raised when subscription validation fails"""
    pass

class SubscriptionNotFoundError(Exception):
    """Raised when subscription resource is not found"""
    pass

class SubscriptionDuplicateError(Exception):
    """Raised when duplicate subscription resource is created"""
    pass

class BillingAccountError(Exception):
    """Raised when billing account operations fail"""
    pass

class PaymentProcessingError(Exception):
    """Raised when payment processing fails"""
    pass

# Exception Handlers
@app.exception_handler(SubscriptionValidationError)
async def subscription_validation_exception_handler(request: Request, exc: SubscriptionValidationError):
    raise HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(SubscriptionNotFoundError)
async def subscription_not_found_exception_handler(request: Request, exc: SubscriptionNotFoundError):
    raise HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(SubscriptionDuplicateError)
async def subscription_duplicate_exception_handler(request: Request, exc: SubscriptionDuplicateError):
    raise HTTPException(status_code=409, detail=str(exc))

@app.exception_handler(BillingAccountError)
async def billing_account_exception_handler(request: Request, exc: BillingAccountError):
    raise HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(PaymentProcessingError)
async def payment_processing_exception_handler(request: Request, exc: PaymentProcessingError):
    raise HTTPException(status_code=500, detail=str(exc))

# Validation Helpers
def validate_uuid(uuid_string: str, field_name: str) -> str:
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_string)
        return uuid_string
    except ValueError:
        raise SubscriptionValidationError(f"Invalid {field_name} format: {uuid_string}")

def set_rls_context(db, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
        
        # Enable RLS for the session
        db.execute(text("SET row_security = on"))
        
    except Exception as e:
        log.warning(f"Failed to set RLS context: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set security context")

# Pydantic Models
class TenantSubscriptionV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    plan_code: str = Field(..., description="Subscription plan code")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: Optional[str] = Field(None, description="External subscription ID")
    current_period_start: Optional[datetime] = Field(None, description="Current period start")
    current_period_end: Optional[datetime] = Field(None, description="Current period end")
    trial_end: Optional[datetime] = Field(None, description="Trial end date")

class CreateBillingAccountV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    payment_method: str = Field(..., description="Payment method: stripe, trade")
    external_id: str = Field(..., description="External billing account ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

# Health Endpoints
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": "2.0.0", "enhanced": True}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    log.info("service_started")

# Subscription Plans Management
@app.get("/subscriptions/v2/plans")
def list_plans_v2(active: Optional[bool] = Query(None)):
    """
    List available subscription plans with pricing.
    """
    try:
        with SessionLocal() as db:
            query = db.query(SubscriptionPlan)
            
            if active is not None:
                query = query.filter(SubscriptionPlan.active == active)
            
            plans = query.order_by(SubscriptionPlan.price_yearly_minor).all()
            
            result = [{
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "price_yearly_minor": plan.price_yearly_minor,
                "currency": plan.currency,
                "active": plan.active
            } for plan in plans]
            
            log.info("plans_listed count=%d active=%s", len(result), active)
            return {"plans": result}
            
    except SQLAlchemyError as e:
        log.error(f"Database error in list_plans: {str(e)}")
        raise PaymentProcessingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in list_plans: {str(e)}")
        raise PaymentProcessingError(f"Internal error: {str(e)}")

@app.get("/subscriptions/v2/plans/{plan_code}/features")
def list_plan_features_v2(plan_code: str = Path(...)):
    """
    List features included in a specific plan.
    """
    try:
        with SessionLocal() as db:
            # Join PlanFeature with Feature to get feature details
            features = db.query(PlanFeature, Feature).join(
                Feature, PlanFeature.feature_code == Feature.code
            ).filter(
                PlanFeature.plan_code == plan_code,
                Feature.active == True
            ).order_by(Feature.category, Feature.name).all()
            
            result = [{
                "feature_code": plan_feature.feature_code,
                "name": feature.name,
                "description": feature.description,
                "category": feature.category,
                "enabled": plan_feature.enabled,
                "limits": plan_feature.limits
            } for plan_feature, feature in features]
            
            log.info("plan_features_listed plan=%s count=%d", plan_code, len(result))
            return {"plan_code": plan_code, "features": result}
            
    except SQLAlchemyError as e:
        log.error(f"Database error in list_plan_features: {str(e)}")
        raise PaymentProcessingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in list_plan_features: {str(e)}")
        raise PaymentProcessingError(f"Internal error: {str(e)}")

# Tenant Subscriptions Management
@app.post("/subscriptions/v2/subscriptions")
def create_subscription_v2(payload: TenantSubscriptionV2Payload = Body(...)):
    """
    Create a new tenant subscription.
    """
    try:
        # Validate inputs
        validate_uuid(payload.tenant_id, "tenant_id")
        
        with SessionLocal() as db:
            set_rls_context(db, payload.tenant_id)
            
            # Check if tenant already has an active subscription
            existing = db.query(TenantSubscription).filter(
                TenantSubscription.tenant_id == payload.tenant_id,
                TenantSubscription.status.in_(['active', 'trialing'])
            ).first()
            
            if existing:
                raise SubscriptionDuplicateError(f"Tenant already has an active subscription")
            
            # Create subscription
            subscription = TenantSubscription(
                tenant_id=payload.tenant_id,
                plan_code=payload.plan_code,
                payment_method=payload.payment_method,
                status='active',
                external_id=payload.external_id or f"sub_{payload.tenant_id}_{int(time.time())}",
                current_period_start=payload.current_period_start,
                current_period_end=payload.current_period_end,
                trial_end=payload.trial_end
            )
            db.add(subscription)
            db.commit()
            
            log.info("subscription_created tenant=%s plan=%s external_id=%s", 
                    payload.tenant_id, payload.plan_code, subscription.external_id)
            
            return {
                "subscription_id": subscription.id,
                "tenant_id": payload.tenant_id,
                "plan_code": payload.plan_code,
                "external_id": subscription.external_id,
                "status": "created"
            }
            
    except (SubscriptionValidationError, SubscriptionNotFoundError, SubscriptionDuplicateError) as e:
        raise e
    except SQLAlchemyError as e:
        log.error(f"Database error in create_subscription: {str(e)}")
        raise PaymentProcessingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in create_subscription: {str(e)}")
        raise PaymentProcessingError(f"Internal error: {str(e)}")

@app.get("/subscriptions/v2/subscriptions/{tenant_id}")
def get_subscription_v2(tenant_id: str = Path(...)):
    """
    Get tenant subscription details.
    """
    try:
        # Validate inputs
        validate_uuid(tenant_id, "tenant_id")
        
        with SessionLocal() as db:
            set_rls_context(db, tenant_id)
            
            # Get subscription
            subscription = db.query(TenantSubscription).filter(
                TenantSubscription.tenant_id == tenant_id
            ).first()
            
            if not subscription:
                raise SubscriptionNotFoundError(f"No subscription found for tenant {tenant_id}")
            
            # Get plan details separately
            plan = db.query(SubscriptionPlan).filter(
                SubscriptionPlan.code == subscription.plan_code
            ).first()
            
            return {
                "subscription_id": subscription.id,
                "tenant_id": tenant_id,
                "plan_code": subscription.plan_code,
                "plan_name": plan.name if plan else None,
                "plan_description": plan.description if plan else None,
                "payment_method": subscription.payment_method,
                "status": subscription.status,
                "external_id": subscription.external_id,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "trial_end": subscription.trial_end,
                "created_at": subscription.created_at
            }
            
    except (SubscriptionValidationError, SubscriptionNotFoundError) as e:
        raise e
    except SQLAlchemyError as e:
        log.error(f"Database error in get_subscription: {str(e)}")
        raise PaymentProcessingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in get_subscription: {str(e)}")
        raise PaymentProcessingError(f"Internal error: {str(e)}")

# Legacy endpoints for backward compatibility (deprecated)
@app.post("/subscriptions/sites/{tenant_id}/{site_id}/subscribe")
def subscribe_site_legacy(
    tenant_id: str = Path(...), 
    site_id: str = Path(...), 
    payload: dict = Body(...)
):
    """
    Legacy endpoint for site subscriptions (deprecated - use tenant-level endpoints).
    """
    raise HTTPException(
        status_code=410, 
        detail="Site-level subscriptions are deprecated. Please use tenant-level subscription endpoints."
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8212)
