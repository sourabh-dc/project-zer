# ZeroQue Engineering Lock v1.1 — Implementation Plan

## Phase 1: Fix the Outbox Foundation (Postgres Layer)

### 1.1 Fix OutboxEvent Model (Section 3.1)

Add missing columns:
- `aggregate_type` (string, not null) — e.g. `"tenant"`, `"user"`, `"vendor"`, `"product"`
- `aggregate_id` (UUID, not null) — the ID of the entity the event is about
- `processed_at` (datetime, nullable) — set when processing completes
- Rename `event_data` → `payload` for spec alignment

Add index: `(processed_at NULLS FIRST, created_at)` for efficient relay polling.

### 1.2 Atomic Outbox Writes (Section 3.2)

Every write endpoint must commit entity + outbox event in a **single** `db.commit()`.

Create helper:
```python
def append_outbox_event(db, tenant_id, aggregate_type, aggregate_id, event_type, payload):
```

### 1.3 Event Immutability (Section 0.5)

Workers must never mutate `payload` after insertion. Move any generated data (e.g. passwords) to the API endpoint before the outbox event is created.

### 1.4 Fix Tenant Signup Flow

Move admin user creation back to synchronous (within the endpoint). Outbox event triggers only async side-effects (welcome email, external sync, future Graph/Vector projection).

### 1.5 Build Relay/Poller

Background task that periodically queries for unprocessed outbox events and re-sends Service Bus notifications. Catches events where initial notification failed.

### 1.6 Dead-Letter Handling (Section 3.2)

When `retry_count >= max_retries`: mark as `dead_letter`, log operational alert, don't acknowledge as successful.

---

## Phase 2: Apply Outbox to All Write Endpoints

| Endpoint | aggregate_type | event_type |
|----------|---------------|------------|
| `POST /tenant-signup` | `tenant` | `tenant.created` |
| `PUT /tenants/{id}` | `tenant` | `tenant.updated` |
| `POST /sites` | `site` | `site.created` |
| `POST /sites/{id}/tenants/{id}` | `site` | `site.tenant_added` |
| `DELETE /sites/{id}/tenants/{id}` | `site` | `site.tenant_removed` |
| `POST /stores` | `store` | `store.created` |
| `PUT /stores/{id}` | `store` | `store.updated` |
| `POST /users` | `user` | `user.created` |
| `POST /vendors` | `vendor` | `vendor.created` |
| `POST /cost-centres` | `cost_centre` | `cost_centre.created` |
| `POST /users/{id}/cost-centres` | `user_cost_centre` | `user_budget.assigned` |
| `POST /budgets/renew` | `cost_centre` | `budget.renewed` |
| `POST /roles` | `role` | `role.created` |
| `POST /users/{id}/roles` | `user` | `user.role_assigned` |
| `DELETE /users/{id}/roles/{id}` | `user` | `user.role_removed` |
| `POST /org_units` | `org_unit` | `org_unit.created` |
| `PUT /org_units/{id}` | `org_unit` | `org_unit.updated` |
| `DELETE /org_units/{id}` | `org_unit` | `org_unit.deleted` |
| `POST /org_units/assignments` | `org_unit` | `org_unit.user_assigned` |
| `DELETE /org_units/assignments/{id}` | `org_unit` | `org_unit.user_removed` |
| `DELETE /org_units/{id}/users/{id}` | `org_unit` | `org_unit.user_removed` |
| `POST /catalog/products` | `product` | `product.created` |
| `POST /catalog/products/bulk-upload` | `product` | `product.created` (one per row) |
| `POST /catalog/categories` | `category` | `category.created` |
| `POST /payments/webhook` | `subscription` | `subscription.activated` |
| `POST /tenant-roles` | `tenant_role` | `tenant_role.created` |
| `POST /tenant-roles/{id}/permissions` | `tenant_role` | `tenant_role.permission_added` |
| `POST /users/{id}/tenant-roles` | `user` | `user.tenant_role_assigned` |
| `POST /vendor-user` | `vendor_user` | `vendor_user.created` |
| `PUT /{user_id}` (vendor user) | `vendor_user` | `vendor_user.updated` |
| `DELETE /{user_id}` (vendor user) | `vendor_user` | `vendor_user.deleted` |
| `POST /roles/map-permission` | `role` | `role.permission_added` |
| `DELETE /roles/delete-permission` | `role` | `role.permission_removed` |

---

## Phase 3: Standardize Delete Semantics (Section 0.2) ✅

- ✅ Added unified `status ∈ {active, inactive, deleted}` to: Tenant, Site, Store, User, OrgUnit, Vendor, Fit, CostCentre, Feature, Category, Product, Variant, VendorUser
- ✅ Replaced hard deletes with soft deletes (OrgUnit, VendorUser) — sets `status = 'deleted'` + outbox event
- ✅ Updated all list/get queries to filter `status != 'deleted'` across provisioning_routes, catalog_routes, internal_routes
- ✅ Junction table removes (SiteTenant, UserRole, UserOrgAssignment, RolePermission) kept as hard deletes — they are edge removals, not entity deletions; outbox events already capture the change

## Phase 4: Add Missing Postgres Models ✅

- ✅ `Carrier` — global entity with name, code, carrier_type, tracking_url_template, status
- ✅ `TenantCarrier` — for ALLOWS_CARRIER edge (relationship_type, integration_type, account_number)
- ✅ `UserApprover` — for IS_APPROVER_FOR edge (approval_limit_minor, currency, rule_set_id)
- ✅ `ApprovedRange` — tenant-scoped, with name, description, is_universal flag, status
- ✅ `ApprovedRangeOrgUnit` — maps approved ranges to org units (many-to-many)
- ✅ `ApprovedRangeProduct` — maps products into approved ranges (many-to-many)
- ✅ Full CRUD routes in `approved_range_routes.py` (10 endpoints)
- ✅ Product search filtering: non-admin users only see products in their org unit's approved ranges + universal ranges
- ✅ Outbox events for all approved range write operations

## Phase 5: Policy Engine

- Architecture document created: `policy_engine_architecture.md`
- Awaiting team decision on 7 decision points before implementation

## Phase 6: Graph and Vector Projection Layers

- 6.1: Neo4j graph projection handlers consuming outbox events
- 6.2: Vector store with (doc_id, version, chunk_index) PK, chunking, embeddings
- 6.3: Wire both into outbox worker routing
