# ZeroQue Usage Service V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Usage Service V4.1 provides comprehensive usage tracking and metering capabilities for the ZeroQue ecosystem. It implements production-ready features including usage event recording, meter management, usage analytics, and billing integration.

## 📋 Service Information

- **Service Name**: usage
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8200` (development)
- **Architecture**: Usage tracking and metering platform
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Usage Event Recording**: Real-time usage event capture and storage
- **Meter Management**: Configurable meters for different usage types
- **Analytics Engine**: Usage analytics and reporting capabilities
- **Billing Integration**: Seamless integration with billing systems
- **Celery Tasks**: Asynchronous usage processing and aggregation
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Prometheus Metrics**: Comprehensive usage monitoring and alerting
- **Database Persistence**: PostgreSQL with proper indexing and optimization

### Usage Tracking Capabilities

- **Event Recording**: Capture usage events in real-time
- **Meter Management**: Define and manage usage meters
- **Usage Analytics**: Analyze usage patterns and trends
- **Billing Integration**: Feed usage data to billing systems
- **Historical Data**: Long-term usage data storage and analysis
- **Real-time Monitoring**: Live usage monitoring and alerting

## 🔧 Configuration

### Environment Variables

```bash
# Database Configuration
DATABASE_URL=postgresql://zeroque:zeroque@localhost:5432/zeroque_dev

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# RabbitMQ Configuration
RABBITMQ_URL=amqp://guest:guest@localhost:5672//

# Service Configuration
ENVIRONMENT=development
SERVICE_PORT=8200
```

### Celery Configuration

The service uses Celery for asynchronous usage processing:

```python
# celeryconfig.py
broker_url = "amqp://guest:guest@localhost:5672//"
result_backend = "redis://localhost:6379/0"
task_routes = {
    'usage.process_usage_event': {'queue': 'usage_events'},
    'usage.aggregate_usage': {'queue': 'usage_aggregation'},
    'usage.sync_billing': {'queue': 'usage_billing'},
}
```

## 📊 Database Schema

### UsageEvent Table

```sql
CREATE TABLE usage_events_new (
    event_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255),
    meter_code VARCHAR(100) NOT NULL,
    quantity DECIMAL(10,2) NOT NULL,
    metadata_json JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Meter Table

```sql
CREATE TABLE meters_new (
    meter_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    meter_code VARCHAR(100) NOT NULL,
    meter_name VARCHAR(255) NOT NULL,
    meter_type VARCHAR(50) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    aggregation_type VARCHAR(50) DEFAULT 'sum',
    billing_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
```

## 🚀 API Endpoints

### Health & Status Endpoints

#### GET /health

**Description**: Service health check endpoint

**Response**:

```json
{
  "status": "ok",
  "service": "usage"
}
```

### Usage Event Endpoints

#### POST /usage/v4/record

**Description**: Record a usage event

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "meter_code": "api_calls",
  "quantity": 1.0,
  "metadata": {
    "endpoint": "/api/users",
    "method": "GET",
    "response_time_ms": 250
  }
}
```

**Response**:

```json
{
  "event_id": "usage_abc123def456",
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "meter_code": "api_calls",
  "quantity": 1.0,
  "recorded": true
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8200/usage/v4/record" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_id": "123e4567-e89b-12d3-a456-426614174001",
    "meter_code": "api_calls",
    "quantity": 1.0,
    "metadata": {
      "endpoint": "/api/users",
      "method": "GET",
      "response_time_ms": 250
    }
  }'
```

#### GET /usage/v4/events

**Description**: List usage events with optional filtering

**Query Parameters**:

- `tenant_id` (string, optional): Filter by tenant ID
- `meter_code` (string, optional): Filter by meter code
- `limit` (integer, optional): Number of events to return (default: 100)

**Response**:

```json
[
  {
    "event_id": "usage_abc123def456",
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_id": "123e4567-e89b-12d3-a456-426614174001",
    "meter_code": "api_calls",
    "quantity": 1.0,
    "recorded_at": "2024-01-15T10:30:00Z"
  },
  {
    "event_id": "usage_def456ghi789",
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_id": "123e4567-e89b-12d3-a456-426614174002",
    "meter_code": "storage_gb",
    "quantity": 5.0,
    "recorded_at": "2024-01-15T10:29:00Z"
  }
]
```

**cURL Examples**:

```bash
# Get all usage events
curl "http://localhost:8200/usage/v4/events"

# Get events for specific tenant
curl "http://localhost:8200/usage/v4/events?tenant_id=123e4567-e89b-12d3-a456-426614174000"

# Get events for specific meter
curl "http://localhost:8200/usage/v4/events?meter_code=api_calls"

# Limit results
curl "http://localhost:8200/usage/v4/events?limit=50"
```

## 🔄 Celery Tasks

### process_usage_event

**Description**: Process and validate usage events

**Parameters**:

- `event_id` (str): ID of the usage event
- `event_data` (dict): Usage event data

**Queue**: `usage_events`

**Example**:

```python
from usage.tasks import process_usage_event

