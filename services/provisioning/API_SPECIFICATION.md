# ZeroQue Provisioning Service API Specification

## Overview

The ZeroQue Provisioning Service provides V2 multi-tenant marketplace architecture with scenario-specific tenant, site, and store management. The service has been enhanced with:

- **Repository Pattern**: Clean separation of data access logic from business logic
- **Service Layer**: Business logic orchestration and transaction management
- **Dependency Injection**: Proper session management with FastAPI dependencies
- **Enhanced Error Handling**: Custom exception handlers with proper HTTP status codes
- **Production-Ready**: Transaction management, rollback mechanisms, and consistent error handling

**Base URL**: `http://localhost:8201`  
**Version**: 2.0.0  
**Architecture**: Multi-tenant marketplace with scenario-specific types

## Health Endpoints

### GET /health

**Description**: Service health check  
**Response**:

```json
{
  "status": "ok",
  "service": "provisioning",
  "version": "2.0.0",
  "enhanced": true
}
```

### GET /readiness

**Description**: Service readiness check  
**Response**:

```json
{
  "service": "provisioning",
  "db": true,
  "redis": true
}
```

## Tenant Types

The system supports the following tenant types:

- `end_user`: End users with budgets and approvals
- `retailer`: Retailers with guest access and loyalty programs
- `distributor`: Distributors with control tower and global catalog
- `custom`: Custom configuration for special use cases

## Site Types

The system supports the following site types:

- `onsite`: End users with budgets (M:N tenant_sites)
- `unmanned`: Retailer public guest access
- `distributor_centre`: Distributor client installs with ERP sync

## Store Types

The system supports the following store types:

- `unmanned_onsite`: Budgets and approvals for end users
- `unmanned_public`: Guest access and loyalty for retailers
- `unmanned_distributed`: Global catalog for distributors

## Tenant Management

### PUT /provisioning/tenants/{tenant_id}

**Description**: Create or update a tenant  
**Request Body**:

```json
{
  "name": "Acme Corporation",
  "type": "end_user",
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Acme Corporation",
  "type": "end_user",
  "created": true,
  "saga_id": "tenant_provision_1696248000"
}
```

### PUT /provisioning/tenants/{tenant_id}

**Description**: Create or update a tenant  
**Parameters**:

- `tenant_id` (path): Tenant identifier (UUID)

**Request Body**:

```json
{
  "name": "string (required)",
  "type": "string (optional, default: 'customer') - end_user, retailer, distributor, custom",
  "scenario_id": "string (optional)"
}
```

**Response**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Acme Corporation",
  "type": "end_user",
  "created": true
}
```

### GET /provisioning/tenants

**Description**: List all tenants  
**Query Parameters**:

- `limit` (integer, optional): Maximum number of tenants to return (default: 100)

**Response**:

```json
[
  {
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Acme Corporation",
    "type": "end_user"
  }
]
```

## Site Management

### PUT /provisioning/sites/{site_id}

**Description**: Create or update a site  
**Parameters**:

- `site_id` (path): Site identifier (UUID)
- `tenant_id` (query): Tenant identifier (UUID, required)

**Request Body**:

```json
{
  "name": "string (required)",
  "site_type": "string (optional, default: 'unmanned') - onsite, unmanned, distributor_centre",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278,
    "address": "string (optional)"
  }
}
```

**Response**:

```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440002",
  "name": "Main Campus",
  "site_type": "onsite",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278
  },
  "created": true
}
```

### GET /provisioning/sites

**Description**: List all sites  
**Query Parameters**:

- `limit` (integer, optional): Maximum number of sites to return (default: 200)

**Response**:

```json
[
  {
    "site_id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Main Campus",
    "site_type": "onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278
    }
  }
]
```

## Store Management

### PUT /provisioning/stores/{store_id}

**Description**: Create or update a store  
**Parameters**:

- `store_id` (path): Store identifier (UUID)
- `site_id` (query): Site identifier (UUID, required)

**Request Body**:

```json
{
  "name": "string (required)",
  "store_type": "string (optional, default: 'cashierless') - unmanned_onsite, unmanned_public, unmanned_distributed",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278,
    "address": "string (optional)"
  }
}
```

**Response**:

```json
{
  "store_id": "550e8400-e29b-41d4-a716-446655440003",
  "name": "ToolRoom",
  "store_type": "unmanned_onsite",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278
  },
  "created": true
}
```

### GET /provisioning/stores

**Description**: List all stores  
**Query Parameters**:

- `limit` (integer, optional): Maximum number of stores to return (default: 200)

**Response**:

```json
[
  {
    "store_id": "550e8400-e29b-41d4-a716-446655440003",
    "name": "ToolRoom",
    "store_type": "unmanned_onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278
    }
  }
]
```

## User Management

### PUT /provisioning/users/{user_id}

**Description**: Create or update a user  
**Parameters**:

- `user_id` (path): User identifier (UUID)

**Request Body**:

```json
{
  "email": "string (required)",
  "display_name": "string (required)"
}
```

**Response**:

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440004",
  "email": "user@example.com",
  "display_name": "John Doe",
  "created": true
}
```

