# Approvals Service V2 - Complete Documentation

## Overview

The Approvals Service V2 is a comprehensive workflow management system for handling approval processes in the ZeroQue platform. It implements a sophisticated chain-based approval system with multi-step workflows, role-based permissions, and event-driven integration.

## Service Information

- **Name**: ZeroQue Approvals Service V2
- **Version**: 2.0.0
- **Port**: 8084 (configurable)
- **Base URL**: `http://localhost:8084`
- **Environment**: Production-ready with comprehensive monitoring

## Architecture Features

### V2 Architecture Compliance

- ✅ **Multi-tenant Architecture** - Complete tenant isolation with RLS
- ✅ **Event-Driven Integration** - Reliable event publishing with outbox pattern
- ✅ **Saga Pattern** - Transactional workflow management with compensation
- ✅ **Row Level Security** - Database-level tenant isolation
- ✅ **Comprehensive Audit Trails** - Complete operation tracking
- ✅ **Prometheus Metrics** - Production-grade observability
- ✅ **JWT Authentication** - Enterprise-grade security
- ✅ **Redis Caching** - High-performance data caching

### Core Components

#### 1. **Approval Chains**

Workflow templates that define the approval process structure:

- **Chain Types**: Budget, Purchase, Access, Custom
- **Multi-step Workflows**: Sequential and parallel approval steps
- **Role-based Assignment**: Dynamic approver assignment
- **Escalation Rules**: Automatic escalation after timeouts

#### 2. **Approval Requests**

Individual approval requests that follow chain workflows:

- **Request Types**: Budget overspend, Purchase orders, Access requests
- **Multi-currency Support**: GBP, USD, EUR with minor unit precision
- **Due Date Management**: Configurable deadlines and escalations
- **Status Tracking**: Pending, In Progress, Approved, Denied, Expired

#### 3. **Approval Workflow Engine**

Sophisticated workflow management:

- **Saga Pattern**: Reliable request processing with compensation
- **Event Publishing**: Reliable APPROVAL_RESOLVED events
- **Audit Integration**: Complete operation tracking

## Database Schema

### Core Tables

```sql
-- Approval chain templates
approval_chains (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    chain_type VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
)

-- Approval chain steps
approval_chain_steps (
    id UUID PRIMARY KEY,
    chain_id UUID REFERENCES approval_chains(id),
    step_order INTEGER NOT NULL,
    step_type VARCHAR(50) NOT NULL,  -- sequential, parallel
    approver_role VARCHAR(100),
    approver_user_id UUID,
    timeout_hours INTEGER DEFAULT 24,
    escalation_role VARCHAR(100),
    is_required BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
)

-- Individual approval requests
approval_requests_new (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    chain_id UUID REFERENCES approval_chains(id),
    request_type VARCHAR(50) NOT NULL,
    requester_id UUID NOT NULL,
    amount_minor BIGINT,
    currency VARCHAR(3),
    cost_centre_id UUID,
    site_id UUID,
    store_id UUID,
    description TEXT,
    metadata JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER,
    due_date TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
)

-- Approver responses and workflow tracking
approval_request_approvers (
    id UUID PRIMARY KEY,
    request_id UUID REFERENCES approval_requests_new(id),
    step_order INTEGER NOT NULL,
    approver_id UUID NOT NULL,
    approver_role VARCHAR(100),
    response VARCHAR(20),  -- pending, approved, denied
    response_date TIMESTAMP WITH TIME ZONE,
    comments TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
)

-- Reliable event publishing
outbox_events (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
)

-- Audit trail
audit_logs (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(255),
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
)
```

## API Endpoints

### Health & Monitoring

#### GET /health

**Description**: Service health check
**Response**:

```json
{
  "status": "ok",
  "service": "approvals_v2",
  "version": "2.0.0",
  "dependencies": {
    "database": "connected",
    "redis": "connected"
  }
}
```

#### GET /metrics

**Description**: Prometheus metrics for monitoring
**Response**: Prometheus-formatted metrics including:

- `approvals_requests_total` - Request counters by method/endpoint/status
- `approvals_request_duration_seconds` - Request duration histograms
- `approvals_workflows_total` - Workflow execution counters
- `approvals_saga_duration_seconds` - Saga execution duration
- `approvals_saga_failures_total` - Saga failure counters

### Chain Management

#### POST /approvals/v2/chains

