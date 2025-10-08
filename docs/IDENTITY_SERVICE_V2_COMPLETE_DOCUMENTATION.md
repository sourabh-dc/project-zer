# ZeroQue Identity Service V2 - Complete API Documentation

## Overview

The ZeroQue Identity Service V2 is a comprehensive identity and access management system that provides user management, role-based access control (RBAC), JWT token generation, and analytics reporting. It aligns with the V4.1 architecture and supports multi-tenancy with Row Level Security (RLS).

## Architecture

### Core Components

- **User Management**: Full CRUD operations for users with metadata support
- **Role Management**: Role creation and permission management
- **Role Assignments**: Dynamic role assignment to users
- **Token Generation**: JWT tokens for guest and loyalty users
- **Analytics**: Blueprint-inspired reports for user and role analytics
- **Event System**: USER_CREATED/UPDATED events with outbox pattern
- **Saga Pattern**: UserCreationSaga with compensation logic
- **Multi-Tenancy**: RLS with tenant isolation

### Database Schema

#### Core Tables

```sql
-- Users table with tenant isolation
users_new:
- id (UUID, PK)
- tenant_id (UUID, FK to tenants)
- email (String, unique per tenant)
- name (String, optional)
- primary_cost_centre_id (UUID, FK to cost_centres_new)
- user_metadata (JSONB, optional)
- created_at, updated_at (Timestamps)

-- Roles table with permissions
roles_new:
- id (UUID, PK)
- tenant_id (UUID, FK to tenants)
- name (String, unique per tenant)
- description (String, optional)
- permissions (JSONB array of strings)
- created_at, updated_at (Timestamps)

-- Role assignments linking users to roles
role_assignments_new:
- id (UUID, PK)
- tenant_id (UUID, FK to tenants)
- user_id (UUID, FK to users_new)
- role_id (UUID, FK to roles_new)
- created_at, updated_at (Timestamps)
```

#### Supporting Tables

- **outbox_events**: Event publishing with retry logic
- **audit_logs**: Comprehensive audit trail
- **RLS Policies**: Tenant isolation on all tables

## API Endpoints

### Health & Monitoring

#### GET /health

**Purpose**: Service health check
**Response**:

```json
{
  "status": "ok",
  "service": "identity",
  "version": "4.1.0"
}
```

#### GET /readiness

**Purpose**: Service readiness check
**Response**:

```json
{
  "service": "identity",
  "version": "4.1.0",
  "db": true,
  "ready": true
}
```

#### GET /metrics

**Purpose**: Prometheus metrics
**Response**: Prometheus format metrics

### User Management

#### POST /identity/v4/users

**Purpose**: Create user with role assignments (Saga Pattern)

**Request**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe",
  "primary_cost_centre_id": "550e8400-e29b-41d4-a716-446655440001",
  "role_ids": ["550e8400-e29b-41d4-a716-446655440002"],
  "user_metadata": {
    "department": "engineering",
    "level": "senior"
  }
}
```

**Response**:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440003",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe",
  "primary_cost_centre_id": "550e8400-e29b-41d4-a716-446655440001",
  "user_metadata": {
    "department": "engineering",
    "level": "senior"
  },
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "roles": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",
      "name": "developer",
      "description": "Software developer role",
      "permissions": ["identity.view_user", "entry.issue_code"]
    }
  ]
}
```

**Saga Steps**:

1. Validate tenant exists
2. Create user record
3. Assign roles
4. Publish USER_CREATED event
5. Create audit log
6. Compensation: Rollback on failure

#### GET /identity/v4/users

**Purpose**: List users with optional filters

**Query Parameters**:

- `tenant_id` (required): Tenant identifier
- `email_filter` (optional): Filter by email pattern
- `role_filter` (optional): Filter by role name

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440003",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "John Doe",
    "primary_cost_centre_id": "550e8400-e29b-41d4-a716-446655440001",
    "user_metadata": {...},
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "roles": [...]
  }
]
```

### Role Management

#### POST /identity/v4/roles

**Purpose**: Create role with permissions

**Request**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "developer",
  "description": "Software developer role",
  "permissions": [
    "identity.view_user",
    "entry.issue_code",
    "entry.validate_code"
  ]
}
```

