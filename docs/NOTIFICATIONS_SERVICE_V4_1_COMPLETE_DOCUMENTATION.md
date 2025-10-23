# ZeroQue Notifications Service V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Notifications Service V4.1 provides comprehensive multi-channel notification delivery with support for email, SMS, and push notifications. It implements production-ready features including multi-provider support, event-driven architecture, saga patterns, and comprehensive monitoring.

## 📋 Service Information

- **Service Name**: notifications
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8701` (development)
- **Architecture**: Multi-channel notification delivery with provider abstraction
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Multi-Provider Support**: Twilio, SendGrid, internal providers with automatic failover
- **Saga Pattern**: Distributed transaction management for reliable delivery
- **Event-Driven Architecture**: Integration with ZeroQue Rails for event processing
- **Outbox Pattern**: Reliable event publishing with retry mechanisms
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Prometheus Metrics**: Comprehensive monitoring and alerting
- **Circuit Breaker**: Resilience patterns for external provider calls
- **Row-Level Security**: Multi-tenant data isolation

### Notification Channels

- **Email**: HTML/text email delivery via SendGrid or SMTP
- **SMS**: Text message delivery via Twilio or other SMS providers
- **Push**: Mobile and web push notifications
- **Internal**: ZeroQue Rails integration for internal notifications

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
SERVICE_PORT=8701

# Provider Configuration
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
SENDGRID_API_KEY=your_sendgrid_key
```

### Celery Configuration

The service uses Celery for asynchronous notification processing:

```python
# celeryconfig.py
broker_url = "amqp://guest:guest@localhost:5672//"
result_backend = "redis://localhost:6379/0"
task_routes = {
    'notifications.send_notification': {'queue': 'notifications_send'},
    'notifications.process_delivery': {'queue': 'notifications_process'},
    'notifications.retry_failed': {'queue': 'notifications_retry'},
}
```

## 📊 Database Schema

### NotificationDeliveryNew Table

```sql
CREATE TABLE notification_deliveries_new (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID,
    channel VARCHAR(20) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'queued',
    template_id VARCHAR(100),
    payload JSONB NOT NULL,
    error JSONB,
    next_attempt_at TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
```

### ZeroqueRail Table

```sql
CREATE TABLE zeroque_rails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    type VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    config JSONB NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
```

### OutboxEvent Table

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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
  "service": "notifications",
  "version": "4.1.0",
  "environment": "development"
}
```

#### GET /readiness

**Description**: Service readiness check endpoint

**Response**:

```json
{
  "service": "notifications",
  "status": "ready",
  "database": "connected"
}
```

#### GET /metrics

**Description**: Prometheus metrics endpoint

**Response**: Prometheus-formatted metrics

### Notification Management Endpoints

#### POST /notifications/v4/send

**Description**: Send notification via configured provider

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "channel": "email",
  "provider": "sendgrid",
  "template_id": "welcome_email",
  "data": {
    "user_name": "John Doe",
    "company": "Acme Corp"
  },
  "to": "user@example.com",
  "subject": "Welcome to ZeroQue",
  "body": "Welcome to our platform!",
  "priority": "normal",
  "delay_until": "2024-01-15T10:00:00Z"
}
```

**Response**:

```json
{
  "delivery_id": "123e4567-e89b-12d3-a456-426614174002",
  "status": "queued",
  "provider": "sendgrid",
  "channel": "email",
  "created_at": "2024-01-15T09:30:00Z"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8701/notifications/v4/send" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-token" \
  -d '{
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_id": "123e4567-e89b-12d3-a456-426614174001",
    "channel": "email",
    "provider": "sendgrid",
    "template_id": "welcome_email",
    "data": {
      "user_name": "John Doe",
      "company": "Acme Corp"
    },
    "to": "user@example.com",
    "subject": "Welcome to ZeroQue",
    "body": "Welcome to our platform!",
    "priority": "normal"
  }'
```

#### POST /notifications/v4/replay

**Description**: Replay failed notification

**Request Body**:

```json
{
  "delivery_id": "123e4567-e89b-12d3-a456-426614174002",
  "force": false
}
```

