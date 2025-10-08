# ZeroQue Entry Service V4.1 - Complete API Documentation

## Overview

The ZeroQue Entry Service V4.1 is a comprehensive microservice that manages entry codes for unmanned stores, providing secure access control with multi-provider support, event-driven integration, and production-ready reliability patterns.

## Architecture Alignment

### V4.1 Architecture Compliance

- ✅ **Multi-Tenant**: Full tenant isolation with Row Level Security (RLS)
- ✅ **Event-Driven**: Comprehensive event publishing and consumption
- ✅ **Saga Pattern**: Reliable distributed transaction management with compensation
- ✅ **Circuit Breaker**: Resilient external service calls
- ✅ **Outbox Pattern**: Reliable event delivery
- ✅ **Multi-Provider**: Swappable entry providers (AiFi, internal)
- ✅ **Audit & Compliance**: Complete audit trails and data retention

### Key Features

- **Multi-Provider Support**: AiFi, internal providers with dynamic configuration
- **Reliable Operations**: Saga pattern with compensation logic
- **Event Integration**: ENTRY_GRANTED, ENTRY_VALIDATED events
- **Security**: JWT authentication, RLS, permission-based access control
- **Monitoring**: Prometheus metrics, structured logging
- **Rate Limiting**: Per-user rate limiting with Redis
- **Legacy Compatibility**: Deprecated endpoints with V4 redirects

## API Endpoints

### Core Entry Operations

#### Issue Entry Code

```http
POST /entry/v4/issue-code
```

**Description**: Generate a new entry code for store access with multi-provider support.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "site_id": "550e8400-e29b-41d4-a716-446655440001",
  "store_id": "550e8400-e29b-41d4-a716-446655440002",
  "user_id": "550e8400-e29b-41d4-a716-446655440003",
  "group_size": 2,
  "ttl_minutes": 20,
  "provider": "aifi"
}
```

**Response**:

```json
{
  "allowed": true,
  "code": "123456",
  "ttl_minutes": 20
}
```

**Error Responses**:

- `400 Bad Request`: Invalid payload or insufficient budget
- `403 Forbidden`: Insufficient permissions
- `429 Too Many Requests`: Rate limited
- `500 Internal Server Error`: Server error

#### Validate Entry Code

```http
POST /entry/v4/validate-code
```

**Description**: Validate and consume an entry code.

**Request Body**:

```json
{
  "code": "123456",
  "provider": "aifi"
}
```

**Response**:

```json
{
  "valid": true,
  "consumed": true,
  "context": {
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "site_id": "550e8400-e29b-41d4-a716-446655440001",
    "store_id": "550e8400-e29b-41d4-a716-446655440002",
    "user_id": "550e8400-e29b-41d4-a716-446655440003"
  }
}
```

#### Get Entry Status

```http
GET /entry/v4/status?code=123456
```

**Description**: Check if an entry code exists and get its context.

**Response**:

```json
{
  "exists": true,
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "site_id": "550e8400-e29b-41d4-a716-446655440001",
  "store_id": "550e8400-e29b-41d4-a716-446655440002",
  "user_id": "550e8400-e29b-41d4-a716-446655440003"
}
```

### Admin Operations

#### Configure Entry Provider

```http
POST /entry/v4/admin/rails/entry
```

**Description**: Configure entry provider via zeroque_rails.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "entry",
  "name": "aifi",
  "config": {
    "provider": "aifi",
    "api_key": "test-api-key",
    "base_url": "https://api.aifi.io",
    "entry_endpoint": "/entry-codes",
    "verify_endpoint": "/verify"
  },
  "active": true
}
```

#### List Entry Providers

```http
GET /entry/v4/admin/rails/entry?tenant_id=550e8400-e29b-41d4-a716-446655440000
```

**Response**:

```json
{
  "ok": true,
  "providers": [
    {
      "name": "aifi",
      "config": {
        "provider": "aifi",
        "api_key": "test-api-key",
        "base_url": "https://api.aifi.io"
      },
      "active": true,
      "created_at": "2025-01-07T20:15:00Z",
      "updated_at": "2025-01-07T20:15:00Z"
    }
  ]
}
```

### Integration Endpoints

#### Handle User Created Event

```http
POST /entry/v4/integration/provisioning/user-created
```