### GET /provisioning/users

**Description**: List all users  
**Query Parameters**:

- `limit` (integer, optional): Maximum number of users to return (default: 200)

**Response**:

```json
[
  {
    "user_id": "550e8400-e29b-41d4-a716-446655440004",
    "email": "user@example.com",
    "display_name": "John Doe"
  }
]
```

## Vendor Management

### PUT /provisioning/vendors/{vendor_id}

**Description**: Create or update a vendor  
**Parameters**:

- `vendor_id` (path): Vendor identifier (UUID)

**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "string (required)",
  "description": "string (optional)",
  "rating": 4.5
}
```

**Response**:

```json
{
  "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Vendor Corp",
  "created": true
}
```

### GET /provisioning/vendors

**Description**: List all vendors  
**Query Parameters**:

- `tenant_id` (string, optional): Filter by tenant ID
- `limit` (integer, optional): Maximum number of vendors to return (default: 200)

**Response**:

```json
[
  {
    "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Vendor Corp",
    "description": "Test vendor",
    "rating": 4.5,
    "active": true
  }
]
```

## Scenario Management

### PUT /provisioning/scenarios/{scenario_id}

**Description**: Create or update a scenario  
**Parameters**:

- `scenario_id` (path): Scenario identifier (UUID)

**Request Body**:

```json
{
  "code": "string (required)",
  "name": "string (required)",
  "config": {
    "feature": "string (optional)"
  }
}
```

**Response**:

```json
{
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000",
  "created": true
}
```

### GET /provisioning/scenarios

**Description**: List all scenarios  
**Query Parameters**:

- `limit` (integer, optional): Maximum number of scenarios to return (default: 200)

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "code": "test_scenario",
    "name": "Test Scenario",
    "config": {
      "feature": "test"
    },
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

## ERP Integration Management

### PUT /provisioning/erp-integrations/{integration_id}

**Description**: Create or update an ERP integration  
**Parameters**:

- `integration_id` (path): Integration identifier (UUID)

**Request Body**:

```json
{
  "tenant_id": "string (optional)",
  "vendor_id": "string (optional)",
  "type": "string (required) - ERP or CRM",
  "config": {
    "api_key": "string (optional)",
    "endpoint": "string (optional)"
  }
}
```

**Response**:

```json
{
  "integration_id": "550e8400-e29b-41d4-a716-446655440000",
  "created": true
}
```

### GET /provisioning/erp-integrations

**Description**: List ERP integrations  
**Query Parameters**:

- `tenant_id` (string, optional): Filter by tenant ID
- `limit` (integer, optional): Maximum number of integrations to return (default: 200)

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "vendor_id": null,
    "type": "ERP",
    "config": {
      "api_key": "test"
    },
    "active": true,
    "last_sync_at": null,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

## Access Control Management

### PUT /provisioning/access-controls/{control_id}

**Description**: Create or update an access control device  
**Parameters**:

- `control_id` (path): Control identifier (UUID)

**Request Body**:

```json
{
  "site_id": "string (optional)",
  "store_id": "string (optional)",
  "type": "string (required) - gate, RFID, lock, card_reader",
  "config": {
    "device_id": "string (optional)",
    "settings": "object (optional)"
  }
}
```

**Response**:

```json
{
  "control_id": "550e8400-e29b-41d4-a716-446655440000",
  "created": true
}
```

### GET /provisioning/access-controls

**Description**: List access controls  
**Query Parameters**:

- `site_id` (string, optional): Filter by site ID
- `store_id` (string, optional): Filter by store ID
- `limit` (integer, optional): Maximum number of controls to return (default: 200)

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "site_id": "550e8400-e29b-41d4-a716-446655440002",
    "store_id": null,
    "type": "gate",
    "config": {
      "device_id": "gate_001"
    },
    "active": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

## User Access Grant Management

### PUT /provisioning/user-access-grants

**Description**: Create or update a user access grant  
**Request Body**:

```json
{
  "user_id": "string (required)",
  "access_control_id": "string (required)",
  "grant_type": "string (optional, default: 'permanent') - permanent or temporary",
  "valid_until": "datetime (optional)"
}
```

**Response**:

```json
{
  "grant_id": "550e8400-e29b-41d4-a716-446655440000",
  "created": true
}
```

### GET /provisioning/user-access-grants

**Description**: List user access grants  
**Query Parameters**:

- `user_id` (string, optional): Filter by user ID
- `limit` (integer, optional): Maximum number of grants to return (default: 200)

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "550e8400-e29b-41d4-a716-446655440004",
    "access_control_id": "550e8400-e29b-41d4-a716-446655440005",
    "grant_type": "permanent",
    "valid_from": "2024-01-01T00:00:00Z",
    "valid_until": null,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

## Examples

**Example**:

```bash
curl -X PUT "http://localhost:8201/provisioning/v2/tenants/tenant-retailer-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Retailer Tenant",
    "type": "retailer"
  }'
