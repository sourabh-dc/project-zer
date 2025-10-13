# ZeroQue Service Registry V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Service Registry V4.1 provides centralized service discovery and health monitoring for the entire ZeroQue microservices ecosystem. It implements production-ready features including service registration, health checks, endpoint discovery, and service status monitoring.

## 📋 Service Information

- **Service Name**: service-registry
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8704` (development)
- **Architecture**: Centralized service discovery and health monitoring
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Service Discovery**: Centralized registry of all microservices
- **Health Monitoring**: Real-time health checks for all services
- **Endpoint Discovery**: Dynamic endpoint discovery and routing
- **Status Tracking**: Comprehensive service status monitoring
- **Background Processing**: Asynchronous health check updates
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Circuit Breaker**: Resilience patterns for service calls
- **Caching**: Fast access to service information

### Service Registry Capabilities

- **Service Registration**: Automatic service discovery and registration
- **Health Checks**: Periodic health monitoring with configurable intervals
- **Status Reporting**: Real-time service status and availability
- **Endpoint Discovery**: Dynamic endpoint discovery for service communication
- **Load Balancing**: Service instance management and load distribution
- **Failure Detection**: Automatic detection of service failures
- **Recovery Monitoring**: Service recovery and availability tracking

## 🔧 Configuration

### Environment Variables

```bash
# Service Configuration
ENVIRONMENT=development
SERVICE_PORT=8704