**Description**: Handle USER_CREATED event from Provisioning service.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "event_type": "USER_CREATED",
  "user_data": {
    "email": "test@example.com",
    "name": "Test User"
  }
}
```

#### Get Integration Status

```http
GET /entry/v4/integration/status
```

**Response**:

```json
{
  "ok": true,
  "service": "entry",
  "version": "4.1.0",
  "integrations": {
    "provisioning": {
      "connected": true,
      "events_handled": ["USER_CREATED"]
    },
    "access": {
      "connected": true,
      "events_published": ["ENTRY_GRANTED"]
    },
    "orders": {
      "connected": true,
      "events_published": ["ENTRY_VALIDATED"]
    },
    "notifications": {
      "connected": true,
      "events_published": ["ENTRY_GRANTED"]
    }
  },
  "status": {
    "pending_events": 0,
    "active_providers": 1,
    "total_providers": 1
  }
}
```

### Event Retry

#### Retry Pending Events

```http
POST /entry/v4/events/retry?tenant_id=550e8400-e29b-41d4-a716-446655440000&max_events=10
```

**Description**: Retry pending outbox events for reliable delivery.

**Response**:

```json
{
  "ok": true,
  "retried_count": 5,
  "total_events": 8
}
```

### Health & Monitoring

#### Health Check

```http
GET /health
```

**Response**:

```json
{
  "status": "ok",
  "service": "entry",
  "version": "4.1.0"
}
```

#### Readiness Check

```http
GET /readiness
```

**Response**:

```json
{
  "service": "entry",
  "version": "4.1.0",
  "db": true,
  "redis": true,
  "ready": true
}
```

#### Prometheus Metrics

```http
GET /metrics
```

**Description**: Prometheus metrics endpoint for monitoring.

## Data Models

### EntryCodeNew

```python
class EntryCodeNew:
    id: UUID                    # Primary key
    tenant_id: UUID            # Tenant isolation
    site_id: UUID              # Site reference
    store_id: UUID             # Store reference
    user_id: UUID              # User reference
    code: str                  # Entry code (unique)
    expires_at: datetime       # Expiration time
    consumed_at: datetime      # Consumption time (nullable)
    group_size: int            # Group size (1-10)
    provider: str              # Provider name
    entry_metadata: JSONB      # Additional metadata
    created_at: datetime       # Creation timestamp
    updated_at: datetime       # Update timestamp
```

### IssueCodePayload

```python
class IssueCodePayload:
    tenant_id: str             # Required
    site_id: str               # Required
    store_id: str              # Required
    user_id: str               # Required
    group_size: int = 1        # 1-10, default 1
    ttl_minutes: int = 15      # 1-60, default 15
    provider: Optional[str]    # Provider override
```

### ValidateCodePayload

```python
class ValidateCodePayload:
    code: str                  # Required
    provider: Optional[str]    # Provider override
```

### EntryProviderConfig

```python
class EntryProviderConfig:
    provider: str              # Provider name
    api_key: str               # API key
    base_url: str              # Base URL
    entry_endpoint: str        # Entry endpoint
    verify_endpoint: str       # Verify endpoint