# Queue usage event processing
task = process_usage_event.delay(
    event_id="usage_abc123def456",
    event_data={
        "tenant_id": "tenant_123",
        "meter_code": "api_calls",
        "quantity": 1.0
    }
)
```

### aggregate_usage

**Description**: Aggregate usage data for reporting

**Parameters**:

- `tenant_id` (str): Tenant ID
- `meter_code` (str): Meter code
- `aggregation_period` (str): Aggregation period (hour, day, month)

**Queue**: `usage_aggregation`

### sync_billing

**Description**: Sync usage data with billing system

**Parameters**:

- `tenant_id` (str): Tenant ID
- `billing_period` (str): Billing period
- `usage_data` (dict): Aggregated usage data

**Queue**: `usage_billing`

## 📈 Prometheus Metrics

### Counters

- `usage_events_recorded_total`: Total usage events recorded
  - Labels: `tenant_id`, `meter_code`
- `usage_event_duration_seconds`: Usage event processing duration
  - Labels: `operation`

### Gauges

- `active_meters_total`: Number of active meters
  - Labels: `tenant_id`

## 🔍 Usage Meter Types

### API Calls Meter

**Description**: Track API endpoint usage

**Characteristics**:

- Counts API requests
- Tracks response times
- Monitors endpoint usage patterns

**Example**:

```json
{
  "meter_code": "api_calls",
  "meter_name": "API Calls",
  "meter_type": "counter",
  "unit": "requests",
  "aggregation_type": "sum"
}
```

### Storage Meter

**Description**: Track storage usage

**Characteristics**:

- Measures storage consumption
- Tracks storage growth
- Monitors storage limits

**Example**:

```json
{
  "meter_code": "storage_gb",
  "meter_name": "Storage Usage",
  "meter_type": "gauge",
  "unit": "GB",
  "aggregation_type": "max"
}
```

### Bandwidth Meter

**Description**: Track network bandwidth usage

**Characteristics**:

- Measures data transfer
- Tracks bandwidth consumption
- Monitors network usage

**Example**:

```json
{
  "meter_code": "bandwidth_mb",
  "meter_name": "Bandwidth Usage",
  "meter_type": "counter",
  "unit": "MB",
  "aggregation_type": "sum"
}
```

### User Sessions Meter

**Description**: Track user session usage

**Characteristics**:

- Counts active sessions
- Tracks session duration
- Monitors concurrent users

**Example**:

```json
{
  "meter_code": "user_sessions",
  "meter_name": "User Sessions",
  "meter_type": "gauge",
  "unit": "sessions",
  "aggregation_type": "max"
}
```

## 🔄 Usage Event Processing

### Event Recording Flow

1. **Event Received**: Usage event received via API
2. **Validation**: Event data validated and sanitized
3. **Storage**: Event stored in database
4. **Processing**: Event queued for background processing
5. **Aggregation**: Event aggregated with existing usage data
6. **Billing**: Usage data synced with billing system
7. **Analytics**: Usage data made available for analytics

### Event Validation

```python
def validate_usage_event(event_data):
    """Validate usage event data"""
    required_fields = ['tenant_id', 'meter_code', 'quantity']

    for field in required_fields:
        if field not in event_data:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(event_data['quantity'], (int, float)):
        raise ValueError("Quantity must be a number")

    if event_data['quantity'] < 0:
        raise ValueError("Quantity must be non-negative")

    return True
```

### Event Aggregation

```python
def aggregate_usage_events(tenant_id, meter_code, period):
    """Aggregate usage events for a specific period"""
    with SessionLocal() as db:
        query = """
        SELECT
            DATE_TRUNC(:period, recorded_at) as period_start,
            SUM(quantity) as total_quantity,
            COUNT(*) as event_count
        FROM usage_events_new
        WHERE tenant_id = :tenant_id
        AND meter_code = :meter_code
        AND recorded_at >= :start_date
        GROUP BY DATE_TRUNC(:period, recorded_at)
        ORDER BY period_start
        """

        results = db.execute(text(query), {
            'tenant_id': tenant_id,
            'meter_code': meter_code,
            'period': period,
            'start_date': datetime.now() - timedelta(days=30)
        }).fetchall()

        return [
            {
                'period_start': r[0],
                'total_quantity': float(r[1]),
                'event_count': r[2]
            }
            for r in results
        ]
```

## 🚨 Error Handling

### Common Error Responses

#### 400 Bad Request

```json
{
  "detail": "Invalid request parameters"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "Usage recording failed: Database connection error"
}
```

### Usage-Specific Errors

#### Invalid Meter Code

```json
{
  "detail": "Usage recording failed: Invalid meter code 'unknown_meter'",
  "error_code": "INVALID_METER_CODE",
  "supported_meters": ["api_calls", "storage_gb", "bandwidth_mb"]
}
```

#### Quantity Validation Error

```json
{
  "detail": "Usage recording failed: Quantity must be non-negative",
  "error_code": "INVALID_QUANTITY",
  "provided_quantity": -1.0
}
```

## 🔧 Deployment

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8200

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usage-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: usage-service
  template:
    metadata:
      labels:
        app: usage-service
    spec:
      containers:
        - name: usage
          image: zeroque/usage:4.1.0
          ports:
            - containerPort: 8200
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: db-secret
                  key: url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: redis-secret
                  key: url
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

### Celery Worker Deployment

```bash
# Start Celery worker
celery -A usage.celery_app worker --loglevel=info --queues=usage_events,usage_aggregation,usage_billing

