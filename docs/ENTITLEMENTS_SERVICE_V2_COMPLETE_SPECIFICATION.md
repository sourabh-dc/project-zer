# ZeroQue Entitlements Service V2 - Complete API Specification

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Authentication & Authorization](#authentication--authorization)
4. [Data Models](#data-models)
5. [API Endpoints](#api-endpoints)
6. [Usage Examples](#usage-examples)
7. [Error Handling](#error-handling)
8. [Performance & Caching](#performance--caching)
9. [Monitoring & Observability](#monitoring--observability)
10. [Deployment Guide](#deployment-guide)

---

## Overview

The **ZeroQue Entitlements Service V2** is a comprehensive subscription management and access control system that manages feature entitlements, usage tracking, and billing integration for the ZeroQue platform. It provides real-time access control based on subscription plans and enforces usage limits across different features.

### Key Features

- **Tenant-Level Subscriptions**: Manage subscriptions at the tenant level (aligned with v2 architecture)
- **Feature-Based Access Control**: Granular feature entitlements with usage limits
- **Real-Time Usage Tracking**: Monitor and enforce usage limits
- **Redis Caching**: High-performance entitlement checks with 5-minute caching
- **Async Processing**: Background processing for subscription activation and usage aggregation
- **Multi-Provider Billing**: Support for Stripe and trade account billing
- **Feature Flags**: Tenant-specific feature toggles for gradual rollouts

### Service Information

- **Service Name**: entitlements
- **Version**: 2.0.0
- **Port**: 8211
- **Base URL**: `http://localhost:8211`

---

## Architecture

### System Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   FastAPI App   │    │   Redis Cache    │    │   PostgreSQL    │
│                 │    │                  │    │                 │
│ • REST API      │◄──►│ • Entitlement    │◄──►│ • Subscriptions │
│ • Validation    │    │   Cache (5min)   │    │ • Plans         │
│ • Error Handling│    │ • Usage Cache    │    │ • Features      │
│ • RLS Context   │    │ • Feature Flags  │    │ • Usage Data    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                                              │
         ▼                                              ▼
┌─────────────────┐                            ┌─────────────────┐
│   Celery Tasks  │                            │   Event Stream  │
│                 │                            │                 │
│ • Subscription  │                            │ • Subscription  │
│   Activation    │                            │   Events        │
│ • Usage         │                            │ • Usage Events  │
│   Aggregation   │                            │ • Audit Trail   │
└─────────────────┘                            └─────────────────┘
```

### Database Schema

#### Core Tables

- **`subscription_plans`**: Available subscription plans with pricing
- **`features`**: Available features with categories
- **`plan_features`**: Feature-to-plan mappings with limits
- **`tenant_subscriptions`**: Tenant-level subscription records
- **`subscription_usage`**: Usage tracking against limits (tenant-level)
- **`usage_aggregates_daily`**: Daily usage aggregates for billing (tenant-level)
- **`feature_flags`**: Tenant-specific feature toggles

---

## Authentication & Authorization

### Row Level Security (RLS)

The service implements Row Level Security to ensure data isolation:

```sql
-- RLS Context Variables
SET LOCAL app.current_tenant_id = 'tenant_uuid';
SET LOCAL app.user_id = 'user_uuid';
SET row_security = on;
```

### Access Patterns

- **Tenant Isolation**: All data is scoped by tenant_id
- **Tenant-Level Access**: Subscriptions and usage are tracked per tenant
- **Feature-Level Permissions**: Granular access control per feature

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
  "plan_code": "pro",
  "feature_code": "api_access",
  "enabled": true,
  "limits": {
    "rate_limit": 1000,
    "burst_limit": 100
  }
}
```

---

## API Endpoints

### Health & Monitoring

#### GET /health

Check service health status.

**Response:**

```json
{
  "status": "ok",
  "service": "entitlements",
  "version": "2.0.0",
  "enhanced": true
}
```

#### GET /readiness

Check service readiness for traffic.

**Response:**

```json
{
  "service": "entitlements",
  "db": true,
  "redis": true
}
```

### Subscription Management

#### POST /entitlements/v2/subscriptions

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
  "status": "created"
}
```

#### GET /entitlements/v2/subscriptions/{tenant_id}

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
  "trial_end": "2024-01-15T00:00:00Z"
}
```

### Entitlement Checking

#### GET /entitlements/v2/check

Check if a tenant has entitlement to a feature.

**Query Parameters:**

- `tenant_id` (required): Tenant UUID
- `feature_code` (required): Feature code to check
- `usage_type` (optional): Usage type for limit checking

**Example:**

```bash
GET /entitlements/v2/check?tenant_id=550e8400-e29b-41d4-a716-446655440000&feature_code=api_access&usage_type=api_calls
```

**Response (Entitled):**

```json
{
  "entitled": true,
  "feature_code": "api_access",
  "limits": {
    "rate_limit": 1000
  },
  "status": "active",
  "plan_code": "pro",
  "cached": false
}
```

**Response (Not Entitled - No Subscription):**

```json
{
  "entitled": false,
  "feature_code": "api_access",
  "limits": null,
  "status": null,
  "plan_code": null,
  "cached": false
}
```

**Response (Not Entitled - Limit Exceeded):**

```json
{
  "entitled": false,
  "reason": "Usage limit exceeded: 1000/1000",
  "feature_code": "api_access",
  "current_usage": 1000,
  "limit": 1000,
  "cached": false
}
```

### Usage Tracking

#### POST /entitlements/v2/usage/record

Record usage for a feature.

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "feature_code": "api_access",
  "usage_type": "api_calls",
  "usage_count": 5
}
```

**Response:**

```json
{
  "recorded": true,
  "current_usage": 125,
  "period": "2024-10",
  "feature_code": "api_access",
  "usage_type": "api_calls"
}
```

#### GET /entitlements/v2/usage/{tenant_id}

Get usage summary for a tenant.

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "period": "2024-10",
  "usage": {
    "api_access": {
      "api_calls": 125
    },
    "bulk_orders": {
      "orders_processed": 50
    }
  }
}
```

### Plan & Feature Management

#### GET /entitlements/v2/plans

List available subscription plans.

**Response:**

```json
{
  "plans": [
    {
      "code": "core",
      "name": "Core Plan",
      "description": "Basic features for small teams",
      "price_yearly_minor": 100,
      "currency": "GBP"
    },
    {
      "code": "pro",
      "name": "Pro Plan",
      "description": "Advanced features for growing businesses",
      "price_yearly_minor": 200,
      "currency": "GBP"
    },
    {
      "code": "enterprise",
      "name": "Enterprise Plan",
      "description": "Full features for large organizations",
      "price_yearly_minor": 400,
      "currency": "GBP"
    }
  ]
}
```

#### GET /entitlements/v2/features

List available features.

**Response:**

```json
{
  "features": [
    {
      "code": "api_access",
      "name": "API Access",
      "description": "REST API access",
      "category": "integration",
      "active": true
    },
    {
      "code": "bulk_orders",
      "name": "Bulk Orders",
      "description": "Process multiple orders efficiently",
      "category": "orders",
      "active": true
    },
    {
      "code": "advanced_pricing",
      "name": "Advanced Pricing",
      "description": "Store-specific pricing and rules engine",
      "category": "pricing",
      "active": true
    }
  ]
}
```

#### GET /entitlements/v2/plans/{plan_code}/features

Get features for a specific plan.

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
      "limits": {
        "rate_limit": 1000
      }
    },
    {
      "feature_code": "bulk_orders",
      "name": "Bulk Orders",
      "description": "Process multiple orders efficiently",
      "category": "orders",
      "enabled": true,
      "limits": {
        "max_orders_per_day": 100
      }
    },
    {
      "feature_code": "multi_store",
      "name": "Multi-Store",
      "description": "Support for multiple stores per site",
      "category": "stores",
      "enabled": false,
      "limits": {}
    }
  ]
}
```

### Feature Flags

#### GET /entitlements/v2/feature-flags/{tenant_id}

Get all feature flags for a tenant.

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "feature_flags": {
    "new_dashboard": {
      "enabled": true,
      "variant": "beta",
      "updated_at": "2024-10-06T10:30:00Z"
    },
    "advanced_analytics": {
      "enabled": false,
      "variant": null,
      "updated_at": "2024-10-06T09:15:00Z"
    }
  }
}
```

#### POST /entitlements/v2/feature-flags

Create or update a feature flag.

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "key": "new_dashboard",
  "enabled": true,
  "variant": "beta"
}
```

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "key": "new_dashboard",
  "enabled": true,
  "variant": "beta",
  "status": "updated"
}
```

### Cache Management

#### POST /entitlements/v2/cache/clear

Clear entitlement cache for a tenant.

**Query Parameters:**

- `tenant_id` (required): Tenant UUID
- `feature_code` (optional): Specific feature code to clear

**Response:**

```json
{
  "cleared": true,
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "feature_code": "api_access"
}
```

---

## Usage Examples

### Example 1: Complete Subscription Flow

#### Step 1: List Available Plans

```bash
curl "http://localhost:8211/entitlements/v2/plans"
```

#### Step 2: Create Tenant Subscription

```bash
curl -X POST "http://localhost:8211/entitlements/v2/subscriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "plan_code": "pro",
    "payment_method": "stripe",
    "external_id": "sub_1234567890"
  }'
```

#### Step 3: Check Feature Access

```bash
curl "http://localhost:8211/entitlements/v2/check?tenant_id=550e8400-e29b-41d4-a716-446655440000&feature_code=api_access"
```

#### Step 4: Record Usage

```bash
curl -X POST "http://localhost:8211/entitlements/v2/usage/record" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "feature_code": "api_access",
    "usage_type": "api_calls",
    "usage_count": 1
  }'
```

### Example 2: API Gateway Integration

```python
# Before processing API request
def check_api_access(tenant_id: str) -> bool:
    response = requests.get(
        "http://localhost:8211/entitlements/v2/check",
        params={
            "tenant_id": tenant_id,
            "feature_code": "api_access",
            "usage_type": "api_calls"
        }
    )

    if response.status_code == 200:
        data = response.json()
        return data.get("entitled", False)

    return False

# After processing API request
def record_api_usage(tenant_id: str, call_count: int = 1):
    requests.post(
        "http://localhost:8211/entitlements/v2/usage/record",
        json={
            "tenant_id": tenant_id,
            "feature_code": "api_access",
            "usage_type": "api_calls",
            "usage_count": call_count
        }
    )
```

### Example 3: Multi-Store Feature Check

```bash
# Check if tenant can create multiple stores
curl "http://localhost:8211/entitlements/v2/check?tenant_id=tenant123&feature_code=multi_store"

# Response for Core plan (feature disabled)
{
  "entitled": false,
  "feature_code": "multi_store",
  "limits": null,
  "status": null,
  "plan_code": null,
  "cached": false
}

# Response for Pro plan (feature enabled)
{
  "entitled": true,
  "feature_code": "multi_store",
  "limits": {"max_stores": 5},
  "status": "active",
  "plan_code": "pro",
  "cached": false
}
```

---

## Error Handling

### HTTP Status Codes

- **200 OK**: Request successful
- **400 Bad Request**: Invalid request parameters
- **404 Not Found**: Resource not found
- **409 Conflict**: Duplicate resource (e.g., existing subscription)
- **500 Internal Server Error**: Server error

### Custom Exception Types

#### EntitlementValidationError (400)

```json
{
  "detail": "Invalid tenant_id format: invalid-uuid"
}
```

#### EntitlementNotFoundError (404)

```json
{
  "detail": "No subscription found for site 550e8400-e29b-41d4-a716-446655440001"
}
```

#### EntitlementDuplicateError (409)

```json
{
  "detail": "Site already has an active subscription"
}
```

#### SubscriptionProcessingError (500)

```json
{
  "detail": "Database error: connection timeout"
}
```

#### UsageTrackingError (500)

```json
{
  "detail": "Failed to record usage: Redis connection error"
}
```

### Error Response Format

All error responses follow this format:

```json
{
  "detail": "Error description",
  "error_code": "ERROR_CODE",
  "timestamp": "2024-10-06T10:30:00Z"
}
```

---

## Performance & Caching

### Redis Caching Strategy

#### Entitlement Cache

- **Key Pattern**: `entitlement_v2:{hash}`
- **TTL**: 5 minutes (300 seconds)
- **Content**: Feature entitlements with limits
- **Invalidation**: On subscription changes

#### Usage Cache

- **Key Pattern**: `usage_v2:{hash}`
- **TTL**: Until end of month
- **Content**: Current usage counts
- **Invalidation**: On usage recording

### Cache Key Generation

```python
def _get_cache_key_v2(tenant_id: str, site_id: str, feature_code: str) -> str:
    key_data = f"{tenant_id}:{site_id}:{feature_code}"
    return f"entitlement_v2:{hashlib.md5(key_data.encode()).hexdigest()}"

def _get_usage_cache_key_v2(tenant_id: str, site_id: str, feature_code: str, usage_type: str, period: str) -> str:
    key_data = f"{tenant_id}:{site_id}:{feature_code}:{usage_type}:{period}"
    return f"usage_v2:{hashlib.md5(key_data.encode()).hexdigest()}"
```

### Performance Optimizations

1. **Connection Pooling**: Database connection pooling for high throughput
2. **Async Processing**: Celery tasks for non-blocking operations
3. **Batch Operations**: Bulk usage recording support
4. **Query Optimization**: Indexed database queries
5. **Lazy Loading**: On-demand feature loading

---

## Monitoring & Observability

### Health Checks

#### Basic Health Check

```bash
curl "http://localhost:8211/health"
```

#### Detailed Health Check

```bash
curl "http://localhost:8211/health/detailed"
```

### Metrics

#### Application Metrics

- **Request Count**: Total API requests per endpoint
- **Response Time**: P50, P95, P99 response times
- **Error Rate**: Error percentage per endpoint
- **Cache Hit Rate**: Redis cache hit percentage

#### Business Metrics

- **Subscription Count**: Active subscriptions per plan
- **Feature Usage**: Usage counts per feature
- **Entitlement Checks**: Daily entitlement check volume
- **Limit Violations**: Usage limit exceed events

### Logging

#### Structured Logging Format

```json
{
  "timestamp": "2024-10-06T10:30:00Z",
  "level": "INFO",
  "service": "entitlements",
  "event": "entitlement_checked",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "site_id": "550e8400-e29b-41d4-a716-446655440001",
  "feature_code": "api_access",
  "enabled": true,
  "cached": false
}
```

#### Key Events Logged

- `subscription_created`: New subscription created
- `entitlement_checked`: Feature access checked
- `usage_recorded`: Usage recorded
- `cache_hit`: Cache hit occurred
- `cache_miss`: Cache miss occurred
- `limit_exceeded`: Usage limit exceeded

### Alerting

#### Critical Alerts

- Service down (health check fails)
- Database connection failures
- Redis connection failures
- High error rates (>5%)

#### Warning Alerts

- High response times (>1s P95)
- Low cache hit rates (<80%)
- Unusual usage patterns

---

## Deployment Guide

### Prerequisites

#### System Requirements

- **Python**: 3.11+
- **PostgreSQL**: 13+
- **Redis**: 6+
- **Memory**: 512MB minimum
- **CPU**: 1 core minimum

#### Dependencies

```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary redis celery pydantic
```

### Environment Variables

#### Required Variables

```bash
# Database
DATABASE_URL=postgresql://zeroque:zeroque@localhost:5000/zeroque_dev

# Redis
REDIS_URL=redis://localhost:4000/0

# Service Configuration
LOG_LEVEL=INFO
SERVICE_NAME=entitlements
SERVICE_PORT=8211
```

#### Optional Variables

```bash
# Celery Configuration
CELERY_BROKER_URL=redis://localhost:4000/0
CELERY_RESULT_BACKEND=redis://localhost:4000/0

# Monitoring
METRICS_ENABLED=true
TRACING_ENABLED=true
```

### Docker Deployment

#### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY services/entitlements/ ./services/entitlements/
COPY packages/zeroque_common/ ./packages/zeroque_common/

EXPOSE 8211

CMD ["uvicorn", "services.entitlements.main:app", "--host", "0.0.0.0", "--port", "8211"]
```

#### Docker Compose

```yaml
version: "3.8"
services:
  entitlements:
    build: .
    ports:
      - "8211:8211"
    environment:
      - DATABASE_URL=postgresql://zeroque:zeroque@postgres:5432/zeroque_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis

  entitlements-worker:
    build: .
    command: celery -A services.entitlements.main.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://zeroque:zeroque@postgres:5432/zeroque_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
```

### Production Configuration

#### Security

- Enable HTTPS/TLS
- Configure proper firewall rules
- Use environment-specific secrets
- Enable database SSL connections

#### Scaling

- **Horizontal Scaling**: Deploy multiple service instances
- **Load Balancing**: Use nginx or cloud load balancer
- **Database**: Read replicas for read-heavy workloads
- **Redis**: Redis Cluster for high availability

#### Monitoring Setup

```bash
# Install monitoring tools
pip install prometheus-client

# Configure log aggregation
# Set up log forwarding to ELK stack or similar
```

### Testing

#### Unit Tests

```bash
# Run unit tests
python -m pytest tests/unit/

# Run with coverage
python -m pytest tests/unit/ --cov=services.entitlements
```

#### Integration Tests

```bash
# Run integration tests
python -m pytest tests/integration/

# Run against test database
DATABASE_URL=postgresql://test:test@localhost:5432/zeroque_test python -m pytest
```

#### Load Testing

```bash
# Install locust
pip install locust

# Run load tests
locust -f tests/load/locustfile.py --host=http://localhost:8211
```

---

## API Reference Summary

| Method | Endpoint                                      | Description                |
| ------ | --------------------------------------------- | -------------------------- |
| GET    | `/health`                                     | Service health check       |
| GET    | `/readiness`                                  | Service readiness check    |
| POST   | `/entitlements/v2/subscriptions`              | Create tenant subscription |
| GET    | `/entitlements/v2/subscriptions/{tenant_id}`  | Get subscription details   |
| GET    | `/entitlements/v2/check`                      | Check feature entitlement  |
| POST   | `/entitlements/v2/usage/record`               | Record usage               |
| GET    | `/entitlements/v2/usage/{tenant_id}`          | Get usage summary          |
| GET    | `/entitlements/v2/plans`                      | List subscription plans    |
| GET    | `/entitlements/v2/features`                   | List available features    |
| GET    | `/entitlements/v2/plans/{plan_code}/features` | Get plan features          |
| GET    | `/entitlements/v2/feature-flags/{tenant_id}`  | Get feature flags          |
| POST   | `/entitlements/v2/feature-flags`              | Set feature flag           |
| POST   | `/entitlements/v2/cache/clear`                | Clear entitlement cache    |

---

## Support & Maintenance

### Troubleshooting

#### Common Issues

1. **Service Won't Start**

   - Check database connectivity
   - Verify Redis connection
   - Check port availability

2. **Entitlement Checks Failing**

   - Verify subscription exists
   - Check feature configuration
   - Clear cache if needed

3. **High Response Times**
   - Check database performance
   - Verify Redis connectivity
   - Review query performance

### Maintenance Tasks

#### Daily

- Monitor health checks
- Review error logs
- Check cache hit rates

#### Weekly

- Review usage metrics
- Check subscription growth
- Validate backup processes

#### Monthly

- Review performance trends
- Update dependencies
- Security patches

### Contact Information

- **Service Owner**: ZeroQue Platform Team
- **Documentation**: This specification document
- **Issues**: GitHub Issues or internal ticketing system
- **Emergency**: On-call rotation

---

_Last Updated: October 6, 2024_
_Version: 2.0.0_
_Service: ZeroQue Entitlements_
