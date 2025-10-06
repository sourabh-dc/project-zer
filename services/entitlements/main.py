# services/entitlements/main.py
from fastapi import FastAPI, Body, Query, HTTPException, Path, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text, Column, String, Boolean, DateTime, Integer, BigInteger, JSON, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import logging, os, json, uuid
from datetime import datetime, timedelta
# Import common modules (fallback to basic implementations)
try:
    from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
    from zeroque_common.observability import add_observability_middleware, add_api_call_meter, add_idempotency_middleware
    from zeroque_common.health import HealthMonitor
    from zeroque_common.circuit_breaker import CircuitBreakerManager
    from zeroque_common.events import EventStreamManager
    from zeroque_common.metrics import metrics
except ImportError:
    # Fallback implementations
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os
    
    def get_engine():
        return create_engine(os.getenv("DATABASE_URL", "postgresql://zeroque:password@localhost:5432/zeroque_dev"))
    
    def init_db():
        pass
    
    def check_db():
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except:
            return False
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    
    def add_observability_middleware(app, service_name):
        pass
    
    def add_api_call_meter(app):
        pass
    
    def add_idempotency_middleware(app, routes=None):
        pass
    
    class HealthMonitor:
        def __init__(self, service_name):
            self.service_name = service_name
        
        async def check_system_health(self):
            return {"status": "ok", "service": self.service_name}
    
    class CircuitBreakerManager:
        pass
    
    class EventStreamManager:
        def emit_event(self, service_name, event_type, data):
            log.info(f"Event: {event_type} from {service_name}")
    
    class metrics:
        @staticmethod
        def counter(name):
            return type('Counter', (), {'inc': lambda: None})()
        
        @staticmethod
        def histogram(name):
            return type('Histogram', (), {'observe': lambda x: None})()
import redis
import hashlib
from celery import Celery

SERVICE_NAME = "entitlements"
app = FastAPI(title="ZeroQue Entitlements Service V2", version="2.0.0")

# ---------- logging ----------
log = logging.getLogger(SERVICE_NAME)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    log.addHandler(h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Redis connection
redis_url = os.getenv("REDIS_URL", "redis://localhost:4000/0")
redis_client = redis.from_url(redis_url, decode_responses=True)

# Celery configuration
celery_app = Celery(
    SERVICE_NAME,
    broker=os.getenv("REDIS_URL", "redis://localhost:4000/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:4000/0")
)

# Observability
add_observability_middleware(app, SERVICE_NAME)
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/entitlements/v2/subscriptions"),
    ("PUT", "/entitlements/v2/subscriptions"),
    ("POST", "/entitlements/v2/usage/record"),
])

# Health monitoring
health_monitor = HealthMonitor(SERVICE_NAME)
circuit_breaker_manager = CircuitBreakerManager()
event_stream_manager = EventStreamManager()

Base = declarative_base()

# V2 SQLAlchemy Models for Entitlements System
class SubscriptionV2(Base):
    __tablename__ = "subscriptions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # stripe, trade_account
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

class SubscriptionPlanV2(Base):
    __tablename__ = "plans"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)

class SubscriptionFeatureV2(Base):
    __tablename__ = "features"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SubscriptionPlanFeatureV2(Base):
    __tablename__ = "plan_features"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    feature_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    limits: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SubscriptionUsageV2(Base):
    __tablename__ = "subscription_usage"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    feature_code: Mapped[str] = mapped_column(String, nullable=False, index=True)
    usage_type: Mapped[str] = mapped_column(String, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class EntitlementV2(Base):
    __tablename__ = "entitlements"
    
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    feature: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class FeatureFlagV2(Base):
    __tablename__ = "feature_flags"
    
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    variant: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UsageMeterV2(Base):
    __tablename__ = "usage_meters"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)

class UsageEventV2(Base):
    __tablename__ = "usage_events"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    site_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    meter_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UsageAggregateDailyV2(Base):
    __tablename__ = "usage_aggregates_daily"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    site_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    meter_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)

