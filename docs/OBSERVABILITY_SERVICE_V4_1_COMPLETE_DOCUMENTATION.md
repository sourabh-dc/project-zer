# ZeroQue Observability Service V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Observability Service V4.1 provides comprehensive system observability, metrics collection, and monitoring capabilities for the entire ZeroQue ecosystem. It implements production-ready features including custom metrics, system monitoring, alerting, and comprehensive dashboards.

## 📋 Service Information

- **Service Name**: observability
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8702` (development)
- **Architecture**: System observability and metrics collection
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Custom Metrics**: Record and track custom business metrics
- **System Monitoring**: Real-time system resource monitoring
- **Prometheus Integration**: Native Prometheus metrics support
- **Celery Tasks**: Asynchronous metrics collection and processing
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Circuit Breaker**: Resilience patterns for external service calls
- **Redis Caching**: Fast access to metrics and monitoring data
- **Database Persistence**: PostgreSQL with proper indexing

### Observability Capabilities

- **Custom Metrics**: Record business and application metrics
- **System Metrics**: CPU, memory, disk, and network monitoring
- **Monitor Management**: Create and manage custom monitors
- **Real-time Data**: Live system metrics and status
- **Historical Data**: Long-term metrics storage and analysis
- **Alerting**: Configurable alerts based on metrics thresholds

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
SERVICE_PORT=8702
```

### Celery Configuration

The service uses Celery for asynchronous metrics collection:

```python
# celeryconfig.py
broker_url = "amqp://guest:guest@localhost:5672//"
result_backend = "redis://localhost:6379/0"
task_routes = {
    'observability.collect_system_metrics': {'queue': 'observability_system'},
    'observability.process_metrics': {'queue': 'observability_metrics'},
    'observability.check_monitors': {'queue': 'observability_monitors'},
}
```

## 📊 Database Schema

### Metric Table

```sql
CREATE TABLE metrics_new (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(255) NOT NULL,
    metric_type VARCHAR(50) NOT NULL,
    value NUMERIC NOT NULL,
    labels JSONB,
    tenant_id VARCHAR(255),
    service_name VARCHAR(100),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Monitor Table

```sql
CREATE TABLE monitors_new (
    id SERIAL PRIMARY KEY,
    monitor_name VARCHAR(255) NOT NULL,
    monitor_type VARCHAR(50) NOT NULL,
    target_service VARCHAR(100) NOT NULL,
    target_endpoint VARCHAR(255) NOT NULL,
    check_interval_seconds INTEGER DEFAULT 60,
    timeout_seconds INTEGER DEFAULT 30,
    threshold_value NUMERIC,
    is_active BOOLEAN DEFAULT TRUE,
    last_check TIMESTAMP WITH TIME ZONE,
    last_status VARCHAR(20),
    metadata JSONB,
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
  "service": "observability",
  "version": "4.1.0",
  "environment": "development"
}
```

#### GET /readiness

**Description**: Service readiness check endpoint

**Response**:

```json
{
  "service": "observability",
  "status": "ready",
  "database": "connected"
}
```

#### GET /metrics

**Description**: Prometheus metrics endpoint

**Response**: Prometheus-formatted metrics

**Example**:

```
# HELP observability_requests_total Total observability requests
# TYPE observability_requests_total counter
observability_requests_total{endpoint="record_metric",status="success"} 150
observability_requests_total{endpoint="get_metrics",status="success"} 200

# HELP observability_request_duration_seconds Observability request duration
# TYPE observability_request_duration_seconds histogram
observability_request_duration_seconds_bucket{endpoint="record_metric",le="0.1"} 120
observability_request_duration_seconds_bucket{endpoint="record_metric",le="0.5"} 140
observability_request_duration_seconds_bucket{endpoint="record_metric",le="1.0"} 150
```

### Metrics Management Endpoints

#### POST /observability/v4/metrics

**Description**: Record a custom metric

**Request Body**:

```json
{
  "metric_name": "user_registrations",
  "metric_type": "counter",
  "value": 1,
  "labels": {
    "tenant": "acme-corp",
    "source": "web"
  },
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "service_name": "identity"
}
```

**Response**:

```json
{
  "metric_id": 123,
  "status": "recorded"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8702/observability/v4/metrics" \
  -H "Content-Type: application/json" \
  -d '{
    "metric_name": "user_registrations",
    "metric_type": "counter",
    "value": 1,
    "labels": {
      "tenant": "acme-corp",
      "source": "web"
    },
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "service_name": "identity"
  }'
```

#### GET /observability/v4/metrics

**Description**: Get metrics with optional filtering

**Query Parameters**:

- `metric_name` (string, optional): Filter by metric name
- `service_name` (string, optional): Filter by service name
- `limit` (integer, optional): Number of metrics to return (default: 100)

**Response**:

```json
[
  {
    "id": 123,
    "metric_name": "user_registrations",
    "metric_type": "counter",
    "value": 1,
    "labels": {
      "tenant": "acme-corp",
      "source": "web"
    },
    "timestamp": "2024-01-15T10:30:00Z",
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "service_name": "identity"
  }
]
```

**cURL Examples**:

```bash
# Get all metrics
curl "http://localhost:8702/observability/v4/metrics"