**Response**:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440002",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "developer",
  "description": "Software developer role",
  "permissions": [
    "identity.view_user",
    "entry.issue_code",
    "entry.validate_code"
  ],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "user_count": 5
}
```

#### GET /identity/v4/roles

**Purpose**: List roles for tenant

**Query Parameters**:

- `tenant_id` (required): Tenant identifier

**Response**:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "developer",
    "description": "Software developer role",
    "permissions": [...],
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "user_count": 5
  }
]
```

### Role Assignments

#### POST /identity/v4/role-assignments

**Purpose**: Assign role to user

**Request**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440003",
  "role_id": "550e8400-e29b-41d4-a716-446655440002"
}
```

**Response**:

```json
{
  "ok": true,
  "message": "Role assigned successfully"
}
```

### Token Generation

#### POST /identity/v4/token

**Purpose**: Generate JWT tokens (unified guest/loyalty)

**Guest Token Request**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "token_type": "guest",
  "guest_info": {
    "device_id": "device-123",
    "ip_address": "192.168.1.1"
  }
}
```

**Guest Token Response**:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "guest",
  "expires_at": "2024-01-16T10:30:00Z",
  "user_id": null,
  "permissions": ["guest.access"]
}
```

**Loyalty Token Request**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "token_type": "loyalty",
  "user_id": "550e8400-e29b-41d4-a716-446655440003"
}
```

