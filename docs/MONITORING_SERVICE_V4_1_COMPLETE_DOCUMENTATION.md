# ZeroQue Monitoring Service V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Monitoring Service V4.1 provides comprehensive health monitoring, alerting, and observability for all microservices in the ZeroQue ecosystem. It implements production-ready monitoring with Celery task queues, RabbitMQ integration, Prometheus metrics, and structured logging.

## 📋 Service Information

- **Service Name**: monitoring
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8700` (development)
- **Architecture**: Microservice health monitoring with alerting
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Celery Integration**: Asynchronous health checks and alert processing
- **RabbitMQ Messaging**: Event-driven communication with other services
- **Prometheus Metrics**: Comprehensive monitoring metrics and dashboards
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Circuit Breaker**: Resilience patterns for external service calls
- **Redis Caching**: Fast access to health status and alert data
- **Database Persistence**: PostgreSQL with proper indexing and RLS

### Monitoring Capabilities

- **Service Health Checks**: Automated health monitoring for all services
- **Alert Management**: Configurable alerts with severity levels
- **Response Time Tracking**: Performance monitoring and SLA tracking
- **Service Discovery**: Automatic detection and monitoring of new services
- **Historical Data**: Long-term health trend analysis
- **Real-time Status**: Live service status updates

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
SERVICE_PORT=8700
```

### Celery Configuration

The service uses Celery for asynchronous health checks and alert processing:

```python
# celeryconfig.py
broker_url = "amqp://guest:guest@localhost:5672//"
result_backend = "redis://localhost:6379/0"
task_routes = {
    'monitoring.check_service_health': {'queue': 'monitoring_health'},
    'monitoring.process_alert': {'queue': 'monitoring_alerts'},
}
```

## 📊 Database Schema

### ServiceHealth Table

```sql
CREATE TABLE service_health_new (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    response_time_ms INTEGER,
    last_check TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Alert Table

```sql
CREATE TABLE alerts_new (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
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
  "service": "monitoring",
  "version": "4.1.0",
  "environment": "development"
}
```

#### GET /readiness

**Description**: Service readiness check endpoint

**Response**:

```json
{
  "service": "monitoring",
  "status": "ready",
  "database": "connected"
}
```

#### GET /metrics

**Description**: Prometheus metrics endpoint

**Response**: Prometheus-formatted metrics

**Example**:

```
# HELP monitoring_checks_total Total monitoring checks
# TYPE monitoring_checks_total counter
monitoring_checks_total{service="provisioning",status="success"} 150
monitoring_checks_total{service="orders",status="failure"} 3

# HELP monitoring_check_duration_seconds Monitoring check duration
# TYPE monitoring_check_duration_seconds histogram
monitoring_check_duration_seconds_bucket{service="provisioning",le="0.1"} 120
monitoring_check_duration_seconds_bucket{service="provisioning",le="0.5"} 140
monitoring_check_duration_seconds_bucket{service="provisioning",le="1.0"} 150
```

### Monitoring Endpoints

#### POST /monitoring/v4/check-health

**Description**: Initiate health check for a service

**Request Body**:

```json
{
  "service_name": "provisioning",
  "endpoint": "/health",
  "timeout_seconds": 30,
  "expected_status": 200
}
```

**Response**:

```json
{
  "task_id": "abc123-def456-ghi789",
  "service_name": "provisioning",
  "status": "initiated"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8700/monitoring/v4/check-health" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "provisioning",
    "endpoint": "/health",
    "timeout_seconds": 30,
    "expected_status": 200
  }'
```

#### GET /monitoring/v4/services/{service_name}/status

**Description**: Get current status of a specific service

**Path Parameters**:

- `service_name` (string, required): Name of the service to check

**Response**:

```json
{
  "service_name": "provisioning",
  "status": "healthy",
  "response_time_ms": 45,
  "last_check": "2024-01-15T10:30:00Z",
  "error_message": null
}
```

**cURL Example**:

```bash
curl "http://localhost:8700/monitoring/v4/services/provisioning/status"
```

#### GET /monitoring/v4/services

**Description**: List all monitored services

**Response**:

```json
[
  {
    "service_name": "provisioning",
    "last_status": "healthy",
    "last_check": "2024-01-15T10:30:00Z"
  },
  {
    "service_name": "orders",
    "last_status": "unhealthy",
    "last_check": "2024-01-15T10:25:00Z"
  }
]
```

**cURL Example**:

```bash
curl "http://localhost:8700/monitoring/v4/services"
```

### Alert Management Endpoints

#### POST /monitoring/v4/alerts

**Description**: Create a new alert

**Request Body**:

```json
{
  "service_name": "provisioning",
  "alert_type": "health_check_failed",
  "severity": "critical",
  "message": "Service is not responding to health checks",
  "metadata": {
    "endpoint": "/health",
    "timeout": 30,
    "retry_count": 3
  }
}
```

**Response**:

```json
{
  "alert_id": 123,
  "status": "created"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8700/monitoring/v4/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "provisioning",
    "alert_type": "health_check_failed",
    "severity": "critical",
    "message": "Service is not responding to health checks",
    "metadata": {
      "endpoint": "/health",
      "timeout": 30,
      "retry_count": 3
    }
  }'
```

#### GET /monitoring/v4/alerts

**Description**: List alerts with optional filtering

**Query Parameters**:

- `service_name` (string, optional): Filter by service name
- `severity` (string, optional): Filter by severity level
- `status` (string, optional): Filter by alert status (default: "active")

**Response**:

```json
[
  {
    "id": 123,
    "service_name": "provisioning",
    "alert_type": "health_check_failed",
    "severity": "critical",
    "message": "Service is not responding to health checks",
    "status": "active",
    "created_at": "2024-01-15T10:30:00Z",
    "metadata": {
      "endpoint": "/health",
      "timeout": 30,
      "retry_count": 3
    }
  }
]
```

**cURL Examples**:

```bash
# Get all active alerts
curl "http://localhost:8700/monitoring/v4/alerts"