# Celery Tasks
@celery_app.task(bind=True)
def process_subscription_activation(self, tenant_id: str, plan_code: str, external_id: str):
    """Process subscription activation asynchronously"""
    try:
        with SessionLocal() as db:
            # Update subscription status
            db.execute(text("""
                UPDATE subscriptions 
                SET status = 'active', updated_at = NOW()
                WHERE tenant_id = :tenant_id AND external_id = :external_id
            """), {"tenant_id": tenant_id, "external_id": external_id})
            db.commit()
            
            # Emit event
            event_stream_manager.emit_event(
                service_name=SERVICE_NAME,
                event_type="subscription.activated",
                data={
                    "tenant_id": tenant_id,
                    "plan_code": plan_code,
                    "external_id": external_id
                }
            )
            
            log.info("subscription_activated", extra={"tenant_id": tenant_id, "plan_code": plan_code})
            return {"status": "success", "tenant_id": tenant_id}
            
    except Exception as e:
        log.error(f"subscription_activation_failed: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)

@celery_app.task(bind=True)
def process_usage_aggregation(self, tenant_id: str, feature_code: str, period_start: datetime):
    """Process usage aggregation for billing"""
    try:
        with SessionLocal() as db:
            # Aggregate usage from subscription_usage
            result = db.execute(text("""
                SELECT COALESCE(SUM(usage_count), 0) as total_usage
                FROM subscription_usage
                WHERE tenant_id = :tenant_id 
                AND feature_code = :feature_code
                AND period_start = :period_start
            """), {
                "tenant_id": tenant_id,
                "feature_code": feature_code,
                "period_start": period_start
            }).scalar()
            
            # Update aggregated usage
            db.execute(text("""
                INSERT INTO usage_aggregates_daily (tenant_id, meter_code, usage_count, period_date)
                VALUES (:tenant_id, :meter_code, :usage_count, :period_date)
                ON CONFLICT (tenant_id, meter_code, period_date)
                DO UPDATE SET usage_count = :usage_count, updated_at = NOW()
            """), {
                "tenant_id": tenant_id,
                "meter_code": feature_code,
                "usage_count": result,
                "period_date": period_start.date()
            })
            db.commit()
            
            log.info("usage_aggregated", extra={"tenant_id": tenant_id, "feature_code": feature_code})
            return {"status": "success", "usage_count": result}
            
    except Exception as e:
        log.error(f"usage_aggregation_failed: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)

@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    log.info("service_started")

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": "2.0.0", "enhanced": True}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# V2 API Endpoints

# Pydantic Models for API
class SubscriptionV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    plan_code: str = Field(..., description="Subscription plan code")
    provider: str = Field(..., description="Payment provider: stripe, trade_account")
    external_id: str = Field(..., description="External subscription ID")
    current_period_start: Optional[datetime] = Field(None, description="Current period start")
    current_period_end: Optional[datetime] = Field(None, description="Current period end")
    trial_end: Optional[datetime] = Field(None, description="Trial end date")

class CheckEntitlementV2Request(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    feature_code: str = Field(..., min_length=1)
    usage_type: Optional[str] = None  # e.g., "api_calls", "storage_gb"

class RecordUsageV2Request(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    feature_code: str = Field(..., min_length=1)
    usage_type: str = Field(..., min_length=1)
    usage_count: int = Field(..., ge=0)

class SubscriptionPlanV2Payload(BaseModel):
    code: str = Field(..., description="Plan code")
    name: str = Field(..., description="Plan name")
    description: Optional[str] = Field(None, description="Plan description")
    price_yearly_minor: int = Field(..., ge=0, description="Yearly price in minor units")
    currency: str = Field("GBP", description="Currency code")

class SubscriptionFeatureV2Payload(BaseModel):
    code: str = Field(..., description="Feature code")
    name: str = Field(..., description="Feature name")
    description: Optional[str] = Field(None, description="Feature description")
    category: Optional[str] = Field(None, description="Feature category")

class SubscriptionPlanFeatureV2Payload(BaseModel):
    plan_code: str = Field(..., description="Plan code")
    feature_code: str = Field(..., description="Feature code")
    enabled: bool = Field(True, description="Feature enabled")
    limits: Optional[dict] = Field(None, description="Feature limits")

class FeatureFlagV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    key: str = Field(..., description="Feature flag key")
    enabled: bool = Field(False, description="Feature flag enabled")
    variant: Optional[str] = Field(None, description="Feature flag variant")

class UsageEventV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    site_id: Optional[str] = Field(None, description="Site ID")
    store_id: Optional[str] = Field(None, description="Store ID")
    meter_code: str = Field(..., description="Usage meter code")
    subject_id: Optional[str] = Field(None, description="Subject ID")
    value: int = Field(..., ge=0, description="Usage value")

class EntitlementV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    site_id: str = Field(..., description="Site ID")
    feature: str = Field(..., description="Feature name")
    enabled: bool = Field(True, description="Feature enabled")

# ---------- V2 Entitlements ----------
def _get_cache_key_v2(tenant_id: str, feature_code: str) -> str:
    """Generate cache key for tenant-level entitlements"""
    key_data = f"{tenant_id}:{feature_code}"
    return f"entitlement_v2:{hashlib.md5(key_data.encode()).hexdigest()}"

def _get_usage_cache_key_v2(tenant_id: str, feature_code: str, usage_type: str, period: str) -> str:
    """Generate cache key for usage tracking"""
    key_data = f"{tenant_id}:{feature_code}:{usage_type}:{period}"
    return f"usage_v2:{hashlib.md5(key_data.encode()).hexdigest()}"

@app.get("/entitlements/v2/check")
def check_entitlement_v2(
    tenant_id: str = Query(...),
    feature_code: str = Query(...),
    usage_type: Optional[str] = Query(None)
):
    """
    Check if a tenant has entitlement to a feature, with optional usage limit checking.
    """
    cache_key = _get_cache_key_v2(tenant_id, feature_code)
    
    # Try Redis cache first
    try:
        cached = redis_client.get(cache_key)
        if cached:
            entitlement_data = json.loads(cached)
            log.info("entitlement_cache_hit tenant=%s feature=%s", tenant_id, feature_code)
            
            # Check usage limits if requested
            if usage_type and entitlement_data.get("limits"):
                limits = entitlement_data["limits"]
                if usage_type in limits:
                    period = datetime.utcnow().strftime("%Y-%m")
                    usage_key = _get_usage_cache_key_v2(tenant_id, feature_code, usage_type, period)
                    current_usage = int(redis_client.get(usage_key) or 0)
                    limit_value = limits[usage_type]
                    
                    if current_usage >= limit_value:
                        return {
                            "entitled": False,
                            "reason": f"Usage limit exceeded: {current_usage}/{limit_value}",
                            "feature_code": feature_code,
                            "current_usage": current_usage,
                            "limit": limit_value,
                            "cached": True
                        }
            
            return {
                "entitled": entitlement_data["enabled"],
                "feature_code": feature_code,
                "limits": entitlement_data.get("limits"),
                "cached": True
            }
    except Exception as e:
        log.warning("entitlement_cache_error: %s", str(e))
    
    # Cache miss - query database
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT pf.enabled, pf.limits, s.status, s.plan_code
              FROM subscriptions s
              JOIN plan_features pf ON s.plan_code = pf.plan_code
              JOIN features f ON pf.feature_code = f.code
             WHERE s.tenant_id = :tid 
               AND pf.feature_code = :feature AND f.active = TRUE
               AND s.status IN ('active', 'trialing')
        """), {"tid": tenant_id, "feature": feature_code}).first()
        
        if not row:
            # No active subscription or feature not found
            entitlement_data = {"enabled": False, "limits": None}
        else:
            enabled, limits, status, plan_code = row
            entitlement_data = {
                "enabled": bool(enabled),
                "limits": limits,
                "status": status,
                "plan_code": plan_code
            }
        
        # Cache the result for 5 minutes
        try:
            redis_client.setex(cache_key, 300, json.dumps(entitlement_data))
        except Exception as e:
            log.warning("entitlement_cache_set_error: %s", str(e))
        
        # Check usage limits if requested
        if usage_type and entitlement_data.get("limits"):
            limits = entitlement_data["limits"]
            if usage_type in limits:
                period = datetime.utcnow().strftime("%Y-%m")
                usage_key = _get_usage_cache_key_v2(tenant_id, feature_code, usage_type, period)
                current_usage = int(redis_client.get(usage_key) or 0)
                limit_value = limits[usage_type]
                
                if current_usage >= limit_value:
                    return {
                        "entitled": False,
                        "reason": f"Usage limit exceeded: {current_usage}/{limit_value}",
                        "feature_code": feature_code,
                        "current_usage": current_usage,
                        "limit": limit_value,
                        "cached": False
                    }
        
        log.info("entitlement_checked tenant=%s feature=%s enabled=%s", 
                tenant_id, feature_code, entitlement_data["enabled"])
        
        return {
            "entitled": entitlement_data["enabled"],
            "feature_code": feature_code,
            "limits": entitlement_data.get("limits"),
            "status": entitlement_data.get("status"),
            "plan_code": entitlement_data.get("plan_code"),
            "cached": False
        }

@app.post("/entitlements/v2/usage/record")
def record_usage_v2(payload: RecordUsageV2Request = Body(...)):
    """
    Record usage for a feature (for limit tracking).
    """
    with SessionLocal() as db:
        # Record usage in database (using site_id as tenant_id for tenant-level tracking)
        period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        db.execute(text("""
            INSERT INTO subscription_usage(tenant_id, site_id, feature_code, usage_type, usage_count, period_start, period_end)
            VALUES(:tid, :tid, :feature, :type, :count, :start, :end)
            ON CONFLICT (tenant_id, site_id, feature_code, usage_type, period_start)
            DO UPDATE SET usage_count = subscription_usage.usage_count + :count,
                        updated_at = NOW()
        """), {
            "tid": payload.tenant_id,
            "feature": payload.feature_code,
            "type": payload.usage_type,
            "count": payload.usage_count,
            "start": period_start,
            "end": period_end
        })
        db.commit()
        
        # Update Redis cache
        period = datetime.utcnow().strftime("%Y-%m")
        usage_key = _get_usage_cache_key_v2(payload.tenant_id, payload.feature_code, payload.usage_type, period)
        
        try:
            current_usage = redis_client.incrby(usage_key, payload.usage_count)
            # Set expiration to end of month
            end_of_month = datetime.utcnow().replace(day=1, month=datetime.utcnow().month + 1) - timedelta(days=1)
            redis_client.expireat(usage_key, end_of_month)
        except Exception as e:
            log.warning("usage_cache_update_error: %s", str(e))
            current_usage = payload.usage_count
        
        # Trigger async aggregation
        process_usage_aggregation.delay(payload.tenant_id, payload.feature_code, period_start)
        
        log.info("usage_recorded tenant=%s feature=%s type=%s count=%d total=%d", 
                payload.tenant_id, payload.feature_code, payload.usage_type, payload.usage_count, current_usage)
        
        return {
            "recorded": True,
            "current_usage": current_usage,
            "period": period,
            "feature_code": payload.feature_code,
            "usage_type": payload.usage_type
        }

@app.get("/entitlements/v2/usage/{tenant_id}")
def get_usage_summary_v2(tenant_id: str = Path(...)):
    """
    Get usage summary for a tenant.
    """
    period = datetime.utcnow().strftime("%Y-%m")
    
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT feature_code, usage_type, usage_count
              FROM subscription_usage
             WHERE tenant_id = :tid 
               AND period_start <= :start AND period_end >= :end
        """), {
            "tid": tenant_id, 
            "start": datetime.utcnow().replace(day=1), 
            "end": datetime.utcnow()
        }).all()
        
        usage_summary = {}
        for row in rows:
            feature_code, usage_type, usage_count = row
            if feature_code not in usage_summary:
                usage_summary[feature_code] = {}
            usage_summary[feature_code][usage_type] = int(usage_count)
        
        log.info("usage_summary_retrieved tenant=%s period=%s", tenant_id, period)
        return {
            "tenant_id": tenant_id,
            "period": period,
            "usage": usage_summary
        }

# Subscription Management
@app.post("/entitlements/v2/subscriptions")
def create_subscription_v2(payload: SubscriptionV2Payload = Body(...)):
    """
    Create a new tenant subscription.
    """
    with SessionLocal() as db:
        # Check if tenant already has an active subscription
        existing = db.execute(text("""
            SELECT id FROM subscriptions 
            WHERE tenant_id = :tid AND status IN ('active', 'trialing')
        """), {"tid": payload.tenant_id}).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Tenant already has an active subscription")
        
        # Create subscription
        result = db.execute(text("""
            INSERT INTO subscriptions(tenant_id, plan_code, provider, external_id, status)
            VALUES(:tid, :plan, :provider, :external, 'active')
            RETURNING id
        """), {
            "tid": payload.tenant_id,
            "plan": payload.plan_code,
            "provider": payload.provider,
            "external": payload.external_id
        })
        
        subscription_id = result.scalar()
        db.commit()
        
        # Trigger async activation
        process_subscription_activation.delay(payload.tenant_id, payload.plan_code, payload.external_id)
        
        log.info("subscription_created", extra={"tenant_id": payload.tenant_id, "plan_code": payload.plan_code})
        return {
            "subscription_id": subscription_id,
            "tenant_id": payload.tenant_id,
            "plan_code": payload.plan_code,
            "status": "created"
        }

@app.get("/entitlements/v2/subscriptions/{tenant_id}")
def get_subscription_v2(tenant_id: str = Path(...)):
    """
    Get tenant subscription details.
    """
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT s.id, s.plan_code, s.provider, s.status, s.external_id,
                   p.name as plan_name, p.description as plan_description
              FROM subscriptions s
              JOIN plans p ON s.plan_code = p.code
             WHERE s.tenant_id = :tid
             ORDER BY s.id DESC
             LIMIT 1
        """), {"tid": tenant_id}).first()
        
        if not row:
            raise HTTPException(status_code=404, detail="No subscription found for tenant")
        
        return {
            "subscription_id": row.id,
            "tenant_id": tenant_id,
            "plan_code": row.plan_code,
            "plan_name": row.plan_name,
            "plan_description": row.plan_description,
            "provider": row.provider,
            "status": row.status,
            "external_id": row.external_id
        }

@app.get("/entitlements/v2/plans")
def list_subscription_plans_v2():
    """
    List available subscription plans.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT code, name, description
              FROM plans
             ORDER BY name ASC
        """)).all()
        
        plans = []
        for row in rows:
            plans.append({
                "code": row.code,
                "name": row.name,
                "description": row.description
            })
        
        return {"plans": plans}

@app.get("/entitlements/v2/features")
def list_features_v2():
    """
    List available features.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT code, name, description, category, active
              FROM features
             WHERE active = TRUE
             ORDER BY category, name
        """)).all()
        
        features = []
        for row in rows:
            features.append({
                "code": row.code,
                "name": row.name,
                "description": row.description,
                "category": row.category,
                "active": row.active
            })
        
        return {"features": features}

@app.get("/entitlements/v2/plans/{plan_code}/features")
def get_plan_features_v2(plan_code: str = Path(...)):
    """
    Get features for a specific plan.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT pf.feature_code, f.name, f.description, f.category,
                   pf.enabled, pf.limits
              FROM plan_features pf
              JOIN features f ON pf.feature_code = f.code
             WHERE pf.plan_code = :plan
             ORDER BY f.category, f.name
        """), {"plan": plan_code}).all()
        
        features = []
        for row in rows:
            features.append({
                "feature_code": row.feature_code,
                "name": row.name,
                "description": row.description,
                "category": row.category,
                "enabled": row.enabled,
                "limits": row.limits
            })
        
        return {"plan_code": plan_code, "features": features}

@app.post("/entitlements/v2/cache/clear")
def clear_entitlement_cache_v2(
    tenant_id: str = Query(...),
    feature_code: Optional[str] = Query(None)
):
    """
    Clear entitlement cache for a tenant (useful after subscription changes).
    """
    try:
        if feature_code:
            # Clear specific feature cache
            cache_key = _get_cache_key_v2(tenant_id, feature_code)
            redis_client.delete(cache_key)
            log.info("entitlement_cache_cleared tenant=%s feature=%s", tenant_id, feature_code)
        else:
            # Clear all entitlement caches for the tenant
            pattern = f"entitlement_v2:*"
            keys = redis_client.keys(pattern)
            deleted_count = 0
            for key in keys:
                # Check if this key belongs to the tenant
                cached_data = redis_client.get(key)
                if cached_data:
                    try:
                        data = json.loads(cached_data)
                        if data.get("tenant_id") == tenant_id:
                            redis_client.delete(key)
                            deleted_count += 1
                    except:
                        pass
            log.info("entitlement_cache_cleared_bulk tenant=%s count=%d", tenant_id, deleted_count)
        
        return {"cleared": True, "tenant_id": tenant_id, "feature_code": feature_code}
        
    except Exception as e:
        log.error("entitlement_cache_clear_error: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to clear cache")

# Health check endpoint
# Feature Flags Management
@app.get("/entitlements/v2/feature-flags/{tenant_id}")
def get_feature_flags_v2(tenant_id: str = Path(...)):
    """
    Get all feature flags for a tenant.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT key, enabled, variant, updated_at
              FROM feature_flags
             WHERE tenant_id = :tid
             ORDER BY key
        """), {"tid": tenant_id}).all()
        
        flags = {}
        for row in rows:
            flags[row.key] = {
                "enabled": row.enabled,
                "variant": row.variant,
                "updated_at": row.updated_at
            }
        
        return {"tenant_id": tenant_id, "feature_flags": flags}

@app.post("/entitlements/v2/feature-flags")
def create_feature_flag_v2(payload: FeatureFlagV2Payload = Body(...)):
    """
    Create or update a feature flag for a tenant.
    """
    with SessionLocal() as db:
        db.execute(text("""
            INSERT INTO feature_flags(tenant_id, key, enabled, variant)
            VALUES(:tid, :key, :enabled, :variant)
            ON CONFLICT (tenant_id, key)
            DO UPDATE SET enabled = :enabled, variant = :variant, updated_at = NOW()
        """), {
            "tid": payload.tenant_id,
            "key": payload.key,
            "enabled": payload.enabled,
            "variant": payload.variant
        })
        db.commit()
        
        log.info("feature_flag_updated", extra={"tenant_id": payload.tenant_id, "key": payload.key})
        return {
            "tenant_id": payload.tenant_id,
            "key": payload.key,
            "enabled": payload.enabled,
            "variant": payload.variant,
            "status": "updated"
        }

# Usage Events Management
@app.post("/entitlements/v2/usage/events")
def record_usage_event_v2(payload: UsageEventV2Payload = Body(...)):
    """
    Record a usage event for tracking and billing.
    """
    with SessionLocal() as db:
        result = db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value)
            VALUES(:tid, :sid, :stid, :meter, :subject, :value)
            RETURNING id
        """), {
            "tid": payload.tenant_id,
            "sid": payload.site_id,
            "stid": payload.store_id,
            "meter": payload.meter_code,
            "subject": payload.subject_id,
            "value": payload.value
        })
        
        event_id = result.scalar()
        db.commit()
        
        # Trigger async aggregation
        process_usage_aggregation.delay(payload.tenant_id, payload.meter_code, datetime.utcnow().replace(day=1))
        
        log.info("usage_event_recorded", extra={
            "event_id": event_id,
            "tenant_id": payload.tenant_id,
            "meter_code": payload.meter_code,
            "value": payload.value
        })
        
        return {
            "event_id": event_id,
            "tenant_id": payload.tenant_id,
            "meter_code": payload.meter_code,
            "value": payload.value,
            "status": "recorded"
        }