# Health Check Configuration
HEALTH_CHECK_INTERVAL_SECONDS=30
HEALTH_CHECK_TIMEOUT_SECONDS=5
SERVICE_DISCOVERY_ENABLED=true
```

### Service Configuration

```python
SERVICES = {
    "cv_gateway": {"port": 8000, "health_path": "/health", "version": "4.1.0"},
    "orders": {"port": 8080, "health_path": "/health", "version": "2.0.0"},
    "identity": {"port": 8085, "health_path": "/health", "version": "4.1.0"},
    "ledger": {"port": 8086, "health_path": "/health", "version": "2.0.0"},
    "payments": {"port": 8087, "health_path": "/health", "version": "2.0.0"},
    "events": {"port": 8088, "health_path": "/events/v4/health", "version": "2.0.0"},
    "cv_connector": {"port": 8100, "health_path": "/health", "version": "4.1.0"},
    "entitlements": {"port": 8211, "health_path": "/health", "version": "2.0.0"},
    "subscriptions": {"port": 8212, "health_path": "/health", "version": "2.0.0"},
    "approvals": {"port": 8213, "health_path": "/health", "version": "2.0.0"},
    "notifications": {"port": 8300, "health_path": "/health", "version": "4.1.0"},
}
```

## 🚀 API Endpoints

### Health & Status Endpoints

#### GET /health

**Description**: Service health check endpoint

**Response**:

```json
{
  "status": "ok",
  "service": "service-registry",
  "version": "4.1.0",
  "environment": "development"
}
```

#### GET /readiness

**Description**: Service readiness check endpoint

**Response**:

```json
{
  "service": "service-registry",
  "status": "ready",
  "healthy_services": 10,
  "total_services": 11
}
```

**Error Response** (503 Service Unavailable):

```json
{
  "detail": "Service registry not ready"
}
```

### Service Discovery Endpoints

#### GET /services

**Description**: Get all services with their current status

**Response**:

```json
{
  "services": [
    {
      "name": "cv_gateway",
      "port": 8000,
      "status": "healthy",
      "version": "4.1.0",
      "last_check": "2024-01-15T10:30:00Z",
      "response_time_ms": 45.2,
      "error": null
    },
    {
      "name": "orders",
      "port": 8080,
      "status": "unhealthy",
      "version": "2.0.0",
      "last_check": "2024-01-15T10:30:00Z",
      "response_time_ms": null,
      "error": "Connection timeout"
    }
  ],
  "total_services": 11,
  "healthy_services": 10,
  "unhealthy_services": 1,
  "last_updated": "2024-01-15T10:30:00Z"
}
```

**cURL Example**:

```bash
curl "http://localhost:8704/services"
```

#### GET /services/{service_name}

**Description**: Get specific service information

**Path Parameters**:

- `service_name` (string, required): Name of the service

**Response**:

```json
{
  "name": "cv_gateway",
  "port": 8000,
  "status": "healthy",
  "version": "4.1.0",
  "last_check": "2024-01-15T10:30:00Z",
  "response_time_ms": 45.2,
  "error": null
}
```

**Error Response** (404 Not Found):

```json
{
  "detail": "Service not found"
}
```

**cURL Example**:

```bash
curl "http://localhost:8704/services/cv_gateway"
```

#### POST /services/refresh

**Description**: Manually refresh service registry

**Response**:

```json
{
  "message": "Service registry refresh initiated"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8704/services/refresh"
```

#### GET /services/healthy

**Description**: Get only healthy services

**Response**:

```json
{
  "services": [
    {
      "name": "cv_gateway",
      "port": 8000,
      "status": "healthy",
      "version": "4.1.0",
      "last_check": "2024-01-15T10:30:00Z",
      "response_time_ms": 45.2,
      "error": null
    },
    {
      "name": "identity",
      "port": 8085,
      "status": "healthy",
      "version": "4.1.0",
      "last_check": "2024-01-15T10:30:00Z",
      "response_time_ms": 32.1,
      "error": null
    }
  ],
  "count": 10
}
```

**cURL Example**:

```bash
curl "http://localhost:8704/services/healthy"
```

#### GET /services/unhealthy

**Description**: Get only unhealthy services

**Response**:

```json
{
  "services": [
    {
      "name": "orders",
      "port": 8080,
      "status": "unhealthy",
      "version": "2.0.0",
      "last_check": "2024-01-15T10:30:00Z",
      "response_time_ms": null,
      "error": "Connection timeout"
    }
  ],
  "count": 1
}
```

**cURL Example**:

```bash
curl "http://localhost:8704/services/unhealthy"
```

### Service Discovery Integration Endpoints

#### GET /discovery/{service_name}/endpoints

**Description**: Get available endpoints for a service

**Path Parameters**:

- `service_name` (string, required): Name of the service

**Response**:

```json
{
  "service_name": "cv_gateway",
  "endpoints": ["/health", "/cv/webhook/order", "/cv/entry/codes"],
  "base_url": "http://localhost:8000",
  "status": "healthy"
}
```

**Error Response** (404 Not Found):

```json
{
  "detail": "Service not found"
}
```

**cURL Example**:

```bash
curl "http://localhost:8704/discovery/cv_gateway/endpoints"
```

## 🔄 Background Processing

### Service Health Check Flow

1. **Periodic Checks**: Health checks run every 30 seconds
2. **Parallel Processing**: All services checked concurrently
3. **Timeout Handling**: 5-second timeout per service
4. **Status Updates**: Service status updated in registry
5. **Error Tracking**: Errors logged and tracked
6. **Recovery Detection**: Automatic recovery detection

### Health Check Implementation

```python
async def check_service_health(service_name: str, config: Dict[str, Any]) -> ServiceInfo:
    start_time = datetime.now()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"http://localhost:{config['port']}{config['health_path']}"
            )

            response_time = (datetime.now() - start_time).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                status = "healthy"
                if isinstance(data, dict):
                    status = data.get("status", "healthy")

                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status=status,
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time
                )
            else:
                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status="unhealthy",
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                    error=f"HTTP {response.status_code}"
                )
    except Exception as e:
        return ServiceInfo(
            name=service_name,
            port=config["port"],
            status="unhealthy",
            version=config["version"],
            last_check=datetime.now(timezone.utc),
            error=str(e)
        )
```

## 📊 Service Status Types

### Healthy Status

**Description**: Service is responding correctly to health checks

**Characteristics**:

- HTTP 200 response from health endpoint
- Response time within acceptable limits
- No error messages
- Service functionality available

**Example**:

```json
{
  "name": "cv_gateway",
  "status": "healthy",
  "response_time_ms": 45.2,
  "error": null
}
```

### Unhealthy Status

**Description**: Service is not responding or responding incorrectly

**Characteristics**:

- HTTP error status codes
- Connection timeouts
- Service errors or exceptions
- Service functionality unavailable

**Example**:

```json
{
  "name": "orders",
  "status": "unhealthy",
  "response_time_ms": null,
  "error": "Connection timeout"
}
```

### Unknown Status

**Description**: Service status cannot be determined

**Characteristics**:

- Service not yet checked
- Check in progress
- Configuration issues
- Network connectivity problems

## 🔍 Service Discovery Patterns

### Service Registration

**Automatic Registration**:

- Services automatically discovered based on configuration
- Health checks initiated immediately
- Status tracked in real-time

**Manual Registration**:

- Services can be manually added to registry
- Configuration updates supported
- Dynamic service discovery

### Health Check Patterns

**Endpoint-Based Checks**:

- Standard health endpoint (`/health`)
- Custom health endpoints supported
- Multiple health check types

**Response Validation**:

- HTTP status code validation
- Response body validation
- Response time monitoring

### Failure Detection

**Timeout Detection**:

- Configurable timeout periods
- Connection timeout handling
- Request timeout management

**Error Classification**:

- Network errors
- Service errors
- Configuration errors

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
  "detail": "Service registry not ready"
}
```

