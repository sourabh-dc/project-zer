# Billing Service V2 - Complete API Specification

## Overview

The Billing Service V2 is a production-ready microservice that handles invoice creation, vendor settlements, and billing workflows using modern patterns including saga orchestration and event-driven architecture. This service replaces the legacy billing system with enhanced reliability, scalability, and integration capabilities.

## Architecture

### Core Features

- **Saga Patterns**: Reliable transaction management with compensation logic
- **Event-Driven**: Asynchronous communication with other services
- **Multi-tenant**: Row-level security and tenant isolation
- **Production-Ready**: Health checks, metrics, structured logging, error handling

### Key Components

- `main.py`: Production FastAPI application
- `sagas.py`: Saga pattern implementations
- `events.py`: Event handlers and publishers
- `models.py`: SQLAlchemy ORM models
- `payloads.py`: Pydantic request/response models

## API Endpoints

### Base URL

```
http://localhost:8083
```

### Authentication

All endpoints require proper authentication. The service integrates with the authentication system for JWT token validation.

### Health & Monitoring

#### GET /health

Comprehensive health check endpoint.

**Response:**

```json
{
  "status": "healthy|degraded|unhealthy",
  "service": "billing-service-v2",
  "version": "2.0.0",
  "environment": "production",
  "timestamp": "2025-10-07T11:14:28.500492Z",
  "checks": {
    "database": {
      "status": "healthy|unhealthy",
      "error": "error message if unhealthy"
    },
    "event_bus": {
      "status": "healthy|unhealthy",
      "error": "error message if unhealthy"
    }
  }
}
```

#### GET /metrics

Prometheus metrics endpoint for monitoring.

**Response:** Prometheus-formatted metrics

---

## Invoice Management

### POST /billing/v2/invoices

