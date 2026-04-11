# Project Zer Supply V2: Complete Rebuild Blueprint

## 1. Purpose and Product Scope

Supply V2 is a multi-tenant procurement orchestration service for order-driven dropship and B2B workflows. It accepts customer orders, splits them into vendor-specific purchase orders (POs), manages vendor acknowledgment/disputes, handles shipment and receipt, performs 3-way invoice matching, and exposes operations APIs for replay/maintenance.

Primary user planes:
- Customer plane: place orders, record receipts
- Vendor plane: view assigned PO/shipment/dispute data, acknowledge PO, create shipment, submit invoices
- Ops plane: resolve disputes, reallocate/cancel lines, run maintenance jobs, replay dead letters, inspect RBAC/audit
- Internal plane: trigger maintenance with internal key

Key non-functional concerns:
- Tenant isolation
- RBAC + policy enforcement on every business endpoint
- Idempotency on key POST endpoints
- Outbox pattern for notifications
- Optional split deployment by app target

## 2. Repository and Runtime Layout

Top-level implementation roots:
- src/supply_v2: core application code
- alembic: schema migrations
- tests: behavior tests (API, persistence, worker, domain flow)
- scripts: smoke/load/openapi/Azure helper scripts
- policy_engine: Rego policy files and OPA config
- deploy: deployment templates

Main runtime entrypoints:
- src/supply_v2/api.py
- src/supply_v2/apps/factory.py
- src/supply_v2/run.py

`SUPPLY_V2_APP_TARGET` decides combined vs split app launch:
- combined -> supply_v2.api:app
- order -> supply_v2.apps.order_server:app
- procurement -> supply_v2.apps.procurement_server:app
- vendor -> supply_v2.apps.vendor_server:app
- fulfilment -> supply_v2.apps.fulfilment_server:app
- dispute -> supply_v2.apps.dispute_server:app
- invoice -> supply_v2.apps.invoice_server:app
- ops -> supply_v2.apps.ops_server:app

## 3. Core Architecture

### 3.1 Layered Design

Layer 1: HTTP APIs (FastAPI routers)
- routes/vendor_routes.py
- routes/order_routes.py
- routes/procurement_routes.py
- routes/fulfilment_routes.py
- routes/dispute_routes.py
- routes/invoice_routes.py
- routes/ops_routes.py

Layer 2: Security gates
- auth.py: AuthContext extraction (header/jwt/entra)
- rbac.py: permission resolution and role mapping
- policy.py: local/OPA policy check wrapper
- idempotency.py: X-Idempotency-Key ingestion

Layer 3: Application orchestrator
- platform.py: SupplyPlatform; composes domain services and cross-step orchestration

Layer 4: Domain services
- services/order_service.py
- services/procurement_service.py
- services/fulfilment_service.py
- services/dispute_service.py
- services/invoice_service.py
- services/notification_service.py
- services/sla_service.py

Layer 5: State model
- store.py: InMemoryStore
- models.py: dataclass entities

