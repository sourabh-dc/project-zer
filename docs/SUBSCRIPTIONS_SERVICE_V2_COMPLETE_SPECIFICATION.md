# ZeroQue Subscriptions Service V2 - Complete API Specification

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Authentication & Authorization](#authentication--authorization)
4. [Data Models](#data-models)
5. [API Endpoints](#api-endpoints)
6. [Usage Examples](#usage-examples)
7. [Error Handling](#error-handling)
8. [Integration Guide](#integration-guide)
9. [Monitoring & Observability](#monitoring--observability)
10. [Deployment Guide](#deployment-guide)
11. [Troubleshooting](#troubleshooting)
12. [API Reference Summary](#api-reference-summary)

---

## Overview

The **ZeroQue Subscriptions Service V2** is a comprehensive tenant-level subscription management system that handles subscription plans, billing accounts, and subscription lifecycle management for the ZeroQue platform. It provides tenant-level subscription management aligned with the v2 architecture.

### Key Features

- **Tenant-Level Subscriptions**: Manage subscriptions at the tenant level (aligned with v2 architecture)
- **Subscription Plans Management**: Define and manage subscription plans with features and pricing
- **Billing Account Integration**: Support for Stripe and trade account billing
- **Feature-Based Plans**: Granular feature entitlements with usage limits per plan
- **Stripe Webhook Integration**: Handle subscription lifecycle events from Stripe
- **Production-Ready**: Comprehensive error handling, RLS, and transaction management

### Service Information

- **Service Name**: subscriptions
- **Version**: 2.0.0
- **Port**: 8212
- **Base URL**: `http://localhost:8212`

---

## Architecture

### Service Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │    │   PostgreSQL    │    │   Stripe API    │
│                 │◄──►│   Database      │◄──►│                 │
│  - REST API     │    │  - Plans        │    │  - Webhooks     │
│  - Validation   │    │  - Features     │    │  - Subscriptions│
│  - Error Handle │    │  - Subscriptions│    │  - Billing      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Database Schema

#### Core Tables

- **`subscription_plans`**: Available subscription plans with pricing
- **`features`**: Available features with categories
- **`plan_features`**: Feature-to-plan mappings with limits
- **`tenant_subscriptions`**: Tenant-level subscription records
- **`site_billing_accounts`**: Billing accounts for tenants (legacy table name maintained for compatibility)

### Row Level Security (RLS)

The service implements Row Level Security to ensure data isolation:

```sql
-- Set RLS context before operations
SET LOCAL app.current_tenant_id = 'tenant_uuid';
SET LOCAL app.user_id = 'user_uuid';
SET row_security = on;
```

### Access Patterns

- **Tenant Isolation**: All data is scoped by tenant_id
- **Tenant-Level Access**: Subscriptions are managed per tenant
- **Feature-Level Plans**: Granular feature entitlements per plan

---

## Data Models

### Subscription Plans

```json
{
  "code": "pro",
  "name": "Pro Plan",
  "description": "Advanced features for growing businesses",
  "price_yearly_minor": 200,
  "currency": "GBP",
  "active": true
}
```

### Features

```json
{
  "code": "api_access",
  "name": "API Access",
  "description": "REST API access",
  "category": "integration",
  "active": true
}
```

### Tenant Subscriptions

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan_code": "pro",
  "payment_method": "stripe",
  "status": "active",
  "external_id": "sub_1234567890",
  "current_period_start": "2024-01-01T00:00:00Z",
  "current_period_end": "2024-12-31T23:59:59Z"
}
```

### Usage Limits

```json
{
  "rate_limit": 10000,
  "max_webhooks": 5,
  "max_stores": 5
}
```

---

## API Endpoints

### Health & Status

#### GET /health

Check service health status.

**Response:**

```json
{
  "status": "ok",
  "service": "subscriptions",
  "version": "2.0.0",
  "enhanced": true
}
```

#### GET /readiness

Check service readiness for traffic.

**Response:**

```json
{
  "service": "subscriptions",
  "db": true,
  "redis": true
}
```

### Subscription Plans Management

#### GET /subscriptions/v2/plans

List available subscription plans.

**Query Parameters:**

- `active` (optional): Filter by active status

**Response:**

```json
{
  "plans": [
    {
      "code": "core",
      "name": "Core Plan",
      "description": "Basic features for small teams",
      "price_yearly_minor": 100,
      "currency": "GBP",
      "active": true
    },
    {
      "code": "pro",
      "name": "Pro Plan",
      "description": "Advanced features for growing businesses",
      "price_yearly_minor": 200,
      "currency": "GBP",
      "active": true
    },
    {
      "code": "enterprise",
      "name": "Enterprise Plan",
      "description": "Full features for large organizations",
      "price_yearly_minor": 400,
      "currency": "GBP",
      "active": true
    }
  ]
}
```

#### GET /subscriptions/v2/plans/{plan_code}/features

Get features included in a specific plan.

**Response:**

```json
{
  "plan_code": "pro",
  "features": [
    {
      "feature_code": "api_access",
      "name": "API Access",
      "description": "REST API access",
      "category": "integration",
      "enabled": true,
      "limits": { "rate_limit": 10000 }
    },
    {
      "feature_code": "bulk_orders",
      "name": "Bulk Orders",
      "description": "Process multiple orders efficiently",
      "category": "orders",
      "enabled": true,
      "limits": { "max_orders_per_day": 1000 }
    }
  ]
}
```

### Tenant Subscriptions Management

#### POST /subscriptions/v2/subscriptions

Create a new tenant subscription.

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan_code": "pro",
  "payment_method": "stripe",
  "external_id": "sub_1234567890",
  "current_period_start": "2024-01-01T00:00:00Z",
  "current_period_end": "2024-12-31T23:59:59Z",
  "trial_end": "2024-01-15T00:00:00Z"
}
```

**Response:**

```json
{
  "subscription_id": 123,
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan_code": "pro",
  "external_id": "sub_1234567890",
  "status": "created"
}
```

#### GET /subscriptions/v2/subscriptions/{tenant_id}

Get tenant subscription details.

**Response:**

```json
{
  "subscription_id": 123,
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan_code": "pro",
  "plan_name": "Pro Plan",
  "plan_description": "Advanced features for growing businesses",
  "payment_method": "stripe",
  "status": "active",
  "external_id": "sub_1234567890",
  "current_period_start": "2024-01-01T00:00:00Z",
  "current_period_end": "2024-12-31T23:59:59Z",
  "trial_end": "2024-01-15T00:00:00Z",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Stripe Webhook Integration

#### POST /subscriptions/v2/webhooks/stripe

Handle Stripe webhooks for subscription lifecycle events.

**Headers:**

- `Stripe-Signature`: Stripe webhook signature

**Request Body:**

Stripe webhook payload (automatically processed)

**Response:**

```json
{
  "ok": true,
  "event_id": "evt_1234567890",
  "event_type": "customer.subscription.updated"
}
```

### Legacy Endpoints (Deprecated)

#### POST /subscriptions/sites/{tenant_id}/{site_id}/subscribe

Legacy endpoint for site subscriptions (deprecated).

**Response:**

```json
{
  "detail": "Site-level subscriptions are deprecated. Please use tenant-level subscription endpoints."
}
```

---

## Usage Examples

### Example 1: Complete Subscription Workflow

#### Step 1: List Available Plans

```bash
curl "http://localhost:8212/subscriptions/v2/plans"
```

#### Step 2: Check Plan Features

```bash
curl "http://localhost:8212/subscriptions/v2/plans/pro/features"
```

#### Step 3: Create Tenant Subscription

```bash
curl -X POST "http://localhost:8212/subscriptions/v2/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "plan_code": "pro",
    "payment_method": "stripe"
  }'
```

#### Step 4: Get Subscription Details

```bash
curl "http://localhost:8212/subscriptions/v2/subscriptions/550e8400-e29b-41d4-a716-446655440000"
```

### Example 2: Integration with Entitlements Service

```python
# Check subscription status before checking entitlements
def check_subscription_status(tenant_id: str) -> bool:
    response = requests.get(
        f"http://localhost:8212/subscriptions/v2/subscriptions/{tenant_id}"
    )

    if response.status_code == 200:
        data = response.json()
        return data.get("status") in ["active", "trialing"]

    return False

# Check entitlements only if subscription is active
def check_feature_access(tenant_id: str, feature_code: str) -> bool:
    if not check_subscription_status(tenant_id):
        return False

    response = requests.get(
        "http://localhost:8211/entitlements/v2/check",
        params={
            "tenant_id": tenant_id,
            "feature_code": feature_code
        }
    )

    if response.status_code == 200:
        data = response.json()
        return data.get("entitled", False)

    return False
```

### Example 3: Stripe Webhook Processing

```python
# Webhook endpoint that forwards to subscription service
@app.post("/webhooks/stripe")
async def handle_stripe_webhook(request: Request):
    # Forward to subscription service
    response = requests.post(
        "http://localhost:8212/subscriptions/v2/webhooks/stripe",
        data=await request.body(),
        headers={"Stripe-Signature": request.headers.get("Stripe-Signature")}
    )

    return response.json()
```

---

## Error Handling

### Custom Exception Types

#### SubscriptionValidationError (400)

```json
{
  "detail": "Invalid tenant_id format: invalid-uuid"
}
```

#### SubscriptionNotFoundError (404)

```json
{
  "detail": "No subscription found for tenant 550e8400-e29b-41d4-a716-446655440000"
}
```

#### SubscriptionDuplicateError (409)

```json
{
  "detail": "Tenant already has an active subscription"
}
```

#### BillingAccountError (400)

```json
{
  "detail": "Billing account already exists for tenant 550e8400-e29b-41d4-a716-446655440000 with payment method stripe"
}
```

#### PaymentProcessingError (500)

```json
{
  "detail": "Database error: connection failed"
}
```

All error responses follow this format:

```json
{
  "detail": "Error message description"
}
```

---

## Integration Guide

### Integration with Entitlements Service

The subscription service works closely with the entitlements service:

1. **Subscription Creation**: Create subscriptions via subscription service
2. **Entitlement Checking**: Check feature access via entitlements service
3. **Usage Tracking**: Track usage against subscription limits via entitlements service

### Integration with Billing Service

The subscription service can integrate with external billing providers:

1. **Stripe Integration**: Handle Stripe subscriptions and webhooks
2. **Trade Account Integration**: Support for trade-based billing
3. **Webhook Processing**: Process billing events and update subscription status

### Database Integration

The service uses PostgreSQL with Row Level Security:

```sql
-- Enable RLS for tenant isolation
ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;

-- Create RLS policy
CREATE POLICY tenant_isolation_tenant_subscriptions
    ON tenant_subscriptions
    FOR ALL
    TO zeroque_app
    USING (tenant_id = current_setting('app.current_tenant_id', true));
```

---

## Monitoring & Observability

### Health Checks

#### Basic Health Check

```bash
curl "http://localhost:8212/health"
```

#### Detailed Health Check

```bash
curl "http://localhost:8212/readiness"
```

### Application Metrics

- **Request Count**: Total API requests per endpoint
- **Response Time**: P50, P95, P99 response times
- **Error Rate**: Error percentage by endpoint
- **Database Connections**: Active database connections

### Business Metrics

- **Subscription Count**: Active subscriptions per plan
- **Plan Distribution**: Subscription distribution across plans
- **Revenue Metrics**: Revenue by plan and time period

### Structured Logging Format

```json
{
  "timestamp": "2024-01-01T00:00:00Z",
  "level": "INFO",
  "service": "subscriptions",
  "event": "subscription_created",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan_code": "pro",
  "external_id": "sub_1234567890"
}
```

#### Key Events Logged

- `subscription_created`: New subscription created
- `subscription_updated`: Subscription status updated
- `plan_features_listed`: Plan features retrieved
- `stripe_webhook_processed`: Stripe webhook processed

### Alerting

#### Critical Alerts

- Service down (health check fails)
- Database connection failures
- High error rates (>5%)

#### Warning Alerts

- High response times (>1s P95)
- Stripe webhook failures
- Subscription creation failures

---

## Deployment Guide

### System Requirements

- **Python**: 3.11+
- **PostgreSQL**: 13+
- **Redis**: 6+ (optional, for caching)
- **Memory**: 512MB minimum
- **CPU**: 1 core minimum

### Dependencies

```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary stripe pydantic
```

### Environment Variables

#### Required Variables

```bash
# Database
DATABASE_URL=postgresql://zeroque:zeroque@localhost:5000/zeroque_dev

# Logging
LOG_LEVEL=INFO
```

#### Optional Variables

```bash
# Stripe Configuration
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Service Configuration
PORT=8212
HOST=0.0.0.0
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY services/subscriptions/ .

EXPOSE 8212

CMD ["python", "main.py"]
```

### Docker Compose

```yaml
version: "3.8"
services:
  subscriptions:
    build: .
    ports:
      - "8212:8212"
    environment:
      - DATABASE_URL=postgresql://zeroque:zeroque@postgres:5432/zeroque_dev
    depends_on:
      - postgres
      - redis

  subscriptions-worker:
    build: .
    command: ["python", "worker.py"]
    environment:
      - DATABASE_URL=postgresql://zeroque:zeroque@postgres:5432/zeroque_dev
    depends_on:
      - postgres
      - redis
```

### Security

- Enable HTTPS/TLS
- Configure proper firewall rules
- Use environment variables for secrets
- Enable database SSL
- Implement proper authentication

### Scaling

- **Horizontal Scaling**: Deploy multiple service instances
- **Load Balancing**: Use nginx or cloud load balancer
- **Database Scaling**: Use read replicas for read operations
- **Caching**: Implement Redis caching for frequently accessed data

### Monitoring Setup

```bash
# Install monitoring tools
pip install prometheus-client

# Configure health checks
curl -f http://localhost:8212/health || exit 1
```

### Testing

#### Unit Tests

```bash
# Run unit tests
python -m pytest tests/unit/

# Run with coverage
python -m pytest tests/unit/ --cov=main --cov-report=html
```

#### Integration Tests

```bash
# Run integration tests
python -m pytest tests/integration/

# Test with database
python -m pytest tests/integration/ --database-url=postgresql://test:test@localhost/test_db
```

#### Load Testing

```bash
# Install locust
pip install locust

# Run load tests
locust -f tests/load/subscription_load_test.py --host=http://localhost:8212
```

---

## Troubleshooting

### Common Issues

1. **Service Won't Start**

   - Check database connectivity
   - Verify environment variables
   - Check port availability

2. **Subscription Creation Failing**

   - Verify tenant exists
   - Check plan code validity
   - Validate payment method

3. **Stripe Webhook Issues**

   - Verify webhook secret
   - Check Stripe signature validation
   - Review webhook endpoint logs

4. **Database Connection Issues**

   - Check database URL format
   - Verify database credentials
   - Check network connectivity

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with debug output
python main.py --debug
```

### Performance Issues

1. **Slow Queries**

   - Check database indexes
   - Review query execution plans
   - Consider query optimization

2. **High Memory Usage**
   - Check for memory leaks
   - Review connection pooling
   - Monitor garbage collection

### Log Analysis

```bash
# Filter subscription events
grep "subscription_created" logs/subscriptions.log

# Check error patterns
grep "ERROR" logs/subscriptions.log | tail -100

# Monitor webhook processing
grep "stripe_webhook" logs/subscriptions.log
```

---

## API Reference Summary

| Method | Endpoint                                       | Description                |
| ------ | ---------------------------------------------- | -------------------------- |
| GET    | `/health`                                      | Service health check       |
| GET    | `/readiness`                                   | Service readiness check    |
| GET    | `/subscriptions/v2/plans`                      | List subscription plans    |
| GET    | `/subscriptions/v2/plans/{plan_code}/features` | Get plan features          |
| POST   | `/subscriptions/v2/subscriptions`              | Create tenant subscription |
| GET    | `/subscriptions/v2/subscriptions/{tenant_id}`  | Get subscription details   |
| POST   | `/subscriptions/v2/webhooks/stripe`            | Stripe webhook handler     |

---

## Maintenance

### Regular Tasks

#### Daily

- Monitor health checks
- Review error logs
- Check subscription creation rates

#### Weekly

- Review subscription metrics
- Check plan feature usage
- Validate webhook processing

#### Monthly

- Review performance trends
- Update dependencies
- Review security patches

### Backup Procedures

```bash
# Backup subscription data
pg_dump -h localhost -U zeroque -d zeroque_dev \
  --table=tenant_subscriptions \
  --table=subscription_plans \
  --table=plan_features \
  > subscriptions_backup_$(date +%Y%m%d).sql
```

### Update Procedures

1. **Code Updates**

   ```bash
   git pull origin main
   pip install -r requirements.txt
   systemctl restart subscriptions
   ```

2. **Database Migrations**

   ```bash
   alembic upgrade head
   ```

3. **Configuration Updates**
   ```bash
   # Update environment variables
   systemctl daemon-reload
   systemctl restart subscriptions
   ```

---

_Last Updated: October 6, 2024_
_Version: 2.0.0_
_Service: ZeroQue Subscriptions_