Create a new invoice using saga pattern for reliability.

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "invoice_number": "INV-001",
  "currency": "GBP",
  "due_date": "2025-11-07",
  "lines": [
    {
      "line_number": 1,
      "description": "Software License",
      "quantity": 1,
      "unit_price_minor": 100000,
      "tax_minor": 20000,
      "tax_code": "VAT20"
    }
  ],
  "ar_customer_code": "CUST-001",
  "terms": "NET30"
}
```

**Response:**

```json
{
  "id": "72a08c8c-3e4e-4cd4-9031-fac97d1589a9",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "invoice_number": "INV-001",
  "status": "posted",
  "amount_minor": 120000,
  "currency": "GBP",
  "tax_total_minor": 20000,
  "subtotal_minor": 100000,
  "due_date": "2025-11-07",
  "posted_at": "2025-10-07T11:14:28.516360Z",
  "created_at": "2025-10-07T11:14:28.500492Z",
  "updated_at": "2025-10-07T11:14:28.500492Z",
  "lines": []
}
```

**Saga Steps:**

1. Validate budget constraints
2. Create invoice record
3. Create invoice lines
4. Post invoice (status: draft → posted)
5. Create ledger entry
6. Notify stakeholders
7. Publish INVOICE_CREATED event

### GET /billing/v2/invoices

List invoices with optional filtering.

**Query Parameters:**

- `tenant_id` (required): Tenant ID
- `status` (optional): Invoice status filter
- `limit` (optional): Maximum number of invoices (default: 100, max: 1000)

**Response:**

```json
{
  "invoices": [
    {
      "id": "72a08c8c-3e4e-4cd4-9031-fac97d1589a9",
      "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
      "invoice_number": "INV-001",
      "status": "posted",
      "amount_minor": 120000,
      "currency": "GBP",
      "tax_total_minor": 20000,
      "subtotal_minor": 100000,
      "due_date": "2025-11-07",
      "posted_at": "2025-10-07T11:14:28.516360Z",
      "created_at": "2025-10-07T11:14:28.500492Z",
      "updated_at": "2025-10-07T11:14:28.500492Z",
      "lines": []
    }
  ],
  "total_count": 1,
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Settlement Management

### POST /billing/v2/settlements

Create a new vendor settlement using saga pattern for reliability.

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440008",
  "settlement_period_start": "2025-10-01",
  "settlement_period_end": "2025-10-31",
  "currency": "GBP",
  "items": [
    {
      "payout_amount_minor": 200000,
      "commission_amount_minor": 20000,
      "fee_amount_minor": 5000,
      "notes": "October sales commission"
    }
  ]
}
```

**Response:**

```json
{
  "settlement_id": "3a3ddf7c-bbe8-4b2f-b236-ba84551f2c70",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440008",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "settlement_period_start": "2025-10-01",
  "settlement_period_end": "2025-10-31",
  "total_sales_minor": 200000,
  "total_commission_minor": 20000,
  "total_adjustments_minor": 0,
  "net_settlement_minor": 175000,
  "currency": "GBP",
  "settlement_status": "completed",
  "settlement_date": "2025-10-07T09:29:43.284623Z",
  "payment_reference": null,
  "created_at": "2025-10-07T09:29:43.270680Z",
  "updated_at": "2025-10-07T09:29:43.270680Z",
  "items": [],
  "adjustments": [],
  "disputes": []
}
```

**Saga Steps:**

1. Validate settlement constraints
2. Create settlement record
3. Create settlement batch
4. Create settlement items
5. Process batch
6. Update settlement status
7. Publish SETTLEMENT_PROCESSED event

---

## Event Handling

### POST /billing/v2/events/approval-resolved

Handle APPROVAL_RESOLVED event from approvals service.

**Request Body:**

```json
{
  "request_id": "test-request-123",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "approved",
  "request_type": "budget",
  "request_data": "{\"amount\": 50000, \"reason\": \"Office supplies\", \"currency\": \"GBP\"}"
}
```

**Response:**

```json
{
  "status": "success",
  "message": "Event processed successfully"
}
```

### POST /billing/v2/events/order-completed

Handle ORDER_COMPLETED event from orders service.

**Request Body:**

```json
{
  "order_id": "test-order-456",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440008",
  "total_amount_minor": 150000,
  "currency": "GBP"
}
```

**Response:**

```json
{
  "status": "success",
  "message": "Event processed successfully"
}
```

---

## Reporting

### GET /billing/v2/reports/ar-aging

Get accounts receivable aging report.

**Query Parameters:**

- `tenant_id` (required): Tenant ID
- `as_of_date` (optional): As of date (YYYY-MM-DD format)

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "as_of_date": "2025-10-07",
  "aging_buckets": {
    "current": 210000,
    "31_60": 0,
    "61_90": 0,
    "over_90": 0
  },
  "total_ar_minor": 210000,
  "currency": "GBP"
}
```

**Aging Buckets:**

- `current`: 0-30 days overdue
- `31_60`: 31-60 days overdue
- `61_90`: 61-90 days overdue
- `over_90`: Over 90 days overdue

### GET /billing/v2/reports/revenue-by-method

Get revenue breakdown by payment method.

**Query Parameters:**

