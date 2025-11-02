from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Integer, Date, DateTime, BigInteger, Text, ForeignKey, Boolean, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

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
    status = Column(String(20), nullable=False, default='processing')
    total_amount_minor = Column(BigInteger, nullable=False, default=0)
    settlement_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


# Phase 4: Cost Centre Budgeting Models
class CostCentre(Base):
    """Cost Centre for budget management - Phase 4"""
    __tablename__ = "cost_centres"

    cost_centre_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(200), nullable=False)
    code = Column(String(50), nullable=False)  # Unique code like "IT-001", "MKT-001"
    description = Column(Text, nullable=True)
    parent_cost_centre_id = Column(UUID(as_uuid=True), ForeignKey('cost_centres.cost_centre_id'), nullable=True)
    budget_owner_id = Column(UUID(as_uuid=True), nullable=False)  # User ID who owns the budget
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship for hierarchical cost centres
    parent_cost_centre = relationship("CostCentre", remote_side=[cost_centre_id])


class Budget(Base):
    """Budget for cost centres - Phase 4"""
    __tablename__ = "budgets"

    budget_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_centre_id = Column(UUID(as_uuid=True), ForeignKey('cost_centres.cost_centre_id'), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    budget_year = Column(Integer, nullable=False)
    budget_month = Column(Integer, nullable=False)  # For monthly budgets
    budget_type = Column(String(50), nullable=False)  # "annual", "monthly", "project"
    budget_amount_minor = Column(BigInteger, nullable=False)
    spent_amount_minor = Column(BigInteger, nullable=False, default=0)
    available_amount_minor = Column(BigInteger, nullable=False, default=0)  # Computed field
    currency = Column(String(3), nullable=False, default='GBP')
    status = Column(String(20), nullable=False, default='active')  # "active", "exceeded", "closed"
    approval_workflow_id = Column(UUID(as_uuid=True), nullable=True)  # Link to approval workflow
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BudgetTransaction(Base):
    """Budget transactions for spend tracking - Phase 4"""
    __tablename__ = "budget_transactions"

    transaction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id = Column(UUID(as_uuid=True), ForeignKey('budgets.budget_id'), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)  # Positive for spend, negative for refunds
    transaction_type = Column(String(50), nullable=False)  # "spend", "refund", "adjustment"
    description = Column(Text, nullable=False)
    reference_id = Column(String(100), nullable=True)  # Invoice ID, order ID, etc.
    reference_type = Column(String(50), nullable=True)  # "invoice", "order", "adjustment"
    approval_id = Column(UUID(as_uuid=True), nullable=True)  # Link to approval if required
    is_approved = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BudgetAlert(Base):
    """Budget alerts for overspend notifications - Phase 4"""
    __tablename__ = "budget_alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id = Column(UUID(as_uuid=True), ForeignKey('budgets.budget_id'), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    alert_type = Column(String(50), nullable=False)  # "warning", "critical", "exceeded"
    threshold_percentage = Column(Numeric(5, 2), nullable=False)  # 80.00, 100.00, etc.
    message = Column(Text, nullable=False)
    is_acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_by = Column(UUID(as_uuid=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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