**Description**: Create approval chain
**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "chain_type": "budget",
  "name": "Budget Overspend Approval",
  "description": "Approval chain for budget overspend requests",
  "is_active": true
}
```

**Response**:

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "chain_type": "budget",
  "name": "Budget Overspend Approval",
  "description": "Approval chain for budget overspend requests",
  "is_active": true,
  "created_at": "2025-10-07T20:30:00Z"
}
```

#### GET /approvals/v2/chains

**Description**: List approval chains with filtering
**Query Parameters**:

- `tenant_id` (required): Tenant ID
- `chain_type` (optional): Filter by chain type
- `is_active` (optional): Filter by active status
- `limit` (optional): Limit results (default: 50, max: 1000)
- `offset` (optional): Offset for pagination (default: 0)

**Response**:

```json
{
  "items": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
      "chain_type": "budget",
      "name": "Budget Overspend Approval",
      "description": "Approval chain for budget overspend requests",
      "is_active": true,
      "created_at": "2025-10-07T20:30:00Z",
      "updated_at": null
    }
  ],
  "total_count": 5,
  "offset": 0,
  "limit": 50,
  "has_more": false
}
```

#### POST /approvals/v2/chains/{chain_id}/steps

**Description**: Add step to approval chain
**Request Body**:

```json
{
  "step_order": 1,
  "step_type": "sequential",
  "approver_role": "manager",
  "timeout_hours": 24,
  "escalation_role": "director",
  "is_required": true
}
```

**Response**:

```json
{
  "id": "456e7890-e89b-12d3-a456-426614174001",
  "chain_id": "123e4567-e89b-12d3-a456-426614174000",
  "step_order": 1,
  "step_type": "sequential",
  "approver_role": "manager",
  "timeout_hours": 24,
  "escalation_role": "director",
  "is_required": true,
  "created_at": "2025-10-07T20:30:00Z"
}
```

#### GET /approvals/v2/chains/{chain_id}/steps

**Description**: List chain steps
**Response**:

```json
[
  {
    "id": "456e7890-e89b-12d3-a456-426614174001",
    "chain_id": "123e4567-e89b-12d3-a456-426614174000",
    "step_order": 1,
    "step_type": "sequential",
    "approver_role": "manager",
    "timeout_hours": 24,
    "escalation_role": "director",
    "is_required": true,
    "created_at": "2025-10-07T20:30:00Z"
  }
]
```

### Request Management

#### POST /approvals/v2/requests

**Description**: Create approval request
**Request Body**:

```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "chain_id": "123e4567-e89b-12d3-a456-426614174000",
  "request_type": "budget_overspend",
  "requester_id": "user123",
  "amount_minor": 50000,
  "currency": "GBP",
  "cost_centre_id": "cc123",
  "site_id": "site456",
  "store_id": "store789",
  "description": "Budget overspend for Q4 marketing campaign",
  "metadata": {
    "campaign_id": "camp123",
    "department": "marketing"
  }
}
```

**Response**:

```json
{
  "id": "789e0123-e89b-12d3-a456-426614174002",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "chain_id": "123e4567-e89b-12d3-a456-426614174000",
  "request_type": "budget_overspend",
  "requester_id": "user123",
  "amount_minor": 50000,
  "currency": "GBP",
  "status": "pending",
  "current_step": 0,
  "total_steps": 2,
  "due_date": "2025-10-08T20:30:00Z",
  "created_at": "2025-10-07T20:30:00Z"
}
```

#### GET /approvals/v2/requests

**Description**: List approval requests with filtering
**Query Parameters**:

- `tenant_id` (required): Tenant ID
- `status` (optional): Filter by status
- `request_type` (optional): Filter by request type
- `requester_id` (optional): Filter by requester
- `cost_centre_id` (optional): Filter by cost centre
- `limit` (optional): Limit results (default: 50, max: 1000)
- `offset` (optional): Offset for pagination (default: 0)

**Response**:

```json
{
  "items": [
    {
      "id": "789e0123-e89b-12d3-a456-426614174002",
      "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
      "chain_id": "123e4567-e89b-12d3-a456-426614174000",
      "request_type": "budget_overspend",
      "requester_id": "user123",
      "amount_minor": 50000,
      "currency": "GBP",
      "status": "pending",
      "current_step": 0,
      "total_steps": 2,
      "due_date": "2025-10-08T20:30:00Z",
      "created_at": "2025-10-07T20:30:00Z"
    }
  ],
  "total_count": 25,
  "offset": 0,
  "limit": 50,
  "has_more": true
}
```

