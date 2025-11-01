from sqlalchemy import Column, ForeignKey, String, BigInteger, DateTime, func, Text, Boolean, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base
import uuid


Base = declarative_base()

# =============================================================================
# DATABASE MODELS
# =============================================================================

class PaymentTransactionNew(Base):
    """V4.1 payment transactions table with multi-provider support"""
    __tablename__ = "payment_transactions_new"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey('vendors.vendor_id'), nullable=True)
    provider = Column(String(50), nullable=False, comment='stripe, adyen, paypal, etc.')
    payment_intent_id = Column(String(255), nullable=True)
    charge_id = Column(String(255), nullable=True)
    amount_minor = Column(BigInteger, nullable=False, comment='Amount in minor units')
    currency = Column(String(3), ForeignKey('currencies.code'), nullable=False, default='GBP')
    status = Column(String(50), nullable=False, comment='pending, succeeded, failed, refunded')
    order_id = Column(UUID(as_uuid=True), nullable=True)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    raw_response = Column(JSONB, nullable=True, comment='Raw provider response')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CustomerNew(Base):
    """V4.1 customers table with multi-provider support"""
    __tablename__ = "customers_new"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False, comment='stripe, adyen, paypal, etc.')
    external_customer_id = Column(String(255), nullable=False, comment='Provider customer ID')
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PaymentRefund(Base):
    """Payment refunds table"""
    __tablename__ = "payment_refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions_new.id'), nullable=False)
    refund_id = Column(String(255), nullable=True, comment='Provider refund ID')
    amount_minor = Column(BigInteger, nullable=False, comment='Refund amount in minor units')
    currency = Column(String(3), nullable=False, default='GBP')
    reason = Column(String(255), nullable=True, comment='Refund reason')
    status = Column(String(50), nullable=False, comment='pending, succeeded, failed')
    transaction_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PaymentAdjustment(Base):
    """Payment adjustments table"""
    __tablename__ = "payment_adjustments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey('payment_transactions_new.id'), nullable=False)
    adjustment_type = Column(String(50), nullable=False, comment='discount, fee, tax, etc.')
    adjustment_amount_minor = Column(BigInteger, nullable=False, comment='Adjustment amount in minor units')
    adjustment_reason = Column(Text, nullable=True)
    currency = Column(String(3), nullable=False, default='GBP')
    is_applied = Column(Boolean, nullable=False, default=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Phase 5: Trade Account & Multi-Currency Models
class TradeAccount(Base):
    """Trade account for business customers - Phase 5"""
    __tablename__ = "trade_accounts"

    trade_account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    account_number = Column(String(100), nullable=False, unique=True)
    company_name = Column(String(200), nullable=False)
    contact_email = Column(String(255), nullable=False)
    credit_limit_minor = Column(BigInteger, nullable=False, default=0)
    available_credit_minor = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_terms_days = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaymentIntent(Base):
    """Payment intent for transaction processing - Phase 5"""
    __tablename__ = "payment_intents"

    payment_intent_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=True)
    trade_account_id = Column(UUID(as_uuid=True), ForeignKey('trade_accounts.trade_account_id'), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default='GBP')
    status = Column(String(20), nullable=False, default='pending')  # pending, processing, succeeded, failed, cancelled
    provider = Column(String(50), nullable=False)  # stripe, adyen, paypal, etc.
    provider_intent_id = Column(String(255), nullable=True)
    payment_method = Column(String(50), nullable=True)  # card, bank_transfer, etc.
    payment_metadata = Column(JSONB, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict
    expires_at = Column(DateTime(timezone=True), nullable=True)
    succeeded_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CurrencyRate(Base):
    """Currency exchange rates - Phase 5"""
    __tablename__ = "currency_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_currency = Column(String(3), nullable=False)
    target_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(15, 8), nullable=False)
    source = Column(String(50), nullable=False, default='manual')  # manual, api, etc.
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PaymentWebhook(Base):
    """Payment webhook events - Phase 5"""
    __tablename__ = "payment_webhooks"

    webhook_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    processed = Column(Boolean, nullable=False, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Audit logs table"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    """Outbox events table for reliable event publishing"""
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(50), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())