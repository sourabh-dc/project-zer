# ZeroQue Provisioning Service V2 - Complete API Specification

## 🎯 Overview

The ZeroQue Provisioning Service V2 provides comprehensive multi-tenant marketplace architecture with scenario-specific tenant, site, and store management. The service has been enhanced with repository patterns, service layers, dependency injection, and production-ready features.

## 📋 Service Information

- **Service Name**: provisioning
- **Version**: 2.0.0
- **Base URL**: `http://localhost:8201` (development)
- **Architecture**: Multi-tenant marketplace with scenario-specific types
- **Status**: ✅ Production Ready

## 🏗️ Architecture Features

### Enhanced Implementation

- **Repository Pattern**: Clean separation of data access logic from business logic
- **Service Layer**: Business logic orchestration and transaction management
- **Dependency Injection**: Proper session management with FastAPI dependencies
- **Enhanced Error Handling**: Custom exception handlers with proper HTTP status codes
- **Production-Ready**: Transaction management, rollback mechanisms, and consistent error handling

### Communication Patterns

- **Service Bus Integration**: Event-driven communication between services
- **Circuit Breaker**: Resilience and fault tolerance
- **Saga Pattern**: Distributed transaction management
- **Event Sourcing**: Complete audit trails and event history
- **Health Monitoring**: Comprehensive system health checks

## 🏢 Tenant Types

The system supports the following tenant types:

- `end_user`: End users with budgets and approvals
- `retailer`: Retailers with guest access and loyalty programs
- `distributor`: Distributors with control tower and global catalog
- `custom`: Custom configuration for special use cases

## 🏭 Site Types

The system supports the following site types:

- `onsite`: End users with budgets (M:N tenant_sites)
- `unmanned`: Retailer public guest access
- `distributor_centre`: Distributor client installs with ERP sync

## 🏪 Store Types

The system supports the following store types:

- `unmanned_onsite`: Budgets and approvals for end users
- `unmanned_public`: Guest access and loyalty for retailers
- `unmanned_distributed`: Global catalog for distributors

## 📊 Complete API Endpoints (30+ Endpoints)

### Health & Monitoring (4 Endpoints)

#### 1. Health Check

```http
GET /health
```

**Response:**

```json
{
  "status": "ok",
  "service": "provisioning",
  "version": "2.0.0",
  "enhanced": true,
  "timestamp": "2024-01-01T00:00:00Z",
  "components": {
    "database": "healthy",
    "service_bus": "healthy",
    "circuit_breaker": "closed"
  }
}
```

#### 2. Readiness Check

```http
GET /readiness
```

**Response:**

```json
{
  "service": "provisioning",
  "db": true,
  "redis": true
}
```

#### 3. System Health

```http
GET /provisioning/system/health
```

#### 4. Circuit Breaker Status

```http
GET /provisioning/circuit-breakers
```

### Tenant Management (3 Endpoints)

#### 5. Create Tenant

```http
POST /provisioning/tenants
```

**Request Body:**

```json
{
  "name": "Acme Corporation",
  "type": "end_user",
  "scenario_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Acme Corporation",
  "type": "end_user",
  "created": true,
  "saga_id": "tenant_provision_1696248000"
}
```

#### 6. Create/Update Tenant

```http
PUT /provisioning/tenants/{tenant_id}
```

**Parameters:**

- `tenant_id` (path): Tenant identifier (UUID)

**Request Body:**

```json
{
  "name": "string (required)",
  "type": "string (optional, default: 'customer') - end_user, retailer, distributor, custom",
  "scenario_id": "string (optional)"
}
```

#### 7. List Tenants

```http
GET /provisioning/tenants?limit=100
```

**Response:**