@app.get("/entitlements/v2/usage/events/{tenant_id}")
def get_usage_events_v2(
    tenant_id: str = Path(...),
    meter_code: Optional[str] = Query(None),
    limit: int = Query(100, le=1000)
):
    """
    Get usage events for a tenant.
    """
    with SessionLocal() as db:
        query = """
            SELECT id, site_id, store_id, meter_code, subject_id, value, occurred_at
              FROM usage_events
             WHERE tenant_id = :tid
        """
        params = {"tid": tenant_id}
        
        if meter_code:
            query += " AND meter_code = :meter"
            params["meter"] = meter_code
        
        query += " ORDER BY occurred_at DESC LIMIT :limit"
        params["limit"] = limit
        
        rows = db.execute(text(query), params).all()
        
        events = []
        for row in rows:
            events.append({
                "id": row.id,
                "site_id": row.site_id,
                "store_id": row.store_id,
                "meter_code": row.meter_code,
                "subject_id": row.subject_id,
                "value": row.value,
                "occurred_at": row.occurred_at
            })
        
        return {"tenant_id": tenant_id, "events": events}

# Usage Meters Management
@app.get("/entitlements/v2/usage/meters")
def list_usage_meters_v2():
    """
    List all available usage meters.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT code, description
              FROM usage_meters
             ORDER BY code
        """)).all()
        
        meters = []
        for row in rows:
            meters.append({
                "code": row.code,
                "description": row.description
            })
        
        return {"meters": meters}

