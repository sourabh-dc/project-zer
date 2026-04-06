# Table Ownership Matrix

Every table in the shared PostgreSQL database has exactly **one writer-owner** service.
Other services may SELECT from these tables but must never issue DDL or write to them directly.

All schema changes must go through Alembic (`alembic upgrade head`) — no service may run
`Base.metadata.create_all()` or ad-hoc `ALTER TABLE` at startup.

---

## Owner: `provisioning_service`

These tables are defined authoritatively in [provisioning_service/Models.py](provisioning_service/Models.py).
`provisioning_service` is the only service that writes to them.

| Table | Notes |
|-------|-------|
| `tenants` | Core tenancy record |
| `sites` | Physical/logical sites |
| `stores` | Store per tenant/site |
| `users` | Primary user record with auth fields |
| `roles` | Global role catalog |
| `user_roles` | User ↔ role assignment |
| `permissions` | Global permission catalog |
| `role_permissions` | Role ↔ permission mapping |
| `tenant_roles` | Tenant-scoped custom roles |
| `tenant_role_permissions` | Tenant role ↔ permission mapping |
| `tenant_user_roles` | User ↔ tenant role assignment |
| `org_units` | Organisational hierarchy |
| `user_org_assignments` | User ↔ org unit assignment |
| `vendors` | Vendor/supplier master |
| `cost_centres` | Budget cost centres |
| `cost_center_budget` | CC budget per period |
| `user_cost_centres` | User budget allocation |
| `financial_calendars` | Financial calendar config |
| `financial_years` | Financial year records |
| `financial_periods` | Financial period records |
| `company_budget_caps` | Company-level budget caps |
| `cc_budget_versions` | CC budget versions |
| `user_budget_limits` | Per-user budget limits |
| `approval_policies` | Approval policy config |
| `approval_stages` | Stages within a policy |
| `approval_stage_conditions` | Stage trigger conditions |
| `approval_stage_approvers` | Approvers per stage |
| `subscription_plans` | SaaS subscription plans |
| `plan_price` | Plan pricing |
| `colour_groups` | Product colour groups |
| `colours` | Colour master |
| `sizes` | Size master |
| `fits` | Fit types |
| `uos_labels` | Unit-of-sale labels |

---

## Owner: `orders_service`

Defined authoritatively in [orders_service/Models.py](orders_service/Models.py).

| Table | Notes |
|-------|-------|
| `purchase_requests` | PR lifecycle |
| `approval_workflows` | Workflow instance per PR |
| `approval_tasks` | Individual approver tasks |
| `outbox_events` | Transactional outbox for event publishing |
| `outbox_event_delivery` | Per-consumer delivery tracking |
| `categories` | Product/request categories |

> **Shared read-only tables from provisioning_service:** `users`, `roles`, `user_roles`,
> `permissions`, `role_permissions`, `org_units`, `user_org_assignments`,
> `cost_centres`, `vendors`, `financial_calendars`, `financial_years`, `financial_periods`,
> `company_budget_caps`, `cc_budget_versions`, `user_budget_limits`,
> `approval_policies`, `approval_stages`, `approval_stage_conditions`, `approval_stage_approvers`

---

## Owner: `policy_service`

Defined authoritatively in [policy_service/Models.py](policy_service/Models.py).

| Table | Notes |
|-------|-------|
| `policies` | Policy definitions |
| `policy_versions` | Immutable version snapshots |
| `policy_rules` | Rules within a version |
| `policy_assignments` | Scope/binding assignments |
| `policy_action_types` | Action type catalog |
| `policy_decisions` | Immutable decision audit log |

---

## Owner: `vector_service`

Schema managed by Alembic revision `20260406_03`.

| Table | Notes |
|-------|-------|
| `product_embeddings` | pgvector embedding chunks per product |

---

## Overlap / Conflict Resolution

The tables below appear in more than one service's Models.py.
The **provisioning_service** definition is canonical; other services use a
lightweight read-only mirror so SQLAlchemy can construct JOINs without
a runtime import dependency on provisioning_service.

| Table | Canonical owner | Read-only mirrors |
|-------|----------------|-------------------|
| `users` | `provisioning_service` | `orders_service` |
| `roles` | `provisioning_service` | `orders_service` |
| `user_roles` | `provisioning_service` | `orders_service` |
| `permissions` | `provisioning_service` | `orders_service` |
| `role_permissions` | `provisioning_service` | `orders_service` |
| `org_units` | `provisioning_service` | `orders_service` |
| `user_org_assignments` | `provisioning_service` | `orders_service` |
| `cost_centres` | `provisioning_service` | `orders_service` |
| `vendors` | `provisioning_service` | `orders_service` |

Mirror models in `orders_service/Models.py` must never add columns not present in
the provisioning definition.  Any column addition must be made in provisioning first,
then mirrored.

---

## Change Lifecycle (expand-contract)

1. **Expand** — add nullable column / new table in a migration; deploy.
2. **Dual-write** (if needed) — services write both old and new paths.
3. **Migrate** — backfill data; flip reads to new path.
4. **Contract** — remove old column in a follow-up migration after all services updated.

Every migration PR must include a **Cross-service impact** section listing which
services read or write the affected tables.
