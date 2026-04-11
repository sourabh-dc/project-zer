# Code Guide

## Entry points

- `src/supply_v2/api.py`
  - Combined API app.
- `src/supply_v2/apps/*_server.py`
  - Service-specific apps.
- `src/supply_v2/run.py`
  - Runtime selector for combined or split app targets.

## Domain services

- `order_service.py`
  - Customer order creation and order status refresh.
- `procurement_service.py`
  - Order splitting, PO generation, vendor acknowledgement, cancellation, reallocation.
- `fulfilment_service.py`
  - Shipment creation and goods receipt.
- `dispute_service.py`
  - Vendor and customer disputes plus resolution.
- `invoice_service.py`
  - 3-way invoice matching.
- `sla_service.py`
  - SLA creation and breach evaluation.
- `notification_service.py`
  - Vendor notification and outbox event generation.

## Security layers

### Authentication

- `src/supply_v2/auth.py`
  - Header mode for local work.
  - JWT mode for Azure Entra.
  - Internal API key mode for service-to-service endpoints.

### RBAC

- `src/supply_v2/rbac.py`
  - Role and permission tables.
  - Default roles and permissions.
  - Permission resolution from claims and DB.

### Policy engine

- `src/supply_v2/policy.py`
  - Local evaluator for dev and tests.
  - OPA sidecar HTTP call for deployed mode.

## Persistence

- `src/supply_v2/db.py`
  - SQLAlchemy tables and state hydration.
- `src/supply_v2/persistent.py`
  - Persistent platform wrapper.

## Workers

- `outbox_worker.py`
  - Outbox to broker to email pipeline.
- `sla_worker.py`
  - SLA breach processing.
- `maintenance_worker.py`
  - Runs both notifications and SLA processing.
- `scheduler_worker_main.py`
  - Looping scheduler process.

## Useful scripts

- `scripts/smoke_all_endpoints.py`
  - Full endpoint smoke test.
- `scripts/export_openapi.py`
  - OpenAPI export.
- `scripts/load_test.py`
  - Concurrent load test.
