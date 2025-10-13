# ZeroQue Reports Service V4.1 - Complete API Documentation

## 🎯 Overview

The ZeroQue Reports Service V4.1 provides comprehensive analytics, reporting, and business intelligence capabilities for the ZeroQue ecosystem. It implements production-ready features including report generation, analytics dashboards, data export, and caching mechanisms.

## 📋 Service Information

- **Service Name**: reports
- **Version**: 4.1.0
- **Base URL**: `http://localhost:8703` (development)
- **Architecture**: Analytics and reporting platform with caching
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Production-Ready Implementation

- **Report Generation**: Asynchronous report generation with multiple formats
- **Analytics Engine**: Real-time analytics and business intelligence
- **Caching System**: Intelligent caching for improved performance
- **Data Export**: Support for JSON, CSV, Excel, and PDF formats
- **Background Processing**: Asynchronous report generation with status tracking
- **Structured Logging**: JSON-formatted logs with correlation IDs
- **Prometheus Metrics**: Comprehensive monitoring and performance tracking
- **Database Persistence**: PostgreSQL with proper indexing and optimization

### Report Types

- **Sales Analytics**: Revenue, orders, and sales performance metrics
- **Inventory Analytics**: Stock levels, turnover, and supply chain insights
- **Customer Analytics**: Customer behavior, segmentation, and lifetime value
- **Operational Analytics**: System performance, usage patterns, and efficiency
- **Financial Analytics**: Revenue, costs, profitability, and financial health
- **Usage Analytics**: Feature usage, adoption rates, and engagement metrics
- **Performance Analytics**: System performance, response times, and reliability

## 🔧 Configuration

### Environment Variables

```bash
# Database Configuration
DATABASE_URL=postgresql://zeroque:zeroque@localhost:5432/zeroque_dev

# Service Configuration
ENVIRONMENT=development
SERVICE_PORT=8703

# Report Configuration
REPORT_CACHE_TTL_MINUTES=60
REPORT_STORAGE_PATH=/tmp/reports
MAX_REPORT_SIZE_MB=100
```

### Report Storage

```bash
# Create report storage directory
mkdir -p /tmp/reports
chmod 755 /tmp/reports
```

## 📊 Database Schema

### ReportJob Table

```sql
CREATE TABLE report_jobs_new (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255),
    report_type VARCHAR(100) NOT NULL,
    report_name VARCHAR(255) NOT NULL,
    parameters JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    file_path VARCHAR(500),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE
);
```

### ReportCache Table

```sql
CREATE TABLE report_cache_new (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    report_type VARCHAR(100) NOT NULL,
    parameters_hash VARCHAR(64) NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
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
  "service": "reports",
  "version": "4.1.0",
  "environment": "development"
}
```

#### GET /readiness

**Description**: Service readiness check endpoint

**Response**:

```json
{
  "service": "reports",
  "status": "ready",
  "database": "connected"
}
```

#### GET /metrics

**Description**: Prometheus metrics endpoint

**Response**: Prometheus-formatted metrics

### Report Generation Endpoints

#### POST /reports/v4/generate

**Description**: Generate a new report

**Request Body**:

```json
{
  "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "123e4567-e89b-12d3-a456-426614174001",
  "report_type": "sales_analytics",
  "report_name": "Monthly Sales Report",
  "parameters": {
    "start_date": "2024-01-01",
    "end_date": "2024-01-31",
    "store_id": "123e4567-e89b-12d3-a456-426614174002",
    "group_by": "day",
    "include_details": true
  },
  "format": "excel",
  "cache_ttl_minutes": 60
}
```

**Response**:

```json
{
  "job_id": "report_20240115_103000_sales_analytics",
  "status": "generating",
  "message": "Report generation initiated",
  "estimated_completion": "2024-01-15T10:35:00Z"
}
```

**cURL Example**:

```bash
curl -X POST "http://localhost:8703/reports/v4/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_id": "123e4567-e89b-12d3-a456-426614174001",
    "report_type": "sales_analytics",
    "report_name": "Monthly Sales Report",
    "parameters": {
      "start_date": "2024-01-01",
      "end_date": "2024-01-31",
      "store_id": "123e4567-e89b-12d3-a456-426614174002",
      "group_by": "day"
    },
    "format": "excel",
    "cache_ttl_minutes": 60
  }'
```