# Start Celery beat scheduler
celery -A usage.celery_app beat --loglevel=info
```

## 📚 Integration Examples

### Service Integration

```python
import httpx

async def record_api_usage(tenant_id, user_id, endpoint, method, response_time):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8200/usage/v4/record",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "meter_code": "api_calls",
                "quantity": 1.0,
                "metadata": {
                    "endpoint": endpoint,
                    "method": method,
                    "response_time_ms": response_time
                }
            }
        )
        return response.json()
```

### Usage Analytics Integration

```python
import httpx

async def get_usage_analytics(tenant_id, meter_code, limit=100):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8200/usage/v4/events",
            params={
                "tenant_id": tenant_id,
                "meter_code": meter_code,
                "limit": limit
            }
        )
        return response.json()
```

### Billing Integration

```python
import httpx

async def sync_usage_with_billing(tenant_id, billing_period):
    async with httpx.AsyncClient() as client:
        # Get usage events for billing period
        response = await client.get(
            "http://localhost:8200/usage/v4/events",
            params={
                "tenant_id": tenant_id,
                "limit": 1000
            }
        )

        usage_events = response.json()

        # Aggregate usage by meter
        aggregated_usage = {}
        for event in usage_events:
            meter_code = event['meter_code']
            if meter_code not in aggregated_usage:
                aggregated_usage[meter_code] = 0
            aggregated_usage[meter_code] += event['quantity']

        # Send to billing service
        billing_response = await client.post(
            "http://localhost:8087/billing/v2/usage",
            json={
                "tenant_id": tenant_id,
                "billing_period": billing_period,
                "usage_data": aggregated_usage
            }
        )

        return billing_response.json()
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use JWT tokens for service-to-service communication
- Implement rate limiting for usage recording endpoints

### Data Privacy

- Sanitize usage metadata to prevent information leakage
- Use structured logging with appropriate log levels
- Implement data retention policies for usage events

### Access Control

- Implement tenant isolation for multi-tenant environments
- Use role-based permissions for usage data access
- Secure usage event storage and transmission

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Usage Dashboard",
    "panels": [
      {
        "title": "Usage Events Volume",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(usage_events_recorded_total[5m])",
            "legendFormat": "{{tenant_id}} - {{meter_code}}"
          }
        ]
      },
      {
        "title": "Active Meters",
        "type": "stat",
        "targets": [
          {
            "expr": "active_meters_total",
            "legendFormat": "{{tenant_id}}"
          }
        ]
      },
      {
        "title": "Usage Event Processing Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, usage_event_duration_seconds_bucket)",
            "legendFormat": "95th percentile - {{operation}}"
          }
        ]
      }
    ]
  }
}
```

## 🧪 Testing

### Unit Tests

```python
import pytest
from fastapi.testclient import TestClient
from usage.main import app

client = TestClient(app)

def test_record_usage():
    response = client.post(
        "/usage/v4/record",
        json={
            "tenant_id": "test-tenant",
            "user_id": "test-user",
            "meter_code": "api_calls",
            "quantity": 1.0,
            "metadata": {
                "endpoint": "/test",
                "method": "GET"
            }
        }
    )
    assert response.status_code == 200
    assert "event_id" in response.json()
    assert response.json()["recorded"] is True

def test_list_usage_events():
    response = client.get("/usage/v4/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_usage_flow():
    async with httpx.AsyncClient() as client:
        # Record usage event
        response = await client.post(
            "http://localhost:8200/usage/v4/record",
            json={
                "tenant_id": "test-tenant",
                "user_id": "test-user",
                "meter_code": "api_calls",
                "quantity": 1.0
            }
        )
        assert response.status_code == 200

        # List usage events
        response = await client.get(
            "http://localhost:8200/usage/v4/events",
            params={"tenant_id": "test-tenant"}
        )
        assert response.status_code == 200
        assert len(response.json()) > 0
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Usage event recording and storage
- Meter management and configuration
- Usage analytics and reporting
- Billing system integration
- Celery task integration for asynchronous processing
- Prometheus metrics integration
- Structured logging with correlation IDs

## 🤝 Contributing

1. Follow the existing code style and patterns
2. Add comprehensive tests for new features
3. Update documentation for API changes
4. Use structured logging for all operations
5. Implement proper error handling and validation

## 📞 Support

For issues and questions:

- Create an issue in the project repository
- Contact the development team
- Check the monitoring dashboard for service status
- Review logs for detailed error information

---

**Last Updated**: January 2024  
**Version**: 4.1.0  
**Status**: Production Ready ✅