**Response**:

```json
{
  "delivery_id": "123e4567-e89b-12d3-a456-426614174002",
  "status": "requeued",
  "retry_count": 1
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8701/notifications/v4/replay" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-token" \
  -d '{
    "delivery_id": "123e4567-e89b-12d3-a456-426614174002",
    "force": false
  }'
```

#### GET /notifications/v4/history

**Description**: Get notification delivery history

**Query Parameters**:

- `tenant_id` (string, required): Tenant ID
- `user_id` (string, optional): User ID filter
- `channel` (string, optional): Channel filter (email, sms, push)
- `status` (string, optional): Status filter (queued, sent, failed)
- `page` (integer, optional): Page number (default: 1)
- `limit` (integer, optional): Items per page (default: 20)

**Response**:

```json
{
  "deliveries": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174002",
      "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
      "user_id": "123e4567-e89b-12d3-a456-426614174001",
      "channel": "email",
      "provider": "sendgrid",
      "status": "sent",
      "template_id": "welcome_email",
      "to": "user@example.com",
      "subject": "Welcome to ZeroQue",
      "retry_count": 0,
      "created_at": "2024-01-15T09:30:00Z",
      "updated_at": "2024-01-15T09:30:05Z"
    }
  ],
  "count": 1,
  "page": 1,
  "limit": 20
}
```

**cURL Example**:

```bash
curl "http://localhost:8701/notifications/v4/history?tenant_id=123e4567-e89b-12d3-a456-426614174000&page=1&limit=20" \
  -H "Authorization: Bearer your-jwt-token"
```

### Provider Management Endpoints

#### POST /admin/rails/notification

**Description**: Configure notification provider

**Request Body**:

```json
{
  "type": "notification",
  "name": "sendgrid",
  "config": {
    "api_key": "your_sendgrid_api_key",
    "from_email": "noreply@zeroque.com",
    "from_name": "ZeroQue Team"
  },
  "active": true
}
```

**Response**:

```json
{
  "rail_id": "123e4567-e89b-12d3-a456-426614174003",
  "status": "configured",
  "provider": "sendgrid"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8701/admin/rails/notification" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-token" \
  -d '{
    "type": "notification",
    "name": "sendgrid",
    "config": {
      "api_key": "your_sendgrid_api_key",
      "from_email": "noreply@zeroque.com",
      "from_name": "ZeroQue Team"
    },
    "active": true
  }'
```

### Integration Endpoints

#### POST /notifications/v4/integration/entry-granted

**Description**: Handle entry granted event

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "entry_id": "123e4567-e89b-12d3-a456-426614174004",
  "site_id": "123e4567-e89b-12d3-a456-426614174005",
  "store_id": "123e4567-e89b-12d3-a456-426614174006"
}
```

#### POST /notifications/v4/integration/user-created

**Description**: Handle user created event

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "user_email": "user@example.com",
  "user_name": "John Doe"
}
```

#### POST /notifications/v4/integration/order-completed

**Description**: Handle order completed event

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "order_id": "123e4567-e89b-12d3-a456-426614174007",
  "order_total": 150.0,
  "items": [
    {
      "name": "Product A",
      "quantity": 2,
      "price": 75.0
    }
  ]
}
```

#### POST /notifications/v4/integration/invoice-posted

**Description**: Handle invoice posted event

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "invoice_id": "123e4567-e89b-12d3-a456-426614174008",
  "amount": 150.0,
  "due_date": "2024-02-15T00:00:00Z"
}
```

### Replay Endpoints

#### POST /notifications/replay/{delivery_id}

**Description**: Replay specific notification delivery

**Path Parameters**:

- `delivery_id` (string, required): Delivery ID to replay

**Response**:

```json
{
  "delivery_id": "123e4567-e89b-12d3-a456-426614174002",
  "status": "requeued",
  "retry_count": 1
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8701/notifications/replay/123e4567-e89b-12d3-a456-426614174002" \
  -H "Authorization: Bearer your-jwt-token"
```

## 🔄 Celery Tasks

