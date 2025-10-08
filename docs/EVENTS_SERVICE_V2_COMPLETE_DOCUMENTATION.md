# ZeroQue Events Service V2 - Complete API Documentation

## Overview

The ZeroQue Events Service V2 is a centralized event processing and management service that provides reliable event publishing, consumption, and monitoring capabilities across the ZeroQue microservices ecosystem. It aligns with the V4.1 architecture and provides a unified event bus for all services.

## Architecture Alignment

### V4.1 Architecture Compliance

- ✅ **Multi-Tenant**: Full tenant isolation with Row Level Security (RLS)
- ✅ **Event-Driven**: Centralized event bus with reliable delivery
- ✅ **Saga Pattern**: Reliable event publishing with compensation logic
- ✅ **Circuit Breaker**: Resilient external service calls
- ✅ **Outbox Pattern**: Reliable event delivery with retry mechanisms
- ✅ **Multi-Provider**: RabbitMQ and Redis support
- ✅ **Audit & Compliance**: Complete audit trails and event history

### Key Features

- **Centralized Event Bus**: Single point of event publishing and routing
- **Reliable Delivery**: Saga pattern with compensation for failed events
- **Event History**: Complete audit trail of all events
- **Multi-Service Integration**: Direct integration with all ZeroQue services
- **Security**: JWT authentication, RLS, permission-based access control
- **Monitoring**: Prometheus metrics, structured logging
- **Legacy Compatibility**: Deprecated endpoints with V4 redirects

## API Endpoints

### Core Event Operations

#### Publish Event

```http
POST /events/v4/publish
```

**Description**: Publish an event to the centralized event bus.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "USER_CREATED",
  "event_data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440003",
    "email": "user@example.com",
    "name": "John Doe"
  },
  "metadata": {
    "source": "identity_service",
    "version": "1.0"
  }
}
```

**Response**:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440004",
  "status": "published",
  "message": "Event published successfully"
}
```

**Required Permissions**: `events.publish`

#### Get Event History

```http
GET /events/v4/history?tenant_id={tenant_id}&event_type={type}&status={status}&limit={limit}&offset={offset}
```

**Description**: Retrieve event history with filtering capabilities.

**Query Parameters**:

- `tenant_id` (required): Tenant ID to filter events
- `event_type` (optional): Filter by event type
- `status` (optional): Filter by event status (pending, published, failed)
- `start_date` (optional): Filter events from this date
- `end_date` (optional): Filter events until this date
- `limit` (optional): Maximum number of events to return (default: 50, max: 100)
- `offset` (optional): Number of events to skip (default: 0)

**Response**:

```json
{
  "events": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440004",
      "event_type": "USER_CREATED",
      "event_data": {
        "user_id": "550e8400-e29b-41d4-a716-446655440003",
        "email": "user@example.com"
      },
      "status": "published",
      "retry_count": 0,
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:01Z",
      "published_at": "2024-01-15T10:30:01Z"
    }
  ],
  "total_count": 150,
  "has_more": true
}
```

**Required Permissions**: `events.view`

#### Retry Failed Events

```http
POST /events/v4/retry
```

**Description**: Retry pending or failed events.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "max_events": 10,
  "event_types": ["USER_CREATED", "ORDER_COMPLETED"]
}
```

**Response**:

```json
{
  "ok": true,
  "retried_count": 5,
  "total_events": 8
}
```

**Required Permissions**: `events.admin`

#### Get Event Statistics

```http
GET /events/v4/stats?tenant_id={tenant_id}&event_type={type}&start_date={date}&end_date={date}
```

**Description**: Get aggregated event statistics.

**Query Parameters**:

- `tenant_id` (required): Tenant ID to filter statistics
- `event_type` (optional): Filter by event type
- `start_date` (optional): Start date for statistics
- `end_date` (optional): End date for statistics

**Response**:

```json
{
  "stats": {
    "total_events": 1250,
    "by_event_type": {
      "USER_CREATED": 150,
      "ORDER_COMPLETED": 800,
      "ENTRY_GRANTED": 300
    },
    "by_status": {
      "published": 1200,
      "failed": 50
    },
    "avg_duration": 0.125,
    "total_duration": 156.25
  },
  "period": "2024-01-01T00:00:00Z to 2024-01-15T23:59:59Z"
}
```

**Required Permissions**: `events.view`

### Admin Operations

#### Create Event Subscription

```http
POST /events/v4/admin/subscriptions
```

**Description**: Create a new event subscription for a service.

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "service_name": "notifications",
  "event_type": "USER_CREATED",
  "queue_name": "user_events_queue"
}
```

