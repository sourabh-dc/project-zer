# Provisioning Service API Specification

## Overview

The Provisioning Service manages tenant onboarding, site/store provisioning, and user management in the Zeroque V2 multi-tenant marketplace architecture.

**Base URL:** `http://localhost:8201`  
**Version:** 2.0.0  
**Service:** provisioning

## Authentication

All endpoints require proper tenant context via RLS (Row-Level Security).

## Endpoints

### Health & Status

#### GET /health

**Description:** Service health check endpoint

**Response:**

```json
{
  "status": "ok",
  "service": "provisioning",
  "version": "2.0.0",
  "enhanced": true
}
```

### Tenant Management

#### GET /provisioning/v2/tenants

**Description:** List all tenants

**Response:**

```json
[
  {
    "tenant_id": "string",
    "name": "string",
    "type": "marketplace|customer",
    "active": true,
    "scenario_id": "string|null",
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/tenants

**Description:** Create a new tenant

**Request Body:**

```json
{
  "name": "string",
  "type": "marketplace|customer",
  "active": true,
  "scenario_id": "string|null"
}
```

**Response:**

```json
{
  "tenant_id": "string",
  "name": "string",
  "type": "string",
  "active": true,
  "scenario_id": "string|null",
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### PUT /provisioning/v2/tenants/{tenant_id}

**Description:** Update an existing tenant

**Path Parameters:**

- `tenant_id` (string): The tenant ID

**Request Body:**

```json
{
  "name": "string",
  "type": "marketplace|customer",
  "active": true,
  "scenario_id": "string|null"
}
```

**Response:**

```json
{
  "tenant_id": "string",
  "name": "string",
  "type": "string",
  "active": true,
  "scenario_id": "string|null",
  "created_at": "2025-10-01T05:21:19.093243+00:00",
  "updated_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### GET /provisioning/v2/tenants/{tenant_id}

**Description:** Get tenant details

**Path Parameters:**

- `tenant_id` (string): The tenant ID

**Response:**

```json
{
  "tenant_id": "string",
  "name": "string",
  "type": "string",
  "active": true,
  "scenario_id": "string|null",
  "created_at": "2025-10-01T05:21:19.093243+00:00",
  "updated_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Site Management

#### GET /provisioning/v2/sites

**Description:** List all sites

**Response:**

```json
[
  {
    "site_id": "string",
    "name": "string",
    "site_type": "warehouse|office|retail",
    "address": "string",
    "geo_lat": 0.0,
    "geo_lng": 0.0,
    "timezone": "string",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/sites

**Description:** Create a new site

**Request Body:**

```json
{
  "name": "string",
  "site_type": "warehouse|office|retail",
  "address": "string",
  "geo_lat": 0.0,
  "geo_lng": 0.0,
  "timezone": "string",
  "active": true
}
```

**Response:**

```json
{
  "site_id": "string",
  "name": "string",
  "site_type": "string",
  "address": "string",
  "geo_lat": 0.0,
  "geo_lng": 0.0,
  "timezone": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Store Management

#### GET /provisioning/v2/stores

**Description:** List all stores

**Response:**

```json
[
  {
    "store_id": "string",
    "name": "string",
    "store_type": "cashierless|traditional|warehouse",
    "address": "string",
    "geo_lat": 0.0,
    "geo_lng": 0.0,
    "timezone": "string",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/stores

**Description:** Create a new store

**Request Body:**

```json
{
  "name": "string",
  "store_type": "cashierless|traditional|warehouse",
  "address": "string",
  "geo_lat": 0.0,
  "geo_lng": 0.0,
  "timezone": "string",
  "active": true
}
```

**Response:**

```json
{
  "store_id": "string",
  "name": "string",
  "store_type": "string",
  "address": "string",
  "geo_lat": 0.0,
  "geo_lng": 0.0,
  "timezone": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### User Management

#### GET /provisioning/v2/users

**Description:** List all users

**Response:**

```json
[
  {
    "user_id": "string",
    "email": "string",
    "display_name": "string",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/users

**Description:** Create a new user

**Request Body:**

```json
{
  "email": "string",
  "display_name": "string",
  "active": true
}
```

**Response:**

```json
{
  "user_id": "string",
  "email": "string",
  "display_name": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### ERP Integration Management

#### GET /provisioning/v2/erp-integrations

**Description:** List all ERP integrations

**Response:**

```json
[
  {
    "id": "string",
    "tenant_id": "string|null",
    "vendor_id": "string|null",
    "type": "ERP|CRM",
    "config": {},
    "active": true,
    "last_sync_at": "2025-10-01T05:21:19.093243+00:00|null",
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/erp-integrations

**Description:** Create a new ERP integration

**Request Body:**

```json
{
  "tenant_id": "string|null",
  "vendor_id": "string|null",
  "type": "ERP|CRM",
  "config": {},
  "active": true
}
```

### Access Control Management

#### GET /provisioning/v2/access-controls

**Description:** List all access controls

**Response:**

```json
[
  {
    "id": "string",
    "site_id": "string|null",
    "store_id": "string|null",
    "type": "gate|RFID|lock|card_reader",
    "config": {},
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/access-controls

**Description:** Create a new access control

**Request Body:**

```json
{
  "site_id": "string|null",
  "store_id": "string|null",
  "type": "gate|RFID|lock|card_reader",
  "config": {},
  "active": true
}
```

### Scenario Management

#### GET /provisioning/v2/scenarios

**Description:** List all scenarios

**Response:**

```json
[
  {
    "id": "string",
    "code": "string",
    "name": "string",
    "config": {},
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /provisioning/v2/scenarios

**Description:** Create a new scenario

**Request Body:**

```json
{
  "code": "string",
  "name": "string",
  "config": {}
}
```

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request

```json
{
  "detail": "Validation error message"
}
```

### 404 Not Found

```json
{
  "detail": "Resource not found"
}
```

### 500 Internal Server Error

```json
{
  "detail": "Internal server error message"
}
```

## Data Models

### Tenant

```json
{
  "tenant_id": "string (UUID)",
  "name": "string",
  "type": "marketplace|customer",
  "active": "boolean",
  "scenario_id": "string (UUID)|null",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

### Site

```json
{
  "site_id": "string (UUID)",
  "name": "string",
  "site_type": "warehouse|office|retail",
  "address": "string",
  "geo_lat": "number (float)",
  "geo_lng": "number (float)",
  "timezone": "string",
  "active": "boolean",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

### Store

```json
{
  "store_id": "string (UUID)",
  "name": "string",
  "store_type": "cashierless|traditional|warehouse",
  "address": "string",
  "geo_lat": "number (float)",
  "geo_lng": "number (float)",
  "timezone": "string",
  "active": "boolean",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

### User

```json
{
  "user_id": "string (UUID)",
  "email": "string",
  "display_name": "string",
  "active": "boolean",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

## Features

- **Multi-tenant Architecture**: Full tenant isolation with RLS
- **Enhanced Communication**: Service bus integration with event publishing
- **Health Monitoring**: Comprehensive health checks
- **Circuit Breaker**: Resilient external service calls
- **Event Sourcing**: Event-driven architecture with saga support
- **Metrics & Logging**: OpenTelemetry integration with Prometheus metrics
- **Time-sortable UUIDs**: Uses uuid7 for better performance
- **Timezone Support**: Full timezone-aware timestamps

## Service Integration

The Provisioning Service integrates with:

- **Observability Service**: Health monitoring and metrics
- **Service Bus**: Event publishing and consumption
- **Database**: PostgreSQL with RLS policies
- **Redis**: Event streaming and caching