# Get metrics for specific service
curl "http://localhost:8702/observability/v4/metrics?service_name=identity"

# Get specific metric
curl "http://localhost:8702/observability/v4/metrics?metric_name=user_registrations"

# Limit results
curl "http://localhost:8702/observability/v4/metrics?limit=50"
```

### Monitor Management Endpoints

#### POST /observability/v4/monitors

**Description**: Create a new monitor

**Request Body**:

```json
{
  "monitor_name": "API Response Time",
  "monitor_type": "health_check",
  "target_service": "provisioning",
  "target_endpoint": "/health",
  "check_interval_seconds": 60,
  "timeout_seconds": 30,
  "threshold_value": 1000,
  "metadata": {
    "alert_threshold": 2000,
    "notification_channels": ["email", "slack"]
  }
}
```

**Response**:

```json
{
  "monitor_id": 456,
  "status": "created"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8702/observability/v4/monitors" \
  -H "Content-Type: application/json" \
  -d '{
    "monitor_name": "API Response Time",
    "monitor_type": "health_check",
    "target_service": "provisioning",
    "target_endpoint": "/health",
    "check_interval_seconds": 60,
    "timeout_seconds": 30,
    "threshold_value": 1000,
    "metadata": {
      "alert_threshold": 2000,
      "notification_channels": ["email", "slack"]
    }
  }'
```

#### GET /observability/v4/monitors

**Description**: List all monitors

**Response**:

```json
[
  {
    "id": 456,
    "monitor_name": "API Response Time",
    "monitor_type": "health_check",
    "target_service": "provisioning",
    "target_endpoint": "/health",
    "is_active": true,
    "last_check": "2024-01-15T10:30:00Z",
    "last_status": "healthy",
    "created_at": "2024-01-15T09:00:00Z"
  }
]
```

**cURL Example**:

```bash
curl "http://localhost:8702/observability/v4/monitors"
```

### System Metrics Endpoints

#### POST /observability/v4/collect-system-metrics

**Description**: Trigger system metrics collection

**Response**:

```json
{
  "task_id": "abc123-def456-ghi789",
  "status": "initiated"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8702/observability/v4/collect-system-metrics"
```

#### GET /observability/v4/system-metrics

**Description**: Get current system metrics

**Response**:

```json
{
  "cpu_usage_percent": 45.2,
  "memory_usage_percent": 67.8,
  "disk_usage_percent": 23.4,
  "network_bytes_sent": 1024000,
  "network_bytes_received": 2048000,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**cURL Example**:

```bash
curl "http://localhost:8702/observability/v4/system-metrics"
```

## 🔄 Celery Tasks

### collect_system_metrics

**Description**: Asynchronous system metrics collection task

**Parameters**: None

**Queue**: `observability_system`

**Example**:

```python
from observability.tasks import collect_system_metrics

# Queue system metrics collection
task = collect_system_metrics.delay()
```

### process_metrics

**Description**: Process and aggregate metrics

**Parameters**:

- `metric_data` (dict): Metric data to process
- `aggregation_type` (str): Type of aggregation (sum, avg, max, min)

**Queue**: `observability_metrics`

### check_monitors

**Description**: Check monitor status and trigger alerts

**Parameters**:

- `monitor_id` (int): ID of the monitor to check
- `threshold_value` (float): Threshold value for alerting

**Queue**: `observability_monitors`

## 📈 Prometheus Metrics

### Counters

- `observability_requests_total`: Total observability requests
  - Labels: `endpoint`, `status`
- `system_metrics_collected_total`: Total system metrics collected
  - Labels: `metric_type`

### Histograms

- `observability_request_duration_seconds`: Observability request duration
  - Labels: `endpoint`

### Gauges

- `active_monitors_total`: Number of active monitors
  - Labels: `monitor_type`

## 🔍 Metric Types

### Counter Metrics

**Description**: Incrementing counters for counting events

**Use Cases**:

- User registrations
- API requests
- Error counts
- Business events

**Example**:

```json
{
  "metric_name": "api_requests_total",
  "metric_type": "counter",
  "value": 1,
  "labels": {
    "endpoint": "/users",
    "method": "POST",
    "status": "200"
  }
}
```

### Gauge Metrics

**Description**: Values that can go up and down

**Use Cases**:

- Current active users
- Queue sizes
- Resource utilization
- Temperature readings

**Example**:

```json
{
  "metric_name": "active_users",
  "metric_type": "gauge",
  "value": 150,
  "labels": {
    "tenant": "acme-corp"
  }
}
```

### Histogram Metrics

**Description**: Distributions of values

**Use Cases**:

- Response times
- Request sizes
- Processing durations
- Latency measurements

**Example**:

```json
{
  "metric_name": "request_duration_seconds",
  "metric_type": "histogram",
  "value": 0.245,
  "labels": {
    "endpoint": "/api/users",
    "method": "GET"
  }
}
```

## 🔄 Monitor Types

### Health Check Monitors

**Description**: Monitor service health endpoints

**Configuration**:

- Target service and endpoint
- Check interval
- Timeout settings
- Expected response codes

**Example**:

```json
{
  "monitor_name": "Service Health",
  "monitor_type": "health_check",
  "target_service": "provisioning",
  "target_endpoint": "/health",
  "check_interval_seconds": 60,
  "timeout_seconds": 30
}
```

### Performance Monitors

**Description**: Monitor performance metrics

**Configuration**:

- Performance thresholds
- Alert conditions
- Notification channels

**Example**:

```json
{
  "monitor_name": "Response Time",
  "monitor_type": "performance",
  "target_service": "api",
  "target_endpoint": "/metrics",
  "threshold_value": 1000,
  "metadata": {
    "alert_threshold": 2000,
    "warning_threshold": 1500
  }
}
```

### Resource Monitors

**Description**: Monitor system resources

**Configuration**:

- CPU usage thresholds
- Memory usage thresholds
- Disk usage thresholds

**Example**:

```json
{
  "monitor_name": "CPU Usage",
  "monitor_type": "resource",
  "target_service": "system",
  "target_endpoint": "/system-metrics",
  "threshold_value": 80,
  "metadata": {
    "alert_threshold": 90,
    "warning_threshold": 75
  }
}
```

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
  "detail": "Monitor not found"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "Failed to record metric"
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
EXPOSE 8702

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: observability-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: observability-service
  template:
    metadata:
      labels:
        app: observability-service
    spec:
      containers:
        - name: observability
          image: zeroque/observability:4.1.0
          ports:
            - containerPort: 8702
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
celery -A observability.celery_app worker --loglevel=info --queues=observability_system,observability_metrics,observability_monitors

# Start Celery beat scheduler
celery -A observability.celery_app beat --loglevel=info
```

## 📚 Integration Examples

### Service Integration

```python
import httpx

async def record_business_metric(metric_name, value, labels=None):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8702/observability/v4/metrics",
            json={
                "metric_name": metric_name,
                "metric_type": "counter",
                "value": value,
                "labels": labels or {},
                "service_name": "my-service"
            }
        )
        return response.json()
```

### Monitor Integration

```python
import httpx

async def create_service_monitor(service_name, endpoint):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8702/observability/v4/monitors",
            json={
                "monitor_name": f"{service_name} Health Check",
                "monitor_type": "health_check",
                "target_service": service_name,
                "target_endpoint": endpoint,
                "check_interval_seconds": 60,
                "timeout_seconds": 30
            }
        )
        return response.json()
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use API keys or JWT tokens for service-to-service communication
- Implement rate limiting for metrics endpoints