```json
[
  {
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Acme Corporation",
    "type": "end_user",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### Site Management (3 Endpoints)

#### 8. Create/Update Site

```http
PUT /provisioning/sites/{site_id}?tenant_id={tenant_id}
```

**Parameters:**

- `site_id` (path): Site identifier (UUID)
- `tenant_id` (query): Tenant identifier (UUID, required)

**Request Body:**

```json
{
  "name": "Main Campus",
  "site_type": "onsite",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278,
    "address": "123 Main St, London, UK"
  }
}
```

**Response:**

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

#### 9. List Sites

```http
GET /provisioning/sites?limit=200
```

**Response:**

```json
[
  {
    "site_id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Main Campus",
    "site_type": "onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278
    },
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

#### 10. Tenant-Site Linking

```http
PUT /provisioning/tenant-sites
```

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "site_id": "550e8400-e29b-41d4-a716-446655440002",
  "role_type": "manager"
}
```

### Store Management (3 Endpoints)

#### 11. Create/Update Store

```http
PUT /provisioning/stores/{store_id}?site_id={site_id}
```

**Parameters:**

- `store_id` (path): Store identifier (UUID)
- `site_id` (query): Site identifier (UUID, required)

**Request Body:**

```json
{
  "name": "ToolRoom",
  "store_type": "unmanned_onsite",
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278,
    "address": "456 Store St, London, UK"
  },
  "timezone": "Europe/London"
}
```

**Response:**

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

#### 12. List Stores

```http
GET /provisioning/stores?limit=200
```

**Response:**

```json
[
  {
    "store_id": "550e8400-e29b-41d4-a716-446655440003",
    "name": "ToolRoom",
    "store_type": "unmanned_onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278
    },
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

#### 13. Site-Store Linking

```http
PUT /provisioning/site-stores
```

**Request Body:**

```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440002",
  "store_id": "550e8400-e29b-41d4-a716-446655440003"
}
```

### User Management (2 Endpoints)

#### 14. Create/Update User

```http
PUT /provisioning/users/{user_id}
```

**Parameters:**

- `user_id` (path): User identifier (UUID)

**Request Body:**

```json
{
  "email": "user@example.com",
  "display_name": "John Doe"
}
```

**Response:**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440004",
  "email": "user@example.com",
  "display_name": "John Doe",
  "created": true
}
```

#### 15. List Users

```http
GET /provisioning/users?limit=200
```

**Response:**

```json
[
  {
    "user_id": "550e8400-e29b-41d4-a716-446655440004",
    "email": "user@example.com",
    "display_name": "John Doe",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### Role Management (3 Endpoints)

#### 16. Create/Update Role

```http
PUT /provisioning/roles/{role_id}
```

**Parameters:**

- `role_id` (path): Role identifier (UUID)

**Request Body:**

```json
{
  "name": "Store Manager",
  "description": "Manages store operations",
  "permissions": ["read", "write", "approve"]
}
```

#### 17. Assign Role to User

```http
PUT /provisioning/role-assignments
```

**Request Body:**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440004",
  "role_id": "550e8400-e29b-41d4-a716-446655440005",
  "scope_type": "store",
  "scope_id": "550e8400-e29b-41d4-a716-446655440003",
  "active": true
}
```

#### 18. List Role Assignments

```http
GET /provisioning/role-assignments?user_id={user_id}&limit=200
```

### Vendor Management (3 Endpoints)

#### 19. Create/Update Vendor

```http
PUT /provisioning/vendors/{vendor_id}
```

**Parameters:**

- `vendor_id` (path): Vendor identifier (UUID)

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Vendor Corp",
  "description": "Technology supplier",
  "rating": 4.5
}
```

**Response:**

```json
{
  "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Vendor Corp",
  "created": true
}
```

#### 20. List Vendors

```http
GET /provisioning/vendors?tenant_id={tenant_id}&limit=200
```

**Response:**

```json
[
  {
    "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Vendor Corp",
    "description": "Technology supplier",
    "rating": 4.5,
    "active": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

#### 21. Store-Vendor Linking

```http
PUT /provisioning/store-vendors
```

**Request Body:**

```json
{
  "store_id": "550e8400-e29b-41d4-a716-446655440003",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
  "active": true
}
```

### Tenant Linking (1 Endpoint)

#### 22. Create Tenant Link

```http
PUT /provisioning/tenant-links
```

**Request Body:**

```json
{
  "parent_tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "child_tenant_id": "550e8400-e29b-41d4-a716-446655440006",
  "link_type": "subsidiary",
  "active": true
}
```

### ERP Integration (2 Endpoints)

#### 23. Create/Update ERP Integration

```http
PUT /provisioning/erp-integrations/{integration_id}
```

**Parameters:**

- `integration_id` (path): Integration identifier (UUID)

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
  "type": "ERP",
  "config": {
    "api_key": "your-api-key",
    "endpoint": "https://erp.example.com/api"
  }
}
```

**Response:**

```json
{
  "integration_id": "550e8400-e29b-41d4-a716-446655440007",
  "created": true
}
```

#### 24. List ERP Integrations

```http
GET /provisioning/erp-integrations?tenant_id={tenant_id}&limit=200
```

**Response:**

```json
[
  {
    "integration_id": "550e8400-e29b-41d4-a716-446655440007",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
    "vendor_id": "550e8400-e29b-41d4-a716-446655440005",
    "type": "ERP",
    "config": {
      "api_key": "your-api-key",
      "endpoint": "https://erp.example.com/api"
    },
    "active": true,
    "last_sync_at": null,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### Access Control Management (3 Endpoints)

#### 25. Create/Update Access Control

```http
PUT /provisioning/access-controls/{control_id}
```

**Parameters:**

- `control_id` (path): Control identifier (UUID)

**Request Body:**

```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440002",
  "store_id": "550e8400-e29b-41d4-a716-446655440003",
  "type": "gate",
  "config": {
    "device_id": "gate_001",
    "settings": {
      "auto_open": true,
      "timeout": 30
    }
  }
}
```

#### 26. List Access Controls

```http
GET /provisioning/access-controls?site_id={site_id}&store_id={store_id}&limit=200
```

**Response:**

```json
[
  {
    "control_id": "550e8400-e29b-41d4-a716-446655440008",
    "site_id": "550e8400-e29b-41d4-a716-446655440002",
    "store_id": "550e8400-e29b-41d4-a716-446655440003",
    "type": "gate",
    "config": {
      "device_id": "gate_001",
      "settings": {
        "auto_open": true,
        "timeout": 30
      }
    },
    "active": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

#### 27. Create User Access Grant

```http
PUT /provisioning/user-access-grants
```

**Request Body:**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440004",
  "access_control_id": "550e8400-e29b-41d4-a716-446655440008",
  "grant_type": "permanent",
  "valid_until": null
}
```

#### 28. List User Access Grants

```http
GET /provisioning/user-access-grants?user_id={user_id}&limit=200
```

### Scenario Management (2 Endpoints)

#### 29. Create/Update Scenario

```http
PUT /provisioning/scenarios/{scenario_id}
```

**Parameters:**

- `scenario_id` (path): Scenario identifier (UUID)

**Request Body:**

```json
{
  "code": "test_scenario",
  "name": "Test Scenario",
  "config": {
    "feature": "test",
    "settings": {
      "enabled": true
    }
  }
}
```

#### 30. List Scenarios

```http
GET /provisioning/scenarios?limit=200
```

### ZeroQue Rails (1 Endpoint)

#### 31. Create/Update ZeroQue Rail

```http
PUT /provisioning/zeroque-rails/{rail_id}
```

**Parameters:**

- `rail_id` (path): Rail identifier (UUID)

**Request Body:**

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
  "rail_type": "payment",
  "config": {
    "provider": "stripe",
    "settings": {
      "webhook_secret": "whsec_123"
    }
  }
}
```

### Event & Monitoring (4 Endpoints)

#### 32. Get Saga Status

```http
GET /provisioning/sagas/{saga_id}
```

#### 33. Get Entity Events

```http
GET /provisioning/events/{entity_id}?limit=100
```

#### 34. Get Event Metrics

```http
GET /provisioning/events/metrics
```

#### 35. Get Services

```http
GET /provisioning/services
```

## ⚠️ Error Handling

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

**400 Bad Request (Validation Error):**

```json
{
  "detail": "Tenant with name 'Test Tenant' already exists"
}
```

**404 Not Found:**

```json
{
  "detail": "Tenant 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

**409 Conflict (Duplicate Error):**

```json
{
  "detail": "User with email 'test@example.com' already exists"
}
```

## 🗄️ Data Models

### Core Models

#### Tenant

- `tenant_id`: UUID (primary key)
- `name`: String (200 chars)
- `type`: String (50 chars, default: 'customer') - end_user, retailer, distributor, custom
- `scenario_id`: UUID (optional)
- `active`: Boolean (default: true)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### Site

- `site_id`: UUID (primary key)
- `name`: String (200 chars)
- `site_type`: String (50 chars, default: 'unmanned') - onsite, unmanned, distributor_centre
- `geo`: JSONB (optional)
- `active`: Boolean (default: true)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### Store

- `store_id`: UUID (primary key)
- `site_id`: UUID (foreign key)
- `name`: String (200 chars)
- `store_type`: String (50 chars, default: 'cashierless') - unmanned_onsite, unmanned_public, unmanned_distributed
- `geo`: JSONB (optional)
- `timezone`: String (optional)
- `active`: Boolean (default: true)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### User

- `user_id`: UUID (primary key)
- `email`: String (unique)
- `display_name`: String (200 chars)
- `active`: Boolean (default: true)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### Vendor

- `vendor_id`: UUID (primary key)
- `tenant_id`: UUID (foreign key)
- `name`: String (200 chars)
- `description`: Text (optional)
- `rating`: Numeric (3,2) (optional)
- `active`: Boolean (default: true)
- `created_at`: Timestamp
- `updated_at`: Timestamp

## 🌍 Geographic Information

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

## 🏭 Scenario-Specific Usage

### Large End-User Sites

- **Tenant Type**: `end_user`
- **Site Type**: `onsite`
- **Store Type**: `unmanned_onsite`
- **Features**: Budget enforcement, approval workflows, 24/7 employee access

### Retailers

- **Tenant Type**: `retailer`
- **Site Type**: `unmanned`
- **Store Type**: `unmanned_public`
- **Features**: Guest/loyalty focus, payments/analytics, public access

### Distributors

- **Tenant Type**: `distributor`
- **Site Type**: `distributor_centre`
- **Store Type**: `unmanned_distributed`
- **Features**: Global views, client installs, ERP sync

## 🚀 Production-Ready Features

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

## 🧪 Complete Test Suite

### Sample Test Data Setup

```bash
# Core entities
TENANT_ID="550e8400-e29b-41d4-a716-446655440001"
SITE_ID="550e8400-e29b-41d4-a716-446655440002"
STORE_ID="550e8400-e29b-41d4-a716-446655440003"
USER_ID="550e8400-e29b-41d4-a716-446655440004"
VENDOR_ID="550e8400-e29b-41d4-a716-446655440005"
```

### Test Flow (Recommended Sequence)

1. **Health Checks** - Verify service is running
2. **Tenant Creation** - Create tenant with scenario
3. **Site Creation** - Create site linked to tenant
4. **Store Creation** - Create store linked to site
5. **User Creation** - Create users for access
6. **Role Assignment** - Assign roles to users
7. **Vendor Management** - Create and link vendors
8. **Access Control** - Set up access controls
9. **ERP Integration** - Configure ERP connections
10. **Monitoring** - Check system health

### Sample Test Commands

```bash
# 1. Health Check
curl -X GET "http://localhost:8201/health" | jq

# 2. Create Tenant
curl -X PUT "http://localhost:8201/provisioning/tenants/$TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Company",
    "type": "end_user"
  }' | jq

