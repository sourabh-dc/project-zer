# services/observability/main.py
"""
ZeroQue Observability Service - Centralized monitoring and insights
"""
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
from datetime import datetime, timezone
import asyncio

from zeroque_common.observability import (
    setup_logging, get_logger, init_metrics, get_metrics,
    init_insights, get_insights, ApplicationInsights
)
from zeroque_common.db.session import SessionLocal, init_db, check_db
from zeroque_common.events.celery_app import celery_app

SERVICE_NAME = "observability"
app = FastAPI(title="ZeroQue Observability Service", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize observability
logger = setup_logging(SERVICE_NAME, "1.0.0")
metrics = init_metrics(SERVICE_NAME)
insights = init_insights(SERVICE_NAME, "1.0.0")

# Startup
@app.on_event("startup")
async def on_startup():
    init_db()
    # Start background collection for insights
    insights.start_background_collection_async()
    logger.info("Observability service started")

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db()}

# Metrics endpoints
@app.get("/metrics")
def get_all_metrics():
    """Get all collected metrics"""
    try:
        all_metrics = metrics.get_all_metrics()
        return {
            "service": SERVICE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "labels": m.labels,
                    "unit": m.unit,
                    "timestamp": m.timestamp.isoformat()
                }
                for m in all_metrics
            ]
        }
    except Exception as e:
        logger.error("Failed to get metrics: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics/summary")
def get_metrics_summary():
    """Get metrics summary"""
    try:
        return metrics.get_metrics_summary()
    except Exception as e:
        logger.error("Failed to get metrics summary: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Insights endpoints
@app.get("/insights")
def get_service_insights():
    """Get service insights"""
    try:
        service_insights = insights.get_insights()
        return {
            "service_name": service_insights.service_name,
            "timestamp": service_insights.timestamp.isoformat(),
            "health_status": service_insights.health_status,
            "performance_metrics": service_insights.performance_metrics,
            "business_metrics": service_insights.business_metrics,
            "error_rate": service_insights.error_rate,
            "uptime_seconds": service_insights.uptime_seconds,
            "version": service_insights.version,
            "environment": service_insights.environment
        }
    except Exception as e:
        logger.error("Failed to get insights: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health/detailed")
def get_detailed_health():
    """Get detailed health status"""
    try:
        return insights.get_health_summary()
    except Exception as e:
        logger.error("Failed to get health summary: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/performance")
def get_performance_summary():
    """Get performance summary"""
    try:
        return insights.get_performance_summary()
    except Exception as e:
        logger.error("Failed to get performance summary: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Service discovery and monitoring
@app.get("/services/status")
def get_all_services_status():
    """Get status of all ZeroQue services"""
    services = [
        {"name": "provisioning", "port": 8201, "url": "http://localhost:8201"},
        {"name": "catalog", "port": 8202, "url": "http://localhost:8202"},
        {"name": "entry", "port": 8204, "url": "http://localhost:8204"},
        {"name": "billing", "port": 8206, "url": "http://localhost:8206"},
        {"name": "orders", "port": 8208, "url": "http://localhost:8208"},
        {"name": "pricing", "port": 8209, "url": "http://localhost:8209"},
        {"name": "identity", "port": 8210, "url": "http://localhost:8210"},
        {"name": "events", "port": 8213, "url": "http://localhost:8213"},
        {"name": "observability", "port": 8214, "url": "http://localhost:8214"}
    ]
    
    service_status = []
    for service in services:
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{service['url']}/health")
                if response.status_code == 200:
                    status = "healthy"
                else:
                    status = "unhealthy"
        except Exception:
            status = "unreachable"
        
        service_status.append({
            "name": service["name"],
            "port": service["port"],
            "url": service["url"],
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    return {
        "services": service_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Event system monitoring
@app.get("/events/status")
def get_event_system_status():
    """Get event system status"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))
        
        # Get Redis Stream info
        stream_info = redis_client.xinfo_stream("zeroque:events")
        
        # Get Celery worker stats
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()
        
        return {
            "redis_stream": {
                "length": stream_info.get("length", 0),
                "first_entry": stream_info.get("first-entry"),
                "last_entry": stream_info.get("last-entry"),
                "groups": stream_info.get("groups", 0)
            },
            "celery_workers": {
                "count": len(stats) if stats else 0,
                "workers": list(stats.keys()) if stats else [],
                "active_tasks": sum(len(tasks) for tasks in active.values()) if active else 0
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error("Failed to get event system status: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Database monitoring
@app.get("/database/status")
def get_database_status():
    """Get database status and metrics"""
    try:
        with SessionLocal() as db:
            # Get basic connection info
            result = db.execute("SELECT version()").scalar()
            
            # Get table counts
            tables = db.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """).all()
            
            table_counts = {}
            for table in tables:
                table_name = table[0]
                try:
                    count = db.execute(f"SELECT COUNT(*) FROM {table_name}").scalar()
                    table_counts[table_name] = count
                except Exception:
                    table_counts[table_name] = "error"
            
            return {
                "status": "healthy",
                "version": result,
                "tables": table_counts,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    except Exception as e:
        logger.error("Failed to get database status: %s", str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Alerting endpoints
@app.post("/alerts/test")
def test_alerting():
    """Test alerting system"""
    try:
        # Record a test business event
        insights.record_business_event("test_alert", 1.0, test=True)
        
        # Record a test error
        insights.record_error("test_error", "This is a test error", test=True)
        
        return {"status": "success", "message": "Test alerts sent"}
    except Exception as e:
        logger.error("Failed to test alerting: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8214))
    uvicorn.run(app, host="0.0.0.0", port=port)