### Data Privacy

- Sanitize metric labels to prevent information leakage
- Use structured logging with appropriate log levels
- Implement data retention policies for metrics data

### Access Control

- Implement role-based access control for monitor management
- Use tenant isolation for multi-tenant environments
- Secure system metrics access

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Observability Dashboard",
    "panels": [
      {
        "title": "System Metrics",
        "type": "graph",
        "targets": [
          {
            "expr": "system_metrics_collected_total",
            "legendFormat": "{{metric_type}}"
          }
        ]
      },
      {
        "title": "Active Monitors",
        "type": "stat",
        "targets": [
          {
            "expr": "active_monitors_total",
            "legendFormat": "{{monitor_type}}"
          }
        ]
      },
      {
        "title": "Request Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, observability_request_duration_seconds_bucket)",
            "legendFormat": "95th percentile"
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
from observability.main import app

client = TestClient(app)

def test_record_metric():
    response = client.post(
        "/observability/v4/metrics",
        json={
            "metric_name": "test_metric",
            "metric_type": "counter",
            "value": 1,
            "service_name": "test-service"
        }
    )
    assert response.status_code == 200
    assert "metric_id" in response.json()

def test_get_metrics():
    response = client.get("/observability/v4/metrics")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_metrics_flow():
    async with httpx.AsyncClient() as client:
        # Record metric
        response = await client.post(
            "http://localhost:8702/observability/v4/metrics",
            json={
                "metric_name": "test_metric",
                "metric_type": "counter",
                "value": 1,
                "service_name": "test-service"
            }
        )
        assert response.status_code == 200

        # Get metrics
        response = await client.get(
            "http://localhost:8702/observability/v4/metrics?service_name=test-service"
        )
        assert response.status_code == 200
        assert len(response.json()) > 0
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Custom metrics recording and retrieval
- System metrics collection and monitoring
- Monitor management and health checks
- Prometheus metrics integration
- Celery task integration for asynchronous processing
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