#### GET /reports/v4/status/{job_id}

**Description**: Get report generation status

**Path Parameters**:

- `job_id` (string, required): Report job ID

**Response**:

```json
{
  "job_id": "report_20240115_103000_sales_analytics",
  "status": "completed",
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:32:15Z",
  "error_message": null,
  "file_path": "/tmp/reports/report_20240115_103000_sales_analytics.xlsx"
}
```

**cURL Example**:

```bash
curl "http://localhost:8703/reports/v4/status/report_20240115_103000_sales_analytics"
```

#### GET /reports/v4/download/{job_id}

**Description**: Download completed report

**Path Parameters**:

- `job_id` (string, required): Report job ID

**Response**: File download (binary content)

**cURL Example**:

```bash
curl "http://localhost:8703/reports/v4/download/report_20240115_103000_sales_analytics" \
  -o "monthly_sales_report.xlsx"
```

### Analytics Endpoints

#### GET /analytics/v4/sales

**Description**: Get sales analytics data

**Query Parameters**:

- `tenant_id` (string, required): Tenant ID
- `start_date` (string, required): Start date (YYYY-MM-DD)
- `end_date` (string, required): End date (YYYY-MM-DD)
- `store_id` (string, optional): Store ID filter
- `group_by` (string, optional): Grouping (day, week, month) (default: day)

**Response**:

```json
{
  "data": {
    "summary": {
      "total_revenue": 15000.0,
      "total_orders": 150,
      "average_order_value": 100.0,
      "growth_rate": 12.5
    },
    "trends": [
      {
        "date": "2024-01-01",
        "revenue": 500.0,
        "orders": 5,
        "average_order_value": 100.0
      },
      {
        "date": "2024-01-02",
        "revenue": 750.0,
        "orders": 7,
        "average_order_value": 107.14
      }
    ],
    "top_products": [
      {
        "product_id": "prod_123",
        "product_name": "Product A",
        "revenue": 3000.0,
        "quantity_sold": 30
      }
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z",
  "generation_time_seconds": 2.5
}
```

**cURL Example**:

```bash
curl "http://localhost:8703/analytics/v4/sales?tenant_id=123e4567-e89b-12d3-a456-426614174000&start_date=2024-01-01&end_date=2024-01-31&group_by=day"
```

#### GET /analytics/v4/inventory

**Description**: Get inventory analytics data

**Query Parameters**:

- `tenant_id` (string, required): Tenant ID
- `store_id` (string, optional): Store ID filter

**Response**:

```json
{
  "data": {
    "summary": {
      "total_items": 1000,
      "total_value": 50000.0,
      "low_stock_items": 25,
      "out_of_stock_items": 5
    },
    "categories": [
      {
        "category": "Electronics",
        "item_count": 300,
        "total_value": 25000.0,
        "turnover_rate": 2.5
      },
      {
        "category": "Clothing",
        "item_count": 400,
        "total_value": 15000.0,
        "turnover_rate": 3.2
      }
    ],
    "low_stock": [
      {
        "product_id": "prod_456",
        "product_name": "Product B",
        "current_stock": 5,
        "reorder_level": 10,
        "days_until_stockout": 3
      }
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z",
  "generation_time_seconds": 1.8
}
```

**cURL Example**:

```bash
curl "http://localhost:8703/analytics/v4/inventory?tenant_id=123e4567-e89b-12d3-a456-426614174000"
```

#### GET /analytics/v4/customers

**Description**: Get customer analytics data

**Query Parameters**:

- `tenant_id` (string, required): Tenant ID
- `start_date` (string, optional): Start date filter
- `end_date` (string, optional): End date filter
- `segment` (string, optional): Customer segment filter

**Response**:

```json
{
  "data": {
    "summary": {
      "total_customers": 500,
      "new_customers": 50,
      "returning_customers": 450,
      "average_lifetime_value": 250.0
    },
    "segments": [
      {
        "segment": "VIP",
        "customer_count": 50,
        "total_revenue": 25000.0,
        "average_order_value": 500.0
      },
      {
        "segment": "Regular",
        "customer_count": 300,
        "total_revenue": 45000.0,
        "average_order_value": 150.0
      }
    ],
    "growth": [
      {
        "month": "2024-01",
        "new_customers": 25,
        "retention_rate": 85.5
      }
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z",
  "generation_time_seconds": 3.2
}
```