**Response**:

```json
{
  "subscription_id": "550e8400-e29b-41d4-a716-446655440005",
  "status": "created",
  "message": "Event subscription created successfully"
}
```

**Required Permissions**: `events.admin`

#### List Event Subscriptions

```http
GET /events/v4/admin/subscriptions?tenant_id={tenant_id}
```

**Description**: List all event subscriptions for a tenant.

**Query Parameters**:

- `tenant_id` (required): Tenant ID to filter subscriptions

**Response**:

```json
{
  "subscriptions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440005",
      "service_name": "notifications",
      "event_type": "USER_CREATED",
      "queue_name": "user_events_queue",
      "active": true,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

**Required Permissions**: `events.admin`

### Integration Endpoints

#### Handle Entry Events

```http
POST /events/v4/integration/entry/entry-granted
```

**Description**: Handle ENTRY_GRANTED events from Entry service.

#### Handle Identity Events

```http
POST /events/v4/integration/identity/user-created
```

**Description**: Handle USER_CREATED events from Identity service.

#### Handle Orders Events

```http
POST /events/v4/integration/orders/order-completed
```

**Description**: Handle ORDER_COMPLETED events from Orders service.

#### Handle Approvals Events

```http
POST /events/v4/integration/approvals/approval-resolved
```

**Description**: Handle APPROVAL_RESOLVED events from Approvals service.

#### Handle Billing Events

```http
POST /events/v4/integration/billing/invoice-posted
```

**Description**: Handle INVOICE_POSTED events from Billing service.

#### Get Integration Status

```http
GET /events/v4/integration/status
```

**Description**: Get integration status for all connected services.

**Response**:

```json
{
  "integration_status": {
    "entry": {
      "status": "connected",
      "response_time": 0.025,
      "url": "http://localhost:8085"
    },
    "identity": {
      "status": "connected",
      "response_time": 0.03,
      "url": "http://localhost:8086"
    },
    "orders": {
      "status": "connected",
      "response_time": 0.028,
      "url": "http://localhost:8080"
    }
  },
  "events_service": "operational",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Required Permissions**: `events.admin`

### Health & Monitoring

#### Health Check

```http
GET /events/v4/health
```

**Response**:

```json
{
  "status": "healthy",
  "service": "events",
  "version": "2.0.0"
}
```

#### Readiness Check

```http
GET /events/v4/readiness
```

**Response**:

```json
{
  "status": "ready",
  "database": "connected",
  "service": "events"
}
```

#### Metrics

```http
GET /events/v4/metrics
```

**Response**: Prometheus metrics in text format

### Legacy Endpoints (Deprecated)

The following endpoints are deprecated and redirect to V4 endpoints:

- `POST /publish` → `POST /events/v4/publish`
- `GET /history` → `GET /events/v4/history`
- `GET /stats` → `GET /events/v4/stats`

## Data Models

### EventNew

```sql
CREATE TABLE events_new (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    retry_count INTEGER DEFAULT 0 NOT NULL,
    max_retries INTEGER DEFAULT 3 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    published_at TIMESTAMP WITH TIME ZONE
);
```

### EventSubscription

```sql
CREATE TABLE event_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    service_name VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    queue_name VARCHAR(100) NOT NULL,
    active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, service_name, event_type)
);
```

### EventMetric

```sql
CREATE TABLE event_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    event_type VARCHAR(100) NOT NULL,
    metric_type VARCHAR(50) NOT NULL,
    metric_value FLOAT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    metadata JSONB
);
```

## Saga Workflows

### EventPublishSaga

The EventPublishSaga ensures reliable event publishing with compensation logic:

1. **Validate Event**: Check required fields and permissions
2. **Store Event**: Save event to database with 'pending' status
3. **Publish to Bus**: Send event to RabbitMQ via Celery
4. **Mark Published**: Update status to 'published' on success
5. **Record Metrics**: Track publishing duration and success
6. **Audit Log**: Create audit trail entry
7. **Compensation**: Mark as 'failed' if any step fails

### EventRetrySaga

The EventRetrySaga handles retry logic for failed events:

1. **Get Pending Events**: Query events with retry_count < max_retries
2. **Retry Publishing**: Attempt to republish each event
3. **Update Status**: Mark as 'published' or 'failed' based on result
4. **Record Metrics**: Track retry success/failure rates

## Event Types

The Events service supports all event types from the ZeroQue ecosystem:

### Core Events

- `USER_CREATED`: User account creation
- `USER_UPDATED`: User account updates
- `USER_DELETED`: User account deletion

### Entry Events

- `ENTRY_GRANTED`: Entry code issued
- `ENTRY_VALIDATED`: Entry code validated
- `ENTRY_EXPIRED`: Entry code expired

### Order Events

- `ORDER_CREATED`: New order created
- `ORDER_COMPLETED`: Order successfully completed
- `ORDER_CANCELLED`: Order cancelled
- `ORDER_FAILED`: Order processing failed

### Approval Events

- `APPROVAL_CREATED`: New approval request created
- `APPROVAL_RESOLVED`: Approval request resolved
- `APPROVAL_EXPIRED`: Approval request expired

### Billing Events

- `INVOICE_CREATED`: New invoice created
- `INVOICE_POSTED`: Invoice posted to ledger
- `PAYMENT_RECEIVED`: Payment received
- `PAYMENT_FAILED`: Payment processing failed

### Catalog Events

- `PRODUCT_CREATED`: New product added
- `PRODUCT_UPDATED`: Product information updated
- `PRODUCT_DELETED`: Product removed

### CV Events

- `ORDER_SUMMARY_RECEIVED`: CV order summary received
- `REVIEW_NEEDED`: Item review required
- `REVIEW_RESOLVED`: Item review resolved

## Security

### Authentication

All endpoints require JWT authentication via Bearer token:

```http
Authorization: Bearer <jwt_token>
```

### Permissions

The service uses role-based access control:

- `events.publish`: Publish events
- `events.view`: View event history and statistics
- `events.admin`: Admin operations (retry, subscriptions)

### Row Level Security (RLS)

All database queries are automatically filtered by tenant_id using RLS policies:

```sql
CREATE POLICY events_new_isolation_policy ON events_new
USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
```

## Monitoring & Observability

### Prometheus Metrics

The service exposes the following metrics:

- `event_publish_total`: Total events published by type and status
- `event_publish_duration_seconds`: Event publishing duration histogram
- `event_consume_total`: Total events consumed by type and status
- `event_retry_total`: Total event retries by type
- `event_queue_length`: Current queue length by queue name

### Structured Logging

All logs use structured JSON format with the following fields:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "logger": "events_service",
  "message": "Event published successfully",
  "event_type": "USER_CREATED",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_id": "550e8400-e29b-41d4-a716-446655440004"
}
```

### Health Checks

The service provides comprehensive health checks:

- Database connectivity
- RabbitMQ connectivity
- Service dependencies
- Resource utilization

## Integration Patterns

### Service-to-Service Communication

Services publish events to the Events service:

```python
async def publish_event(event_type: str, event_data: Dict[str, Any], tenant_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8087/events/v4/publish",
            json={
                "tenant_id": tenant_id,
                "event_type": event_type,
                "event_data": event_data
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        return response.status_code == 200
```

### Event Consumption

Services consume events via RabbitMQ queues:

```python
@celery_app.task
def process_user_created_event(event_data: Dict[str, Any]):
    """Process USER_CREATED event"""
    user_id = event_data.get("user_id")
    email = event_data.get("email")

    # Process the event
    logger.info(f"Processing user creation for {email}")

    return True
```

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/zeroque

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost:5672//

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0

# Service Configuration
EVENT_RETENTION_DAYS=30
MAX_EVENTS_PER_REQUEST=100

# Logging
LOG_LEVEL=INFO
```

### Docker Deployment

```yaml
version: "3.8"
services:
  events-service:
    build: .
    ports:
      - "8087:8087"
    environment:
      - DATABASE_URL=postgresql://postgres:password@postgres:5432/zeroque
      - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672//
      - CELERY_BROKER_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - rabbitmq
      - redis
```

## Testing

### Unit Tests

The service includes comprehensive unit tests for:

- Saga execution and compensation
- Event validation and publishing
- Database operations
- Authentication and authorization
- Error handling

### Integration Tests

Integration tests cover:

- End-to-end event publishing flow
- Service-to-service communication
- Event history and filtering
- Retry mechanisms
- Performance under load

### Load Testing

Load tests validate:

- Concurrent event publishing
- Database performance
- RabbitMQ throughput
- Memory usage
- Response times

## Troubleshooting

### Common Issues

1. **Event Publishing Failures**

   - Check RabbitMQ connectivity
   - Verify tenant permissions
   - Review event payload format

2. **Database Connection Issues**

   - Verify database URL
   - Check network connectivity
   - Review connection pool settings

3. **Authentication Errors**
   - Validate JWT token
   - Check user permissions
   - Verify tenant context

### Debugging

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
```

Check service health:

```bash
curl http://localhost:8087/events/v4/health
curl http://localhost:8087/events/v4/readiness
```

View metrics:

```bash
curl http://localhost:8087/events/v4/metrics
```

## Migration Guide

### From Legacy Events Service

1. **Update Service URLs**: Change from `/publish` to `/events/v4/publish`
2. **Add Authentication**: Include JWT tokens in requests
3. **Update Payloads**: Use new request/response formats
4. **Test Integration**: Verify event publishing and consumption

### Database Migration

Run the Alembic migration:

```bash
alembic upgrade head
```

This creates the new tables and RLS policies.

## Performance Considerations

### Optimization Tips

1. **Batch Operations**: Use batch endpoints for multiple events
2. **Connection Pooling**: Configure appropriate pool sizes
3. **Caching**: Cache frequently accessed data
4. **Indexing**: Ensure proper database indexes

### Scaling

The service supports horizontal scaling:

- Multiple service instances
- Database read replicas
- RabbitMQ clustering
- Redis clustering

## Future Enhancements

### Planned Features

1. **Event Streaming**: Real-time event streaming via WebSockets
2. **Event Replay**: Ability to replay historical events
3. **Advanced Analytics**: Event pattern analysis and insights
4. **Multi-Region**: Cross-region event replication
5. **Event Sourcing**: Complete event sourcing capabilities

### Roadmap

- Q1 2024: Event streaming and WebSocket support
- Q2 2024: Advanced analytics dashboard
- Q3 2024: Multi-region deployment
- Q4 2024: Event sourcing implementation

## Support

For technical support:

- **Documentation**: This API documentation
- **Issues**: GitHub issues repository
- **Slack**: #events-service channel
- **Email**: events-support@zeroque.com

## License

This service is part of the ZeroQue platform and is proprietary software.
