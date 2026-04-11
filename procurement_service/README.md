# Procurement Service (Rebuilt)

This folder contains a rebuilt procurement service following the structure/style of provisioning_service while implementing the procurement domain from project-zer-supply-v2 docs.

## Structure

- main.py: FastAPI app entrypoint (provisioning-style wiring)
- Models.py: Domain dataclasses
- Schemas.py: Pydantic request schemas
- core/config.py: Central settings (pydantic-settings style)
- core/db_config.py: DB session setup pattern aligned with provisioning service
- core/user_auth.py: Header/JWT auth + permission gate
- core/policy_client.py: Policy dependency gate
- core/procurement_engine.py: Core in-memory procurement domain engine
- core/runtime.py: Singleton runtime container + idempotency helpers
- services/: Domain routers (vendors/orders/procurement/fulfilment/disputes/invoices/ops)
- utils/logger.py: Shared logger

## API Surface

- POST /vendors
- GET /vendors/{vendor_id}/purchase-orders
- GET /vendors/{vendor_id}/shipments
- GET /vendors/{vendor_id}/disputes
- POST /orders
- GET /orders/{order_id}
- POST /orders/{order_id}/receipts
- POST /orders/{order_id}/finalize
- GET /purchase-orders/{po_id}
- POST /purchase-orders/{po_id}/acknowledge
- POST /purchase-orders/{po_id}/vendor-disputes
- POST /orders/{order_id}/cancel-line
- POST /orders/{order_id}/reallocate-line
- POST /purchase-orders/{po_id}/shipments
- GET /disputes/{dispute_id}
- POST /disputes/{dispute_id}/resolve
- POST /purchase-orders/{po_id}/invoices
- GET /purchase-orders/{po_id}/slas
- POST /ops/run-notifications
- POST /ops/run-slas
- GET /ops/dead-letters
- POST /ops/dead-letters/{dead_letter_id}/replay
- GET /ops/audit-events
- GET /ops/rbac/roles
- GET /ops/rbac/permissions
- POST /ops/rbac/assign-role
- POST /internal/maintenance/run

## Run

From repository root:

```bash
uvicorn procurement_service.main:app --reload --port 8011
```

## Config

Environment variables are managed in core/config.py and mirror provisioning_service style:

- DATABASE_URL
- PORT
- LOG_LEVEL
- AUTH_MODE
- JWT_ISSUER
- JWT_AUDIENCE
- JWT_ALGORITHM
- JWT_SECRET
- POLICY_MODE
- INTERNAL_API_KEY
- CORS_ALLOW_ORIGINS