# Get alerts for specific service
curl "http://localhost:8700/monitoring/v4/alerts?service_name=provisioning"

# Get critical alerts only
curl "http://localhost:8700/monitoring/v4/alerts?severity=critical"

# Get resolved alerts
curl "http://localhost:8700/monitoring/v4/alerts?status=resolved"
```

## 🔄 Celery Tasks

### check_service_health

**Description**: Asynchronous health check task

**Parameters**:

- `service_name` (str): Name of the service to check
- `endpoint` (str): Health check endpoint
- `timeout_seconds` (int): Request timeout

**Queue**: `monitoring_health`

**Example**:

```python
from monitoring.tasks import check_service_health

# Queue health check
task = check_service_health.delay(
    service_name="provisioning",
    endpoint="/health",
    timeout_seconds=30
)
```

### process_alert

**Description**: Process and route alerts

**Parameters**:

- `alert_id` (int): ID of the alert to process
- `action` (str): Action to take (notify, escalate, etc.)

**Queue**: `monitoring_alerts`

## 📈 Prometheus Metrics

### Counters

- `monitoring_checks_total`: Total number of health checks performed
  - Labels: `service`, `status`

### Histograms

- `monitoring_check_duration_seconds`: Duration of health checks
  - Labels: `service`

### Gauges

- `service_health_status`: Current health status of services
  - Labels: `service`
- `active_alerts_total`: Number of active alerts
  - Labels: `severity`

## 🔍 Monitoring Best Practices

### Health Check Configuration

1. **Regular Intervals**: Set appropriate check intervals (30-60 seconds)
2. **Timeout Settings**: Use reasonable timeouts (10-30 seconds)
3. **Endpoint Selection**: Use lightweight health endpoints
4. **Retry Logic**: Implement retry mechanisms for transient failures

### Alert Management

1. **Severity Levels**: Use consistent severity levels (critical, warning, info)
2. **Alert Grouping**: Group related alerts to prevent spam
3. **Escalation**: Implement alert escalation for critical issues
4. **Resolution**: Track alert resolution and root cause analysis

### Performance Monitoring

1. **Response Time Tracking**: Monitor response times for SLA compliance
2. **Error Rate Monitoring**: Track error rates and failure patterns
3. **Resource Usage**: Monitor CPU, memory, and disk usage
4. **Dependency Health**: Monitor external service dependencies

## 🚨 Error Handling

### Common Error Responses

#### 400 Bad Request

```json
{
  "detail": "Invalid request parameters"
}
```

#### 404 Not Found

```json
{
  "detail": "Service not found"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "Internal server error"
}
```

#### 503 Service Unavailable

```json
{
  "detail": "Service not ready: Database connection failed"
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
EXPOSE 8700

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: monitoring-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: monitoring-service
  template:
    metadata:
      labels:
        app: monitoring-service
    spec:
      containers:
        - name: monitoring
          image: zeroque/monitoring:4.1.0
          ports:
            - containerPort: 8700
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
```

### Celery Worker Deployment

```bash
# Start Celery worker
celery -A monitoring.celery_app worker --loglevel=info --queues=monitoring_health,monitoring_alerts

# Start Celery beat scheduler
celery -A monitoring.celery_app beat --loglevel=info
```

## 📚 Integration Examples

### Service Registration

```python
import httpx

async def register_service():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8700/monitoring/v4/check-health",
            json={
                "service_name": "my-service",
                "endpoint": "/health",
                "timeout_seconds": 30
            }
        )
        return response.json()
```

### Alert Integration

```python
import httpx

async def send_alert(service_name, message, severity="warning"):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8700/monitoring/v4/alerts",
            json={
                "service_name": service_name,
                "alert_type": "custom",
                "severity": severity,
                "message": message
            }
        )
        return response.json()
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use API keys or JWT tokens for service-to-service communication
- Implement rate limiting for health check endpoints

### Data Privacy

- Sanitize error messages to prevent information leakage
- Use structured logging with appropriate log levels
- Implement data retention policies for health check data

### Network Security

- Use HTTPS in production environments
- Implement proper firewall rules
- Use VPN or private networks for internal communication

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Monitoring Dashboard",
    "panels": [
      {
        "title": "Service Health Status",
        "type": "stat",
        "targets": [
          {
            "expr": "service_health_status",
            "legendFormat": "{{service}}"
          }
        ]
      },
      {
        "title": "Health Check Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, monitoring_check_duration_seconds_bucket)",
            "legendFormat": "95th percentile"
          }
        ]
      },
      {
        "title": "Active Alerts",
        "type": "table",
        "targets": [
          {
            "expr": "active_alerts_total",
            "legendFormat": "{{severity}}"
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
from monitoring.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_service_status():
    response = client.get("/monitoring/v4/services/provisioning/status")
    assert response.status_code in [200, 404]
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_health_check_flow():
    async with httpx.AsyncClient() as client:
        # Initiate health check
        response = await client.post(
            "http://localhost:8700/monitoring/v4/check-health",
            json={
                "service_name": "test-service",
                "endpoint": "/health",
                "timeout_seconds": 30
            }
        )
        assert response.status_code == 200

        # Check status
        response = await client.get(
            "http://localhost:8700/monitoring/v4/services/test-service/status"
        )
        assert response.status_code in [200, 404]
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Celery integration for asynchronous health checks
- Prometheus metrics integration
- Comprehensive alert management
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