**cURL Example**:

```bash
curl "http://localhost:8703/analytics/v4/customers?tenant_id=123e4567-e89b-12d3-a456-426614174000&start_date=2024-01-01&end_date=2024-01-31"
```

#### GET /analytics/v4/operational

**Description**: Get operational analytics data

**Query Parameters**:

- `tenant_id` (string, required): Tenant ID
- `metric_type` (string, optional): Metric type filter
- `time_range` (string, optional): Time range (1h, 24h, 7d, 30d)

**Response**:

```json
{
  "data": {
    "summary": {
      "total_requests": 10000,
      "average_response_time": 250,
      "error_rate": 0.5,
      "uptime": 99.9
    },
    "performance": [
      {
        "service": "provisioning",
        "requests": 2000,
        "average_response_time": 200,
        "error_rate": 0.2
      },
      {
        "service": "orders",
        "requests": 3000,
        "average_response_time": 300,
        "error_rate": 0.8
      }
    ],
    "trends": [
      {
        "timestamp": "2024-01-15T10:00:00Z",
        "requests": 100,
        "response_time": 250,
        "errors": 1
      }
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z",
  "generation_time_seconds": 1.5
}
```

**cURL Example**:

```bash
curl "http://localhost:8703/analytics/v4/operational?tenant_id=123e4567-e89b-12d3-a456-426614174000&time_range=24h"
```

## 📊 Report Formats

### JSON Format

**Description**: Structured JSON data for programmatic access

**Use Cases**:

- API integrations
- Data processing pipelines
- Real-time dashboards

**Example**:

```json
{
  "report_type": "sales_analytics",
  "generated_at": "2024-01-15T10:30:00Z",
  "data": {
    "summary": {...},
    "details": [...]
  }
}
```

### CSV Format

**Description**: Comma-separated values for spreadsheet applications

**Use Cases**:

- Excel analysis
- Data import/export
- Simple reporting

**Example**:

```csv
date,revenue,orders,average_order_value
2024-01-01,500.00,5,100.00
2024-01-02,750.00,7,107.14
```

### Excel Format

**Description**: Microsoft Excel format with multiple sheets

**Use Cases**:

- Business presentations
- Detailed analysis
- Multi-sheet reports

**Features**:

- Multiple worksheets
- Charts and graphs
- Formatting and styling
- Data validation

### PDF Format

**Description**: Portable Document Format for sharing and printing

**Use Cases**:

- Executive summaries
- Printed reports
- Document sharing

**Features**:

- Professional formatting
- Charts and graphs
- Page breaks
- Header/footer

## 🔄 Background Processing

### Report Generation Flow

1. **Request Received**: Client submits report generation request
2. **Job Created**: Report job record created in database
3. **Background Task**: Asynchronous report generation started
4. **Data Collection**: Data gathered from various sources
5. **Processing**: Data processed and formatted
6. **File Generation**: Report file created in specified format
7. **Status Update**: Job status updated to completed
8. **Notification**: Client notified of completion

### Status Tracking

- **pending**: Report job created, waiting to start
- **generating**: Report generation in progress
- **completed**: Report generation completed successfully
- **failed**: Report generation failed with error

## 📈 Prometheus Metrics

### Counters

- `report_requests_total`: Total report requests
  - Labels: `report_type`, `status`
- `report_cache_hits`: Total cache hits
  - Labels: `report_type`

### Histograms

- `report_generation_duration_seconds`: Report generation duration
  - Labels: `report_type`

### Gauges

- `active_report_sessions`: Number of active report sessions
  - Labels: `report_type`

## 🔍 Caching Strategy

### Cache Key Generation

```python
cache_key = f"{tenant_id}:{report_type}:{hash(str(parameters))}"
```

### Cache TTL

- **Default**: 60 minutes
- **Configurable**: Per report type
- **Automatic**: Based on data freshness requirements

### Cache Invalidation

