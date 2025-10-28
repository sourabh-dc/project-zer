# services/usage/main.py - ZeroQue Usage Service V4.1
# Production-ready usage service with Celery, RabbitMQ, and comprehensive metrics

import os
import uuid
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from celery import Celery
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import pybreaker

from services.usage.schemas import UsageEventRequest
from utils.user_auth import get_user_context, check_permission
from repositories.db_config import SessionLocal, get_db_with_rls
from utils.usage_logger import logger
from models import UsageEvent, OutboxEvent, AuditLog

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "usage"
SERVICE_VERSION = "4.1.0"

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "false").lower() == "true"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Celery setup
celery_app = Celery(
    SERVICE_NAME,
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=[f'{SERVICE_NAME}.tasks']
)

# Load Celery configuration
try:
    celery_app.config_from_object('celeryconfig')
except ImportError:
    logger.warning("Celery config not found, using defaults")

# Prometheus metrics
usage_events_recorded = Counter('usage_events_recorded_total', 'Total usage events recorded', ['tenant_id', 'meter_code'])
usage_event_duration = Histogram('usage_event_duration_seconds', 'Usage event processing duration', ['operation'])
active_meters = Gauge('active_meters_total', 'Total active meters', ['tenant_id'])

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)


def publish_to_rabbitmq(event_type: str, event_data: Dict, tenant_id: str):
    """Publish event to RabbitMQ"""
    try:
        conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        ch = conn.channel()
        ch.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        msg = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        ch.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=msg,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        conn.close()
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="ZeroQue Usage Service", version=SERVICE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/usage/v4/record")
async def record_usage(request: UsageEventRequest):
    """Record a usage event"""
    try:
        event_id = f"usage_{uuid.uuid4().hex[:12]}"
        
        with SessionLocal() as db:
            event = UsageEvent(
                event_id=event_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                meter_code=request.meter_code,
                quantity=request.quantity,
                metadata_json=request.metadata
            )
            db.add(event)
            db.commit()
        
        logger.info(f"Usage recorded: {event_id}")
        
        return {
            "event_id": event_id,
            "tenant_id": request.tenant_id,
            "meter_code": request.meter_code,
            "quantity": request.quantity,
            "recorded": True
        }
    
    except Exception as e:
        logger.error(f"Usage recording failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usage/v4/events")
async def get_usage_events(tenant_id: str = Query(...), limit: int = Query(100), uctx: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    """Get usage events for a tenant"""
    try:
        if not check_permission(uctx, "usage.view"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        events = db.query(UsageEvent).filter(
            UsageEvent.tenant_id == tenant_id
        ).order_by(UsageEvent.recorded_at.desc()).limit(limit).all()
        
        return [{
            "event_id": e.event_id,
            "meter_code": e.meter_code,
            "quantity": e.quantity,
            "recorded_at": e.recorded_at.isoformat()
        } for e in events]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(name='usage.publish_outbox_events')
def publish_outbox_events():
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            evts = db.query(OutboxEvent).filter(
                OutboxEvent.status == "pending",
                OutboxEvent.retry_count < 5
            ).limit(100).all()
            
            for e in evts:
                event_data = json.loads(e.event_data) if isinstance(e.event_data, str) else e.event_data
                if publish_to_rabbitmq(e.event_type, event_data, e.aggregate_id):
                    e.status = "published"
                    e.published_at = datetime.now(timezone.utc)
                else:
                    e.retry_count += 1
                    if e.retry_count >= 5:
                        e.status = "failed"
                db.commit()
            
            if evts:
                logger.info(f"Published {len(evts)} events")
    except Exception as ex:
        logger.error(f"Outbox publish failed: {ex}")

@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_usage_events')
def cleanup_old_usage_events(self):
    """Clean up old usage events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM usage_events_new WHERE recorded_at < :cutoff"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old usage events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup usage events: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_outbox_events')
def cleanup_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            result = db.execute(
                text("DELETE FROM outbox_events WHERE created_at < :cutoff AND status IN ('published', 'failed')"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old outbox events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(name='usage.process_entry_granted')
def process_entry_granted(event_data: Dict):
    """Process ENTRY_GRANTED event"""
    try:
        tenant_id = event_data.get('tenant_id')
        user_id = event_data.get('user_id')
        
        if tenant_id:
            with SessionLocal() as db:
                # Record entry as usage event
                event_id = f"usage_{uuid.uuid4().hex[:12]}"
                event = UsageEvent(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    meter_code='entry_count',
                    quantity=1,
                    metadata_json={"source": "entry_service"}
                )
                db.add(event)
                db.commit()
                logger.info(f"Recorded entry usage for tenant {tenant_id}")
        
        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Failed to process ENTRY_GRANTED: {e}")
        return {'status': 'error'}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8200")))
    uvicorn.run(app, host="0.0.0.0", port=port)
