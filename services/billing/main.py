# Billing Service V2 - Consolidated Production Ready
# All billing functionality in a single file for simplicity

import os
import uuid
import logging
import json
import time
from datetime import datetime, timezone, date, timedelta
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, Any, Optional, List, Callable

from fastapi import FastAPI, HTTPException, Query, Depends, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import create_engine, func, text, Column, String, Boolean, DateTime, Integer, BigInteger, Text, UUID, ForeignKey, Date
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import JSONB
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from pydantic import BaseModel, Field, field_validator
import structlog

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

Base = declarative_base()

class VendorSettlement(Base):
    """Vendor Settlement: Main settlement record for vendor payouts"""
    __tablename__ = "vendor_settlements"
    
    settlement_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    settlement_period_start = Column(Date, nullable=False)
    settlement_period_end = Column(Date, nullable=False)
    total_sales_minor = Column(BigInteger, nullable=False, default=0)
    total_commission_minor = Column(BigInteger, nullable=False, default=0)
    total_adjustments_minor = Column(BigInteger, nullable=False, default=0)
    net_settlement_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    settlement_status = Column(String(20), nullable=False, default='pending')
    settlement_date = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    items = relationship("VendorSettlementItem", back_populates="settlement")
    adjustments = relationship("VendorSettlementAdjustment", back_populates="settlement")
    disputes = relationship("VendorDispute", back_populates="settlement")

