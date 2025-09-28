# services/entitlements/main.py
from fastapi import FastAPI, Body, Query, HTTPException, Path, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text
import logging, os, json
from datetime import datetime, timedelta
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
import redis
import hashlib

SERVICE_NAME = "entitlements"
app = FastAPI(title="ZeroQue Entitlements Service", version="0.1.0")

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

@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    log.info("service_started")

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    try:
        redis_client.ping()
        redis_status = True
    except:
        redis_status = False
    return {"service": SERVICE_NAME, "db": check_db(), "redis": redis_status}

# ---------- payloads ----------
class CheckEntitlementRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    site_id: str = Field(..., min_length=1)
    feature_code: str = Field(..., min_length=1)
    usage_type: Optional[str] = None  # e.g., "api_calls", "storage_gb"

class RecordUsageRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    site_id: str = Field(..., min_length=1)
    feature_code: str = Field(..., min_length=1)
    usage_type: str = Field(..., min_length=1)
    usage_count: int = Field(..., ge=0)

# ---------- entitlements ----------
def _get_cache_key(tenant_id: str, site_id: str, feature_code: str) -> str:
    """Generate cache key for entitlements"""
    key_data = f"{tenant_id}:{site_id}:{feature_code}"
    return f"entitlement:{hashlib.md5(key_data.encode()).hexdigest()}"

def _get_usage_cache_key(tenant_id: str, site_id: str, feature_code: str, usage_type: str, period: str) -> str:
    """Generate cache key for usage tracking"""
    key_data = f"{tenant_id}:{site_id}:{feature_code}:{usage_type}:{period}"
    return f"usage:{hashlib.md5(key_data.encode()).hexdigest()}"