### Service-Specific Errors

#### Connection Errors

```json
{
  "name": "orders",
  "status": "unhealthy",
  "error": "Connection timeout"
}
```

#### HTTP Errors

```json
{
  "name": "payments",
  "status": "unhealthy",
  "error": "HTTP 500"
}
```

#### Configuration Errors

```json
{
  "name": "unknown_service",
  "status": "unknown",
  "error": "Service not configured"
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
EXPOSE 8704

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: service-registry
spec:
  replicas: 2
  selector:
    matchLabels:
      app: service-registry
  template:
    metadata:
      labels:
        app: service-registry
    spec:
      containers:
        - name: service-registry
          image: zeroque/service-registry:4.1.0
          ports:
            - containerPort: 8704
          env:
            - name: ENVIRONMENT
              value: "production"
            - name: HEALTH_CHECK_INTERVAL_SECONDS
              value: "30"
          resources:
            requests:
              memory: "128Mi"
              cpu: "50m"
            limits:
              memory: "256Mi"
              cpu: "200m"
```

### Service Mesh Integration

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: service-registry-config
data:
  services.yaml: |
    services:
      cv_gateway:
        port: 8000
        health_path: "/health"
        version: "4.1.0"
      orders:
        port: 8080
        health_path: "/health"
        version: "2.0.0"
```

## 📚 Integration Examples

### Service Discovery Integration

```python
import httpx

async def discover_service(service_name):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8704/services/{service_name}"
        )
        if response.status_code == 200:
            service_info = response.json()
            if service_info["status"] == "healthy":
                return f"http://localhost:{service_info['port']}"
        return None
```

### Health Check Integration

```python
import httpx

async def check_all_services():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://localhost:8704/services")
        if response.status_code == 200:
            registry = response.json()
            return {
                "total": registry["total_services"],
                "healthy": registry["healthy_services"],
                "unhealthy": registry["unhealthy_services"]
            }
        return None
```

### Endpoint Discovery Integration

```python
import httpx

async def get_service_endpoints(service_name):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8704/discovery/{service_name}/endpoints"
        )
        if response.status_code == 200:
            discovery = response.json()
            return {
                "base_url": discovery["base_url"],
                "endpoints": discovery["endpoints"]
            }
        return None
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use API keys or JWT tokens for service-to-service communication
- Implement rate limiting for discovery endpoints

### Data Privacy

- Sanitize service information to prevent information leakage
- Use structured logging with appropriate log levels
- Implement access control for sensitive service information

### Network Security

- Use HTTPS in production environments
- Implement proper firewall rules
- Use VPN or private networks for internal communication

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Service Registry Dashboard",
    "panels": [
      {
        "title": "Service Health Status",
        "type": "stat",
        "targets": [
          {
            "expr": "service_registry_healthy_services",
            "legendFormat": "Healthy Services"
          }
        ]
      },
      {
        "title": "Service Response Times",
        "type": "graph",
        "targets": [
          {
            "expr": "service_registry_response_time_ms",
            "legendFormat": "{{service_name}}"
          }
        ]
      },
      {
        "title": "Service Status Distribution",
        "type": "pie",
        "targets": [
          {
            "expr": "service_registry_status_total",
            "legendFormat": "{{status}}"
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
from service_registry.main import app

client = TestClient(app)

def test_get_services():
    response = client.get("/services")
    assert response.status_code == 200
    assert "services" in response.json()
    assert "total_services" in response.json()

def test_get_service():
    response = client.get("/services/cv_gateway")
    assert response.status_code in [200, 404]
    if response.status_code == 200:
        assert "name" in response.json()
        assert "status" in response.json()
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_service_discovery():
    async with httpx.AsyncClient() as client:
        # Get all services
        response = await client.get("http://localhost:8704/services")
        assert response.status_code == 200

        # Get specific service
        response = await client.get("http://localhost:8704/services/cv_gateway")
        assert response.status_code in [200, 404]

        # Get service endpoints
        response = await client.get("http://localhost:8704/discovery/cv_gateway/endpoints")
        assert response.status_code in [200, 404]
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Centralized service discovery and registration
- Real-time health monitoring for all services
- Service endpoint discovery and routing
- Background health check processing
- Comprehensive service status tracking
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

