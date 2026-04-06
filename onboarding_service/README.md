# Onboarding Service

Tenant signup, admin provisioning, and entity CRUD for the ZeroQue platform.

## Architecture

```
                        ┌─────────────────────┐
      Admin arrives →   │  POST /onboarding/  │
      at signup page    │  tenant-signup       │
                        └─────────┬───────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  1. Create Tenant (Postgres) │
                    │  2. Emit tenant.signup event │
                    │  3. Run Worker:              │
                    │     → admin User             │
                    │     → tenant_admin Role       │
                    │     → 8 core Permissions      │
                    │     → UserRole assignment     │
                    │  4. Emit user.created event   │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  Admin gets JWT             │
                    │  (via auth_service)         │
                    └─────────────┬──────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           │                      │                      │
    ┌──────▼──────┐        ┌──────▼──────┐        ┌──────▼──────┐
    │ Create      │        │ Create      │        │ Create      │
    │ Sites       │        │ Users       │        │ Vendors     │
    │ Stores      │        │ Org Units   │        │ Cost Centres│
    └─────────────┘        └─────────────┘        └─────────────┘
           │                      │                      │
           └──────────────────────┼──────────────────────┘
                                  │
                    Events emitted for every DB write
                    → consumed by graph_service, etc.
```

## Flow

1. **Tenant Signup** — `POST /onboarding/tenant-signup` (public, no auth)
   - Creates Tenant record in Postgres
   - Provisions admin user with `tenant_admin` role + 8 core permissions
   - Emits `tenant.signup` and `user.created` events

2. **Admin gets JWT** — via `auth_service` (Auth0 or local mode)
   - JWT contains `org_id` (tenant context), `roles`, `permissions`

3. **Entity CRUD** — all protected by `auth_service` + `policy_engine`
   - Sites, Stores, Users, Vendors, Cost Centres, Org Units, Roles
   - Every write emits an event to the outbox

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/onboarding/tenant-signup` | None | Tenant signup + admin provisioning |
| GET | `/onboarding/tenants/{id}` | JWT | Get tenant details |
| PUT | `/onboarding/tenants/{id}` | JWT + Policy | Update tenant |
| POST | `/onboarding/sites` | JWT + Policy | Create site |
| GET | `/onboarding/sites` | JWT + Policy | List tenant's sites |
| GET | `/onboarding/sites/{id}` | JWT + Policy | Get site |
| PUT | `/onboarding/sites/{id}` | JWT + Policy | Update site |
| DELETE | `/onboarding/sites/{id}` | JWT + Policy | Delete site |
| POST | `/onboarding/stores` | JWT + Policy | Create store |
| GET | `/onboarding/stores` | JWT + Policy | List tenant's stores |
| DELETE | `/onboarding/stores/{id}` | JWT + Policy | Delete store |
| POST | `/onboarding/users` | JWT + Policy | Create user |
| GET | `/onboarding/users` | JWT + Policy | List tenant's users |
| GET | `/onboarding/users/{id}` | JWT + Policy | Get user |
| DELETE | `/onboarding/users/{id}` | JWT + Policy | Delete user |
| POST | `/onboarding/vendors` | JWT + Policy | Create vendor |
| GET | `/onboarding/vendors` | JWT + Policy | List tenant's vendors |
| POST | `/onboarding/cost-centres` | JWT + Policy | Create cost centre |
| GET | `/onboarding/cost-centres` | JWT + Policy | List cost centres |
| POST | `/onboarding/org-units` | JWT + Policy | Create org unit |
| GET | `/onboarding/org-units` | JWT + Policy | List org units |
| POST | `/onboarding/roles` | JWT + Policy | Create role |
| GET | `/onboarding/roles` | JWT | List roles |

## 8 Core Permissions (assigned to tenant_admin)

| Code | Description |
|------|-------------|
| `tenant.admin` | Full tenant administration |
| `users.manage` | Create and manage users |
| `sites.manage` | Create and manage sites |
| `stores.manage` | Create and manage stores |
| `vendors.manage` | Create and manage vendors |
| `budgets.manage` | Manage budgets and cost centres |
| `approvals.manage` | Manage approval chains |
| `catalog.manage` | Manage products and catalog |

## Integrations

| Component | How it's used |
|-----------|---------------|
| `auth_service` | JWT validation via `require_auth` |
| `policy_engine` | OPA authorization via `require_policy("action", "resource")` |
| `event_service` | Outbox event emission on every DB write |

## Models (ported from project-zer-prov_policy)

Tenant, User, Site, Store, Role, Permission, RolePermission, UserRole, TenantRole, TenantRolePermission, TenantUserRole, OrgUnit, UserOrgAssignment, Vendor, CostCentre.

Uses a cross-database `GUID` TypeDecorator — works with both PostgreSQL (production) and SQLite (testing).