# 3. Create Site
curl -X PUT "http://localhost:8201/provisioning/sites/$SITE_ID?tenant_id=$TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Main Office",
    "site_type": "onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278,
      "address": "123 Main St, London, UK"
    }
  }' | jq

# 4. Create Store
curl -X PUT "http://localhost:8201/provisioning/stores/$STORE_ID?site_id=$SITE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Employee Store",
    "store_type": "unmanned_onsite",
    "geo": {
      "lat": 51.5074,
      "lng": -0.1278,
      "address": "456 Store St, London, UK"
    }
  }' | jq

# 5. Link Tenant to Site
curl -X PUT "http://localhost:8201/provisioning/tenant-sites" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "site_id": "'$SITE_ID'",
    "role_type": "manager"
  }' | jq

# 6. Link Site to Store
curl -X PUT "http://localhost:8201/provisioning/site-stores" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": "'$SITE_ID'",
    "store_id": "'$STORE_ID'"
  }' | jq

# 7. System Health Check
curl -X GET "http://localhost:8201/provisioning/system/health" | jq
```

### Error Handling Examples

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

## 📈 Performance Characteristics

### Optimization Features

- **Repository pattern** for optimized data access
- **Connection pooling** for database performance
- **Async processing** for event handling
- **Circuit breaker** patterns for resilience
- **Bulk operations** support for high throughput

### Scalability Features

- **Multi-tenant architecture** for horizontal scaling
- **Event-driven decoupling** for service independence
- **Database sharding** ready with tenant isolation
- **Microservice patterns** for independent scaling

## 🛡️ Security Implementation

### Multi-Tenant Security

- **Tenant isolation** with complete data separation
- **Role-based access controls** with scoped permissions
- **User-based access controls** with permission validation
- **Site-level and store-level scoping** for operations

### Data Protection

- **Input validation** with comprehensive business rules
- **SQL injection prevention** with parameterized queries
- **XSS protection** with input sanitization
- **Audit trails** for all operations
- **Data encryption** support for sensitive data

## 📊 Monitoring & Observability

### Health Monitoring

- **Component-level health checks** with detailed status
- **Performance metrics** tracking with real-time data
- **Error tracking** with comprehensive logging
- **Integration tests** for service connectivity
- **Circuit breaker monitoring** for resilience

### Event Management

- **Complete event sourcing** with full audit trails
- **Saga pattern monitoring** for distributed transactions
- **Event metrics** for performance analysis
- **Service registry** for service discovery
- **Health monitoring** for system-wide health

## 🎯 Current Status

### ✅ Production Ready

The provisioning service is now **fully production-ready** with:

- ✅ **Complete V2 architecture** with all required models
- ✅ **30+ API endpoints** with full functionality
- ✅ **Enhanced error handling** with custom exceptions
- ✅ **Repository and service patterns** for clean architecture
- ✅ **Event-driven communication** with saga patterns
- ✅ **Comprehensive monitoring** with health checks
- ✅ **Production-ready features** with transaction management

### ✅ Ready for Integration

The service is ready for:

- ✅ **Production deployment** with full confidence
- ✅ **Integration with other services** using event-driven patterns
- ✅ **Client application integration** with comprehensive APIs
- ✅ **Performance testing** with optimized operations
- ✅ **Load testing** with scalable architecture

## 🆘 Support

For issues or questions, refer to the ZeroQue documentation or contact the development team.

---

**Status: ✅ COMPLETE AND PRODUCTION READY** 🚀
