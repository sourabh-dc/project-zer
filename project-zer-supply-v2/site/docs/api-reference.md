# API Reference Guide

## Core business endpoints

- `POST /vendors`
- `GET /vendors/{vendor_id}/purchase-orders`
- `GET /vendors/{vendor_id}/shipments`
- `GET /vendors/{vendor_id}/disputes`
- `POST /orders`
- `GET /orders/{order_id}`
- `POST /orders/{order_id}/receipts`
- `POST /orders/{order_id}/finalize`
- `GET /purchase-orders/{po_id}`
- `POST /purchase-orders/{po_id}/acknowledge`
- `POST /purchase-orders/{po_id}/shipments`
- `POST /purchase-orders/{po_id}/invoices`
- `GET /purchase-orders/{po_id}/slas`
- `GET /disputes/{dispute_id}`
- `POST /disputes/{dispute_id}/resolve`

## Operational endpoints

- `POST /orders/{order_id}/cancel-line`
- `POST /orders/{order_id}/reallocate-line`
- `POST /ops/run-notifications`
- `POST /ops/run-slas`
- `GET /ops/dead-letters`
- `POST /ops/dead-letters/{dead_letter_id}/replay`
- `GET /ops/audit-events`
- `GET /ops/rbac/roles`
- `GET /ops/rbac/permissions`
- `POST /ops/rbac/assign-role`
- `POST /internal/maintenance/run`

## Platform endpoints

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /events`
- `GET /docs`
- `GET /redoc`
