# services/usage/main.py - ZeroQue Usage Service V4.1
# Production-ready usage service with Celery, RabbitMQ, and comprehensive metrics

import os
import uuid
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError
from celery import Celery
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "usage"
SERVICE_VERSION = "4.1.0"

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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

# Models
class UsageEvent(Base):
    __tablename__ = "usage_events_new"
    
    event_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=True)
    meter_code = Column(String(100), nullable=False)
    quantity = Column(Integer, default=1)
    metadata_json = Column(JSON, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

try:
    Base.metadata.create_all(engine)
except:
    pass

# Payloads
class UsageEventRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    meter_code: str
    quantity: int = 1
    metadata: Optional[Dict] = None

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
async def list_usage_events(
    tenant_id: Optional[str] = Query(None),
    meter_code: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """List usage events"""
    try:
        with SessionLocal() as db:
            query = "SELECT * FROM usage_events_new WHERE 1=1"
            params = {}
            
            if tenant_id:
                query += " AND tenant_id = :tenant_id"
                params["tenant_id"] = tenant_id
            
            if meter_code:
                query += " AND meter_code = :meter_code"
                params["meter_code"] = meter_code
            
            query += " ORDER BY recorded_at DESC LIMIT :limit"
            params["limit"] = limit
            
            results = db.execute(text(query), params).fetchall()
            
            return [
                {
                    "event_id": r[0],
                    "tenant_id": r[1],
                    "user_id": r[2],
                    "meter_code": r[3],
                    "quantity": r[4],
                    "recorded_at": r[6]
                }
                for r in results
            ]
    
    except Exception as e:
        logger.error(f"List usage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8200")))
    uvicorn.run(app, host="0.0.0.0", port=port)