### send_notification

**Description**: Asynchronous notification sending task

**Parameters**:

- `delivery_id` (str): ID of the notification delivery
- `provider` (str): Provider to use for sending
- `payload` (dict): Notification payload

**Queue**: `notifications_send`

### process_delivery

**Description**: Process notification delivery status

**Parameters**:

- `delivery_id` (str): ID of the notification delivery
- `status` (str): Delivery status
- `error` (dict, optional): Error details if failed

**Queue**: `notifications_process`

### retry_failed

**Description**: Retry failed notification deliveries

**Parameters**:

- `delivery_id` (str): ID of the failed delivery
- `max_retries` (int): Maximum number of retries

**Queue**: `notifications_retry`

## 📈 Prometheus Metrics

### Counters

- `notification_send_total`: Total notifications sent
  - Labels: `channel`, `provider`, `status`
- `notification_failures_total`: Total notification failures
  - Labels: `channel`, `provider`, `error_type`

### Histograms

- `notification_send_duration_seconds`: Notification send duration
  - Labels: `channel`, `provider`

### Gauges

- `notification_queue_size`: Current notification queue size
  - Labels: `channel`, `provider`

## 🔍 Notification Channels

### Email Notifications

**Supported Providers**:

- SendGrid
- SMTP
- Internal email service

**Template Support**:

- HTML templates with variable substitution
- Text fallback for HTML emails
- Attachment support

**Example**:

```json
{
  "channel": "email",
  "provider": "sendgrid",
  "template_id": "welcome_email",
  "data": {
    "user_name": "John Doe",
    "company": "Acme Corp",
    "login_url": "https://app.zeroque.com/login"
  },
  "to": "user@example.com",
  "subject": "Welcome to ZeroQue"
}
```

### SMS Notifications

**Supported Providers**:

- Twilio
- Internal SMS service

**Features**:

- Character limit handling
- Delivery status tracking
- International number support

**Example**:

```json
{
  "channel": "sms",
  "provider": "twilio",
  "data": {
    "verification_code": "123456",
    "expires_in": "10 minutes"
  },
  "to": "+1234567890",
  "body": "Your ZeroQue verification code is 123456. Valid for 10 minutes."
}
```

### Push Notifications

**Supported Providers**:

- Firebase Cloud Messaging (FCM)
- Apple Push Notification Service (APNS)
- Web Push

**Features**:

- Rich media support
- Action buttons
- Deep linking
- Badge management

**Example**:

```json
{
  "channel": "push",
  "provider": "fcm",
  "data": {
    "title": "New Order",
    "body": "Your order #12345 has been confirmed",
    "action_url": "https://app.zeroque.com/orders/12345",
    "image_url": "https://cdn.zeroque.com/order-confirmation.png"
  },
  "to": "device_token_here"
}
```

## 🔄 Saga Patterns

### SendNotificationSaga

**Description**: Manages the complete notification sending process

**Steps**:

1. Validate request and permissions
2. Select appropriate provider
3. Create delivery record
4. Send notification via provider
5. Update delivery status
6. Publish delivery event
7. Handle failures with compensation

**Compensation Logic**:

- Mark delivery as failed
- Increment retry count
- Schedule retry if under limit
- Publish failure event

### ReplaySaga

**Description**: Manages notification replay process

**Steps**:

1. Validate delivery exists
2. Check retry limits
3. Reset delivery status
4. Requeue for processing
5. Update retry count

## 🚨 Error Handling

### Common Error Responses

#### 400 Bad Request

```json
{
  "detail": "Invalid request parameters"
}
```

#### 403 Forbidden

```json
{
  "detail": "Insufficient permissions"
}
```

#### 404 Not Found

```json
{
  "detail": "Delivery not found"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "Notification send failed: Provider unavailable"
}
```

### Provider-Specific Errors

#### SendGrid Errors

```json
{
  "detail": "SendGrid error: Invalid API key",
  "provider": "sendgrid",
  "error_code": "401"
}
```

#### Twilio Errors