#### GET /approvals/v2/requests/{request_id}

**Description**: Get approval request details
**Response**:

```json
{
  "id": "789e0123-e89b-12d3-a456-426614174002",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "chain_id": "123e4567-e89b-12d3-a456-426614174000",
  "request_type": "budget_overspend",
  "requester_id": "user123",
  "amount_minor": 50000,
  "currency": "GBP",
  "cost_centre_id": "cc123",
  "site_id": "site456",
  "store_id": "store789",
  "description": "Budget overspend for Q4 marketing campaign",
  "metadata": {
    "campaign_id": "camp123",
    "department": "marketing"
  },
  "status": "pending",
  "current_step": 0,
  "total_steps": 2,
  "due_date": "2025-10-08T20:30:00Z",
  "created_at": "2025-10-07T20:30:00Z",
  "updated_at": null
}
```

#### GET /approvals/v2/requests/{request_id}/approvers

**Description**: Get request approvers and their responses
**Response**:

```json
[
  {
    "id": "approver123",
    "request_id": "789e0123-e89b-12d3-a456-426614174002",
    "step_order": 1,
    "approver_id": "manager456",
    "approver_role": "manager",
    "response": "pending",
    "response_date": null,
    "comments": null,
    "created_at": "2025-10-07T20:30:00Z"
  }
]
```

### Workflow Management

#### POST /approvals/v2/requests/{request_id}/respond

**Description**: Enhanced workflow response (approve/deny)
**Request Body**:

```json
{
  "approver_id": "manager456",
  "response": "approved",
  "comments": "Approved for Q4 marketing campaign",
  "metadata": {
    "approval_notes": "Budget is within acceptable limits"
  }
}
```

**Response**:

```json
{
  "ok": true,
  "request_id": "789e0123-e89b-12d3-a456-426614174002",
  "new_status": "approved",
  "next_step": null,
  "workflow_completed": true,
  "message": "Request approved successfully"
}
```

#### POST /approvals/v2/requests/{request_id}/approve

**Description**: Legacy approve endpoint (deprecated)
**Request Body**:

```json
{
  "approved": true,
  "approver_id": "manager456",
  "comments": "Approved"
}
```

**Response**:

```json
{
  "deprecated": true,
  "migrate_to": "/approvals/v2/requests/{request_id}/respond",
  "message": "This endpoint is deprecated. Please use /approvals/v2/requests/{request_id}/respond"
}
```

### Event Management

#### POST /approvals/v2/events/retry

**Description**: Retry failed event publishing
**Security**: `approvals.admin` permission required
**Response**:

```json
{
  "ok": true,
  "retried_events": 3,
  "failed_events": 1,
  "total_processed": 4
}
```

#### GET /approvals/v2/events/status

**Description**: Get event publishing status
**Security**: `approvals.admin` permission required
**Response**:

```json
{
  "total_events": 100,
  "pending_events": 5,
  "published_events": 90,
  "failed_events": 5,
  "success_rate": 90.0,
  "last_event_time": "2025-10-07T20:30:00Z"
}
```

### Security & Audit

#### GET /approvals/v2/security/audit-logs

**Description**: Get audit logs for approvals
**Security**: `approvals.admin` permission required
**Query Parameters**:

- `tenant_id` (required): Tenant ID
- `action` (optional): Filter by action
- `resource_type` (optional): Filter by resource type
- `limit` (optional): Limit results (default: 50)
- `offset` (optional): Offset for pagination (default: 0)

**Response**:

```json
{
  "items": [
    {
      "id": "audit123",
      "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
      "user_id": "user123",
      "action": "create_approval_request",
      "resource_type": "approval_request",
      "resource_id": "789e0123-e89b-12d3-a456-426614174002",
      "details": {
        "request_type": "budget_overspend",
        "amount_minor": 50000
      },
      "ip_address": "192.168.1.100",
      "created_at": "2025-10-07T20:30:00Z"
    }
  ],
  "total_count": 150,
  "offset": 0,
  "limit": 50,
  "has_more": true
}
```

#### GET /approvals/v2/security/user-context

**Description**: Get current user context
**Security**: `approvals.read` permission required
**Response**:

```json
{
  "user_id": "user123",
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "roles": ["manager", "approver"],
  "permissions": ["approvals.read", "approvals.approve", "approvals.create"]
}
```

#### POST /approvals/v2/security/validate-permission

**Description**: Validate user permission
**Security**: `approvals.admin` permission required
**Request Body**:

```json
{
  "user_id": "user123",
  "permission": "approvals.approve"
}
```

**Response**:

```json
{
  "has_permission": true,
  "user_id": "user123",
  "permission": "approvals.approve",
  "roles": ["manager", "approver"]
}
```

## Saga Pattern Implementation

### ApprovalWorkflowSaga

The approvals service implements a comprehensive saga pattern for reliable workflow management:

#### Saga Steps:

1. **Validate Request** - Verify request data and permissions
2. **Create Request** - Insert approval request record
3. **Assign Approvers** - Create approver assignments from chain
4. **Start Workflow** - Initialize workflow state
5. **Publish Event** - Publish APPROVAL_REQUEST_CREATED event
6. **Audit Log** - Record operation in audit trail

#### Compensation Logic:

- **Delete Request** - Remove approval request on failure
- **Cleanup Approvers** - Remove approver assignments
- **Revert Workflow** - Reset workflow state

#### Event Publishing:

- **APPROVAL_REQUEST_CREATED** - Published on request creation
- **APPROVAL_RESOLVED** - Published on workflow completion
- **Event Data**: Includes tenant_id, request_id, status, amount, currency, approvers

## Integration Patterns

### Service Integration

The approvals service integrates with other ZeroQue services through event-driven patterns:

#### Orders Service Integration

```json
{
  "event_type": "ORDER_COMPLETED",
  "event_data": {
    "tenant_id": "tenant123",
    "order_id": "order456",
    "total_amount_minor": 50000,
    "currency": "GBP",
    "cost_centre_id": "cc123"
  }
}
```

#### Billing Service Integration

```json
{
  "event_type": "INVOICE_POSTED",
  "event_data": {
    "tenant_id": "tenant123",
    "invoice_id": "inv789",
    "total_amount_minor": 75000,
    "currency": "GBP"
  }
}
```

#### Ledger Service Integration

```json
{
  "event_type": "APPROVAL_RESOLVED",
  "event_data": {
    "tenant_id": "tenant123",
    "request_id": "req101",
    "amount_minor": 100000,
    "approved": true,
    "currency": "GBP"
  }
}
```

### Event Types Published

- `APPROVAL_REQUEST_CREATED` - New approval request created
- `APPROVAL_RESOLVED` - Approval workflow completed
- Event includes: tenant_id, request_id, status, amount_minor, currency, approvers

## Security & Authentication

### JWT Authentication

All endpoints require valid JWT tokens with appropriate permissions:

```bash
Authorization: Bearer <jwt_token>
```

### Permission System

- `approvals.read` - Read approval chains and requests
- `approvals.create` - Create approval chains and requests
- `approvals.approve` - Approve/deny requests
- `approvals.admin` - Administrative operations (audit, events)

### Row Level Security (RLS)

Database-level tenant isolation ensures data security:

```sql
-- Automatic tenant filtering on all queries
SET LOCAL app.current_tenant_id = 'tenant-uuid';
```

## Performance & Monitoring

### Caching Strategy

- **Redis Caching**: High-performance caching for chains and requests
- **Query Optimization**: Optimized indexes on tenant_id, status, request_type

### Metrics & Observability

- **Request Counters**: Track API usage by endpoint and status
- **Duration Histograms**: Monitor API response times
- **Saga Metrics**: Track saga execution times and failures
- **Workflow Metrics**: Monitor workflow completion rates

### Database Optimization

- **Indexes**: Optimized indexes on tenant_id, status, request_type, approver_id
- **Connection Pooling**: Efficient database connection management
- **Redis Integration**: High-performance caching layer

## Error Handling

### Standard Error Responses

```json
{
  "detail": "Validation failed: amount_minor must be greater than 0",
  "status_code": 400
}
```

### Common Error Codes

- `400` - Bad Request (validation errors)
- `401` - Unauthorized (invalid JWT)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found (chain/request not found)
- `500` - Internal Server Error (saga failures, database errors)

## Testing & Validation

### Health Checks

```bash
curl http://localhost:8084/health
```