Layer 6: Persistence + integration adapters
- db.py: SQLAlchemy tables + hydration/dehydration
- persistent.py: PersistentPlatform wrapper
- messaging/broker.py: database/azure broker
- email_provider.py: console/azure email provider
- workers/*: async processing path

### 3.2 App Container and Concurrency

Dependency container:
- dependencies.py -> AppContainer

It contains:
- platform: SupplyPlatform (in-memory or persistent-backed)
- persistent: PersistentPlatform (optional)
- lock: threading.RLock

Route mutation pattern:
1. acquire lock
2. reload state from DB (if persistent)
3. idempotency lookup (if endpoint supports it)
4. perform business operation
5. save idempotency record (if used)
6. commit full state snapshot (if persistent)

## 4. Domain Model and Entity Semantics

All entities are dataclasses in models.py.

Master entities:
- Vendor
- CustomerOrder
- CustomerOrderLine
- VendorAllocation
- PurchaseOrder
- PurchaseOrderLine
- Notification
- OutboxEvent
- Dispute
- Shipment
- ShipmentLine
- GoodsReceipt
- GoodsReceiptLine
- Invoice
- InvoiceLine
- SLARecord
- IdempotencyRecord

### 4.1 Aggregate Relationships

Order aggregate:
- CustomerOrder has many CustomerOrderLine
- CustomerOrder has many PurchaseOrder (vendor split)
- CustomerOrder has many GoodsReceipt
- CustomerOrder has many Dispute

PO aggregate:
- PurchaseOrder has many PurchaseOrderLine
- PurchaseOrder has many Dispute
- PurchaseOrder has many Shipment
- PurchaseOrder has many Invoice

Shipment/Receipt aggregate:
- Shipment has many ShipmentLine
- GoodsReceipt has many GoodsReceiptLine (mapped from ShipmentLine)

Async aggregate:
- Notification -> OutboxEvent -> BrokerMessage -> EmailDelivery

## 5. Endpoints: Complete Inventory and Contracts

### 5.1 Platform and docs
- GET /health
- GET /ready
- GET /metrics
- GET /events
- GET /docs
- GET /redoc

### 5.2 Vendor routes
- POST /vendors
  - permission: vendors.manage
  - policy: create vendor
  - request: VendorCreate
- GET /vendors/{vendor_id}/purchase-orders
  - permission: vendors.portal.view
  - policy: read vendor
- GET /vendors/{vendor_id}/shipments
  - permission: vendors.portal.view
  - policy: read shipment
- GET /vendors/{vendor_id}/disputes
  - permission: vendors.portal.view
  - policy: read dispute

### 5.3 Order routes
- POST /orders
  - permission: orders.create
  - policy: create order
  - idempotent: yes (POST:/orders)
  - request: OrderCreate
  - effect: place order + vendor allocation + PO issue + notification outbox + SLA creation
- GET /orders/{order_id}
  - permission: orders.view
  - policy: read order
- POST /orders/{order_id}/receipts
  - permission: receipts.create
  - policy: create shipment (policy resource type is shipment)
  - idempotent: yes (POST:/orders/{order_id}/receipts)
  - request: ReceiptCreate
- POST /orders/{order_id}/finalize
  - permission: orders.finalize
  - policy: update order

### 5.4 Procurement routes
- GET /purchase-orders/{po_id}
  - permission: purchase_orders.view
  - policy: read purchase_order
- POST /purchase-orders/{po_id}/acknowledge
  - permission: purchase_orders.acknowledge
  - policy: acknowledge purchase_order
  - request: list[AckDecisionIn]
- POST /purchase-orders/{po_id}/vendor-disputes
  - no AuthContext path; uses X-Vendor-Access-Token
  - verifies token tenant/vendor/po binding
  - request: VendorDisputeRaiseIn
  - behavior: internally calls same vendor_acknowledge pipeline
- POST /orders/{order_id}/cancel-line
  - permission: orders.cancel
  - policy: cancel order
  - request: CancelLineIn
- POST /orders/{order_id}/reallocate-line
  - permission: orders.reallocate
  - policy: reallocate order
  - request: ReallocateLineIn

### 5.5 Fulfilment routes
- POST /purchase-orders/{po_id}/shipments
  - permission: shipments.create
  - policy: create shipment
  - idempotent: yes (POST:/purchase-orders/{po_id}/shipments)
  - request: ShipmentCreate

### 5.6 Dispute routes
- GET /disputes/{dispute_id}
  - permission: disputes.view
  - policy: read dispute
- POST /disputes/{dispute_id}/resolve
  - permission: disputes.resolve
  - policy: resolve dispute
  - request: DisputeResolveIn

### 5.7 Invoice routes
- POST /purchase-orders/{po_id}/invoices
  - permission: invoices.create
  - policy: create invoice
  - idempotent: yes (POST:/purchase-orders/{po_id}/invoices)
  - request: InvoiceCreate
- GET /purchase-orders/{po_id}/slas
  - permission: slas.view
  - policy: read purchase_order

### 5.8 Ops routes
All ops endpoints require persistent backend (container.persistent exists).

- POST /ops/run-notifications
  - permission: ops.manage
  - policy: run ops
  - runs NotificationWorker
- POST /ops/run-slas
  - permission: ops.manage
  - policy: run ops
  - evaluates SLAs
- GET /ops/dead-letters
  - permission: ops.manage
  - policy: read ops
- POST /ops/dead-letters/{dead_letter_id}/replay
  - permission: ops.manage
  - policy: replay ops
- GET /ops/audit-events
  - permission: ops.manage
  - policy: read ops
- GET /ops/rbac/roles
- GET /ops/rbac/permissions
- POST /ops/rbac/assign-role
  - permission: ops.manage
  - policy: update ops
- POST /internal/maintenance/run
  - auth: X-Internal-Api-Key only
  - executes notification + sla jobs in one call

## 6. Request Schema Definitions

From schemas.py:
- VendorCreate: vendor_id, name, primary_email, channel=email_link
- OrderItemIn: vendor_id, sku, description, quantity>=1, unit_price_minor>=0
- OrderCreate: customer_id, ship_to map, items[]
- AckDecisionIn: po_line_id, accepted_quantity>=0, proposed_unit_price_minor>=0 optional, status, reason
- ShipmentLineIn: po_line_id, quantity>=1
- ShipmentCreate: tracking_number, lines[]
- ReceiptLineIn: shipment_line_id, received_quantity>=0, condition=good
- ReceiptCreate: shipment_id, lines[]
- VendorDisputeRaiseIn: po_line_id, status, accepted_quantity>=0, proposed_unit_price_minor optional, reason
- InvoiceLineIn: po_line_id, billed_quantity>=0, billed_unit_price_minor>=0
- InvoiceCreate: invoice_number, lines[]
- CancelLineIn: order_line_id, reason
- ReallocateLineIn: order_line_id, new_vendor_id, reason
- DisputeResolveIn: resolution

## 7. Security Model

### 7.1 Authentication modes

From auth.py + config.py:
- header mode (default)
  - x-tenant-id, x-user-id, x-role
- jwt mode
  - Bearer token HS256 with SUPPLY_V2_JWT_SECRET
  - audience/issuer validation
- entra mode
  - Bearer token RS256 validated via Entra discovery/JWKS
  - uses tid/tenant_id, oid/preferred_username/sub

Internal service auth:
- require_internal_service validates x-internal-api-key against SUPPLY_V2_INTERNAL_API_KEY

### 7.2 RBAC

Permissions (default):
- vendors.manage, vendors.view, vendors.portal.view
- orders.create, orders.view, orders.finalize, orders.cancel, orders.reallocate
- purchase_orders.view, purchase_orders.acknowledge
- shipments.create
- receipts.create
- disputes.view, disputes.resolve
- invoices.create
- slas.view
- ops.manage

Role mapping:
- admin, tenant_admin -> wildcard *
- ops -> broad operational set
- vendor -> portal + acknowledge + shipment + invoice + dispute view + sla view
- customer -> order create/view + receipt create

RBAC persistence tables:
- auth_roles
- auth_permissions
- auth_role_permissions
- auth_user_roles

### 7.3 Policy layer

Policy modes:
- local
- opa
- disabled

Policy dependency execution:
1. Extract route/body/path resource hints
2. Hydrate extra resource attributes from in-memory store (tenant_id, po_status, dispute_status, etc.)
3. Enforce policy decision

Local policy notable checks:
- cross_tenant_denied
- vendor_scope_denied (vendor can only access own vendor_id)
- customer_scope_denied (customer can only act on own customer_id order)
- po_terminal_state_denied on acknowledge if PO is terminal
- po_not_shippable if shipment requested before acceptable PO state
- po_not_invoiceable if invoice requested before invoiceable PO state
- dispute_already_resolved

## 8. State Machines and Workflow Logic

### 8.1 Order lifecycle

Created in allocating state, then derived by refresh_order_status:
- allocating
- fully_procured
- partially_shipped -> shipped
- partially_received -> received
- disputed or partially_disputed
- completed (all lines completed/cancelled)
- cancelled (all lines cancelled)

### 8.2 PO lifecycle

Driven by procurement + fulfilment + dispute resolution:
- issued
- accepted / accepted_with_changes / rejected
- partially_shipped / shipped
- partially_received / received
- cancelled or reallocated (line-level cascade conditions)

### 8.3 Line-level behavior

OrderLine status examples:
- placed -> allocated -> procured
- disputed (vendor/customer disputes)
- partially_shipped/shipped
- partially_received/received
- completed
- cancelled

PurchaseOrderLine status examples:
- issued
- accepted / disputed / rejected / reallocated / cancelled
- partially_shipped/shipped
- partially_received/received

### 8.4 Order to PO split flow

1. place_order creates order + order lines
2. allocate_order groups lines by vendor
3. for each vendor:
- create PurchaseOrder
- create PurchaseOrderLine per line
- queue notification + outbox event
4. create vendor ACK SLA for each created PO

### 8.5 Vendor acknowledgement/dispute flow

Input: list of AckDecisionIn per po_line

Per decision:
- accepted -> po_line accepted, order_line procured
- else -> po_line disputed, order_line disputed, vendor dispute created

PO result:
- all accepted -> accepted
- any rejected -> rejected
- else -> accepted_with_changes

### 8.6 Shipment and receipt flow

Shipment:
- create Shipment + ShipmentLine
- increment po_line shipped_quantity and order_line shipped_quantity
- set line and PO shipped/partially_shipped statuses

Receipt:
- create GoodsReceipt + GoodsReceiptLine
- increment received quantities
- if short receipt: create customer dispute
- if condition not good: create customer dispute
- else set received/partially_received statuses

### 8.7 Dispute resolution flow

Vendor disputes:
- accepted_vendor_terms:
  - apply proposed qty/price to PO line
  - set po_line accepted, order_line procured
  - if all PO lines accepted -> PO accepted
- rejected_vendor_terms:
  - po_line rejected
  - order_line disputed
  - PO rejected

Customer disputes:
- accept_customer_claim or commercial_settlement -> line completed
- customer_claim_rejected or close_as_received -> line received
- else -> line remains disputed

### 8.8 Invoice 3-way match logic

For each invoice line:
- expected_qty = accepted_qty or ordered_qty
- expected_price = accepted_unit_price_minor or unit_price_minor
- receipt_qty = po_line.received_quantity

Result matrix:
- exact qty+price and receipt covers billed qty -> matched
- billed qty > received qty -> receipt_mismatch
- billed qty/price differ from expected -> po_mismatch
- fallback -> mismatch

Invoice status:
- matched if all lines matched, else mismatch

## 9. Notification, Outbox, Broker, Dead-letter

### 9.1 Notification generation

During PO issue:
- create Notification(status=queued)
- create OutboxEvent(topic=notification.send_email, status=pending)
- include issued vendor token in payload

### 9.2 Outbox forwarding

OutboxForwarder:
- reads pending outbox rows
- publishes to broker
- marks outbox row forwarded (database broker) or published (azure)

### 9.3 Broker processing (database backend)

BrokerConsumer process_notifications:
- fetch queued broker messages available_at <= now
- increment attempts
- locate NotificationRow
- send email via provider
- success:
  - notification status sent
  - broker message processed
  - email delivery row inserted
- failure:
  - if attempts >=3 -> dead_lettered + dead letter row
  - else backoff available_at = now + 2^attempts seconds

### 9.4 Dead-letter replay

Ops replay endpoint:
- locate dead letter row
- create new queued BrokerMessageRow
- delete dead letter row

## 10. Persistence Model

### 10.1 SQLAlchemy row models (db.py)

Business tables:
- vendors
- customer_orders
- customer_order_lines
- vendor_allocations
- purchase_orders
- purchase_order_lines
- notifications
- disputes
- shipments
- shipment_lines
- goods_receipts
- goods_receipt_lines
- invoices
- invoice_lines
- sla_records
- idempotency_records

Operational tables:
- outbox_events
- broker_messages
- dead_letters
- email_deliveries
- domain_events

RBAC tables:
- auth_roles
- auth_permissions
- auth_role_permissions
- auth_user_roles

### 10.2 Persistence strategy

PersistentPlatform commit behavior is full snapshot replacement:
- clear_all_tables(session)
- insert all in-memory entities
- insert event rows
- commit

Hydration behavior:
- load all rows
- recreate in-memory dataclasses
- reconstruct aggregate list references (line_ids, po_ids, etc.)
- infer id counters from existing entity IDs

Implication:
- simple and deterministic
- expensive for large datasets (full rewrite each commit)

### 10.3 Migration state

Migration file:
- alembic/versions/0001_initial_schema.py

Creates all current tables; downgrade drops all tables.

## 11. Idempotency Behavior

Header:
- X-Idempotency-Key

Container methods:
- get_idempotent_response(tenant_id, endpoint, key)
- save_idempotent_response(...)

Implemented on:
- POST /orders
- POST /orders/{order_id}/receipts
- POST /purchase-orders/{po_id}/shipments
- POST /purchase-orders/{po_id}/invoices

Storage:
- in-memory idempotency_records (and persisted to idempotency_records table when persistent backend is used)

Limitations:
- no TTL
- only selected POST endpoints
- no request hash comparison (same key returns prior payload regardless of body)

## 12. Observability

Middleware in observability.py:
- assigns/preserves x-request-id
- adds x-response-time-ms

Optional Azure Monitor hook if APPLICATIONINSIGHTS_CONNECTION_STRING is present.

Metrics endpoint currently returns static JSON health metadata (not Prometheus-format metrics).

## 13. Worker Topology

Workers:
- outbox_forwarder.py
- broker_consumer.py
- outbox_worker.py (orchestrates forwarder + consumer)
- sla_worker.py
- maintenance_worker.py (notifications + sla)
- scheduler_worker_main.py (loops maintenance worker)

Process entrypoints:
- workers/outbox_worker_main.py
- workers/sla_worker_main.py
- workers/maintenance_worker_main.py
- workers/scheduler_worker_main.py

Scheduler control:
- SUPPLY_V2_SCHEDULER_INTERVAL_SECONDS (default 30)

## 14. Configuration Reference

Core runtime vars:
- SUPPLY_V2_DB_URL
- SUPPLY_V2_APP_TARGET
- PORT

Security vars:
- SUPPLY_V2_AUTH_MODE
- SUPPLY_V2_JWT_SECRET
- SUPPLY_V2_JWT_AUDIENCE
- SUPPLY_V2_JWT_ISSUER
- SUPPLY_V2_ENTRA_TENANT_ID
- SUPPLY_V2_ENTRA_CLIENT_ID
- SUPPLY_V2_ENTRA_AUTHORITY
- SUPPLY_V2_ENTRA_JWKS_URL
- SUPPLY_V2_INTERNAL_API_KEY
- SUPPLY_V2_VENDOR_LINK_SECRET

Policy vars:
- SUPPLY_V2_POLICY_MODE
- OPA_URL

Messaging/email vars:
- SUPPLY_V2_BROKER_BACKEND
- AZURE_SERVICE_BUS_CONNECTION_STRING
- AZURE_SERVICE_BUS_QUEUE_NAME
- SUPPLY_V2_EMAIL_BACKEND
- AZURE_EMAIL_CONNECTION_STRING
- AZURE_EMAIL_SENDER

Observability vars:
- APPLICATIONINSIGHTS_CONNECTION_STRING

Worker vars:
- SUPPLY_V2_SCHEDULER_INTERVAL_SECONDS

## 15. Test Coverage Map

tests/test_api_flow.py validates:
- health + metrics headers
- end-to-end API flow
- dispute resolution via API
- reallocate + cancel APIs
- idempotency behavior
- vendor/customer policy scoping
- policy blocking shipment before PO acceptance

tests/test_supply_flow.py validates domain service flows in-memory:
- split procurement + notifications
- vendor price dispute resolution
- customer short receipt dispute
- invoice matching + SLA breach
- reallocate + cancel
- rejected vendor dispute path

tests/test_persistence.py validates persistent reload/hydration across app instances.

tests/test_worker_flow.py validates:
- split apps on same persistent store
- notification worker path end-to-end
- tenant isolation
- role guards
- ops endpoints including internal maintenance key path

## 16. Scripts and Operational Usage

Key scripts:
- scripts/smoke_all_endpoints.py
  - complete smoke with persistent sqlite DB
- scripts/load_test.py
  - async 100-order load run
- scripts/export_openapi.py
  - OpenAPI export
- scripts/build_docs_site.py
- scripts/azure_live_checks.py
- scripts/azure_servicebus_send.py
- scripts/azure_email_send.py
- scripts/azure_end_to_end_live.py
- scripts/entra_token_check.py

CI workflow (.github/workflows/ci.yml):
1. install editable package with dev extras
2. run pytest
3. run smoke script
4. build docker image

## 17. Deployment Topology

Local infra:
- docker-compose.yml provides postgres:16 at localhost:54329

Deployment styles:
- Monolith: single combined app
- Split: separate app targets + separate workers

External services expected in production docs:
- PostgreSQL
- Service Bus
- Azure Communication Email
- Entra ID
- App Insights
- OPA

## 18. Known Gaps, Risks, and Code Quirks

1. Full snapshot persistence is simple but not scalable for high write volume.
2. Messaging broker code has a likely bug in messaging/broker.py:
- dead_letter method appears indented under get_broker after return path, making it unreachable for DatabaseBroker.
- BrokerConsumer currently calls self.broker.dead_letter(...) and tests may not cover failure path strongly.
3. DisputeService sets dispute.updated_at = dispute.created_at during resolution instead of now timestamp.
4. Customer dispute type is currently always customer_quantity_dispute even for condition-based problems.
5. Idempotency has no expiration and no payload consistency hash.
6. Metrics endpoint is placeholder, not metrics scrape format.
7. Internal key is static shared secret; stronger service identity is planned but not fully rolled out.
8. OPA policies exist in policy_engine/policies but full parity with local policy conditions is documented as pending.

## 19. Rebuild Blueprint (for reimplementation in a different style)

This section is a prescriptive guide to rebuild the service while preserving behavior.

### 19.1 Required bounded contexts

Implement these contexts explicitly:
- Identity and access context
- Vendor master context
- Order orchestration context
- Procurement context
- Fulfilment context
- Dispute context
- Invoice/matching context
- Notification/outbox context
- Ops/maintenance context

### 19.2 Required invariants

Must preserve:
- tenant-scoped read/write on all entities
- role + policy double-gate for business APIs
- order split into vendor-specific POs on create
- vendor non-accept decisions create disputes
- receipt mismatch auto-creates customer dispute
- invoice status is derived from per-line 3-way match
- dead-letter replay semantics
- idempotent responses for key POSTs

### 19.3 Suggested target design (alternative implementation style)

If rebuilding with event-sourcing/CQRS style:
- Command side aggregates:
  - OrderAggregate
  - PurchaseOrderAggregate
  - DisputeAggregate
  - ShipmentAggregate
  - InvoiceAggregate
- Event store:
  - append-only domain events
- Projection side:
  - read models for order detail, vendor portal, ops dashboards
- Outbox:
  - transactional outbox table with dispatcher service
- Workflow engine:
  - explicit saga for order->po->ack->ship->receipt->invoice

If rebuilding with transactional relational style:
- keep same resource model
- move away from full snapshot persistence
- use per-transaction writes and optimistic locking/version columns
- add explicit state transition guards in DB/service layer

### 19.4 Minimal API parity checklist

Must expose equivalent routes and semantics for:
- vendor create/read portal
- order create/get/finalize
- receipt create
- PO get/acknowledge/vendor token dispute
- shipment create
- invoice create + SLA list
- dispute get/resolve
- ops run/list/replay/audit/rbac
- internal maintenance endpoint

### 19.5 Data parity checklist

At minimum preserve fields for:
- tenant identifiers on all tenant-scoped entities
- external business IDs (order_number, po_number, invoice_number)
- quantity triplets (ordered, shipped, received)
- accepted vs proposed invoice/po prices
- dispute source/type/reason/resolution/history
- event/outbox/dead-letter traces
- idempotency key + endpoint + response payload

### 19.6 Security parity checklist

Must preserve:
- authentication mode pluggability (header/jwt/entra)
- role definitions and permissions
- policy enforcement as explicit dependency in each route
- vendor token signed access for email-driven dispute path
- internal maintenance endpoint service credential

### 19.7 Async processing parity checklist

Must preserve:
- outbox pending->forwarded/published semantics
- broker message queued/processed/dead_lettered states
- retry with backoff and max attempts
- dead-letter replay API
- SLA due evaluation with breached transition

### 19.8 Testing parity checklist

Rebuild should include integration tests for:
- complete happy path flow
- vendor and customer dispute branches
- policy denials (cross-tenant, vendor scope, customer scope, po_not_shippable)
- idempotency replay
- persistence restart/reload
- worker success and dead-letter failure/replay path

## 20. Concrete Rebuild Plan Template

Use this phased plan when re-implementing:

Phase 1: Foundation
- scaffold domain entities and persistence schema
- implement AuthContext, RBAC, policy abstraction
- implement app container + transaction pattern

Phase 2: Core business flows
- order placement + vendor split POs
- PO acknowledge + vendor disputes
- shipment + receipt + customer disputes
- invoice 3-way match

Phase 3: Async and ops
- notification/outbox/broker/email pipeline
- SLA worker
- dead-letter and replay
- ops maintenance endpoints

Phase 4: Hardening
- idempotency TTL and request hash checks
- observability and true metrics
- performance optimization (incremental persistence)
- production auth/policy integration and rollout

## 21. Quick Commands Reference

Local run:
- docker compose up -d
- python -m alembic -c alembic.ini upgrade head
- python -m pytest -q
- PYTHONPATH=src python scripts/smoke_all_endpoints.py

Run app:
- python -m supply_v2.run

Run scheduler worker:
- python -m supply_v2.workers.scheduler_worker_main

## 22. File-to-Responsibility Map

Core:
- src/supply_v2/apps/factory.py: app composition
- src/supply_v2/run.py: runtime target launcher
- src/supply_v2/platform.py: orchestration facade
- src/supply_v2/dependencies.py: state container + lock + idempotency cache

Security:
- src/supply_v2/auth.py
- src/supply_v2/rbac.py
- src/supply_v2/policy.py
- src/supply_v2/vendor_access.py

Business:
- src/supply_v2/services/order_service.py
- src/supply_v2/services/procurement_service.py
- src/supply_v2/services/fulfilment_service.py
- src/supply_v2/services/dispute_service.py
- src/supply_v2/services/invoice_service.py
- src/supply_v2/services/notification_service.py
- src/supply_v2/services/sla_service.py

Persistence and integrations:
- src/supply_v2/db.py
- src/supply_v2/persistent.py
- src/supply_v2/messaging/broker.py
- src/supply_v2/email_provider.py
- src/supply_v2/workers/*.py

API surface:
- src/supply_v2/routes/*.py

Tests:
- tests/test_api_flow.py
- tests/test_supply_flow.py
- tests/test_persistence.py
- tests/test_worker_flow.py

---

This blueprint captures behavior, contracts, state transitions, persistence model, async processing, and security assumptions required to rebuild Supply V2 in a different architecture while preserving externally observable behavior.