```

## Site Management

### PUT /provisioning/sites/{site_id}

**Description**: Create or update a site  
**Parameters**:

- `site_id` (path): Site identifier (string, max 100 chars)
- `tenant_id` (query): Tenant identifier (required)

**Request Body**:

```json
{
  "name": "string (required)",
  "site_type": "string (optional, default: 'unmanned')",
  "geo": {
    "lat": "number (optional)",
    "lng": "number (optional)",
    "address": "string (optional)"
  }
}
```

**Site Types**:

- `onsite`: Internal 24/7 access
- `unmanned`: Public-facing guest access
- `warehouse`: Storage facilities
- `distribution_center`: Client installs
- `custom`: Flexible type

**Response**:

```json
{
  "site_id": "string",
  "name": "string",
  "site_type": "string",
  "geo": "object (optional)",
  "created": true
}
```

**Example**:

```bash
curl -X PUT "http://localhost:8201/provisioning/v2/sites/site-unmanned-001?tenant_id=tenant-retailer-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Unmanned Site",
    "site_type": "unmanned",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278,
      "address": "123 Retail St, London, UK"
    }
  }'
```

### GET /provisioning/sites

**Description**: List sites  
**Parameters**:

- `limit` (query): Maximum number of sites to return (default: 200)

**Response**:

```json
[
  {
    "site_id": "string",
    "name": "string",
    "geo": "object (optional)",
    "active": "boolean",
    "created_at": "datetime"
  }
]
```

## Store Management

### PUT /provisioning/stores/{store_id}

**Description**: Create or update a store  
**Parameters**:

- `store_id` (path): Store identifier (string, max 100 chars)
- `site_id` (query): Site identifier (required)

**Request Body**:

```json
{
  "name": "string (required)",
  "store_type": "string (optional, default: 'cashierless')",
  "geo": {
    "lat": "number (optional)",
    "lng": "number (optional)",
    "address": "string (optional)"
  },
  "timezone": "string (optional)"
}
```

**Store Types**:

- `cashierless`: 24/7 employee access
- `vending`: Automated vending machines
- `kiosk`: Self-service units
- `traditional`: Standard retail with cashiers
- `custom`: Flexible type

**Response**:

```json
{
  "store_id": "string",
  "name": "string",
  "store_type": "string",
  "geo": "object (optional)",
  "created": true
}
```

**Example**:

```bash
curl -X PUT "http://localhost:8201/provisioning/v2/stores/store-kiosk-001?site_id=site-unmanned-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Kiosk Store",
    "store_type": "kiosk",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278,
      "address": "456 Kiosk St, London, UK"
    }
  }'
