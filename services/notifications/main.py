#!/usr/bin/env python3
"""
ZeroQue Notifications Service V4.1
Enhanced notifications with multi-provider support, event-driven architecture, and v4.1 compliance
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Depends, Body, Query, Path, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, Column, String, Integer, DateTime, Boolean, Text, ForeignKey, JSON, func, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.exc import SQLAlchemyError
from celery import Celery
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import structlog
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

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

# Service configuration
SERVICE_NAME = "notifications"
SERVICE_VERSION = "4.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")

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
    pass

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# Prometheus metrics
notification_operations_total = Counter('notification_operations_total', 'Total notification operations', ['operation', 'status'])
notification_request_duration = Histogram('notification_request_duration_seconds', 'Notification request duration', ['operation'])
notification_queue_size = Gauge('notification_queue_size', 'Current notification queue size')
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['saga_type'])

# ---- Database Models ----
class NotificationDeliveryNew(Base):
    __tablename__ = "notification_deliveries_new"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    channel = Column(String(20), nullable=False)  # email, sms, push
    provider = Column(String(50), nullable=False)  # twilio, sendgrid, internal
    status = Column(String(20), nullable=False, default='queued')  # queued, sent, failed
    template_id = Column(String(100), nullable=True)
    payload = Column(JSONB, nullable=False)
    error = Column(JSONB, nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))

class ZeroqueRail(Base):
    __tablename__ = "zeroque_rails"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    type = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    config = Column(JSONB, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), default='pending')
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=text('NOW()'))

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('NOW()'), nullable=False)

# ---- Pydantic Models ----
class SendNotificationRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    channel: str = Field(..., description="Notification channel: email, sms, push")
    provider: Optional[str] = None  # Auto-select if not provided
    template_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    to: str = Field(..., description="Recipient address")
    subject: Optional[str] = None
    body: Optional[str] = None
    priority: str = Field(default="normal", description="Priority: low, normal, high")
    delay_until: Optional[datetime] = None

class ReplayRequest(BaseModel):
    delivery_id: str
    force: bool = Field(default=False, description="Force replay even if max retries reached")

class RailRequest(BaseModel):
    type: str = Field(default="notification")
    name: str = Field(..., description="Provider name (e.g., twilio, sendgrid)")
    config: Dict[str, Any] = Field(..., description="Provider configuration")
    active: bool = Field(default=True)

class NotificationResponse(BaseModel):
    delivery_id: str
    status: str
    provider: str
    channel: str
    created_at: datetime

class NotificationHistoryResponse(BaseModel):
    deliveries: List[Dict[str, Any]]
    count: int
    page: int
    limit: int

# ---- Notification Provider Interface ----
class NotificationProvider:
    """Base class for notification providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
    
    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
    
    async def send_push(self, to: str, title: str, body: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

class TwilioProvider(NotificationProvider):
    """Twilio SMS provider"""
    
    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.config['account_sid']}/Messages.json",
                auth=(self.config['account_sid'], self.config['auth_token']),
                data={
                    'From': self.config['from_number'],
                    'To': to,
                    'Body': message
                }
            )
            response.raise_for_status()
            return response.json()
    
    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        # Twilio SendGrid integration would go here
        raise NotImplementedError("Email not implemented for Twilio provider")

class SendGridProvider(NotificationProvider):
    """SendGrid email provider"""
    
    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    'Authorization': f"Bearer {self.config['api_key']}",
                    'Content-Type': 'application/json'
                },
                json={
                    'personalizations': [{'to': [{'email': to}]}],
                    'from': {'email': self.config['from_email']},
                    'subject': subject,
                    'content': [{'type': 'text/html', 'value': body}]
                }
            )
            response.raise_for_status()
            return {"message_id": response.headers.get('X-Message-Id')}
    
    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("SMS not implemented for SendGrid provider")

