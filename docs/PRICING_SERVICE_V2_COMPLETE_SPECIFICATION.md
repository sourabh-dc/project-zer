# Pricing Service API Specification

## Overview

The Pricing Service manages pricebooks, pricing rules, price calculations, and price resolution in the Zeroque V2 multi-tenant marketplace architecture. It implements sophisticated pricing logic with caching and versioning.

**Base URL:** `http://localhost:8209`  
**Version:** 2.0.0  
**Service:** pricing

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
  "service": "pricing",
  "version": "2.0.0",
  "enhanced": true
}
```

### Price Resolution

#### POST /pricing/v2/resolve

**Description:** Resolve price for a product offer

**Request Body:**

```json
{
  "store_id": "string",
  "offer_id": "string",
  "user_id": "string",
  "site_id": "string|null",
  "tenant_id": "string|null",
  "currency": "string",
  "quantity": 0
}
```

**Response:**

```json
{
  "offer_id": "string",
  "unit_price_minor": 0,
  "total_price_minor": 0,
  "currency": "string",
  "price_source": "pricebook|rule|promotion",
  "applied_rules": [],
  "applied_promotions": [],
  "cache_hit": true,
  "calculated_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Pricebook Management

#### GET /pricing/v2/pricebooks

**Description:** List all pricebooks

**Response:**

```json
[
  {
    "pricebook_id": "string",
    "name": "string",
    "pricebook_type": "standard|promotional|seasonal",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/pricebooks

**Description:** Create a new pricebook

**Request Body:**

```json
{
  "name": "string",
  "pricebook_type": "standard|promotional|seasonal",
  "active": true
}
```

**Response:**

```json
{
  "pricebook_id": "string",
  "name": "string",
  "pricebook_type": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### PUT /pricing/v2/pricebooks/{pricebook_id}

**Description:** Update an existing pricebook

**Path Parameters:**

- `pricebook_id` (string): The pricebook ID

**Request Body:**

```json
{
  "name": "string",
  "pricebook_type": "standard|promotional|seasonal",
  "active": true
}
```

**Response:**

```json
{
  "pricebook_id": "string",
  "name": "string",
  "pricebook_type": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00",
  "updated_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### GET /pricing/v2/pricebooks/{pricebook_id}

**Description:** Get pricebook details

**Path Parameters:**

- `pricebook_id` (string): The pricebook ID

**Response:**

```json
{
  "pricebook_id": "string",
  "name": "string",
  "pricebook_type": "string",
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00",
  "updated_at": "2025-10-01T05:21:19.093243+00:00"
}
```

### Pricebook Assignment Management

#### GET /pricing/v2/pricebook-assignments

**Description:** List all pricebook assignments

**Response:**

```json
[
  {
    "assignment_id": "string",
    "pricebook_id": "string",
    "target_type": "store|site|tenant|user",
    "target_id": "string",
    "priority": 0,
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/pricebook-assignments

**Description:** Create a new pricebook assignment

**Request Body:**

```json
{
  "pricebook_id": "string",
  "target_type": "store|site|tenant|user",
  "target_id": "string",
  "priority": 0,
  "active": true
}
```

**Response:**

```json
{
  "assignment_id": "string",
  "pricebook_id": "string",
  "target_type": "string",
  "target_id": "string",
  "priority": 0,
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### PUT /pricing/v2/pricebook-assignments/{assignment_id}

**Description:** Update an existing pricebook assignment

**Path Parameters:**

- `assignment_id` (string): The assignment ID

**Request Body:**

```json
{
  "pricebook_id": "string",
  "target_type": "store|site|tenant|user",
  "target_id": "string",
  "priority": 0,
  "active": true
}
```

### Pricebook Entry Management

#### GET /pricing/v2/pricebook-entries

**Description:** List all pricebook entries

**Response:**

```json
[
  {
    "entry_id": "string",
    "pricebook_id": "string",
    "offer_id": "string",
    "price_minor": 0,
    "min_quantity": 0,
    "max_quantity": 0,
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/pricebook-entries

**Description:** Create a new pricebook entry

**Request Body:**

```json
{
  "pricebook_id": "string",
  "offer_id": "string",
  "price_minor": 0,
  "min_quantity": 0,
  "max_quantity": 0,
  "active": true
}
```

**Response:**

```json
{
  "entry_id": "string",
  "pricebook_id": "string",
  "offer_id": "string",
  "price_minor": 0,
  "min_quantity": 0,
  "max_quantity": 0,
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### PUT /pricing/v2/pricebook-entries/{entry_id}

**Description:** Update an existing pricebook entry

**Path Parameters:**

- `entry_id` (string): The entry ID

**Request Body:**

```json
{
  "pricebook_id": "string",
  "offer_id": "string",
  "price_minor": 0,
  "min_quantity": 0,
  "max_quantity": 0,
  "active": true
}
```

### Price Rule Management

#### GET /pricing/v2/price-rules

**Description:** List all price rules

**Response:**

```json
[
  {
    "rule_id": "string",
    "name": "string",
    "rule_type": "percentage|fixed|tiered",
    "value_minor": 0,
    "conditions": {},
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/price-rules

**Description:** Create a new price rule

**Request Body:**

```json
{
  "name": "string",
  "rule_type": "percentage|fixed|tiered",
  "value_minor": 0,
  "conditions": {},
  "active": true
}
```

**Response:**

```json
{
  "rule_id": "string",
  "name": "string",
  "rule_type": "string",
  "value_minor": 0,
  "conditions": {},
  "active": true,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### PUT /pricing/v2/price-rules/{rule_id}

**Description:** Update an existing price rule

**Path Parameters:**

- `rule_id` (string): The rule ID

**Request Body:**

```json
{
  "name": "string",
  "rule_type": "percentage|fixed|tiered",
  "value_minor": 0,
  "conditions": {},
  "active": true
}
```

### Calculated Prices Management

#### GET /pricing/v2/calculated-prices

**Description:** List calculated prices (cached prices)

**Query Parameters:**

- `store_id` (string, optional): Filter by store ID
- `offer_id` (string, optional): Filter by offer ID
- `limit` (integer, optional): Number of records to return (default: 10)

**Response:**

```json
[
  {
    "sku": "string",
    "store_id": "string",
    "user_id": "string|null",
    "price_minor": 0,
    "currency": "string",
    "price_source": "string",
    "applied_rules": [],
    "applied_promotions": [],
    "calculated_at": "2025-10-01T05:21:19.093243+00:00",
    "expires_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

### Price Hook Management

#### GET /pricing/v2/price-hooks

**Description:** List all price hooks

**Response:**

```json
[
  {
    "hook_id": "string",
    "name": "string",
    "hook_type": "pre_calculation|post_calculation",
    "config": {},
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/price-hooks

**Description:** Create a new price hook

**Request Body:**

```json
{
  "name": "string",
  "hook_type": "pre_calculation|post_calculation",
  "config": {},
  "active": true
}
```

### Rule Condition Management

#### GET /pricing/v2/rule-conditions

**Description:** List all rule conditions

**Response:**

```json
[
  {
    "condition_id": "string",
    "rule_id": "string",
    "condition_type": "quantity|user_type|time",
    "operator": "eq|gt|lt|gte|lte",
    "value": "string",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/rule-conditions

**Description:** Create a new rule condition

**Request Body:**

```json
{
  "rule_id": "string",
  "condition_type": "quantity|user_type|time",
  "operator": "eq|gt|lt|gte|lte",
  "value": "string",
  "active": true
}
```

### Pricing Version Management

#### GET /pricing/v2/versions

**Description:** List pricing versions

**Response:**

```json
[
  {
    "version_id": "string",
    "version_number": 0,
    "description": "string",
    "active": true,
    "created_at": "2025-10-01T05:21:19.093243+00:00"
  }
]
```

#### POST /pricing/v2/versions

**Description:** Create a new pricing version

**Request Body:**

```json
{
  "version_number": 0,
  "description": "string",
  "active": true
}
```

### Saga Endpoints

#### POST /pricing/v2/sagas/pricebook

**Description:** Execute pricebook creation saga

**Request Body:**

```json
{
  "name": "string",
  "pricebook_type": "standard|promotional|seasonal",
  "active": true
}
```

**Response:**

```json
{
  "saga_id": "string",
  "status": "completed|failed",
  "pricebook_id": "string",
  "steps_completed": 0,
  "total_steps": 0,
  "created_at": "2025-10-01T05:21:19.093243+00:00"
}
```

#### POST /pricing/v2/sagas/pricebook-assignment

**Description:** Execute pricebook assignment saga

**Request Body:**

```json
{
  "pricebook_id": "string",
  "target_type": "store|site|tenant|user",
  "target_id": "string",
  "priority": 0,
  "active": true
}
```

#### POST /pricing/v2/sagas/pricebook-entry

**Description:** Execute pricebook entry saga

**Request Body:**

```json
{
  "pricebook_id": "string",
  "offer_id": "string",
  "price_minor": 0,
  "min_quantity": 0,
  "max_quantity": 0,
  "active": true
}
```

### Legacy Endpoints (Deprecated)

#### GET /pricing/store-products/{store_id}

**Description:** Legacy endpoint for store products (deprecated)

**Response:**

```json
{
  "products": [],
  "deprecated": true,
  "message": "This endpoint is deprecated. Use /pricing/v2/resolve instead."
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

### Pricebook

```json
{
  "pricebook_id": "string (UUID)",
  "name": "string",
  "pricebook_type": "standard|promotional|seasonal",
  "active": "boolean",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)|null"
}
```

### Pricebook Assignment

```json
{
  "assignment_id": "string (UUID)",
  "pricebook_id": "string (UUID)",
  "target_type": "store|site|tenant|user",
  "target_id": "string (UUID)",
  "priority": "integer",
  "active": "boolean",
  "created_at": "string (ISO 8601)"
}
```

### Pricebook Entry

```json
{
  "entry_id": "string (UUID)",
  "pricebook_id": "string (UUID)",
  "offer_id": "string (UUID)",
  "price_minor": "integer",
  "min_quantity": "integer",
  "max_quantity": "integer",
  "active": "boolean",
  "created_at": "string (ISO 8601)"
}
```

### Price Rule

```json
{
  "rule_id": "string (UUID)",
  "name": "string",
  "rule_type": "percentage|fixed|tiered",
  "value_minor": "integer",
  "conditions": "object",
  "active": "boolean",
  "created_at": "string (ISO 8601)"
}
```

### Calculated Price

```json
{
  "sku": "string",
  "store_id": "string (UUID)",
  "user_id": "string (UUID)|null",
  "price_minor": "integer",
  "currency": "string",
  "price_source": "string",
  "applied_rules": "array",
  "applied_promotions": "array",
  "calculated_at": "string (ISO 8601)",
  "expires_at": "string (ISO 8601)"
}
```

## Price Resolution Logic

The pricing service implements sophisticated price resolution with the following priority:

1. **Pricebook Entries** - Direct pricing from assigned pricebooks
2. **Price Rules** - Dynamic pricing based on conditions
3. **Promotions** - Special promotional pricing
4. **Exchange Rates** - Currency conversion for multi-currency support
5. **Price Hooks** - Custom pricing logic via hooks

### Price Resolution Flow

1. Check cached calculated prices
2. Resolve from pricebooks (by priority)
3. Apply price rules (if conditions match)
4. Apply promotions
5. Apply exchange rate conversion
6. Execute price hooks
7. Cache the result

## Saga Orchestration

The Pricing Service implements sagas for complex pricing operations:

### Pricebook Saga Steps

1. **validate_pricebook** - Validate pricebook data
2. **create_pricebook** - Create pricebook record
3. **notify_pricebook_created** - Publish event
4. **invalidate_cache** - Clear related cache

### Pricebook Assignment Saga Steps

1. **validate_assignment** - Validate assignment data
2. **create_assignment** - Create assignment record
3. **notify_assignment_created** - Publish event
4. **invalidate_cache** - Clear related cache

### Pricebook Entry Saga Steps

1. **validate_entry** - Validate entry data
2. **create_entry** - Create entry record
3. **notify_entry_created** - Publish event
4. **invalidate_entry_cache** - Clear related cache

## Service Integration

The Pricing Service integrates with:

- **Catalog Service**: Product and offer information
- **Inventory Service**: Stock levels for pricing rules
- **Exchange Rate Service**: Currency conversion
- **Observability Service**: Health monitoring and metrics
- **Service Bus**: Event publishing and consumption
- **Database**: PostgreSQL with RLS policies
- **Redis**: Price caching and event streaming

## Features

- **Multi-tenant Architecture**: Full tenant isolation with RLS
- **Advanced Price Resolution**: Sophisticated pricing logic with multiple sources
- **Price Caching**: High-performance price caching with TTL
- **Price Versioning**: Version control for pricing changes
- **Exchange Rate Support**: Multi-currency pricing with real-time conversion
- **Price Hooks**: Extensible pricing logic via hooks
- **Rule Conditions**: Complex conditional pricing rules
- **Saga Pattern**: Distributed transaction management for pricing operations
- **Circuit Breaker**: Resilient external service calls
- **Event Sourcing**: Event-driven architecture with comprehensive event handling
- **Metrics & Logging**: OpenTelemetry integration with Prometheus metrics
- **Time-sortable UUIDs**: Uses uuid7 for better performance
- **Timezone Support**: Full timezone-aware timestamps
- **Legacy Support**: Backward compatibility with deprecation warnings

## Event Types

The service publishes and consumes the following events:

- `PRICEBOOK_CREATED` - Pricebook successfully created
- `PRICEBOOK_UPDATED` - Pricebook updated
- `PRICEBOOK_ASSIGNMENT_CREATED` - Pricebook assignment created
- `PRICEBOOK_ENTRY_CREATED` - Pricebook entry created
- `PRICE_RULE_CREATED` - Price rule created
- `PRICE_CALCULATED` - Price calculation completed
- `PRICE_CACHE_INVALIDATED` - Price cache cleared
- `VERSION_CHANGED` - Pricing version updated