### Create Approval Chain

```bash
curl -X POST http://localhost:8084/approvals/v2/chains \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "chain_type": "budget",
    "name": "Budget Overspend Approval",
    "description": "Approval chain for budget overspend requests"
  }'
```

### Create Approval Request

```bash
curl -X POST http://localhost:8084/approvals/v2/requests \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "chain_id": "123e4567-e89b-12d3-a456-426614174000",
    "request_type": "budget_overspend",
    "requester_id": "user123",
    "amount_minor": 50000,
    "currency": "GBP",
    "description": "Budget overspend for Q4 marketing campaign"
  }'
```

### Approve Request

```bash
curl -X POST http://localhost:8084/approvals/v2/requests/789e0123-e89b-12d3-a456-426614174002/respond \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "approver_id": "manager456",
    "response": "approved",
    "comments": "Approved for Q4 marketing campaign"
  }'
```

## Production Deployment

### Environment Variables

```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/zeroque
REDIS_URL=redis://localhost:6379
EVENT_BUS_URL=http://localhost:8085
JWT_SECRET=your-secret-key
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8084"]
```

### Monitoring Setup

- **Prometheus**: Metrics collection
- **Grafana**: Dashboards and alerting
- **ELK Stack**: Log aggregation and analysis
- **Health Checks**: Kubernetes readiness/liveness probes

## Business Use Cases

### End User Scenarios

- **Budget Overspend**: Request approval for budget overages
- **Purchase Orders**: Approve high-value purchases
- **Access Requests**: Approve system access requests

### Manager Scenarios

- **Workflow Management**: Configure approval chains
- **Request Review**: Review and approve/deny requests
- **Escalation Handling**: Handle escalated requests

### Admin Scenarios

- **Chain Configuration**: Set up approval workflows
- **Audit Compliance**: Monitor approval activities
- **Performance Management**: Track approval metrics

## Service Statistics

- **Total Endpoints**: 17
- **V2 Endpoints**: 15 (88% V2 compliance)
- **Functions**: 5 core functions
- **Classes**: 20 (models, requests, responses)
- **Lines of Code**: ~1,841
- **Version**: 2.0.0

## Key V2 Endpoints

### Chain Management

- `POST /approvals/v2/chains` - Create approval chains
- `GET /approvals/v2/chains` - List chains with filtering
- `POST /approvals/v2/chains/{chain_id}/steps` - Add chain steps
- `GET /approvals/v2/chains/{chain_id}/steps` - List chain steps

### Request Management

- `POST /approvals/v2/requests` - Create approval requests
- `GET /approvals/v2/requests` - List requests with filtering
- `GET /approvals/v2/requests/{request_id}` - Get request details
- `GET /approvals/v2/requests/{request_id}/approvers` - Get approvers

### Workflow Management

- `POST /approvals/v2/requests/{request_id}/approve` - Approve/deny (legacy)
- `POST /approvals/v2/requests/{request_id}/respond` - Enhanced workflow response

### Event Management

- `POST /approvals/v2/events/retry` - Retry failed events
- `GET /approvals/v2/events/status` - Event publishing status

### Security & Audit

- `GET /approvals/v2/security/audit-logs` - Audit trail access
- `GET /approvals/v2/security/user-context` - User context info
- `POST /approvals/v2/security/validate-permission` - Permission validation

### Monitoring

- `GET /health` - Comprehensive health check
- `GET /metrics` - Prometheus metrics

## Conclusion

The Approvals Service V2 provides a robust, production-ready solution for workflow management in the ZeroQue platform. With its sophisticated chain-based approval system, event-driven architecture, and enterprise-grade security, it enables comprehensive approval management across all business scenarios.

Key strengths:

- **Chain-based Workflows**: Flexible approval chain configuration
- **Event-Driven Integration**: Seamless integration with Orders, Billing, and Ledger services
- **Enterprise Security**: JWT authentication, RLS, and comprehensive audit trails
- **High Performance**: Redis caching and optimized database queries
- **Reliable Processing**: Saga pattern with compensation logic
- **Production Monitoring**: Comprehensive metrics and health checks
- **Multi-tenant Architecture**: Complete tenant isolation and security
- **Workflow Engine**: Sophisticated multi-step approval processing

The service is ready for production deployment and integration with other V2 services in the ZeroQue platform! 🎉