```

### GET /provisioning/stores

**Description**: List stores  
**Parameters**:

- `limit` (query): Maximum number of stores to return (default: 200)

**Response**:

```json
[
  {
    "store_id": "string",
    "name": "string",
    "active": "boolean",
    "created_at": "datetime"
  }
]
```

## User Management

### PUT /provisioning/users/{user_id}

**Description**: Create or update a user  
**Parameters**:

- `user_id` (path): User identifier (UUID)

**Request Body**:

```json
{
  "email": "string (required)",
  "display_name": "string (required)"
}
```

**Response**:

```json
{
  "user_id": "string",
  "email": "string",
  "display_name": "string",
  "created": true
}
```

## Vendor Management

### PUT /provisioning/vendors/{vendor_id}

**Description**: Create or update a vendor  
**Parameters**:

- `vendor_id` (path): Vendor identifier (UUID)

**Request Body**:

```json
{
  "tenant_id": "string (required)",
  "name": "string (required)",
  "description": "string (optional)"
}
```

**Response**:

```json
{
  "vendor_id": "string",
  "name": "string",
  "description": "string",
  "created": true
}
```

## Enhanced Error Handling

The service implements comprehensive error handling with custom exception handlers:

### HTTP Status Codes

- `200 OK`: Success
- `201 Created`: Resource created successfully
- `400 Bad Request`: Validation error (invalid request data)
- `404 Not Found`: Resource not found
- `409 Conflict`: Duplicate resource error
- `422 Unprocessable Entity`: Validation error
- `500 Internal Server Error`: Server error

### Custom Exception Types

- **ValidationError**: Invalid request data or business rule violations
- **NotFoundError**: Requested resource does not exist
- **DuplicateError**: Resource already exists (conflict)
- **ProvisioningError**: General provisioning service errors

### Error Response Format

```json
{
  "detail": "Error message description"
}
```

### Error Examples

**400 Bad Request (Validation Error)**:

```json
{
  "detail": "Tenant with name 'Test Tenant' already exists"
}
```

**404 Not Found**:

```json
{
  "detail": "Tenant 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

**409 Conflict (Duplicate Error)**:

```json
{
  "detail": "User with email 'test@example.com' already exists"
}
```

**500 Internal Server Error**:

```json
{
  "detail": "Internal provisioning error"
}
```

## Data Models

### Tenant

- `tenant_id`: String (100 chars, primary key)
- `name`: String (200 chars)
- `tenant_type`: String (50 chars, default: 'customer')

### Site

- `site_id`: String (100 chars, primary key)
- `tenant_id`: String (100 chars, foreign key)
- `name`: String (200 chars)
- `site_type`: String (50 chars, default: 'unmanned')
- `geo`: JSONB (optional)

### Store

- `store_id`: String (100 chars, primary key)
- `site_id`: String (100 chars, foreign key)
- `name`: String (200 chars)
- `store_type`: String (50 chars, default: 'cashierless')
- `geo`: JSONB (optional)

## Scenario-Specific Usage

### Large End-User Sites

- **Tenant Type**: `end_user`
- **Site Type**: `onsite`
- **Store Type**: `cashierless`
- **Features**: Budget enforcement, approval workflows, 24/7 employee access

### Retailers

- **Tenant Type**: `retailer`
- **Site Type**: `unmanned`
- **Store Type**: `kiosk` or `traditional`
- **Features**: Guest/loyalty focus, payments/analytics, public access

### Distributors

- **Tenant Type**: `distributor`
- **Site Type**: `distribution_center`
- **Store Type**: `cashierless`
- **Features**: Global views, client installs, ERP sync

## Geographic Information

The `geo` field is optional and can contain:

```json
{
  "lat": 51.5074,
  "lng": -0.1278,
  "address": "123 Main St, London, UK"
}
```

- **lat**: Latitude coordinate (number)
- **lng**: Longitude coordinate (number)
- **address**: Human-readable address (string)

## Production-Ready Features

The provisioning service has been enhanced with production-ready features:

### Repository Pattern

- Clean separation of data access logic from business logic
- Consistent CRUD operations across all entities
- Proper error handling and transaction management
- Easy testing and mocking capabilities

### Service Layer

- Business logic orchestration
- Transaction management at service level
- Validation and orchestration of multiple repository calls
- Consistent error handling

### Dependency Injection

- Proper session management with FastAPI dependencies
- Automatic session cleanup
- Connection pooling support
- Lifecycle management

### Enhanced Error Handling

- Custom exception classes for different error types
- Consistent HTTP status codes
- Structured error responses
- Proper logging and monitoring

### Transaction Management

- Automatic rollback on errors
- Proper transaction boundaries
- Concurrent access handling
- Retry logic for transient failures

### Testing Examples

**Complete Tenant Setup Flow**:

```bash
# 1. Create tenant
curl -X PUT "http://localhost:8201/provisioning/tenants/tenant-001" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Company", "type": "end_user"}'

# 2. Create site
curl -X PUT "http://localhost:8201/provisioning/sites/site-001?tenant_id=tenant-001" \
  -H "Content-Type: application/json" \
  -d '{"name": "Main Office", "site_type": "onsite"}'

# 3. Create store
curl -X PUT "http://localhost:8201/provisioning/stores/store-001?site_id=site-001" \
  -H "Content-Type: application/json" \
  -d '{"name": "Employee Store", "store_type": "cashierless"}'

# 4. Link tenant to site
curl -X PUT "http://localhost:8201/provisioning/tenant-sites" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "tenant-001", "site_id": "site-001", "role_type": "manager"}'

# 5. Link site to store
curl -X PUT "http://localhost:8201/provisioning/site-stores" \
  -H "Content-Type: application/json" \
  -d '{"site_id": "site-001", "store_id": "store-001"}'
```

**Error Handling Examples**:

```bash
# Duplicate tenant name (409 Conflict)
curl -X PUT "http://localhost:8201/provisioning/tenants/tenant-002" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Company", "type": "end_user"}'

# Invalid tenant ID (400 Bad Request)
curl -X PUT "http://localhost:8201/provisioning/sites/site-002?tenant_id=invalid-id" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Site", "site_type": "retail"}'
```