**Loyalty Token Response**:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "loyalty",
  "expires_at": "2024-01-15T11:30:00Z",
  "user_id": "550e8400-e29b-41d4-a716-446655440003",
  "permissions": [
    "identity.view_user",
    "entry.issue_code",
    "entry.validate_code"
  ]
}
```

### Analytics & Reports

#### GET /identity/v4/reports

**Purpose**: Generate identity analytics reports

**Query Parameters**:

- `tenant_id` (required): Tenant identifier
- `report_type` (required): Report type
- `period_start` (optional): ISO date string
- `period_end` (optional): ISO date string

**Report Types**:

##### Active Users Report

```
GET /identity/v4/reports?tenant_id=...&report_type=active_users
```

**Response**:

```json
{
  "report_type": "active_users",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "generated_at": "2024-01-15T10:30:00Z",
  "period": null,
  "summary": {
    "total_users": 150,
    "new_users_30d": 25,
    "active_users_7d": 120
  },
  "data": []
}
```

##### Role Counts Report

```
GET /identity/v4/reports?tenant_id=...&report_type=role_counts
```

**Response**:

```json
{
  "report_type": "role_counts",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "generated_at": "2024-01-15T10:30:00Z",
  "period": null,
  "summary": {
    "total_roles": 8,
    "total_assignments": 150
  },
  "data": [
    {
      "role_name": "developer",
      "description": "Software developer role",
      "user_count": 45,
      "permissions": ["identity.view_user", "entry.issue_code"]
    },
    {
      "role_name": "admin",
      "description": "Administrator role",
      "user_count": 5,
      "permissions": ["identity.admin", "identity.view_reports"]
    }
  ]
}
```

### Legacy Endpoints (Deprecated)

#### POST /guest-token

**Purpose**: Legacy guest token generation
**Status**: Deprecated - redirects to `/identity/v4/token`

#### POST /loyalty-token

**Purpose**: Legacy loyalty token generation
**Status**: Deprecated - redirects to `/identity/v4/token`

## Event System

### Events Published

#### USER_CREATED

**Trigger**: User creation via saga
**Data**:

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440003",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe",
  "roles": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",
      "name": "developer",
      "permissions": ["identity.view_user", "entry.issue_code"]
    }
  ],
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Event Handlers

#### USER_CREATED → Entry Service

- **Endpoint**: `/entry/v4/integration/provisioning/user-created`
- **Purpose**: Sync user to entry providers (AiFi, internal)
- **Action**: Create user in external systems

#### USER_CREATED → Provisioning Service

- **Endpoint**: `/provisioning/v2/integration/identity/user-created`
- **Purpose**: Sync user to provisioning systems
- **Action**: Create user accounts in external systems

## Security & Permissions

### Authentication

- JWT Bearer token authentication
- Token validation and user context extraction
- Permission-based access control

### Permissions

#### Identity Permissions

- `identity.create_user`: Create new users
- `identity.view_user`: View user information
- `identity.update_user`: Update user information
- `identity.delete_user`: Delete users
- `identity.create_role`: Create roles
- `identity.view_role`: View role information
- `identity.admin`: Full administrative access
- `identity.generate_token`: Generate JWT tokens
- `identity.view_reports`: Access analytics reports

#### Cross-Service Permissions

- `entry.issue_code`: Issue entry codes
- `entry.validate_code`: Validate entry codes
- `entry.view_status`: View entry code status

### Row Level Security (RLS)

- All tables have RLS policies
- Tenant isolation enforced at database level
- Context setting via `app.tenant_id` and `app.user_id`

## Integration Points

### Service Dependencies

#### Provisioning Service

- **USER_CREATED** → Sync user to external systems
- **Role changes** → Update user permissions

#### Entry Service

- **USER_CREATED** → Sync user to entry providers
- **Token validation** → Verify user permissions for entry codes

#### Orders Service

- **Token validation** → Authenticate order creation
- **User context** → Apply user-specific pricing/budgeting

#### Notifications Service

- **USER_CREATED** → Send welcome emails
- **Role assignments** → Notify users of permission changes

### External Systems

#### AiFi Integration

- User sync on creation
- Role-based access control
- Token-based authentication

## Performance & Monitoring

### Metrics

#### Prometheus Metrics

- `identity_requests_total`: Total API requests by endpoint and status
- `identity_request_duration_seconds`: Request duration histogram
- `identity_tokens_generated_total`: Tokens generated by type and tenant
- `identity_saga_duration_seconds`: Saga execution duration
- `identity_saga_failures_total`: Saga failures by type and reason

#### Logging

- Structured logging with `structlog`
- JSON format for production
- Request/response logging
- Error tracking and correlation

### Performance Characteristics

- **User Creation**: ~200ms (including saga steps)
- **Token Generation**: ~50ms
- **Role Assignment**: ~100ms
- **Report Generation**: ~500ms (depending on data size)

## Error Handling

### HTTP Status Codes

- `200`: Success
- `400`: Bad Request (validation errors)
- `401`: Unauthorized (invalid token)
- `403`: Forbidden (insufficient permissions)
- `404`: Not Found (resource doesn't exist)
- `500`: Internal Server Error

### Error Response Format

```json
{
  "detail": "Error message description",
  "error_code": "VALIDATION_ERROR",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Saga Compensation

- Automatic rollback on failure
- Step-by-step compensation
- Audit logging of compensation actions

## Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `JWT_SECRET`: JWT signing secret
- `JWT_ALGORITHM`: JWT algorithm (default: HS256)
- `JWT_EXPIRY_MINUTES`: JWT expiry time (default: 60)
- `GUEST_TOKEN_TTL_HOURS`: Guest token TTL (default: 24)

### Database Configuration

- Async SQLAlchemy with asyncpg
- Connection pooling
- RLS policies enabled
- Indexes on tenant_id, email, and foreign keys

## Testing

### Test Coverage

- Unit tests for all endpoints
- Integration tests for saga workflows
- Performance tests for metrics collection
- Error handling tests
- Legacy endpoint compatibility tests

### Test Scenarios

1. **User Management**: Create, list, filter users
2. **Role Management**: Create, assign, list roles
3. **Token Generation**: Guest and loyalty tokens
4. **Reports**: Analytics and user counts
5. **Error Handling**: Validation and permission errors
6. **Performance**: Metrics and response times

## Deployment

### Docker Configuration

- Multi-stage build
- Python 3.13 base image
- Health check endpoints
- Environment-based configuration

### Production Considerations

- Database connection pooling
- JWT secret rotation
- RLS policy management
- Event retry mechanisms
- Monitoring and alerting

## Future Enhancements

### Planned Features

1. **OAuth2/OpenID Connect**: External identity provider integration
2. **Multi-Factor Authentication**: 2FA/MFA support
3. **Advanced Analytics**: User behavior tracking
4. **API Rate Limiting**: Per-user and per-tenant limits
5. **Audit Trail**: Enhanced audit logging with search
6. **User Self-Service**: Password reset, profile management

### Integration Roadmap

1. **SSO Integration**: SAML, OAuth2 providers
2. **Directory Services**: LDAP/Active Directory sync
3. **Advanced RBAC**: Hierarchical roles and permissions
4. **Compliance**: GDPR, SOC2 compliance features
5. **Multi-Region**: Cross-region user synchronization

---

**Version**: 4.1.0  
**Last Updated**: January 2024  
**Maintainer**: ZeroQue Platform Team
