# Orders Service API Specification

## Overview

The Orders Service manages order creation, processing, fulfillment, and lifecycle management in the Zeroque V2 multi-tenant marketplace architecture. It implements comprehensive saga patterns for distributed transaction management.

**Base URL:** `http://localhost:8203`  
**Version:** 2.0.0  
**Service:** orders

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
  "service": "orders",
  "version": "2.0.0",
  "enhanced": true
}
```

### Order Management

#### GET /orders/v2

**Description:** List orders for a tenant

**Query Parameters:**

- `tenant_id` (string, required): The tenant ID
- `limit` (integer, optional): Number of orders to return (default: 5)

**Response:**

```json
[
  {
    "order_id": "string",
    "order_number": "string",
    "tenant_id": "string",
    "site_id": "string|null",
    "store_id": "string",
    "customer_id": "string",
    "total_minor": 0,
    "currency": "string",
    "status": "created|pending|completed|cancelled",
    "payment_method": "string",
    "payment_status": "string|null",
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /orders/v2

**Description:** Create a new order using V2 architecture with saga orchestration

**Request Body:**

```json
{
  "tenant_id": "string",
  "site_id": "string|null",
  "store_id": "string",
  "customer_id": "string",
  "currency": "string",
  "items": [
    {
      "offer_id": "string",
      "quantity": 0,
      "unit_price_minor": 0,
      "total_minor": 0
    }
  ],
  "payment_method": "string",
  "idempotency_key": "string|null"
}
```

**Response:**

```json
{
  "order_id": "string",
  "order_number": "string",
  "status": "created|pending|completed",
  "total_minor": 0,
  "currency": "string",
  "saga_id": "string",
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### GET /orders/v2/{order_id}

**Description:** Get order details

**Path Parameters:**

- `order_id` (string): The order ID

**Response:**

```json
{
  "order_id": "string",
  "order_number": "string",
  "tenant_id": "string",
  "site_id": "string|null",
  "store_id": "string",
  "customer_id": "string",
  "total_minor": 0,
  "currency": "string",
  "status": "string",
  "payment_method": "string",
  "payment_status": "string|null",
  "created_at": "2025-10-01T05:21:19.093243+00:00",
  "updated_at": "2025-10-01T05:21:19.093243+00:00|null"
}
```

### Sub-Order Management

#### GET /orders/v2/{order_id}/sub-orders

**Description:** Get sub-orders for an order

**Path Parameters:**

- `order_id` (string): The order ID

**Response:**

```json
[
  {
    "sub_order_id": "string",
    "order_id": "string",
    "vendor_id": "string",
    "sub_order_number": "string",
    "status": "string",
    "total_amount_minor": 0,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

### Order Item Management

#### GET /orders/v2/{order_id}/items

**Description:** Get order items for an order

**Path Parameters:**

- `order_id` (string): The order ID

**Response:**

```json
[
  {
    "item_id": "string",
    "order_id": "string",
    "sub_order_id": "string",
    "offer_id": "string",
    "quantity": 0,
    "unit_price_minor": 0,
    "total_price_minor": 0,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

### Returns Management

#### POST /orders/v2/returns

**Description:** Create a return for an order

**Request Body:**

```json
{
  "order_id": "string",
  "reason": "string",
  "items": [
    {
      "item_id": "string",
      "quantity": 0,
      "reason": "string"
    }
  ]
}
```

**Response:**

```json
{
  "return_id": "string",
  "order_id": "string",
  "status": "pending|approved|rejected",
  "reason": "string",
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Refunds Management

#### POST /orders/v2/refunds

**Description:** Create a refund for an order

**Request Body:**

```json
{
  "order_id": "string",
  "amount_minor": 0,
  "reason": "string",
  "refund_method": "string"
}
```

**Response:**

```json
{
  "refund_id": "string",
  "order_id": "string",
  "amount_minor": 0,
  "status": "pending|processed|failed",
  "reason": "string",
  "refund_method": "string",
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Legacy Endpoints (Deprecated)

#### GET /orders

**Description:** Legacy endpoint for listing orders (deprecated)

**Response:**

```json
{
  "orders": [],
  "deprecated": true,
  "message": "This endpoint is deprecated. Use /orders/v2 instead."
}
```

#### POST /orders

**Description:** Legacy endpoint for creating orders (deprecated)

**Response:**

```json
{
  "deprecated": true,
  "message": "This endpoint is deprecated. Use /orders/v2 instead."
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

### Order

```json
{
  "order_id": "string (UUID)",
  "order_number": "string",
  "tenant_id": "string",
  "site_id": "string (UUID)|null",
  "store_id": "string (UUID)",
  "customer_id": "string (UUID)",
  "total_minor": "integer",
  "currency": "string",
  "status": "created|pending|completed|cancelled",
  "payment_method": "string",
  "payment_status": "string|null",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

### Order Item

```json
{
  "item_id": "string (UUID)",
  "order_id": "string (UUID)",
  "sub_order_id": "string (UUID)",
  "offer_id": "string (UUID)",
  "quantity": "integer",
  "unit_price_minor": "integer",
  "total_price_minor": "integer",
  "created_at": "string (ISO 8601)"
}
```

### Sub Order

```json
{
  "sub_order_id": "string (UUID)",
  "order_id": "string (UUID)",
  "vendor_id": "string (UUID)",
  "sub_order_number": "string",
  "status": "pending|completed|cancelled",
  "total_amount_minor": "integer",
  "created_at": "string (ISO 8601)"
}
```

### Return

```json
{
  "return_id": "string (UUID)",
  "order_id": "string (UUID)",
  "status": "pending|approved|rejected",
  "reason": "string",
  "created_at": "string (ISO 8601)"
}
```

### Refund

```json
{
  "refund_id": "string (UUID)",
  "order_id": "string (UUID)",
  "amount_minor": "integer",
  "status": "pending|processed|failed",
  "reason": "string",
  "refund_method": "string",
  "created_at": "string (ISO 8601)"
}
```

## Saga Orchestration

The Orders Service implements a comprehensive saga pattern for order processing:

### Order Saga Steps

1. **validate_inventory** - Validate inventory availability
2. **validate_budget** - Check budget and approval requirements
3. **calculate_pricing** - Calculate pricing via Pricing service
4. **reserve_inventory** - Reserve inventory with TTL
5. **process_payment** - Process payment via Payments service
6. **create_order** - Create order record with sub-orders
7. **commit_inventory** - Commit inventory reservations
8. **complete_order** - Mark order as completed
9. **send_notification** - Send order confirmation

### Compensation Logic

Each saga step includes compensation logic for rollback scenarios:

- **compensate_inventory** - Release inventory reservations
- **compensate_pricing** - Revert pricing calculations
- **refund_payment** - Process payment refunds
- **delete_order_record** - Remove order records

## Service Integration

The Orders Service integrates with:

- **Pricing Service**: Price calculation and resolution
- **Inventory Service**: Inventory validation and reservation
- **Payments Service**: Payment processing and refunds
- **Observability Service**: Health monitoring and metrics
- **Service Bus**: Event publishing and consumption
- **Database**: PostgreSQL with RLS policies
- **Redis**: Event streaming and caching

## Features

- **Saga Pattern**: Comprehensive distributed transaction management
- **Multi-tenant Architecture**: Full tenant isolation with RLS
- **Vendor Management**: Automatic sub-order creation per vendor
- **Inventory Integration**: Real-time inventory validation and reservation
- **Payment Processing**: Support for multiple payment methods
- **Circuit Breaker**: Resilient external service calls
- **Event Sourcing**: Event-driven architecture with comprehensive event handling
- **Metrics & Logging**: OpenTelemetry integration with Prometheus metrics
- **Time-sortable UUIDs**: Uses uuid7 for better performance
- **Timezone Support**: Full timezone-aware timestamps
- **Idempotency**: Support for idempotency keys to prevent duplicate orders
- **Legacy Support**: Backward compatibility with deprecation warnings

## Event Types

The service publishes and consumes the following events:

- `ORDER_CREATED` - Order successfully created
- `ORDER_UPDATED` - Order status or details updated
- `ORDER_COMPLETED` - Order processing completed
- `ORDER_CANCELLED` - Order cancelled
- `INVENTORY_UPDATED` - Inventory changes affecting orders
- `PRICE_CALCULATED` - Price calculation completed
- `PAYMENT_PROCESSED` - Payment processing completed