# Direct Entitlements Management
@app.get("/entitlements/v2/direct/{tenant_id}")
def get_direct_entitlements_v2(tenant_id: str = Path(...)):
    """
    Get direct entitlements for a tenant.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT site_id, feature, enabled
              FROM entitlements
             WHERE tenant_id = :tid
             ORDER BY site_id, feature
        """), {"tid": tenant_id}).all()
        
        entitlements = {}
        for row in rows:
            if row.site_id not in entitlements:
                entitlements[row.site_id] = {}
            entitlements[row.site_id][row.feature] = row.enabled
        
        return {"tenant_id": tenant_id, "entitlements": entitlements}

@app.post("/entitlements/v2/direct")
def create_direct_entitlement_v2(payload: EntitlementV2Payload = Body(...)):
    """
    Create or update a direct entitlement.
    """
    with SessionLocal() as db:
        db.execute(text("""
            INSERT INTO entitlements(tenant_id, site_id, feature, enabled)
            VALUES(:tid, :sid, :feature, :enabled)
            ON CONFLICT (tenant_id, site_id, feature)
            DO UPDATE SET enabled = :enabled
        """), {
            "tid": payload.tenant_id,
            "sid": payload.site_id,
            "feature": payload.feature,
            "enabled": payload.enabled
        })
        db.commit()
        
        log.info("direct_entitlement_updated", extra={
            "tenant_id": payload.tenant_id,
            "site_id": payload.site_id,
            "feature": payload.feature
        })
        return {
            "tenant_id": payload.tenant_id,
            "site_id": payload.site_id,
            "feature": payload.feature,
            "enabled": payload.enabled,
            "status": "updated"
        }

# Usage Aggregates
@app.get("/entitlements/v2/usage/aggregates/{tenant_id}")
def get_usage_aggregates_v2(
    tenant_id: str = Path(...),
    days: int = Query(30, le=365)
):
    """
    Get daily usage aggregates for a tenant.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, site_id, store_id, meter_code, value
              FROM usage_aggregates_daily
             WHERE tenant_id = :tid
               AND day >= :start_date
             ORDER BY day DESC, meter_code
        """), {
            "tid": tenant_id,
            "start_date": datetime.utcnow().date() - timedelta(days=days)
        }).all()
        
        aggregates = {}
        for row in rows:
            day_str = row.day.strftime("%Y-%m-%d")
            if day_str not in aggregates:
                aggregates[day_str] = {}
            
            key = f"{row.site_id or 'global'}:{row.store_id or 'global'}:{row.meter_code}"
            aggregates[day_str][key] = row.value
        
        return {"tenant_id": tenant_id, "aggregates": aggregates}

@app.get("/health/detailed")
async def detailed_health():
    """Get detailed health information"""
    return await health_monitor.check_system_health()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8211)