class InternalProvider(NotificationProvider):
    """Internal notification provider (for testing/development)"""
    
    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal email sent", to=to, subject=subject)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}
    
    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal SMS sent", to=to, message=message)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}
    
    async def send_push(self, to: str, title: str, body: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal push sent", to=to, title=title, body=body)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}

# ---- Provider Factory ----
def create_provider(provider_name: str, config: Dict[str, Any]) -> NotificationProvider:
    """Factory method to create notification providers"""
    if provider_name == "twilio":
        return TwilioProvider(config)
    elif provider_name == "sendgrid":
        return SendGridProvider(config)
    elif provider_name == "internal":
        return InternalProvider(config)
    else:
        raise ValueError(f"Unknown provider: {provider_name}")

# ---- Saga Implementation ----
class SendNotificationSaga:
    """Saga for reliable notification delivery"""
    
    def __init__(self, db: Session):
        self.db = db
        self.compensation_steps = []
    
    async def execute(self, request: SendNotificationRequest, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the notification send saga"""
        start_time = datetime.now()
        
        try:
            # Step 1: Validate request and get provider
            provider_config = await self._get_provider_config(request.tenant_id, request.provider, request.channel)
            self.compensation_steps.append(("validate_provider", None))
            
            # Step 2: Create delivery record
            delivery_id = await self._create_delivery_record(request, provider_config)
            self.compensation_steps.append(("create_delivery", delivery_id))
            
            # Step 3: Send notification
            result = await self._send_notification(request, provider_config)
            self.compensation_steps.append(("send_notification", delivery_id))
            
            # Step 4: Update delivery status
            await self._update_delivery_status(delivery_id, "sent", result)
            
            # Step 5: Publish event
            await self._publish_notification_sent_event(delivery_id, request, result)
            
            # Step 6: Audit log
            await self._audit_notification_send(delivery_id, request, user_context)
            
            duration = (datetime.now() - start_time).total_seconds()
            if saga_duration:
                saga_duration.labels(saga_type="send_notification", status="success").observe(duration)
            
            return {
                "delivery_id": str(delivery_id),
                "status": "sent",
                "provider": provider_config["name"],
                "result": result
            }
            
        except Exception as e:
            # Compensation logic
            await self._compensate()
            duration = (datetime.now() - start_time).total_seconds()
            if saga_duration:
                saga_duration.labels(saga_type="send_notification", status="failed").observe(duration)
            
            logger.error("Send notification saga failed", error=str(e), compensation_steps=self.compensation_steps)
            raise HTTPException(status_code=500, detail=f"Notification send failed: {str(e)}")
    
    async def _get_provider_config(self, tenant_id: str, provider: Optional[str], channel: str) -> Dict[str, Any]:
        """Get provider configuration from rails"""
        if not provider:
            # Auto-select provider based on channel
            if channel == "email":
                provider = "sendgrid"
            elif channel == "sms":
                provider = "twilio"
            else:
                provider = "internal"
        
        # Get provider config from zeroque_rails
        result = self.db.execute(text("""
            SELECT config FROM zeroque_rails 
            WHERE tenant_id = :tenant_id AND type = 'notification' AND name = :name AND active = true
        """), {"tenant_id": tenant_id, "name": provider}).first()
        
        if not result:
            # Fallback to internal provider
            provider = "internal"
            result = self.db.execute(text("""
                SELECT config FROM zeroque_rails 
                WHERE tenant_id = :tenant_id AND type = 'notification' AND name = 'internal' AND active = true
            """), {"tenant_id": tenant_id}).first()
            
            if not result:
                # Default internal config
                config = {"fallback": True}
            else:
                config = result[0]
        else:
            config = result[0]
        
        return {"name": provider, "config": config}
    
    async def _create_delivery_record(self, request: SendNotificationRequest, provider_config: Dict[str, Any]) -> uuid.UUID:
        """Create notification delivery record"""
        delivery_id = uuid.uuid4()
        
        payload = {
            "to": str(request.to),
            "subject": request.subject,
            "body": request.body,
            "data": request.data,
            "priority": request.priority
        }
        
        next_attempt_at = request.delay_until or datetime.now(timezone.utc)
        
        self.db.execute(text("""
            INSERT INTO notification_deliveries_new (
                id, tenant_id, user_id, channel, provider, status, template_id,
                payload, next_attempt_at, retry_count, max_retries, created_at
            ) VALUES (
                :id, :tenant_id, :user_id, :channel, :provider, 'queued', :template_id,
                :payload, :next_attempt_at, 0, 3, NOW()
            )
        """), {
            "id": delivery_id,
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "channel": request.channel,
            "provider": provider_config["name"],
            "template_id": request.template_id,
            "payload": json.dumps(payload),
            "next_attempt_at": next_attempt_at
        })
        
        self.db.commit()
        return delivery_id
    
    async def _send_notification(self, request: SendNotificationRequest, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        """Send notification via provider"""
        provider = create_provider(provider_config["name"], provider_config["config"])
        
        if request.channel == "email":
            result = await provider.send_email(
                to=str(request.to),
                subject=request.subject or "Notification",
                body=request.body or ""
            )
        elif request.channel == "sms":
            result = await provider.send_sms(
                to=str(request.to),
                message=request.body or "Notification"
            )
        elif request.channel == "push":
            result = await provider.send_push(
                to=str(request.to),
                title=request.subject or "Notification",
                body=request.body or ""
            )
        else:
            raise ValueError(f"Unsupported channel: {request.channel}")
        
        return result
    
    async def _update_delivery_status(self, delivery_id: uuid.UUID, status: str, result: Dict[str, Any]):
        """Update delivery status"""
        self.db.execute(text("""
            UPDATE notification_deliveries_new 
            SET status = :status, updated_at = NOW()
            WHERE id = :id
        """), {"id": delivery_id, "status": status})
        self.db.commit()
    
    async def _publish_notification_sent_event(self, delivery_id: uuid.UUID, request: SendNotificationRequest, result: Dict[str, Any]):
        """Publish NOTIFICATION_SENT event"""
        event_data = {
            "delivery_id": str(delivery_id),
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "channel": request.channel,
            "to": str(request.to),
            "status": "sent",
            "result": result
        }
        
        # Store in outbox_events for reliable publishing
        self.db.execute(text("""
            INSERT INTO outbox_events (tenant_id, event_type, event_data, status, created_at)
            VALUES (:tenant_id, 'NOTIFICATION_SENT', :event_data, 'pending', NOW())
        """), {
            "tenant_id": request.tenant_id,
            "event_data": json.dumps(event_data)
        })
        self.db.commit()
    
    async def _audit_notification_send(self, delivery_id: uuid.UUID, request: SendNotificationRequest, user_context: Dict[str, Any]):
        """Audit notification send"""
        self.db.execute(text("""
            INSERT INTO audit_logs (
                tenant_id, user_id, action, resource_type, resource_id, details, created_at
            ) VALUES (
                :tenant_id, :user_id, 'SEND_NOTIFICATION', 'notification_delivery', :resource_id, :details, NOW()
            )
        """), {
            "tenant_id": request.tenant_id,
            "user_id": user_context.get("user_id"),
            "resource_id": str(delivery_id),
            "details": json.dumps({
                "channel": request.channel,
                "to": str(request.to),
                "template_id": request.template_id
            })
        })
        self.db.commit()
    
    async def _compensate(self):
        """Compensation logic for saga failures"""
        for step, delivery_id in reversed(self.compensation_steps):
            try:
                if step == "create_delivery" and delivery_id:
                    # Mark delivery as failed
                    self.db.execute(text("""
                        UPDATE notification_deliveries_new 
                        SET status = 'failed', updated_at = NOW()
                        WHERE id = :id
                    """), {"id": delivery_id})
                    self.db.commit()
                # Add more compensation steps as needed
            except Exception as e:
                logger.error("Compensation step failed", step=step, error=str(e))

class ReplaySaga:
    """Saga for replaying failed notifications"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def execute(self, request: ReplayRequest, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the replay saga"""
        start_time = datetime.now()
        
        try:
            # Step 1: Get delivery record
            delivery = await self._get_delivery_record(request.delivery_id)
            
            # Step 2: Validate replay eligibility
            await self._validate_replay_eligibility(delivery, request.force)
            
            # Step 3: Reset delivery status
            await self._reset_delivery_status(delivery["id"])
            
            # Step 4: Schedule retry
            await self._schedule_retry(delivery["id"])
            
            # Step 5: Audit replay
            await self._audit_replay(delivery["id"], user_context)
            
            duration = (datetime.now() - start_time).total_seconds()
            saga_duration.labels(saga_type="replay_notification", status="success").observe(duration)
            
            return {"delivery_id": request.delivery_id, "status": "replayed", "next_attempt_at": delivery["next_attempt_at"]}
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            saga_duration.labels(saga_type="replay_notification", status="failed").observe(duration)
            
            logger.error("Replay saga failed", delivery_id=request.delivery_id, error=str(e))
            raise HTTPException(status_code=500, detail=f"Replay failed: {str(e)}")
    
    async def _get_delivery_record(self, delivery_id: str) -> Dict[str, Any]:
        """Get delivery record"""
        result = self.db.execute(text("""
            SELECT id, tenant_id, user_id, channel, provider, status, payload, retry_count, max_retries, next_attempt_at
            FROM notification_deliveries_new WHERE id = :id
        """), {"id": delivery_id}).first()
        
        if not result:
            raise HTTPException(status_code=404, detail="Delivery not found")
        
        return dict(result._mapping)
    
    async def _validate_replay_eligibility(self, delivery: Dict[str, Any], force: bool):
        """Validate if delivery can be replayed"""
        if delivery["status"] == "sent" and not force:
            raise HTTPException(status_code=400, detail="Delivery already sent")
        
        if delivery["retry_count"] >= delivery["max_retries"] and not force:
            raise HTTPException(status_code=400, detail="Max retries reached")
    
    async def _reset_delivery_status(self, delivery_id: str):
        """Reset delivery status to queued"""
        self.db.execute(text("""
            UPDATE notification_deliveries_new 
            SET status = 'queued', error = NULL, updated_at = NOW()
            WHERE id = :id
        """), {"id": delivery_id})
        self.db.commit()
    
    async def _schedule_retry(self, delivery_id: str):
        """Schedule retry attempt"""
        next_attempt = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.db.execute(text("""
            UPDATE notification_deliveries_new 
            SET next_attempt_at = :next_attempt_at, retry_count = retry_count + 1, updated_at = NOW()
            WHERE id = :id
        """), {"id": delivery_id, "next_attempt_at": next_attempt})
        self.db.commit()
    
    async def _audit_replay(self, delivery_id: str, user_context: Dict[str, Any]):
        """Audit replay action"""
        self.db.execute(text("""
            INSERT INTO audit_logs (
                tenant_id, user_id, action, resource_type, resource_id, details, created_at
            ) VALUES (
                :tenant_id, :user_id, 'REPLAY_NOTIFICATION', 'notification_delivery', :resource_id, :details, NOW()
            )
        """), {
            "tenant_id": user_context.get("tenant_id"),
            "user_id": user_context.get("user_id"),
            "resource_id": delivery_id,
            "details": json.dumps({"action": "replay"})
        })
        self.db.commit()

# ---- Utility Functions ----
def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_context() -> Dict[str, Any]:
    """Get user context (simplified for demo)"""
    return {
        "user_id": "demo-user-123",
        "tenant_id": "demo-tenant-456",
        "permissions": ["notifications.send", "notifications.admin"]
    }

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    return required_permission in user_context.get("permissions", [])

def set_rls_context(db: Session, tenant_id: str, user_id: Optional[str] = None):
    """Set RLS context for database queries"""
    db.execute(text("SET app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET app.user_id = :user_id"), {"user_id": user_id})

# ---- Event Handlers ----
async def handle_entry_granted(event_data: Dict[str, Any], db: Session):
    """Handle ENTRY_GRANTED event"""
    try:
        user_id = event_data.get("user_id")
        tenant_id = event_data.get("tenant_id")
        entry_code = event_data.get("entry_code")
        
        if user_id and tenant_id:
            # Send SMS notification for entry granted
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                channel="sms",
                to="+1234567890",  # This would come from user profile
                body=f"Entry code: {entry_code}. Use this code to enter the store.",
                subject="Entry Code"
            )
            
            saga = SendNotificationSaga(db)
            user_context = {"user_id": user_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)
            
            logger.info("Entry granted notification sent", user_id=user_id, entry_code=entry_code)
            
    except Exception as e:
        logger.error("Failed to handle ENTRY_GRANTED event", error=str(e), event_data=event_data)

async def handle_user_created(event_data: Dict[str, Any], db: Session):
    """Handle USER_CREATED event"""
    try:
        user_id = event_data.get("user_id")
        tenant_id = event_data.get("tenant_id")
        email = event_data.get("email")
        
        if user_id and tenant_id and email:
            # Send welcome email
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                channel="email",
                to=email,
                subject="Welcome to ZeroQue",
                body="Welcome to the ZeroQue platform! Your account has been created successfully.",
                template_id="welcome_email"
            )
            
            saga = SendNotificationSaga(db)
            user_context = {"user_id": user_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)
            
            logger.info("Welcome email sent", user_id=user_id, email=email)
            
    except Exception as e:
        logger.error("Failed to handle USER_CREATED event", error=str(e), event_data=event_data)