- **Time-based**: Automatic expiration
- **Event-based**: Data change notifications
- **Manual**: Administrative cache clearing

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
  "detail": "Report job not found"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "Failed to generate report: Database connection failed"
}
```

#### 503 Service Unavailable

```json
{
  "detail": "Service not ready: Database connection failed"
}
```

### Report Generation Errors

#### Data Source Errors

```json
{
  "detail": "Failed to generate report: Data source unavailable",
  "error_code": "DATA_SOURCE_ERROR",
  "retry_after": 300
}
```

#### Format Errors

```json
{
  "detail": "Failed to generate report: Invalid format specified",
  "error_code": "FORMAT_ERROR",
  "supported_formats": ["json", "csv", "excel", "pdf"]
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
EXPOSE 8703

# Create report storage directory
RUN mkdir -p /tmp/reports && chmod 755 /tmp/reports

CMD ["python", "main.py"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reports-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: reports-service
  template:
    metadata:
      labels:
        app: reports-service
    spec:
      containers:
        - name: reports
          image: zeroque/reports:4.1.0
          ports:
            - containerPort: 8703
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: db-secret
                  key: url
            - name: REPORT_STORAGE_PATH
              value: "/tmp/reports"
          volumeMounts:
            - name: report-storage
              mountPath: /tmp/reports
          resources:
            requests:
              memory: "512Mi"
              cpu: "200m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
      volumes:
        - name: report-storage
          emptyDir: {}
```

## 📚 Integration Examples

### Service Integration

```python
import httpx

async def generate_sales_report(tenant_id, start_date, end_date):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8703/reports/v4/generate",
            json={
                "tenant_id": tenant_id,
                "report_type": "sales_analytics",
                "report_name": "Sales Report",
                "parameters": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "group_by": "day"
                },
                "format": "excel"
            }
        )
        return response.json()
```

### Analytics Integration

```python
import httpx

async def get_sales_analytics(tenant_id, start_date, end_date):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8703/analytics/v4/sales",
            params={
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "group_by": "day"
            }
        )
        return response.json()
```

## 🔐 Security Considerations

### Authentication

- All endpoints require proper authentication
- Use JWT tokens for service-to-service communication
- Implement role-based access control for sensitive reports

### Data Privacy

- Sanitize report parameters to prevent injection attacks
- Use structured logging with appropriate log levels
- Implement data retention policies for report files

### Access Control

- Implement tenant isolation for multi-tenant environments
- Use role-based permissions for report access
- Secure report file storage and access

## 📊 Monitoring Dashboard

### Grafana Dashboard Configuration

```json
{
  "dashboard": {
    "title": "ZeroQue Reports Dashboard",
    "panels": [
      {
        "title": "Report Generation Volume",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(report_requests_total[5m])",
            "legendFormat": "{{report_type}} - {{status}}"
          }
        ]
      },
      {
        "title": "Report Generation Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, report_generation_duration_seconds_bucket)",
            "legendFormat": "95th percentile - {{report_type}}"
          }
        ]
      },
      {
        "title": "Cache Hit Rate",
        "type": "stat",
        "targets": [
          {
            "expr": "rate(report_cache_hits[5m]) / rate(report_requests_total[5m]) * 100",
            "legendFormat": "Cache Hit Rate %"
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
from reports.main import app

client = TestClient(app)

def test_generate_report():
    response = client.post(
        "/reports/v4/generate",
        json={
            "tenant_id": "test-tenant",
            "report_type": "sales_analytics",
            "report_name": "Test Report",
            "parameters": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31"
            },
            "format": "json"
        }
    )
    assert response.status_code == 200
    assert "job_id" in response.json()

def test_get_analytics():
    response = client.get(
        "/analytics/v4/sales",
        params={
            "tenant_id": "test-tenant",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31"
        }
    )
    assert response.status_code == 200
    assert "data" in response.json()
```

### Integration Tests

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_report_flow():
    async with httpx.AsyncClient() as client:
        # Generate report
        response = await client.post(
            "http://localhost:8703/reports/v4/generate",
            json={
                "tenant_id": "test-tenant",
                "report_type": "sales_analytics",
                "report_name": "Test Report",
                "parameters": {
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31"
                },
                "format": "json"
            }
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        # Check status
        response = await client.get(
            f"http://localhost:8703/reports/v4/status/{job_id}"
        )
        assert response.status_code == 200
```

## 📝 Changelog

### Version 4.1.0

- Initial production release
- Comprehensive report generation system
- Real-time analytics endpoints
- Multiple export formats (JSON, CSV, Excel, PDF)
- Background processing with status tracking
- Intelligent caching system
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