- `tenant_id` (required): Tenant ID
- `date_from` (required): From date (YYYY-MM-DD format)
- `date_to` (required): To date (YYYY-MM-DD format)

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "period": {
    "from": "2025-10-01",
    "to": "2025-10-31"
  },
  "revenue_breakdown": {
    "trade_invoices_minor": 140000,
    "settlements_minor": 132000,
    "stripe_minor": 0,
    "total_minor": 272000
  },
  "currency": "GBP"
}
```

**Revenue Sources:**

- `trade_invoices_minor`: Revenue from trade invoices
- `settlements_minor`: Revenue from vendor settlements
- `stripe_minor`: Revenue from Stripe payments (future integration)

---

## Data Models

### Invoice Line Request

```json
{
  "line_number": 1,
  "description": "Product description",
  "quantity": 1,
  "unit_price_minor": 100000,
  "tax_minor": 20000,
  "tax_code": "VAT20"
}
```

### Settlement Item Request

```json
{
  "payout_amount_minor": 200000,
  "commission_amount_minor": 20000,
  "fee_amount_minor": 5000,
  "notes": "Settlement notes"
}
```

---

## Error Handling

### HTTP Status Codes

- `200`: Success
- `400`: Bad Request (validation error)
- `404`: Not Found
- `409`: Conflict (duplicate resource)
- `422`: Unprocessable Entity (business logic error)
- `500`: Internal Server Error

### Error Response Format

```json
{
  "detail": "Error description"
}
```

### Custom Exceptions

- `BillingValidationError`: Input validation failures
- `BillingNotFoundError`: Resource not found
- `BillingDuplicateError`: Duplicate resource creation
- `SettlementProcessingError`: Settlement processing failures

---

## Event-Driven Integration

### Incoming Events

The billing service handles the following events from other services:

#### APPROVAL_RESOLVED

Triggered when a budget approval request is resolved.

- **Source**: Approvals Service
- **Action**: Create invoice for approved budget requests
- **Endpoint**: `POST /billing/v2/events/approval-resolved`

#### ORDER_COMPLETED

Triggered when an order is completed.

- **Source**: Orders Service
- **Action**: Trigger settlement calculation for vendors
- **Endpoint**: `POST /billing/v2/events/order-completed`

#### SUBSCRIPTION_UPDATED

Triggered when a subscription is updated.

- **Source**: Subscriptions Service
- **Action**: Update tenant billing preferences
- **Endpoint**: `POST /billing/v2/events/subscription-updated`

### Outgoing Events

The billing service publishes the following events:

#### INVOICE_CREATED

Published when an invoice is created and posted.

```json
{
  "invoice_id": "72a08c8c-3e4e-4cd4-9031-fac97d1589a9",
  "invoice_number": "INV-001",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "amount_minor": 120000,
  "currency": "GBP",
  "posted_at": "2025-10-07T11:14:28.516360Z",
  "created_at": "2025-10-07T11:14:28.500492Z"
}
```

#### SETTLEMENT_PROCESSED

Published when a settlement is processed.

```json
{
  "settlement_id": "3a3ddf7c-bbe8-4b2f-b236-ba84551f2c70",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440008",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "net_settlement_minor": 175000,
  "currency": "GBP",
  "processed_at": "2025-10-07T09:29:43.284623Z"
}
```

---

## Saga Patterns

### Invoice Creation Saga

The invoice creation process uses a 7-step saga pattern:

1. **Validate Budget**: Check budget constraints and overspend limits
2. **Create Invoice**: Create the main invoice record
3. **Create Lines**: Create invoice line items
4. **Post Invoice**: Change status from draft to posted
5. **Create Ledger Entry**: Record in the ledger system
6. **Notify Stakeholders**: Send notifications to relevant parties
7. **Publish Event**: Publish INVOICE_CREATED event

**Compensation Logic**: If any step fails, all previous steps are rolled back in reverse order.

### Settlement Creation Saga

The settlement creation process uses a 7-step saga pattern:

1. **Validate Settlement**: Check vendor and period constraints
2. **Create Settlement**: Create the main settlement record
3. **Create Batch**: Create settlement batch for processing
4. **Create Items**: Create settlement line items
5. **Process Batch**: Update batch status to processed
6. **Update Status**: Update settlement status to completed
7. **Publish Event**: Publish SETTLEMENT_PROCESSED event

**Compensation Logic**: If any step fails, all previous steps are rolled back in reverse order.

---

## Monitoring & Observability

### Health Checks

The service provides comprehensive health checks at `/health`:

- Database connectivity
- Event bus connectivity
- Service status and version information

### Metrics

Prometheus metrics are available at `/metrics`:

- `billing_requests_total`: Request counts by method/endpoint/status
- `billing_request_duration_seconds`: Request duration histogram
- `billing_invoices_created_total`: Invoice creation counts
- `billing_settlements_created_total`: Settlement creation counts
- `billing_events_published_total`: Event publishing counts

### Logging

Structured JSON logging with:

- Request/response correlation IDs
- Saga step tracking
- Error context and stack traces
- Business event logging

---

## Security

### Authentication

- JWT token validation (integrates with auth service)
- API key authentication for service-to-service calls

### Authorization

- Row-level security (RLS) for multi-tenant data isolation
- Role-based access control (RBAC) integration

### Data Protection

- Input validation with Pydantic models
- SQL injection prevention with SQLAlchemy ORM
- UUID validation for all identifiers

---

## Performance

### Database Optimization

- Proper indexing on tenant_id, vendor_id, status fields
- Connection pooling with SQLAlchemy
- Query optimization with eager loading

### Caching

- Redis integration for session management
- Query result caching for reports

### Scalability

- Stateless service design
- Horizontal scaling support
- Async/await patterns for I/O operations

---

## Deployment

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d

# Or build and run standalone
docker build -t billing-service-v2 .
docker run -p 8083:8083 \
  -e DATABASE_URL=postgresql://user:pass@host:port/db \
  -e REDIS_URL=redis://host:port/0 \
  -e ENVIRONMENT=production \
  billing-service-v2
```

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `ENVIRONMENT`: Environment (development/production)
- `PORT`: Service port (default: 8083)