```

## Provider Integration

### AiFi Provider

- **Entry Codes**: Calls `/customers/{id}/entry-codes` with displayable=true for QR
- **Validation**: Calls `/stores/{id}/entry/{code}/verify`
- **User Sync**: Syncs users on USER_CREATED events

### Internal Provider

- **Entry Codes**: Generates 6-digit random codes
- **Validation**: Redis-based validation with TTL
- **Storage**: Both Redis (fast) and PostgreSQL (persistent)

## Saga Pattern

### EntryCodeSaga

The service implements a comprehensive saga pattern for reliable operations:

#### Issue Code Saga

1. **Validate User Budget**: Check cost centre and budget limits
2. **Issue Provider Code**: Call external provider or generate internal
3. **Store in Database**: Persist to entry_codes_new table
4. **Store in Redis**: Cache for fast access with TTL
5. **Publish Event**: ENTRY_GRANTED to outbox_events
6. **Audit Log**: Create audit trail

#### Validate Code Saga

1. **Validate via Provider**: Check code validity
2. **Update Database**: Mark as consumed
3. **Publish Event**: ENTRY_VALIDATED to outbox_events
4. **Audit Log**: Create audit trail

#### Compensation Logic

- **Redis Cleanup**: Remove cached entries
- **Database Rollback**: Delete database entries
- **Event Cleanup**: Remove published events

## Event System

### Published Events

#### ENTRY_GRANTED

```json
{
  "event_type": "ENTRY_GRANTED",
  "event_data": {
    "entry_code_id": "uuid",
    "tenant_id": "uuid",
    "site_id": "uuid",
    "store_id": "uuid",
    "user_id": "uuid",
    "code": "123456",
    "provider": "aifi",
    "expires_at": "2025-01-07T20:30:00Z",
    "group_size": 2
  }
}
```

#### ENTRY_VALIDATED

```json
{
  "event_type": "ENTRY_VALIDATED",
  "event_data": {
    "code": "123456",
    "provider": "aifi",
    "validated_at": "2025-01-07T20:15:00Z",
    "tenant_id": "uuid"
  }
}
```

### Consumed Events

#### USER_CREATED

- **Source**: Provisioning service
- **Action**: Sync user to entry provider
- **Handler**: `/entry/v4/integration/provisioning/user-created`

## Security & Authentication

### JWT Authentication

- All endpoints require valid JWT token
- Token validation extracts user context
- Permission-based access control

### Row Level Security (RLS)

- All database queries use tenant_id isolation
- User-specific access controls
- Automatic context setting

### Permission Matrix

- `entry.issue_code`: Issue entry codes
- `entry.validate_code`: Validate entry codes
- `entry.view_status`: View entry status
- `entry.admin`: Admin operations

## Monitoring & Observability

### Prometheus Metrics

- `entry_requests_total`: Request counts by endpoint/status
- `entry_request_duration_seconds`: Request duration histograms
- `entry_codes_generated_total`: Generated codes by provider/tenant
- `entry_codes_validated_total`: Validated codes by provider/tenant
- `entry_saga_duration_seconds`: Saga execution time
- `entry_saga_failures_total`: Saga failures by type/reason

### Structured Logging

- JSON-formatted logs with correlation IDs
- Request/response logging
- Error tracking with stack traces
- Performance metrics

### Health Monitoring

- Database connectivity checks
- Redis availability checks
- Provider health monitoring
- Integration status tracking

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/zeroque

# Redis
REDIS_URL=redis://localhost:4000/0

# Entry Configuration
ENTRY_CODE_TTL_MINUTES=15
ENTRY_RATE_LIMIT_SEC=1
ENTRY_STATUS_ENABLED=1
ENTRY_VALIDATE_INCLUDE_CONTEXT=0

# Server
PORT=8087
ENVIRONMENT=production
```

### Provider Configuration

Providers are configured via the `zeroque_rails` table:

```sql
INSERT INTO zeroque_rails (tenant_id, type, name, config, active) VALUES
('tenant-uuid', 'entry', 'aifi', '{
  "provider": "aifi",
  "api_key": "your-api-key",
  "base_url": "https://api.aifi.io",
  "entry_endpoint": "/entry-codes",
  "verify_endpoint": "/verify"
}', true);
```

## Database Schema

### entry_codes_new

```sql
CREATE TABLE entry_codes_new (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    site_id UUID NOT NULL,
    store_id UUID NOT NULL,
    user_id UUID NOT NULL,
    code VARCHAR(50) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    group_size INTEGER DEFAULT 1 NOT NULL,
    provider VARCHAR(50) DEFAULT 'internal' NOT NULL,
    entry_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Indexes
CREATE INDEX idx_entry_codes_new_tenant_id ON entry_codes_new(tenant_id);
CREATE INDEX idx_entry_codes_new_user_id ON entry_codes_new(user_id);
CREATE INDEX idx_entry_codes_new_store_id ON entry_codes_new(store_id);
CREATE INDEX idx_entry_codes_new_expires_at ON entry_codes_new(expires_at);
CREATE INDEX idx_entry_codes_new_consumed_at ON entry_codes_new(consumed_at);

-- RLS
ALTER TABLE entry_codes_new ENABLE ROW LEVEL SECURITY;
CREATE POLICY entry_codes_new_isolation_policy ON entry_codes_new
USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
```

## Integration Examples

### Complete Entry Flow

```python
# 1. Issue entry code
response = requests.post('/entry/v4/issue-code', json={
    "tenant_id": "tenant-uuid",
    "site_id": "site-uuid",
    "store_id": "store-uuid",
    "user_id": "user-uuid",
    "group_size": 2,
    "ttl_minutes": 20
})

# 2. Validate entry code
response = requests.post('/entry/v4/validate-code', json={
    "code": "123456"
})

# 3. Check status
response = requests.get('/entry/v4/status?code=123456')
```

