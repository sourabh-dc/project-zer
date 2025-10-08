# ZeroQue Payments Service V2 - Complete API Documentation

## Overview

The ZeroQue Payments Service V2 is a comprehensive, multi-provider payment processing system built with V4.1 architecture principles. It supports multiple payment providers (Stripe, Adyen, PayPal, etc.), implements saga patterns for reliable transactions, and provides full integration with the ZeroQue ecosystem.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Database Schema](#database-schema)
3. [API Endpoints](#api-endpoints)
4. [Payment Providers](#payment-providers)
5. [Saga Implementation](#saga-implementation)
6. [Event System](#event-system)
7. [Integration Points](#integration-points)
8. [Security & Authentication](#security--authentication)
9. [Monitoring & Metrics](#monitoring--metrics)
10. [Error Handling](#error-handling)
11. [Testing](#testing)
12. [Deployment](#deployment)

## Architecture Overview

### V4.1 Architecture Features

- **Multi-Provider Support**: Dynamic provider configuration via `zeroque_rails`
- **Saga Pattern**: Reliable payment processing with compensation
- **Event-Driven**: Outbox events for reliable integration
- **Row-Level Security**: Tenant isolation and data protection
- **Multi-Tenant**: Full tenant isolation with RLS policies
- **Audit Logging**: Comprehensive audit trail for all operations
- **Prometheus Metrics**: Detailed monitoring and observability

### Key Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Payment       │    │   Provider      │    │   Event         │
│   Intent        │───▶│   Integration   │───▶│   Publishing    │
│   Saga          │    │   (Stripe/      │    │   (Outbox)      │
│                 │    │    Adyen/etc)   │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Transaction   │    │   Customer      │    │   Integration   │
│   Storage       │    │   Management    │    │   Endpoints     │
│   (V4.1 Tables) │    │   (Multi-       │    │   (Orders/      │
│                 │    │    Provider)    │    │    Billing)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Database Schema

### Core Tables

#### `payment_transactions_new`

```sql
CREATE TABLE payment_transactions_new (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    vendor_id UUID REFERENCES vendors(vendor_id),
    provider VARCHAR(50) NOT NULL, -- 'stripe', 'adyen', 'paypal', etc.
    payment_intent_id VARCHAR(255),
    charge_id VARCHAR(255),
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL REFERENCES currencies(code),
    status VARCHAR(50) NOT NULL, -- 'pending', 'succeeded', 'failed', 'refunded'
    order_id UUID,
    site_id UUID,
    store_id UUID,
    user_id UUID,
    metadata JSONB,
    raw_response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
```

#### `customers_new`

```sql
CREATE TABLE customers_new (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    provider VARCHAR(50) NOT NULL,
    external_customer_id VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    name VARCHAR(255),
    phone VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    UNIQUE(tenant_id, provider, external_customer_id)
);
```

#### `payment_refunds`

```sql
CREATE TABLE payment_refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    payment_transaction_id UUID NOT NULL REFERENCES payment_transactions_new(id),
    refund_id VARCHAR(255),
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    reason VARCHAR(255),
    status VARCHAR(50) NOT NULL, -- 'pending', 'succeeded', 'failed'
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
```

#### `payment_adjustments`

```sql
CREATE TABLE payment_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    payment_transaction_id UUID NOT NULL REFERENCES payment_transactions_new(id),
    adjustment_type VARCHAR(50) NOT NULL, -- 'discount', 'fee', 'tax', etc.
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    reason VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Row-Level Security

All payment tables have RLS policies for tenant isolation:

```sql
-- Enable RLS
ALTER TABLE payment_transactions_new ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers_new ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_refunds ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_adjustments ENABLE ROW LEVEL SECURITY;

-- Create policies
CREATE POLICY payment_transactions_tenant_isolation ON payment_transactions_new
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY customers_tenant_isolation ON customers_new
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

## API Endpoints

### Payment Intent Management

#### `POST /payments/v2/intent`

Create a payment intent with any supported provider.

**Request:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "order_id": "550e8400-e29b-41d4-a716-446655440001",
  "amount_minor": 2500,
  "currency": "GBP",
  "provider": "stripe",
  "site_id": "550e8400-e29b-41d4-a716-446655440002",
  "store_id": "550e8400-e29b-41d4-a716-446655440003",
  "user_id": "550e8400-e29b-41d4-a716-446655440004",
  "metadata": {
    "description": "Order payment",
    "customer_id": "cus_1234567890"
  }
}
```

**Response:**

```json
{
  "ok": true,
  "payment_intent_id": "pi_1234567890",
  "client_secret": "pi_1234567890_secret_abcdef",
  "status": "requires_payment_method",
  "transaction_id": "550e8400-e29b-41d4-a716-446655440005"
}
```

### Customer Management

#### `POST /payments/v2/customers`

Create or update a customer with any supported provider.

**Request:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "provider": "stripe",
  "email": "customer@example.com",
  "name": "John Doe",
  "phone": "+44123456789",
  "metadata": {
    "source": "web",
    "marketing_consent": true
  }
}
```

**Response:**

```json
{
  "ok": true,
  "customer_id": "cus_1234567890",
  "email": "customer@example.com",
  "name": "John Doe"
}
```

### Refund Management

#### `POST /payments/v2/refund`

Refund a payment (full or partial).

**Request:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "payment_intent_id": "pi_1234567890",
  "amount_minor": 1000,
  "reason": "Customer requested refund"
}
```

**Response:**

```json
{
  "ok": true,
  "refund_id": "re_1234567890",
  "amount_minor": 1000,
  "status": "succeeded"
}
```

### Webhook Processing

#### `POST /payments/v2/webhook/{provider}`

Process webhooks from payment providers.

**Example Stripe Webhook:**

```json
{
  "id": "evt_1234567890",
  "object": "event",
  "type": "payment_intent.succeeded",
  "data": {
    "object": {
      "id": "pi_1234567890",
      "object": "payment_intent",
      "amount": 2500,
      "currency": "gbp",
      "status": "succeeded"
    }
  }
}
```

### Transaction Querying

#### `GET /payments/v2/transactions`

List payment transactions with filtering.

**Query Parameters:**

- `tenant_id` (required): Tenant ID
- `provider` (optional): Filter by provider
- `status` (optional): Filter by status
- `limit` (optional): Number of results (default: 100, max: 1000)
- `offset` (optional): Pagination offset (default: 0)

**Response:**

```json
{
  "ok": true,
  "transactions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440005",
      "provider": "stripe",
      "payment_intent_id": "pi_1234567890",
      "charge_id": "ch_1234567890",
      "amount_minor": 2500,
      "currency": "GBP",
      "status": "succeeded",
      "order_id": "550e8400-e29b-41d4-a716-446655440001",
      "created_at": "2025-10-07T14:30:00Z",
      "updated_at": "2025-10-07T14:31:00Z"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

### Payment Reports

#### `GET /payments/v2/reports`

Get payment analytics and reports (blueprint-inspired).

**Query Parameters:**

- `tenant_id` (required): Tenant ID
- `period_start` (required): Start date (YYYY-MM-DD)
- `period_end` (required): End date (YYYY-MM-DD)
- `currency` (optional): Currency filter (default: GBP)

**Response:**

```json
{
  "ok": true,
  "period": {
    "start": "2025-10-01",
    "end": "2025-10-07",
    "currency": "GBP"
  },
  "summary": {
    "stripe": {
      "succeeded": {
        "count": 25,
        "total_amount_minor": 62500
      },
      "failed": {
        "count": 2,
        "total_amount_minor": 500
      }
    }
  },
  "daily_trends": [
    {
      "date": "2025-10-01",
      "count": 5,
      "total_amount_minor": 12500
    },
    {
      "date": "2025-10-02",
      "count": 8,
      "total_amount_minor": 20000
    }
  ],
  "generated_at": "2025-10-07T15:00:00Z"
}
```

### Admin Configuration

#### `POST /payments/v2/admin/rails/payment`

Configure payment provider for a tenant.

**Request:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "payment",
  "name": "stripe",
  "config": {
    "api_key": "sk_live_...",
    "webhook_secret": "whsec_...",
    "base_url": "https://api.stripe.com/v1"
  },
  "active": true
}
```

## Payment Providers

### Provider Architecture

The service supports multiple payment providers through a pluggable architecture:

```python
class BasePaymentProvider:
    async def create_payment_intent(self, amount_minor: int, currency: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        raise NotImplementedError

    async def create_customer(self, email: str, name: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        raise NotImplementedError

    async def process_webhook(self, payload: Dict[str, Any], signature: str = None) -> Dict[str, Any]:
        raise NotImplementedError

    async def refund_payment(self, payment_intent_id: str, amount_minor: int = None, reason: str = None) -> Dict[str, Any]:
        raise NotImplementedError
```

### Supported Providers

#### Stripe Provider

- **Configuration**: API key, webhook secret, base URL
- **Features**: Payment intents, customers, refunds, webhooks
- **Events**: `payment_intent.succeeded`, `payment_intent.payment_failed`

#### Adyen Provider (Planned)

- **Configuration**: API key, merchant account, webhook username/password
- **Features**: Payments, refunds, webhooks
- **Events**: `AUTHORISATION`, `REFUND`, `CANCELLATION`

#### PayPal Provider (Planned)

- **Configuration**: Client ID, client secret, webhook ID
- **Features**: Orders, refunds, webhooks
- **Events**: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`

### Provider Configuration

Providers are configured via the `zeroque_rails` table:

```sql
INSERT INTO zeroque_rails (tenant_id, type, name, config, active) VALUES (
    '550e8400-e29b-41d4-a716-446655440000',
    'payment',
    'stripe',
    '{"api_key": "sk_live_...", "webhook_secret": "whsec_...", "base_url": "https://api.stripe.com/v1"}',
    true
);
```

## Saga Implementation

### PaymentIntentSaga

The PaymentIntentSaga ensures reliable payment intent creation with compensation:

```python
class PaymentIntentSaga:
    async def create_payment_intent(self, request: PaymentIntentRequest) -> Dict[str, Any]:
        try:
            # Step 1: Validate tenant and get provider config
            provider_config = await self._get_provider_config(request.tenant_id, request.provider)

            # Step 2: Create payment intent with provider
            provider = await self._get_provider(request.provider, provider_config)
            provider_result = await provider.create_payment_intent(...)

            # Step 3: Store payment transaction
            transaction = PaymentTransactionNew(...)
            self.db.add(transaction)
            self.db.commit()

            # Step 4: Publish event
            await self._publish_event(request.tenant_id, "PAYMENT_CREATED", {...})

            return {"ok": True, "payment_intent_id": provider_result["payment_intent_id"]}

        except Exception as e:
            await self._compensate()  # Rollback any changes
            return {"ok": False, "error": str(e)}
```

### Compensation Logic

If any step fails, the saga executes compensation:

1. **Provider Failure**: No compensation needed (transaction not stored)
2. **Database Failure**: Rollback transaction creation
3. **Event Failure**: Transaction stored, but event can be retried later

## Event System

### Outbox Events

The service uses an outbox pattern for reliable event publishing:

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
```

### Published Events

#### `PAYMENT_CREATED`

Published when a payment intent is successfully created.

```json
{
  "event_type": "PAYMENT_CREATED",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_data": {
    "payment_intent_id": "pi_1234567890",
    "amount_minor": 2500,
    "currency": "GBP",
    "provider": "stripe",
    "order_id": "550e8400-e29b-41d4-a716-446655440001"
  }
}
```

#### `PAYMENT_PAID`

Published when a payment is successfully completed.

```json
{
  "event_type": "PAYMENT_PAID",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_data": {
    "payment_intent_id": "pi_1234567890",
    "amount_minor": 2500,
    "currency": "gbp",
    "status": "succeeded"
  }
}
```

#### `PAYMENT_REFUNDED`

Published when a payment is refunded.

```json
{
  "event_type": "PAYMENT_REFUNDED",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_data": {
    "payment_intent_id": "pi_1234567890",
    "refund_id": "re_1234567890",
    "amount_minor": 1000,
    "currency": "GBP"
  }
}
```

### Event Consumption

The service consumes events from other services:

#### `ORDER_COMPLETED`

Triggers payment intent creation for orders requiring payment.

## Integration Points

### Orders Service Integration

#### `POST /payments/v2/integration/orders/payment-required`

Handles `ORDER_COMPLETED` events that require payment processing.

### Billing Service Integration

The service publishes `PAYMENT_PAID` events that the Billing service consumes to:

- Create invoices for completed payments
- Update customer billing records
- Trigger settlement processes

### Ledger Service Integration

Payment events are consumed by the Ledger service to:

- Create ledger entries for successful payments
- Record refund transactions
- Maintain accurate financial records

### Notifications Service Integration

Payment events trigger notifications:

- Payment confirmation emails
- Refund notifications
- Payment failure alerts

## Security & Authentication

### Row-Level Security (RLS)

All payment tables implement RLS for tenant isolation:

```python
async def set_rls_context(db: Session, tenant_id: str, user_id: str = None):
    """Set Row Level Security context"""
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET app.current_user_id = :user_id"), {"user_id": user_id})
```

### JWT Authentication

All endpoints require JWT authentication with tenant context:

```python
def get_user_context(request: Request) -> Dict[str, Any]:
    """Get user context from request"""
    # Extract from JWT token
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    return {
        "user_id": payload.get("user_id"),
        "tenant_id": payload.get("tenant_id"),
        "role": payload.get("role")
    }
```

### Permission Checks

Role-based access control for different operations:

```python
def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check user permissions"""
    role = user_context.get("role")

    permission_map = {
        "payments.create_intent": ["admin", "manager"],
        "payments.refund": ["admin", "manager"],
        "payments.view_transactions": ["admin", "manager", "user"],
        "payments.admin.configure": ["admin"]
    }

    return role in permission_map.get(permission, [])
```

### Audit Logging

All operations are logged for audit purposes:

```python
async def log_audit(db: Session, action: str, resource_type: str, resource_id: str = None,
                   details: Dict[str, Any] = None, tenant_id: str = None, user_id: str = None):
    """Log audit event"""
    audit_log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit_log)
    db.commit()
```

## Monitoring & Metrics

### Prometheus Metrics

The service exposes comprehensive Prometheus metrics:

#### Payment Metrics

```python
payment_requests_total = Counter(
    'payment_requests_total',
    'Total payment requests',
    ['provider', 'status', 'currency']
)

payment_amount_total = Counter(
    'payment_amount_total',
    'Total payment amounts',
    ['provider', 'currency']
)

payment_duration_seconds = Histogram(
    'payment_duration_seconds',
    'Payment processing duration',
    ['provider', 'operation']
)
```

#### Webhook Metrics

```python
webhook_requests_total = Counter(
    'webhook_requests_total',
    'Total webhook requests',
    ['provider', 'event_type', 'status']
)
```

#### Saga Metrics

```python
saga_duration_seconds = Histogram(
    'saga_duration_seconds',
    'Saga processing duration',
    ['saga_type', 'status']
)
```

### Health Checks

#### `GET /health`

Basic health check endpoint.

#### `GET /readiness`

Readiness check including database connectivity.

#### `GET /metrics`

Prometheus metrics endpoint.

### Structured Logging

All operations use structured logging with `structlog`:

```python
logger = structlog.get_logger(__name__)

logger.info(
    "Payment intent created",
    payment_intent_id=payment_intent_id,
    amount_minor=amount_minor,
    currency=currency,
    provider=provider,
    tenant_id=tenant_id
)
```

## Error Handling

### Error Response Format

All errors follow a consistent format:

```json
{
  "detail": "Error description",
  "error_code": "PAYMENT_INTENT_CREATION_FAILED",
  "timestamp": "2025-10-07T15:00:00Z",
  "request_id": "req_1234567890"
}
```

### Common Error Codes

- `INVALID_TENANT_ID`: Invalid or missing tenant ID
- `PROVIDER_NOT_CONFIGURED`: Payment provider not configured for tenant
- `PAYMENT_INTENT_CREATION_FAILED`: Failed to create payment intent with provider
- `WEBHOOK_SIGNATURE_INVALID`: Invalid webhook signature
- `REFUND_AMOUNT_EXCEEDS_PAYMENT`: Refund amount exceeds original payment
- `TRANSACTION_NOT_FOUND`: Payment transaction not found

### Retry Logic

- **Webhook Processing**: Automatic retry with exponential backoff
- **Event Publishing**: Retry via outbox events with configurable max retries
- **Provider API Calls**: Circuit breaker pattern for external API failures

## Testing

### Test Scenarios

The service includes comprehensive test scenarios:

1. **Provider Configuration**: Test multi-provider setup
2. **Customer Management**: Create, update, and query customers
3. **Payment Intent Creation**: Test payment intent creation with different providers
4. **Webhook Processing**: Test webhook handling and event processing
5. **Refund Processing**: Test full and partial refunds
6. **Transaction Querying**: Test filtering and pagination
7. **Payment Reports**: Test analytics and reporting features
8. **Integration Endpoints**: Test service-to-service integration
9. **Error Scenarios**: Test error handling and edge cases
10. **Legacy Deprecation**: Test deprecated endpoint warnings

### Load Testing

The service supports load testing scenarios:

- High-volume payment intent creation
- Concurrent webhook processing
- Multi-tenant isolation testing
- Database connection pooling

### Test Data

Test scenarios create realistic data:

- Multiple tenants with different configurations
- Various payment amounts and currencies
- Different payment statuses and scenarios
- Provider-specific test data

## Deployment

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/zeroque_dev

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256

# Service Configuration
SERVICE_NAME=payments
SERVICE_VERSION=2.0.0
LOG_LEVEL=INFO

# Monitoring
PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY services/payments/ ./services/payments/
COPY packages/zeroque_common/ ./packages/zeroque_common/

EXPOSE 8087

CMD ["python", "-m", "services.payments.main"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: payments-service
  template:
    metadata:
      labels:
        app: payments-service
    spec:
      containers:
        - name: payments
          image: zeroque/payments-service:2.0.0
          ports:
            - containerPort: 8087
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: payments-secrets
                  key: database-url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: payments-secrets
                  key: redis-url
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

### Database Migration

Run Alembic migrations to set up the database schema:

```bash
# Apply migrations
alembic upgrade head

# Verify migration
alembic current
```

### Health Checks

The service provides health check endpoints for Kubernetes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8087
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /readiness
    port: 8087
  initialDelaySeconds: 5
  periodSeconds: 5
```

## Summary

The ZeroQue Payments Service V2 provides a robust, scalable, and secure payment processing solution that:

- **Supports Multiple Providers**: Stripe, Adyen, PayPal, and extensible architecture
- **Implements V4.1 Architecture**: Saga patterns, event-driven integration, RLS
- **Ensures Reliability**: Comprehensive error handling, retry logic, compensation
- **Provides Full Observability**: Prometheus metrics, structured logging, audit trails
- **Maintains Security**: JWT authentication, RLS, permission-based access control
- **Enables Analytics**: Blueprint-inspired reporting and tenant-facing insights
- **Supports Integration**: Seamless integration with Orders, Billing, Ledger, and Notifications services

The service is production-ready and follows all V4.1 architecture principles while incorporating the best features from the blueprint requirements.