@app.get("/entitlements/check")
def check_entitlement(
    tenant_id: str = Query(...),
    site_id: str = Query(...),
    feature_code: str = Query(...),
    usage_type: Optional[str] = Query(None)
):
    """
    Check if a site has entitlement to a feature, with optional usage limit checking.
    """
    cache_key = _get_cache_key(tenant_id, site_id, feature_code)
    
    # Try Redis cache first
    try:
        cached = redis_client.get(cache_key)
        if cached:
            entitlement_data = json.loads(cached)
            log.info("entitlement_cache_hit tenant=%s site=%s feature=%s", tenant_id, site_id, feature_code)
            
            # Check usage limits if requested
            if usage_type and entitlement_data.get("limits"):
                limits = entitlement_data["limits"]
                if usage_type in limits:
                    period = datetime.utcnow().strftime("%Y-%m")
                    usage_key = _get_usage_cache_key(tenant_id, site_id, feature_code, usage_type, period)
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
            SELECT pf.enabled, pf.limits, ss.status, ss.plan_code
              FROM site_subscriptions ss
              JOIN plan_features pf ON ss.plan_code = pf.plan_code
              JOIN features f ON pf.feature_code = f.code
             WHERE ss.tenant_id = :tid AND ss.site_id = :sid 
               AND pf.feature_code = :feature AND f.active = TRUE
               AND ss.status IN ('active', 'trialing')
        """), {"tid": tenant_id, "sid": site_id, "feature": feature_code}).first()
        
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
                usage_key = _get_usage_cache_key(tenant_id, site_id, feature_code, usage_type, period)
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
        
        log.info("entitlement_checked tenant=%s site=%s feature=%s enabled=%s", 
                tenant_id, site_id, feature_code, entitlement_data["enabled"])
        
        return {
            "entitled": entitlement_data["enabled"],
            "feature_code": feature_code,
            "limits": entitlement_data.get("limits"),
            "status": entitlement_data.get("status"),
            "plan_code": entitlement_data.get("plan_code"),
            "cached": False
        }

@app.post("/entitlements/usage/record")
def record_usage(payload: RecordUsageRequest = Body(...)):
    """
    Record usage for a feature (for limit tracking).
    """
    with SessionLocal() as db:
        # Verify entitlement exists
        row = db.execute(text("""
            SELECT pf.enabled, pf.limits
              FROM site_subscriptions ss
              JOIN plan_features pf ON ss.plan_code = pf.plan_code
              JOIN features f ON pf.feature_code = f.code
             WHERE ss.tenant_id = :tid AND ss.site_id = :sid 
               AND pf.feature_code = :feature AND f.active = TRUE
               AND ss.status IN ('active', 'trialing')
        """), {"tid": payload.tenant_id, "sid": payload.site_id, "feature": payload.feature_code}).first()
        
        if not row:
            raise HTTPException(status_code=404, detail="No active subscription or feature not found")
        
        enabled, limits = row
        if not enabled:
            raise HTTPException(status_code=403, detail="Feature not enabled for this subscription")
        
        # Record usage in Redis (monthly period)
        period = datetime.utcnow().strftime("%Y-%m")
        usage_key = _get_usage_cache_key(payload.tenant_id, payload.site_id, payload.feature_code, 
                                        payload.usage_type, period)
        
        try:
            # Increment usage counter
            current_usage = redis_client.incrby(usage_key, payload.usage_count)
            
            # Set expiration to end of month
            end_of_month = datetime.utcnow().replace(day=1, month=datetime.utcnow().month + 1) - timedelta(days=1)
            redis_client.expireat(usage_key, end_of_month)
            
            # Also store in database for long-term tracking
            db.execute(text("""
                INSERT INTO subscription_usage(tenant_id, site_id, feature_code, usage_type, 
                                             usage_count, period_start, period_end)
                VALUES(:tid, :sid, :feature, :type, :count, :start, :end)
                ON CONFLICT (tenant_id, site_id, feature_code, usage_type, period_start)
                DO UPDATE SET usage_count = subscription_usage.usage_count + :count,
                            updated_at = NOW()
            """), {
                "tid": payload.tenant_id, "sid": payload.site_id, "feature": payload.feature_code,
                "type": payload.usage_type, "count": payload.usage_count,
                "start": datetime.utcnow().replace(day=1),
                "end": end_of_month
            })
            db.commit()
            
            log.info("usage_recorded tenant=%s site=%s feature=%s type=%s count=%d total=%d", 
                    payload.tenant_id, payload.site_id, payload.feature_code, 
                    payload.usage_type, payload.usage_count, current_usage)
            
            return {
                "recorded": True,
                "current_usage": current_usage,
                "period": period,
                "feature_code": payload.feature_code,
                "usage_type": payload.usage_type
            }
            
        except Exception as e:
            log.error("usage_recording_error: %s", str(e))
            raise HTTPException(status_code=500, detail="Failed to record usage")

@app.get("/entitlements/usage/{tenant_id}/{site_id}")
def get_usage_summary(tenant_id: str = Path(...), site_id: str = Path(...)):
    """
    Get usage summary for a site.
    """
    period = datetime.utcnow().strftime("%Y-%m")
    
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT feature_code, usage_type, usage_count
              FROM subscription_usage
             WHERE tenant_id = :tid AND site_id = :sid 
               AND period_start <= :start AND period_end >= :end
        """), {"tid": tenant_id, "sid": site_id, "start": datetime.utcnow().replace(day=1), "end": datetime.utcnow()}).all()
        
        usage_summary = {}
        for row in rows:
            feature_code, usage_type, usage_count = row
            if feature_code not in usage_summary:
                usage_summary[feature_code] = {}
            usage_summary[feature_code][usage_type] = int(usage_count)
        
        log.info("usage_summary_retrieved tenant=%s site=%s period=%s", tenant_id, site_id, period)
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "period": period,
            "usage": usage_summary
        }

@app.post("/entitlements/cache/clear")
def clear_entitlement_cache(
    tenant_id: str = Query(...),
    site_id: str = Query(...),
    feature_code: Optional[str] = Query(None)
):
    """
    Clear entitlement cache for a site (useful after subscription changes).
    """
    try:
        if feature_code:
            # Clear specific feature cache
            cache_key = _get_cache_key(tenant_id, site_id, feature_code)
            redis_client.delete(cache_key)
            log.info("entitlement_cache_cleared tenant=%s site=%s feature=%s", tenant_id, site_id, feature_code)
        else:
            # Clear all entitlement caches for the site
            pattern = f"entitlement:*"
            keys = redis_client.keys(pattern)
            deleted_count = 0
            for key in keys:
                # Check if this key belongs to the tenant/site
                cached_data = redis_client.get(key)
                if cached_data:
                    try:
                        data = json.loads(cached_data)
                        if (data.get("tenant_id") == tenant_id and 
                            data.get("site_id") == site_id):
                            redis_client.delete(key)
                            deleted_count += 1
                    except:
                        pass
            log.info("entitlement_cache_cleared_bulk tenant=%s site=%s count=%d", tenant_id, site_id, deleted_count)
        
        return {"cleared": True, "tenant_id": tenant_id, "site_id": site_id, "feature_code": feature_code}
        
    except Exception as e:
        log.error("entitlement_cache_clear_error: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to clear cache")