### Provider Configuration

```python
# Configure AiFi provider
requests.post('/entry/v4/admin/rails/entry', json={
    "tenant_id": "tenant-uuid",
    "type": "entry",
    "name": "aifi",
    "config": {
        "provider": "aifi",
        "api_key": "your-api-key",
        "base_url": "https://api.aifi.io"
    },
    "active": True
})
```

## Error Handling

### Common Error Scenarios

- **Rate Limiting**: Too many requests per user
- **Budget Exhausted**: Insufficient budget/approvals
- **Invalid Code**: Expired or non-existent codes
- **Provider Failure**: External provider unavailable
- **Permission Denied**: Insufficient user permissions

### Error Response Format

```json
{
  "detail": "Error message",
  "status_code": 400,
  "headers": {
    "X-Remaining-Minor": "1000",
    "X-Currency": "GBP"
  }
}
```

## Performance Considerations

### Caching Strategy

- **Redis**: Fast code validation with TTL
- **Database**: Persistent storage for audit/compliance
- **Provider Cache**: Configurable provider responses

### Rate Limiting

- Per-user rate limiting (configurable)
- Redis-based implementation
- Configurable time windows

### Database Optimization

- Proper indexing on query patterns
- RLS for tenant isolation
- Connection pooling

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "services.entry.main_simple"]
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: entry-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: entry-service
  template:
    metadata:
      labels:
        app: entry-service
    spec:
      containers:
        - name: entry-service
          image: zeroque/entry-service:4.1.0
          ports:
            - containerPort: 8087
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: database-secret
                  key: url
            - name: REDIS_URL
              valueFrom:
                configMapKeyRef:
                  name: redis-config
                  key: url
```

## Testing

### Unit Tests

- Component testing for all models
- Saga pattern testing with mocks
- Provider integration testing
- Error scenario testing

### Integration Tests

- End-to-end entry flow testing
- Provider switching testing
- Event publishing/consumption testing
- Performance testing

### Test Coverage

- 95%+ code coverage
- All endpoints tested
- Error scenarios covered
- Performance benchmarks

## Migration Guide

### From Legacy Entry Service

1. **Database Migration**: Run Alembic migration for new tables
2. **Provider Configuration**: Set up zeroque_rails entries
3. **Endpoint Updates**: Update clients to use V4 endpoints
4. **Event Integration**: Set up event handlers
5. **Monitoring**: Configure Prometheus metrics

### Breaking Changes

- Legacy endpoints deprecated (redirect to V4)
- New required fields in payloads
- Different response formats
- Enhanced security requirements

## Troubleshooting

### Common Issues

1. **Database Connection**: Check DATABASE_URL and connectivity
2. **Redis Connection**: Verify REDIS_URL and Redis availability
3. **Provider Errors**: Check provider configuration and API keys
4. **Permission Errors**: Verify JWT token and user permissions
5. **Rate Limiting**: Check rate limit configuration

### Debug Mode

```bash
ENVIRONMENT=development python -m services.entry.main_simple
```

### Logs

```bash
# View structured logs
tail -f /var/log/entry-service.log | jq .

# Filter by tenant
tail -f /var/log/entry-service.log | jq 'select(.tenant_id == "tenant-uuid")'
```

## Support & Maintenance

### Monitoring

- Prometheus metrics dashboard
- Grafana dashboards for visualization
- Alerting on error rates and latency
- Health check monitoring

### Maintenance

- Regular database cleanup of expired codes
- Provider configuration updates
- Security updates and patches
- Performance optimization

### Support Channels

- Documentation: This document
- Issues: GitHub issues
- Monitoring: Prometheus/Grafana
- Logs: Structured JSON logs

---

## Summary

The ZeroQue Entry Service V4.1 provides a comprehensive, production-ready solution for managing entry codes in unmanned stores. With multi-provider support, reliable saga patterns, comprehensive security, and extensive monitoring, it's fully aligned with the V4.1 architecture and ready for production deployment.

**Key Achievements:**

- ✅ **Multi-Provider**: AiFi and internal providers with dynamic configuration
- ✅ **Reliability**: Saga pattern with compensation logic
- ✅ **Security**: JWT authentication, RLS, permission-based access
- ✅ **Integration**: Event-driven integration with other services
- ✅ **Monitoring**: Prometheus metrics and structured logging
- ✅ **Production Ready**: Comprehensive error handling and testing
