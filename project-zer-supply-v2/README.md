# Project Zer Supply V2

Supply V2 is an order-driven procurement platform for dropship and B2B fulfilment.

## What it does

- Accepts customer orders.
- Splits one order into vendor-specific purchase orders.
- Notifies vendors by email.
- Lets vendors react with acceptance or disputes.
- Tracks shipment and goods receipt.
- Resolves vendor and customer disputes.
- Runs 3-way invoice matching.
- Enforces RBAC and policy decisions.
- Emits domain events and outbox events.

## Main components

- `src/supply_v2/routes/`
  - FastAPI endpoints for vendor, order, procurement, fulfilment, dispute, invoice, and ops.
- `src/supply_v2/services/`
  - Core business logic.
- `src/supply_v2/policy.py`
  - Policy enforcement and local evaluator.
- `src/supply_v2/rbac.py`
  - Roles, permissions, and permission checks.
- `src/supply_v2/workers/`
  - Notification, SLA, maintenance, and scheduler workers.
- `policy_engine/`
  - OPA Rego policies and sidecar Dockerfile.
- `docs/`
  - Architecture, disputes, execution status, and business diagrams.

## Run locally

```bash
docker compose up -d
python3 -m alembic -c alembic.ini upgrade head
python3 -m pytest -q
PYTHONPATH=src python3 scripts/smoke_all_endpoints.py
```

## OpenAPI

- Combined app Swagger: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON export script: `scripts/export_openapi.py`

## Business docs

- `docs/dispute-flow.md`
- `docs/pending-vs-plan.md`
- `docs/supply-v2-architecture.drawio`
- `docs/supply-v2-order-po-flow.drawio`
- `docs/supply-v2-dispute-auth-flow.drawio`

## Related repos

- `project-zer-supply-v2`
  - this procurement service
- `project-zer-new`
  - policy engine reference
- `project-zer-prov_policy`
  - RBAC and tenant functional flow reference

## Live Azure helper scripts

- `scripts/azure_live_checks.py`
- `scripts/azure_servicebus_send.py`
- `scripts/azure_email_send.py`
- `scripts/entra_token_check.py`
- `scripts/build_docs_site.py`