### Database Setup

The service requires the following tables:

- `vendor_settlements`: Vendor settlement records
- `vendor_settlement_items`: Settlement line items
- `vendor_settlement_batches`: Settlement batch processing
- `vendor_settlement_adjustments`: Settlement adjustments
- `vendor_disputes`: Settlement disputes
- `trade_invoices`: Invoice records
- `trade_invoice_lines`: Invoice line items
- `billing_outbox_events`: Event outbox for reliability

---

## Testing

### Integration Tests

Run comprehensive integration tests:

```bash
python -m services.billing.test_integration
```

### Business Scenarios

Test end-to-end business workflows:

```bash
python -m services.billing.integration_scenarios
```

### Test Coverage

- Basic functionality: Invoice and settlement creation
- Saga patterns: Compensation logic and error handling
- Event handling: Incoming and outgoing events
- Reporting: AR aging and revenue reports
- Error handling: Validation and business logic errors
- Multi-tenancy: Data isolation and security
- Performance: Concurrent operations and load testing

---

## Migration from V1

### Data Migration

1. Export data from legacy tables
2. Transform data to new schema
3. Import to new tables
4. Verify data integrity
5. Update dependent services

### API Migration

1. Deploy V2 service alongside V1
2. Update dependent services to use V2 endpoints
3. Monitor for issues
4. Deprecate V1 endpoints
5. Remove V1 service

---

## Troubleshooting

### Common Issues

1. **Database Connection**: Check DATABASE_URL and network connectivity
2. **Event Publishing**: Verify Redis connectivity and outbox_events table
3. **Saga Failures**: Check logs for specific step failures and compensation
4. **Performance**: Monitor metrics and database query performance

### Log Analysis

Search for specific patterns:

- Saga step failures: `"Saga step failed"`
- Event publishing issues: `"Event publishing failed"`
- Database errors: `"Database transaction failed"`

---

## Support

For production support:

1. Check health endpoint: `GET /health`
2. Review metrics: `GET /metrics`
3. Analyze structured logs
4. Monitor saga execution
5. Verify event processing

---

## Version History

### V2.0.0 (Current)

- Saga pattern implementation
- Event-driven architecture
- Production-ready features
- Comprehensive testing
- Multi-tenant support

### V1.x (Legacy)

- Basic invoice and settlement management
- Direct database operations
- Limited error handling
- No event integration

---

## Contact

For questions or support regarding the Billing Service V2, please contact the development team or refer to the internal documentation portal.