class VendorSettlementItem(Base):
    """Vendor Settlement Item: Individual items within a settlement"""
    __tablename__ = "vendor_settlement_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), nullable=False)
    settlement_id = Column(UUID(as_uuid=True), ForeignKey('vendor_settlements.settlement_id'), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    payout_amount_minor = Column(BigInteger, nullable=False)
    commission_amount_minor = Column(BigInteger, nullable=False)
    fee_amount_minor = Column(BigInteger, nullable=False, default=0)
    net_amount_minor = Column(BigInteger, nullable=False)
    settlement_status = Column(String(20), nullable=False, default='pending')
    paid_out_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    settlement = relationship("VendorSettlement", back_populates="items")
    adjustments = relationship("VendorSettlementAdjustment", back_populates="settlement_item")
    disputes = relationship("VendorDispute", back_populates="settlement_item")

class VendorSettlementAdjustment(Base):
    """Vendor Settlement Adjustment: Adjustments to settlement amounts"""
    __tablename__ = "vendor_settlement_adjustments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_id = Column(UUID(as_uuid=True), ForeignKey('vendor_settlements.settlement_id'), nullable=False)
    settlement_item_id = Column(UUID(as_uuid=True), ForeignKey('vendor_settlement_items.id'), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    adjustment_amount_minor = Column(BigInteger, nullable=False)
    adjustment_reason = Column(String(255), nullable=False)
    adjustment_type = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False)
    adjustment_status = Column(String(20), nullable=False, default='pending')
    adjustment_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    settlement = relationship("VendorSettlement", back_populates="adjustments")
    settlement_item = relationship("VendorSettlementItem", back_populates="adjustments")

class VendorDispute(Base):
    """Vendor Dispute: Disputes related to settlements or items"""
    __tablename__ = "vendor_disputes"
    
    dispute_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_item_id = Column(UUID(as_uuid=True), ForeignKey('vendor_settlement_items.id'), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    dispute_type = Column(String(50), nullable=False)
    dispute_reason = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='open')
    resolution = Column(String(20), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    sla_deadline = Column(DateTime(timezone=True), nullable=False)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    
    # Relationships
    settlement_item = relationship("VendorSettlementItem", back_populates="disputes")

class VendorSettlementBatch(Base):
    """Vendor Settlement Batch: Batch processing for settlements"""
    __tablename__ = "vendor_settlement_batches"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    batch_number = Column(String(50), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    total_amount_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class TradeInvoice(Base):
    """Trade Invoice: Tenant invoices for billing"""
    __tablename__ = "trade_invoices"
    
    id = Column(String(120), primary_key=True)
    tenant_id = Column(String(100), nullable=False)
    invoice_number = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default='draft')
    amount_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    tax_total_minor = Column(BigInteger, nullable=False, default=0)
    subtotal_minor = Column(BigInteger, nullable=False, default=0)
    due_date = Column(Date, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    ar_customer_code = Column(String(100), nullable=True)
    terms = Column(String(20), nullable=False, default='NET30')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    lines = relationship("TradeInvoiceLine", back_populates="invoice")

class TradeInvoiceLine(Base):
    """Trade Invoice Line: Line items for invoices"""
    __tablename__ = "trade_invoice_lines"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(String(120), ForeignKey('trade_invoices.id'), nullable=False)
    line_number = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price_minor = Column(BigInteger, nullable=False)
    line_total_minor = Column(BigInteger, nullable=False)
    tax_minor = Column(BigInteger, nullable=False, default=0)
    tax_code = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    invoice = relationship("TradeInvoice", back_populates="lines")

class BillingOutboxEvent(Base):
    """Billing Outbox Event: For reliable event publishing"""
    __tablename__ = "billing_outbox_events"
    
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

# =============================================================================
# PAYLOADS (Pydantic)
# =============================================================================

class BaseBillingRequest(BaseModel):
    """Base request model with common fields"""
    tenant_id: str = Field(..., description="Tenant ID for multi-tenancy")
    
    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('tenant_id must be a valid UUID')

class InvoiceLineRequest(BaseModel):
    """Request model for invoice line items"""
    line_number: int = Field(..., description="Line number", ge=1)
    description: str = Field(..., description="Line item description", max_length=255)
    quantity: int = Field(..., description="Quantity", gt=0)
    unit_price_minor: int = Field(..., description="Unit price in minor units", ge=0)
    tax_minor: int = Field(0, description="Tax amount in minor units", ge=0)
    tax_code: Optional[str] = Field(None, description="Tax code", max_length=20)
    
    @property
    def line_total_minor(self) -> int:
        return (self.quantity * self.unit_price_minor) + self.tax_minor

class CreateInvoiceRequest(BaseBillingRequest):
    """Request model for creating invoices"""
    invoice_number: Optional[str] = Field(None, description="Invoice number", max_length=50)
    currency: str = Field("GBP", description="Currency code", max_length=3)
    due_date: Optional[date] = Field(None, description="Due date")
    lines: List[InvoiceLineRequest] = Field(..., description="Invoice line items", min_items=1)
    ar_customer_code: Optional[str] = Field(None, description="AR customer code", max_length=100)
    terms: str = Field("NET30", description="Payment terms", max_length=20)
    
    @field_validator('lines')
    @classmethod
    def validate_lines(cls, v):
        if not v:
            raise ValueError('At least one line item is required')
        
        # Check for duplicate line numbers
        line_numbers = [line.line_number for line in v]
        if len(line_numbers) != len(set(line_numbers)):
            raise ValueError('Line numbers must be unique')
        
        return v
    
    @property
    def subtotal_minor(self) -> int:
        return sum(line.quantity * line.unit_price_minor for line in self.lines)
    
    @property
    def tax_total_minor(self) -> int:
        return sum(line.tax_minor for line in self.lines)
    
    @property
    def total_minor(self) -> int:
        return self.subtotal_minor + self.tax_total_minor

class InvoiceResponse(BaseModel):
    """Response model for invoices"""
    id: str
    tenant_id: str
    invoice_number: Optional[str]
    status: str
    amount_minor: int
    currency: str
    tax_total_minor: int
    subtotal_minor: int
    due_date: Optional[date]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    lines: List[Dict[str, Any]] = []

class SettlementItemRequest(BaseModel):
    """Request model for settlement items"""
    order_id: Optional[str] = Field(None, description="Order ID")
    sub_order_id: Optional[str] = Field(None, description="Sub-order ID")
    payout_amount_minor: int = Field(..., description="Payout amount in minor units", ge=0)
    commission_amount_minor: int = Field(..., description="Commission amount in minor units", ge=0)
    fee_amount_minor: int = Field(0, description="Fee amount in minor units", ge=0)
    notes: Optional[str] = Field(None, description="Item notes")
    
    @property
    def net_amount_minor(self) -> int:
        return self.payout_amount_minor - self.commission_amount_minor - self.fee_amount_minor

class CreateSettlementRequest(BaseBillingRequest):
    """Request model for creating vendor settlements"""
    vendor_id: str = Field(..., description="Vendor ID")
    settlement_period_start: date = Field(..., description="Settlement period start date")
    settlement_period_end: date = Field(..., description="Settlement period end date")
    currency: str = Field("GBP", description="Currency code", max_length=3)
    items: List[SettlementItemRequest] = Field(..., description="Settlement items", min_items=1)
    notes: Optional[str] = Field(None, description="Settlement notes")
    
    @field_validator('vendor_id')
    @classmethod
    def validate_vendor_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('vendor_id must be a valid UUID')

class SettlementResponse(BaseModel):
    """Response model for settlements"""
    settlement_id: str
    vendor_id: str
    tenant_id: str
    settlement_period_start: date
    settlement_period_end: date
    total_sales_minor: int
    total_commission_minor: int
    net_settlement_minor: int
    currency: str
    settlement_status: str
    settlement_date: Optional[datetime]
    created_at: datetime

# =============================================================================
# SAGAS
# =============================================================================

class BillingSaga:
    """Base saga class for billing operations with compensation logic"""
    
    def __init__(self, db_session):
        self.db_session = db_session
        self.compensation_steps: List[Callable] = []
        self.executed_steps: List[str] = []
    
    async def execute_step(self, step_name: str, action: Callable, compensation: Optional[Callable] = None):
        """Execute a saga step with compensation tracking"""
        try:
            logging.info(f"Executing saga step: {step_name}")
            result = await action()
            self.executed_steps.append(step_name)
            
            if compensation:
                self.compensation_steps.insert(0, compensation)  # LIFO for compensation
            
            logging.info(f"Saga step completed: {step_name}")
            return result
            
        except Exception as e:
            logging.error(f"Saga step failed: {step_name} - {str(e)}")
            await self.compensate()
            raise Exception(f"Step {step_name} failed: {str(e)}")
    
    async def compensate(self):
        """Execute compensation steps in reverse order"""
        logging.warning(f"Starting compensation for {len(self.compensation_steps)} steps")
        
        for i, compensation_step in enumerate(self.compensation_steps):
            try:
                logging.info(f"Executing compensation step {i+1}/{len(self.compensation_steps)}")
                await compensation_step()
            except Exception as e:
                logging.error(f"Compensation step {i+1} failed: {str(e)}")
                # Continue with other compensation steps
        
        logging.warning("Compensation completed")

class InvoiceCreationSaga(BillingSaga):
    """Saga for creating invoices with validation and ledger integration"""
    
    def __init__(self, db_session, request: CreateInvoiceRequest):
        super().__init__(db_session)
        self.request = request
        self.invoice_id: Optional[str] = None
        self.line_ids: List[int] = []
    
    async def execute(self) -> str:
        """Execute the complete invoice creation saga"""
        
        # Step 1: Create invoice record
        invoice_id = await self.execute_step(
            "create_invoice",
            lambda: self._create_invoice_record(),
            lambda: self._delete_invoice_record()
        )
        
        # Step 2: Create invoice lines
        await self.execute_step(
            "create_invoice_lines",
            lambda: self._create_invoice_lines(invoice_id),
            lambda: self._delete_invoice_lines()
        )
        
        # Step 3: Post invoice (change status to posted)
        await self.execute_step(
            "post_invoice",
            lambda: self._post_invoice(invoice_id),
            lambda: self._unpost_invoice(invoice_id)
        )
        
        # Step 4: Publish event
        await self.execute_step(
            "publish_event",
            lambda: self._publish_invoice_created_event(invoice_id),
            None  # No compensation needed for event publishing
        )
        
        return invoice_id
    
    def _create_invoice_record(self) -> str:
        """Create the main invoice record"""
        invoice_id = f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        
        invoice = TradeInvoice(
            id=invoice_id,
            tenant_id=self.request.tenant_id,
            invoice_number=self.request.invoice_number or f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            status='draft',
            amount_minor=self.request.total_minor,
            currency=self.request.currency,
            tax_total_minor=self.request.tax_total_minor,
            subtotal_minor=self.request.subtotal_minor,
            due_date=self.request.due_date,
            ar_customer_code=self.request.ar_customer_code,
            terms=self.request.terms
        )
        
        self.db_session.add(invoice)
        self.db_session.commit()
        
        self.invoice_id = invoice_id
        return invoice_id
    
    def _create_invoice_lines(self, invoice_id: str):
        """Create invoice line items"""
        for line in self.request.lines:
            invoice_line = TradeInvoiceLine(
                invoice_id=invoice_id,
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                line_total_minor=line.line_total_minor,
                tax_minor=line.tax_minor,
                tax_code=line.tax_code
            )
            
            self.db_session.add(invoice_line)
            self.db_session.flush()  # Get the ID
            self.line_ids.append(invoice_line.id)
        
        self.db_session.commit()
    
    def _post_invoice(self, invoice_id: str):
        """Post the invoice (change status to posted)"""
        invoice = self.db_session.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
        if invoice:
            invoice.status = 'posted'
            invoice.posted_at = datetime.now(timezone.utc)
            self.db_session.commit()
    
    def _publish_invoice_created_event(self, invoice_id: str):
        """Publish invoice created event"""
        event_data = {
            "invoice_id": invoice_id,
            "tenant_id": self.request.tenant_id,
            "amount_minor": self.request.total_minor,
            "currency": self.request.currency,
            "status": "posted",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        outbox_event = BillingOutboxEvent(
            aggregate_id=uuid.uuid4(),
            event_type="INVOICE_CREATED",
            event_data=json.dumps(event_data),
            status="pending"
        )
        
        self.db_session.add(outbox_event)
        self.db_session.commit()
    
    def _delete_invoice_record(self):
        """Compensation: Delete invoice record"""
        if self.invoice_id:
            self.db_session.query(TradeInvoice).filter(TradeInvoice.id == self.invoice_id).delete()
            self.db_session.commit()
    
    def _delete_invoice_lines(self):
        """Compensation: Delete invoice lines"""
        if self.line_ids:
            self.db_session.query(TradeInvoiceLine).filter(TradeInvoiceLine.id.in_(self.line_ids)).delete()
            self.db_session.commit()
    
    def _unpost_invoice(self, invoice_id: str):
        """Compensation: Unpost invoice"""
        invoice = self.db_session.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
        if invoice:
            invoice.status = 'draft'
            invoice.posted_at = None
            self.db_session.commit()

class SettlementCreationSaga(BillingSaga):
    """Saga for creating vendor settlements"""
    
    def __init__(self, db_session, request: CreateSettlementRequest):
        super().__init__(db_session)
        self.request = request
        self.settlement_id: Optional[str] = None
        self.batch_id: Optional[str] = None
    
    async def execute(self) -> str:
        """Execute the complete settlement creation saga"""
        
        # Step 1: Create settlement batch
        batch_id = await self.execute_step(
            "create_batch",
            lambda: self._create_settlement_batch(),
            lambda: self._delete_settlement_batch()
        )
        
        # Step 2: Create settlement
        settlement_id = await self.execute_step(
            "create_settlement",
            lambda: self._create_settlement(batch_id),
            lambda: self._delete_settlement()
        )
        
        # Step 3: Create settlement items
        await self.execute_step(
            "create_items",
            lambda: self._create_settlement_items(settlement_id, batch_id),
            lambda: self._delete_settlement_items()
        )
        
        # Step 4: Process settlement
        await self.execute_step(
            "process_settlement",
            lambda: self._process_settlement(settlement_id),
            lambda: self._unprocess_settlement(settlement_id)
        )
        
        return settlement_id
    
    def _create_settlement_batch(self) -> str:
        """Create settlement batch"""
        batch_id = str(uuid.uuid4())
        
        batch = VendorSettlementBatch(
            id=batch_id,
            tenant_id=self.request.tenant_id,
            batch_number=f"BATCH-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            period_start=self.request.settlement_period_start,
            period_end=self.request.settlement_period_end,
            currency=self.request.currency,
            status='pending'
        )
        
        self.db_session.add(batch)
        self.db_session.commit()
        
        self.batch_id = batch_id
        return batch_id
    
    def _create_settlement(self, batch_id: str) -> str:
        """Create settlement record"""
        settlement_id = str(uuid.uuid4())
        
        total_sales = sum(item.payout_amount_minor for item in self.request.items)
        total_commission = sum(item.commission_amount_minor for item in self.request.items)
        net_settlement = sum(item.net_amount_minor for item in self.request.items)
        
        settlement = VendorSettlement(
            settlement_id=settlement_id,
            vendor_id=self.request.vendor_id,
            tenant_id=self.request.tenant_id,
            settlement_period_start=self.request.settlement_period_start,
            settlement_period_end=self.request.settlement_period_end,
            total_sales_minor=total_sales,
            total_commission_minor=total_commission,
            net_settlement_minor=net_settlement,
            currency=self.request.currency,
            settlement_status='pending'
        )
        
        self.db_session.add(settlement)
        self.db_session.commit()
        
        self.settlement_id = settlement_id
        return settlement_id
    
    def _create_settlement_items(self, settlement_id: str, batch_id: str):
        """Create settlement items"""
        for item in self.request.items:
            settlement_item = VendorSettlementItem(
                batch_id=batch_id,
                settlement_id=settlement_id,
                vendor_id=self.request.vendor_id,
                tenant_id=self.request.tenant_id,
                payout_amount_minor=item.payout_amount_minor,
                commission_amount_minor=item.commission_amount_minor,
                fee_amount_minor=item.fee_amount_minor,
                net_amount_minor=item.net_amount_minor,
                settlement_status='pending'
            )
            
            self.db_session.add(settlement_item)
        
        self.db_session.commit()
    
    def _process_settlement(self, settlement_id: str):
        """Process settlement (change status to processed)"""
        settlement = self.db_session.query(VendorSettlement).filter(VendorSettlement.settlement_id == settlement_id).first()
        if settlement:
            settlement.settlement_status = 'processed'
            settlement.settlement_date = datetime.now(timezone.utc)
            self.db_session.commit()
    
    def _delete_settlement_batch(self):
        """Compensation: Delete settlement batch"""
        if self.batch_id:
            self.db_session.query(VendorSettlementBatch).filter(VendorSettlementBatch.id == self.batch_id).delete()
            self.db_session.commit()
    
    def _delete_settlement(self):
        """Compensation: Delete settlement"""
        if self.settlement_id:
            self.db_session.query(VendorSettlement).filter(VendorSettlement.settlement_id == self.settlement_id).delete()
            self.db_session.commit()
    
    def _delete_settlement_items(self):
        """Compensation: Delete settlement items"""
        if self.settlement_id:
            self.db_session.query(VendorSettlementItem).filter(VendorSettlementItem.settlement_id == self.settlement_id).delete()
            self.db_session.commit()
    
    def _unprocess_settlement(self, settlement_id: str):
        """Compensation: Unprocess settlement"""
        settlement = self.db_session.query(VendorSettlement).filter(VendorSettlement.settlement_id == settlement_id).first()
        if settlement:
            settlement.settlement_status = 'pending'
            settlement.settlement_date = None
            self.db_session.commit()

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5000/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
SERVICE_NAME = "billing-service-v2"
SERVICE_VERSION = "2.0.0"

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = structlog.get_logger()

# Database setup
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Prometheus metrics
try:
    billing_requests = Counter('billing_requests_total', 'Total billing requests', ['method', 'endpoint', 'status'])
    billing_requests_duration = Histogram('billing_requests_duration_seconds', 'Billing request duration')
    billing_requests_in_flight = Gauge('billing_requests_in_flight', 'Billing requests currently being processed')
    billing_saga_duration = Histogram('billing_saga_duration_seconds', 'Billing saga execution duration', ['saga_type'])
    billing_saga_failures = Counter('billing_saga_failures_total', 'Total billing saga failures', ['saga_type', 'step'])
except ValueError:
    # Metrics already registered
    pass

# =============================================================================
# UTILITIES
# =============================================================================

def validate_uuid(uuid_string: str) -> str:
    """Validate and return UUID string"""
    try:
        uuid.UUID(uuid_string)
        return uuid_string
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

async def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context"""
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET app.current_user_id = :user_id"), {"user_id": user_id})

# =============================================================================
# EXCEPTIONS
# =============================================================================

class BillingValidationError(Exception):
    """Billing validation error"""
    pass

class BillingNotFoundError(Exception):
    """Billing resource not found error"""
    pass

class BillingDuplicateError(Exception):
    """Billing duplicate resource error"""
    pass

class SettlementProcessingError(Exception):
    """Settlement processing error"""
    pass

# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    log.info("Starting Billing Service V2", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Initialize database tables
    Base.metadata.create_all(bind=engine)
    
    yield
    
    log.info("Shutting down Billing Service V2")

app = FastAPI(
    title="Billing Service V2",
    description="Production-ready billing service with invoice creation and vendor settlements",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Exception handlers
@app.exception_handler(BillingValidationError)
async def billing_validation_exception_handler(request: Request, exc: BillingValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": f"Validation error: {str(exc)}"}
    )

@app.exception_handler(BillingNotFoundError)
async def billing_not_found_exception_handler(request: Request, exc: BillingNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"detail": f"Resource not found: {str(exc)}"}
    )

@app.exception_handler(BillingDuplicateError)
async def billing_duplicate_exception_handler(request: Request, exc: BillingDuplicateError):
    return JSONResponse(
        status_code=409,
        content={"detail": f"Resource already exists: {str(exc)}"}
    )

@app.exception_handler(SettlementProcessingError)
async def settlement_processing_exception_handler(request: Request, exc: SettlementProcessingError):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Settlement processing error: {str(exc)}"}
    )

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connectivity
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                "database": {"status": "healthy"}
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

@app.post("/billing/v2/invoices", response_model=InvoiceResponse)
async def create_invoice(request: CreateInvoiceRequest, db = Depends(get_db)):
    """Create a new invoice using saga pattern"""
    billing_requests_in_flight.inc()
    
    try:
        with billing_requests_duration.time():
            # Set RLS context
            set_rls_context(db, request.tenant_id)
            
            # Execute saga
            saga = InvoiceCreationSaga(db, request)
            invoice_id = await saga.execute()
            
            # Get created invoice
            invoice = db.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
            if not invoice:
                raise BillingNotFoundError(f"Invoice {invoice_id} not found after creation")
            
            # Get invoice lines
            lines = db.query(TradeInvoiceLine).filter(TradeInvoiceLine.invoice_id == invoice_id).all()
            
            billing_requests.labels(method='POST', endpoint='/billing/v2/invoices', status='success').inc()
            
            return InvoiceResponse(
                id=invoice.id,
                tenant_id=invoice.tenant_id,
                invoice_number=invoice.invoice_number,
                status=invoice.status,
                amount_minor=invoice.amount_minor,
                currency=invoice.currency,
                tax_total_minor=invoice.tax_total_minor,
                subtotal_minor=invoice.subtotal_minor,
                due_date=invoice.due_date,
                posted_at=invoice.posted_at,
                created_at=invoice.created_at,
                updated_at=invoice.updated_at,
                lines=[{
                    "id": line.id,
                    "line_number": line.line_number,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price_minor": line.unit_price_minor,
                    "line_total_minor": line.line_total_minor,
                    "tax_minor": line.tax_minor,
                    "tax_code": line.tax_code
                } for line in lines]
            )
            
    except Exception as e:
        billing_requests.labels(method='POST', endpoint='/billing/v2/invoices', status='error').inc()
        log.error("Failed to create invoice", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")
    
    finally:
        billing_requests_in_flight.dec()

@app.get("/billing/v2/settlements")
async def list_settlements(
    tenant_id: str = Query(..., description="Tenant ID"),
    vendor_id: Optional[str] = Query(None, description="Vendor ID filter"),
    status: Optional[str] = Query(None, description="Settlement status filter"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    limit: int = Query(100, description="Number of results to return"),
    offset: int = Query(0, description="Number of results to skip"),
    db = Depends(get_db)
):
    """List settlements with filtering and pagination"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(VendorSettlement).filter(VendorSettlement.tenant_id == tenant_id)
        
        if vendor_id:
            query = query.filter(VendorSettlement.vendor_id == vendor_id)
        
        if status:
            query = query.filter(VendorSettlement.settlement_status == status)
        
        if start_date:
            query = query.filter(VendorSettlement.settlement_period_start >= start_date)
        
        if end_date:
            query = query.filter(VendorSettlement.settlement_period_end <= end_date)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        settlements = query.order_by(VendorSettlement.created_at.desc()).offset(offset).limit(limit).all()
        
        return {
            "settlements": [
                {
                    "settlement_id": str(settlement.settlement_id),
                    "vendor_id": str(settlement.vendor_id),
                    "tenant_id": str(settlement.tenant_id),
                    "settlement_period_start": settlement.settlement_period_start.isoformat(),
                    "settlement_period_end": settlement.settlement_period_end.isoformat(),
                    "total_sales_minor": settlement.total_sales_minor,
                    "total_commission_minor": settlement.total_commission_minor,
                    "net_settlement_minor": settlement.net_settlement_minor,
                    "currency": settlement.currency,
                    "settlement_status": settlement.settlement_status,
                    "settlement_date": settlement.settlement_date.isoformat() if settlement.settlement_date else None,
                    "created_at": settlement.created_at.isoformat(),
                    "updated_at": settlement.updated_at.isoformat() if settlement.updated_at else None
                }
                for settlement in settlements
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        log.error("Failed to list settlements", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to list settlements: {str(e)}")

@app.post("/billing/v2/settlements", response_model=SettlementResponse)
async def create_settlement(request: CreateSettlementRequest, db = Depends(get_db)):
    """Create a new vendor settlement using saga pattern"""
    billing_requests_in_flight.inc()
    
    try:
        with billing_requests_duration.time():
            # Set RLS context
            set_rls_context(db, request.tenant_id)
            
            # Execute saga
            saga = SettlementCreationSaga(db, request)
            settlement_id = await saga.execute()
            
            # Get created settlement
            settlement = db.query(VendorSettlement).filter(VendorSettlement.settlement_id == settlement_id).first()
            if not settlement:
                raise BillingNotFoundError(f"Settlement {settlement_id} not found after creation")
            
            billing_requests.labels(method='POST', endpoint='/billing/v2/settlements', status='success').inc()
            
            return SettlementResponse(
                settlement_id=str(settlement.settlement_id),
                vendor_id=str(settlement.vendor_id),
                tenant_id=str(settlement.tenant_id),
                settlement_period_start=settlement.settlement_period_start,
                settlement_period_end=settlement.settlement_period_end,
                total_sales_minor=settlement.total_sales_minor,
                total_commission_minor=settlement.total_commission_minor,
                net_settlement_minor=settlement.net_settlement_minor,
                currency=settlement.currency,
                settlement_status=settlement.settlement_status,
                settlement_date=settlement.settlement_date,
                created_at=settlement.created_at
            )
            
    except Exception as e:
        billing_requests.labels(method='POST', endpoint='/billing/v2/settlements', status='error').inc()
        log.error("Failed to create settlement", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create settlement: {str(e)}")
    
    finally:
        billing_requests_in_flight.dec()

@app.get("/billing/v2/invoices")
async def list_invoices(
    tenant_id: str = Query(..., description="Tenant ID"),
    status: Optional[str] = Query(None, description="Invoice status filter"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    limit: int = Query(100, description="Number of results to return"),
    offset: int = Query(0, description="Number of results to skip"),
    db = Depends(get_db)
):
    """List invoices with filtering and pagination"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(TradeInvoice).filter(TradeInvoice.tenant_id == tenant_id)
        
        if status:
            query = query.filter(TradeInvoice.status == status)
        
        if start_date:
            query = query.filter(TradeInvoice.created_at >= start_date)
        
        if end_date:
            query = query.filter(TradeInvoice.created_at <= end_date)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        invoices = query.order_by(TradeInvoice.created_at.desc()).offset(offset).limit(limit).all()
        
        return {
            "invoices": [
                {
                    "id": invoice.id,
                    "tenant_id": invoice.tenant_id,
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                    "amount_minor": invoice.amount_minor,
                    "currency": invoice.currency,
                    "tax_total_minor": invoice.tax_total_minor,
                    "subtotal_minor": invoice.subtotal_minor,
                    "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                    "posted_at": invoice.posted_at.isoformat() if invoice.posted_at else None,
                    "created_at": invoice.created_at.isoformat(),
                    "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None
                }
                for invoice in invoices
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        log.error("Failed to list invoices", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to list invoices: {str(e)}")

class CreateDisputeRequest(BaseModel):
    """Request model for creating disputes"""
    tenant_id: str = Field(..., description="Tenant ID")
    settlement_id: Optional[str] = Field(None, description="Settlement ID")
    settlement_item_id: Optional[str] = Field(None, description="Settlement item ID")
    dispute_amount_minor: int = Field(..., description="Dispute amount in minor units", ge=0)
    dispute_reason: str = Field(..., description="Dispute reason", max_length=255)
    dispute_notes: Optional[str] = Field(None, description="Dispute notes")
    
    @field_validator('tenant_id', 'settlement_id', 'settlement_item_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError(f'Invalid UUID format: {v}')

class DisputeResponse(BaseModel):
    """Response model for disputes"""
    id: str
    settlement_id: Optional[str]
    settlement_item_id: Optional[str]
    tenant_id: str
    dispute_amount_minor: int
    dispute_reason: str
    dispute_status: str
    dispute_notes: Optional[str]
    created_at: datetime

@app.post("/billing/v2/disputes", response_model=DisputeResponse)
async def create_dispute(request: CreateDisputeRequest, db = Depends(get_db)):
    """Create a new dispute"""
    try:
        # Set RLS context
        set_rls_context(db, request.tenant_id)
        
        # Validate that either settlement_id or settlement_item_id is provided
        if not request.settlement_id and not request.settlement_item_id:
            raise HTTPException(status_code=400, detail="Either settlement_id or settlement_item_id must be provided")
        
        # Create dispute
        dispute = VendorDispute(
            settlement_item_id=request.settlement_item_id or request.settlement_id,
            vendor_id="550e8400-e29b-41d4-a716-446655440008",  # Default vendor for testing
            dispute_type="amount_dispute",
            dispute_reason=request.dispute_reason,
            status='open',
            sla_deadline=datetime.now(timezone.utc) + timedelta(days=7),  # 7 days SLA
            tenant_id=request.tenant_id
        )
        
        db.add(dispute)
        db.commit()
        db.refresh(dispute)
        
        log.info("Created dispute", dispute_id=str(dispute.id), tenant_id=request.tenant_id)
        
        return DisputeResponse(
            id=str(dispute.dispute_id),
            settlement_id=request.settlement_id,
            settlement_item_id=str(dispute.settlement_item_id),
            tenant_id=str(dispute.tenant_id),
            dispute_amount_minor=request.dispute_amount_minor,
            dispute_reason=dispute.dispute_reason,
            dispute_status=dispute.status,
            dispute_notes=request.dispute_notes,
            created_at=dispute.created_at
        )
        
    except Exception as e:
        log.error("Failed to create dispute", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create dispute: {str(e)}")

class CreateAdjustmentRequest(BaseModel):
    """Request model for creating adjustments"""
    tenant_id: str = Field(..., description="Tenant ID")
    settlement_id: str = Field(..., description="Settlement ID")
    settlement_item_id: Optional[str] = Field(None, description="Settlement item ID")
    adjustment_amount_minor: int = Field(..., description="Adjustment amount in minor units")
    adjustment_reason: str = Field(..., description="Adjustment reason", max_length=255)
    adjustment_type: str = Field(..., description="Adjustment type", pattern="^(commission|chargeback|refund|bonus|penalty)$")
    currency: str = Field("GBP", description="Currency code", max_length=3)
    adjustment_notes: Optional[str] = Field(None, description="Adjustment notes")
    
    @field_validator('tenant_id', 'settlement_id', 'settlement_item_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError(f'Invalid UUID format: {v}')

class AdjustmentResponse(BaseModel):
    """Response model for adjustments"""
    id: str
    settlement_id: str
    settlement_item_id: Optional[str]
    tenant_id: str
    adjustment_amount_minor: int
    adjustment_reason: str
    adjustment_type: str
    currency: str
    adjustment_status: str
    created_at: datetime

@app.post("/billing/v2/adjustments", response_model=AdjustmentResponse)
async def create_adjustment(request: CreateAdjustmentRequest, db = Depends(get_db)):
    """Create a new settlement adjustment"""
    try:
        # Set RLS context
        set_rls_context(db, request.tenant_id)
        
        # Create adjustment
        adjustment = VendorSettlementAdjustment(
            settlement_id=request.settlement_id,
            settlement_item_id=request.settlement_item_id,
            tenant_id=request.tenant_id,
            adjustment_amount_minor=request.adjustment_amount_minor,
            adjustment_reason=request.adjustment_reason,
            adjustment_type=request.adjustment_type,
            currency=request.currency,
            adjustment_status='pending',
            adjustment_notes=request.adjustment_notes
        )
        
        db.add(adjustment)
        db.commit()
        db.refresh(adjustment)
        
        log.info("Created adjustment", adjustment_id=str(adjustment.id), tenant_id=request.tenant_id)
        
        return AdjustmentResponse(
            id=str(adjustment.id),
            settlement_id=str(adjustment.settlement_id),
            settlement_item_id=str(adjustment.settlement_item_id) if adjustment.settlement_item_id else None,
            tenant_id=str(adjustment.tenant_id),
            adjustment_amount_minor=adjustment.adjustment_amount_minor,
            adjustment_reason=adjustment.adjustment_reason,
            adjustment_type=adjustment.adjustment_type,
            currency=adjustment.currency,
            adjustment_status=adjustment.adjustment_status,
            created_at=adjustment.created_at
        )
        
    except Exception as e:
        log.error("Failed to create adjustment", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create adjustment: {str(e)}")

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/billing/v2/integration/ledger/invoice-posted")
async def notify_ledger_invoice_posted(
    tenant_id: str = Body(...),
    invoice_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None)
):
    """Integration endpoint for Ledger service to handle INVOICE_POSTED events"""
    try:
        log.info("Processing INVOICE_POSTED event for ledger integration", invoice_id=invoice_id, tenant_id=tenant_id)
        
        # Validate invoice exists
        with SessionLocal() as db:
            invoice = db.execute(
                text("SELECT * FROM trade_invoices WHERE id = :invoice_id AND tenant_id = :tenant_id"),
                {"invoice_id": invoice_id, "tenant_id": tenant_id}
            ).fetchone()

            if not invoice:
                raise HTTPException(status_code=404, detail="Invoice not found")

            # Prepare event data for ledger
            ledger_event_data = {
                "tenant_id": tenant_id,
                "invoice_id": invoice_id,
                "total_amount_minor": total_amount_minor,
                "currency": currency,
                "customer_id": customer_id,
                "event_source": "billing_service"
            }

        # Notify ledger service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8086/ledger/v4/events/invoice-posted",
                    json=ledger_event_data
                )

                if response.status_code == 200:
                    log.info("Successfully notified ledger service", invoice_id=invoice_id)
                    return {"ok": True, "ledger_notified": True, "invoice_id": invoice_id}
                else:
                    log.warning("Ledger service returned error status", invoice_id=invoice_id, status_code=response.status_code)
                    return {"ok": False, "ledger_notified": False, "invoice_id": invoice_id, "error": "Ledger service error"}
        except Exception as e:
            log.error("Failed to notify ledger service", invoice_id=invoice_id, error=str(e))
            return {"ok": False, "ledger_notified": False, "invoice_id": invoice_id, "error": str(e)}
            
    except Exception as e:
        log.error("Error processing INVOICE_POSTED event", invoice_id=invoice_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process INVOICE_POSTED event: {str(e)}")

@app.post("/billing/v2/integration/cv-gateway/invoice-creation")
async def create_invoice_for_cv_order(
    tenant_id: str = Body(...),
    order_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None),
    items: List[Dict[str, Any]] = Body(...)
):
    """Integration endpoint for CV Gateway service to create invoices"""
    try:
        log.info("Processing invoice creation for CV Gateway", order_id=order_id, tenant_id=tenant_id)
        
        # Create invoice using existing invoice creation logic
        invoice_data = {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "currency": currency,
            "total_amount_minor": total_amount_minor,
            "tax_total_minor": int(total_amount_minor * 0.2),  # 20% tax
            "subtotal_minor": int(total_amount_minor * 0.8),   # 80% subtotal
            "status": "draft",
            "due_date": datetime.now(timezone.utc) + timedelta(days=30),
            "items": items
        }
        
        # Use existing invoice creation endpoint logic
        try:
            # Create invoice lines
            invoice_lines = []
            for item in items:
                line_data = {
                    "product_id": item.get("product_id"),
                    "description": item.get("description", "CV Order Item"),
                    "quantity": item.get("quantity", 1),
                    "unit_price_minor": item.get("unit_price_minor", 0),
                    "total_price_minor": item.get("total_price_minor", 0),
                    "tax_minor": int(item.get("total_price_minor", 0) * 0.2),
                    "tax_code": "VAT_STANDARD"
                }
                invoice_lines.append(line_data)
            
            invoice_data["lines"] = invoice_lines
            
            # Create invoice using existing logic
            invoice = await create_invoice(invoice_data)
            
            if invoice:
                log.info("Successfully created invoice for CV order", invoice_id=invoice.get("id"), order_id=order_id)
                return {"ok": True, "invoice_created": True, "invoice_id": invoice.get("id"), "order_id": order_id}
            else:
                log.warning("Failed to create invoice for CV order", order_id=order_id)
                return {"ok": False, "invoice_created": False, "order_id": order_id, "error": "Invoice creation failed"}
                
        except Exception as e:
            log.error("Failed to create invoice for CV order", order_id=order_id, error=str(e))
            return {"ok": False, "invoice_created": False, "order_id": order_id, "error": str(e)}
            
    except Exception as e:
        log.error("Error processing invoice creation for CV Gateway", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process invoice creation: {str(e)}")

@app.get("/billing/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8000"},
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"},
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error("Error getting integration status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

@app.get("/billing/v2/reports/ar-aging")
async def get_ar_aging_report(
    tenant_id: str = Query(..., description="Tenant ID"),
    as_of_date: Optional[date] = Query(None, description="As of date for aging report"),
    currency: Optional[str] = Query("GBP", description="Currency filter"),
    db = Depends(get_db)
):
    """Get accounts receivable aging report"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        if not as_of_date:
            as_of_date = date.today()
        
        # Calculate aging buckets
        current_cutoff = as_of_date
        days_31_60 = current_cutoff - timedelta(days=30)
        days_61_90 = current_cutoff - timedelta(days=60)
        days_over_90 = current_cutoff - timedelta(days=90)
        
        # Build base query with currency filter
        base_query = db.query(TradeInvoice).filter(
            TradeInvoice.tenant_id == tenant_id,
            TradeInvoice.status == 'posted',
            TradeInvoice.currency == currency
        )
        
        # Get invoices by aging bucket
        current_query = base_query.filter(TradeInvoice.due_date >= current_cutoff).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_31_60 = base_query.filter(
            TradeInvoice.due_date >= days_31_60,
            TradeInvoice.due_date < current_cutoff
        ).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_61_90 = base_query.filter(
            TradeInvoice.due_date >= days_61_90,
            TradeInvoice.due_date < days_31_60
        ).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_over_90 = base_query.filter(TradeInvoice.due_date < days_61_90).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        total_ar = current_query + bucket_31_60 + bucket_61_90 + bucket_over_90
        
        return {
            "tenant_id": tenant_id,
            "as_of_date": as_of_date.isoformat(),
            "currency": currency,
            "aging_buckets": {
                "current": current_query,
                "31_60": bucket_31_60,
                "61_90": bucket_61_90,
                "over_90": bucket_over_90
            },
            "total_ar_minor": total_ar
        }
        
    except Exception as e:
        log.error("Failed to generate AR aging report", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to generate AR aging report: {str(e)}")

@app.post("/billing/v2/events/retry")
async def retry_outbox_events(
    tenant_id: str = Query(..., description="Tenant ID"),
    max_retries: int = Query(3, description="Maximum retry attempts"),
    db = Depends(get_db)
):
    """Retry pending outbox events"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Get pending events that haven't exceeded max retries
        pending_events = db.query(BillingOutboxEvent).filter(
            BillingOutboxEvent.status == 'pending',
            BillingOutboxEvent.retry_count < max_retries
        ).limit(100).all()
        
        processed_count = 0
        failed_count = 0
        
        for event in pending_events:
            try:
                # Simulate event publishing (in real implementation, this would call external services)
                log.info("Processing outbox event", event_id=str(event.event_id), event_type=event.event_type)
                
                # Mark as published
                event.status = 'published'
                event.published_at = datetime.now(timezone.utc)
                event.retry_count += 1
                
                processed_count += 1
                
            except Exception as e:
                log.error("Failed to process outbox event", event_id=str(event.event_id), error=str(e))
                event.retry_count += 1
                
                if event.retry_count >= max_retries:
                    event.status = 'failed'
                
                failed_count += 1
        
        db.commit()
        
        return {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "total_events": len(pending_events)
        }
        
    except Exception as e:
        log.error("Failed to retry outbox events", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to retry outbox events: {str(e)}")

# Event handlers for integration
@app.post("/billing/v2/events/order-completed")
async def handle_order_completed(event_data: Dict[str, Any], db = Depends(get_db)):
    """Handle ORDER_COMPLETED event from orders service"""
    try:
        log.info("Handling ORDER_COMPLETED event", event_data=event_data)
        
        tenant_id = event_data.get("tenant_id")
        vendor_id = event_data.get("vendor_id")
        order_id = event_data.get("order_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if tenant_id and vendor_id and total_amount_minor > 0:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Create settlement item for this order
            settlement_item = SettlementItemRequest(
                order_id=order_id,
                payout_amount_minor=total_amount_minor,
                commission_amount_minor=int(total_amount_minor * 0.05),  # 5% commission
                fee_amount_minor=0,
                notes=f"Settlement for order {order_id}"
            )
            
            # Create settlement request
            settlement_request = CreateSettlementRequest(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                settlement_period_start=date.today(),
                settlement_period_end=date.today(),
                currency=currency,
                items=[settlement_item]
            )
            
            # Execute settlement saga
            saga = SettlementCreationSaga(db, settlement_request)
            settlement_id = await saga.execute()
            
            log.info("Created settlement from order", settlement_id=settlement_id, order_id=order_id)
            
            return {"status": "success", "settlement_id": settlement_id}
        
        return {"status": "skipped", "reason": "Missing required fields"}
        
    except Exception as e:
        log.error("Failed to handle ORDER_COMPLETED event", error=str(e), event_data=event_data)
        raise HTTPException(status_code=500, detail=f"Failed to handle ORDER_COMPLETED event: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