async def handle_order_completed(event_data: Dict[str, Any], db: Session):
    """Handle ORDER_COMPLETED event"""
    try:
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        customer_id = event_data.get("customer_id")
        
        if order_id and tenant_id:
            # Send order confirmation notification
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=customer_id,
                channel="email",
                to="customer@example.com",  # This would come from customer profile
                subject=f"Order #{order_id} Confirmed",
                body=f"Your order #{order_id} has been completed successfully.",
                template_id="order_confirmation"
            )
            
            saga = SendNotificationSaga(db)
            user_context = {"user_id": customer_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)
            
            logger.info("Order confirmation sent", order_id=order_id, customer_id=customer_id)
            
    except Exception as e:
        logger.error("Failed to handle ORDER_COMPLETED event", error=str(e), event_data=event_data)

async def handle_invoice_posted(event_data: Dict[str, Any], db: Session):
    """Handle INVOICE_POSTED event"""
    try:
        invoice_id = event_data.get("invoice_id")
        tenant_id = event_data.get("tenant_id")
        customer_id = event_data.get("customer_id")
        amount = event_data.get("amount")
        
        if invoice_id and tenant_id:
            # Send billing notification
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=customer_id,
                channel="email",
                to="customer@example.com",  # This would come from customer profile
                subject=f"Invoice #{invoice_id} Posted",
                body=f"Your invoice #{invoice_id} for {amount} has been posted.",
                template_id="invoice_notification"
            )
            
            saga = SendNotificationSaga(db)
            user_context = {"user_id": customer_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)
            
            logger.info("Invoice notification sent", invoice_id=invoice_id, customer_id=customer_id)
            
    except Exception as e:
        logger.error("Failed to handle INVOICE_POSTED event", error=str(e), event_data=event_data)