```json
{
  "detail": "Twilio error: Invalid phone number",
  "provider": "twilio",
  "error_code": "21211"
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
EXPOSE 8701

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: notifications-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: notifications-service
  template:
    metadata:
      labels:
        app: notifications-service
    spec:
      containers:
        - name: notifications
          image: zeroque/notifications:4.1.0
          ports:
            - containerPort: 8701
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: db-secret
                  key: url
            - name: TWILIO_ACCOUNT_SID
              valueFrom:
                secretKeyRef:
                  name: twilio-secret
                  key: account_sid
            - name: SENDGRID_API_KEY
              valueFrom:
                secretKeyRef:
                  name: sendgrid-secret
                  key: api_key
```

### Celery Worker Deployment

```bash
# Start Celery worker
celery -A notifications.celery_app worker --loglevel=info --queues=notifications_send,notifications_process,notifications_retry

# Start Celery beat scheduler
celery -A notifications.celery_app beat --loglevel=info
```

## 📚 Integration Examples

### Service Integration

```python
import httpx

async def send_welcome_email(user_id, email, name):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8701/notifications/v4/send",
            json={
                "tenant_id": "your-tenant-id",
                "user_id": user_id,
                "channel": "email",
                "provider": "sendgrid",
                "template_id": "welcome_email",
                "data": {
                    "user_name": name,
                    "login_url": "https://app.zeroque.com/login"
                },
                "to": email,
                "subject": "Welcome to ZeroQue"
            },
            headers={"Authorization": "Bearer your-jwt-token"}
        )
        return response.json()
```

### Event-Driven Integration

```python
import httpx

async def handle_user_created_event(event):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8701/notifications/v4/integration/user-created",
            json={
                "tenant_id": event["tenant_id"],
                "user_id": event["user_id"],
                "user_email": event["email"],
                "user_name": event["name"]
            },
            headers={"Authorization": "Bearer your-jwt-token"}
        )
        return response.json()
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use JWT tokens for service-to-service communication
- Implement API key authentication for external integrations

### Data Privacy

- Sanitize notification content to prevent injection attacks
- Use structured logging with appropriate log levels
- Implement data retention policies for delivery history

### Provider Security

- Store provider credentials in secure secret management
- Use environment variables for sensitive configuration
- Implement provider-specific security best practices

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Notifications Dashboard",
    "panels": [
      {
        "title": "Notification Volume",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(notification_send_total[5m])",
            "legendFormat": "{{channel}} - {{provider}}"
          }
        ]
      },
      {
        "title": "Delivery Success Rate",
        "type": "stat",
        "targets": [
          {
            "expr": "rate(notification_send_total{status=\"success\"}[5m]) / rate(notification_send_total[5m]) * 100",
            "legendFormat": "Success Rate %"
          }
        ]
      },
      {
        "title": "Failed Deliveries",
        "type": "table",
        "targets": [
          {
            "expr": "notification_failures_total",
            "legendFormat": "{{channel}} - {{provider}} - {{error_type}}"
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
from notifications.main import app

client = TestClient(app)

def test_send_notification():
    response = client.post(
        "/notifications/v4/send",
        json={
            "tenant_id": "test-tenant",
            "channel": "email",
            "to": "test@example.com",
            "subject": "Test",
            "body": "Test message"
        },
        headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    assert "delivery_id" in response.json()
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_notification_flow():
    async with httpx.AsyncClient() as client:
        # Send notification
        response = await client.post(
            "http://localhost:8701/notifications/v4/send",
            json={
                "tenant_id": "test-tenant",
                "channel": "email",
                "to": "test@example.com",
                "subject": "Test",
                "body": "Test message"
            },
            headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        # Check delivery status
        delivery_id = response.json()["delivery_id"]
        response = await client.get(
            f"http://localhost:8701/notifications/v4/history?delivery_id={delivery_id}",
            headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Multi-provider support (SendGrid, Twilio, internal)
- Saga pattern implementation for reliable delivery
- Event-driven architecture with ZeroQue Rails
- Comprehensive monitoring and alerting
- Structured logging with correlation IDs
- Circuit breaker patterns for resilience

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