# ---- Application Setup ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME} service", version=VERSION, environment=ENVIRONMENT)
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    # Start background tasks
    # Note: In production, these would be separate Celery workers
    
    yield
    
    logger.info(f"Shutting down {SERVICE_NAME} service")

app = FastAPI(
    title=f"ZeroQue {SERVICE_NAME.title()} Service V4.1",
    description=f"Enhanced {SERVICE_NAME} management with multi-provider support and event-driven architecture",
    version=VERSION
    # lifespan=lifespan  # Temporarily disabled for debugging
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Health Endpoints ----
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "environment": ENVIRONMENT
    }

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    try:
        # Check database connectivity
        with SessionLocal() as db:
            db.execute(text("SELECT 1")).fetchone()
        
        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(status_code=503, detail="Service not ready")

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

# ---- Notification Endpoints ----
@app.post("/notifications/v4/send", response_model=NotificationResponse)
async def send_notification(
    request: SendNotificationRequest = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Send notification via configured provider"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Set RLS context
    set_rls_context(db, request.tenant_id, request.user_id)
    
    try:
        saga = SendNotificationSaga(db)
        result = await saga.execute(request, user_context)
        
        # Update metrics
        if notification_send_total:
            notification_send_total.labels(
                channel=request.channel,
                provider=result["provider"],
                status="success"
            ).inc()
        
        return NotificationResponse(
            delivery_id=result["delivery_id"],
            status=result["status"],
            provider=result["provider"],
            channel=request.channel,
            created_at=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        # Update failure metrics
        if notification_failures_total:
            notification_failures_total.labels(
                channel=request.channel,
                provider=request.provider or "unknown",
                error_type=type(e).__name__
            ).inc()
        
        logger.error("Notification send failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification send failed: {str(e)}")

@app.post("/notifications/v4/replay")
async def replay_notification(
    request: ReplayRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Replay failed notification"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        saga = ReplaySaga(db)
        result = await saga.execute(request, user_context)
        
        return result
        
    except Exception as e:
        logger.error("Notification replay failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification replay failed: {str(e)}")

@app.get("/notifications/v4/history", response_model=NotificationHistoryResponse)
async def get_notification_history(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get notification delivery history"""
    if not check_permission("notifications.view", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Set RLS context
    set_rls_context(db, tenant_id)
    
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = """
            SELECT id, tenant_id, user_id, channel, provider, status, template_id,
                   payload, error, retry_count, created_at, updated_at
            FROM notification_deliveries_new
            WHERE tenant_id = :tenant_id
        """
        params = {"tenant_id": tenant_id}
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        if channel:
            query += " AND channel = :channel"
            params["channel"] = channel
        
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params.update({"limit": limit, "offset": offset})
        
        # Get deliveries
        deliveries = db.execute(text(query), params).fetchall()
        
        # Get total count
        count_query = """
            SELECT COUNT(*) FROM notification_deliveries_new
            WHERE tenant_id = :tenant_id
        """
        count_params = {"tenant_id": tenant_id}
        
        if status:
            count_query += " AND status = :status"
            count_params["status"] = status
        
        if channel:
            count_query += " AND channel = :channel"
            count_params["channel"] = channel
        
        total_count = db.execute(text(count_query), count_params).scalar()
        
        # Convert to dict format
        delivery_list = []
        for delivery in deliveries:
            delivery_dict = dict(delivery._mapping)
            delivery_dict["payload"] = json.loads(delivery_dict["payload"]) if delivery_dict["payload"] else {}
            delivery_dict["error"] = json.loads(delivery_dict["error"]) if delivery_dict["error"] else None
            delivery_list.append(delivery_dict)
        
        return NotificationHistoryResponse(
            deliveries=delivery_list,
            count=total_count,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error("Failed to get notification history", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get notification history")

# ---- Admin Endpoints ----
@app.post("/admin/rails/notification")
async def configure_notification_provider(
    request: RailRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure notification provider"""
    if not check_permission("notifications.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        tenant_id = user_context.get("tenant_id")
        
        # Check if provider already exists
        existing = db.execute(text("""
            SELECT id FROM zeroque_rails 
            WHERE tenant_id = :tenant_id AND type = :type AND name = :name
        """), {
            "tenant_id": tenant_id,
            "type": request.type,
            "name": request.name
        }).first()
        
        if existing:
            # Update existing provider
            db.execute(text("""
                UPDATE zeroque_rails 
                SET config = :config, active = :active, updated_at = NOW()
                WHERE id = :id
            """), {
                "id": existing[0],
                "config": json.dumps(request.config),
                "active": request.active
            })
        else:
            # Create new provider
            db.execute(text("""
                INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at)
                VALUES (:tenant_id, :type, :name, :config, :active, NOW())
            """), {
                "tenant_id": tenant_id,
                "type": request.type,
                "name": request.name,
                "config": json.dumps(request.config),
                "active": request.active
            })
        
        db.commit()
        
        return {"message": f"Provider {request.name} configured successfully", "active": request.active}
        
    except Exception as e:
        logger.error("Failed to configure provider", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail="Failed to configure provider")

# ---- Event Integration Endpoints ----
@app.post("/notifications/v4/integration/entry-granted")
async def handle_entry_granted_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ENTRY_GRANTED event from Entry service"""
    try:
        await handle_entry_granted(event_data, db)
        return {"status": "processed", "event": "ENTRY_GRANTED"}
    except Exception as e:
        logger.error("Failed to process ENTRY_GRANTED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/user-created")
async def handle_user_created_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle USER_CREATED event from Identity service"""
    try:
        await handle_user_created(event_data, db)
        return {"status": "processed", "event": "USER_CREATED"}
    except Exception as e:
        logger.error("Failed to process USER_CREATED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/order-completed")
async def handle_order_completed_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        await handle_order_completed(event_data, db)
        return {"status": "processed", "event": "ORDER_COMPLETED"}
    except Exception as e:
        logger.error("Failed to process ORDER_COMPLETED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/invoice-posted")
async def handle_invoice_posted_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        await handle_invoice_posted(event_data, db)
        return {"status": "processed", "event": "INVOICE_POSTED"}
    except Exception as e:
        logger.error("Failed to process INVOICE_POSTED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

# ---- Legacy Endpoint (Deprecated) ----
@app.post("/notifications/replay/{delivery_id}")
async def replay_legacy(
    delivery_id: str = Path(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy replay endpoint - deprecated"""
    logger.warning("Legacy replay endpoint used", delivery_id=delivery_id)
    
    request = ReplayRequest(delivery_id=delivery_id)
    saga = ReplaySaga(db)
    result = await saga.execute(request, user_context)
    
    return {"replayed": delivery_id, "status": result["status"]}

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_notification_delivery(self, notification_id: str, delivery_data: Dict[str, Any]):
    """Process notification delivery asynchronously"""
    try:
        with SessionLocal() as db:
            # Get notification
            notification = db.execute(text("""
                SELECT * FROM notifications_new WHERE id = :id
            """), {"id": notification_id}).fetchone()
            
            if not notification:
                raise ValueError(f"Notification {notification_id} not found")
            
            # Process delivery logic here
            logger.info(f"Processing notification delivery for notification {notification_id}")
            
            # Update status
            db.execute(text("""
                UPDATE notifications_new 
                SET status = 'delivered', delivered_at = NOW()
                WHERE id = :id
            """), {"id": notification_id})
            
            db.commit()
            
            # Update metrics
            notification_operations_total.labels(operation="delivery", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process notification delivery for notification {notification_id}: {e}")
        notification_operations_total.labels(operation="delivery", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_email_notification(self, tenant_id: str, email_data: Dict[str, Any]):
    """Process email notification asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process email logic here
            logger.info(f"Processing email notification for tenant {tenant_id}")
            
            # Update metrics
            notification_operations_total.labels(operation="email", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process email notification for tenant {tenant_id}: {e}")
        notification_operations_total.labels(operation="email", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_notifications(self):
    """Clean up old notifications"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            
            # Clean up old notifications
            notification_result = db.execute(text("""
                DELETE FROM notifications_new 
                WHERE created_at < :cutoff_date AND status IN ('delivered', 'failed')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old delivery attempts
            delivery_result = db.execute(text("""
                DELETE FROM delivery_attempts_new 
                WHERE created_at < :cutoff_date AND status IN ('delivered', 'failed')
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {notification_result.rowcount} old notifications and {delivery_result.rowcount} old delivery attempts")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old notifications: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8222")))
    logger.info(f"Starting {SERVICE_NAME} service v{VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )