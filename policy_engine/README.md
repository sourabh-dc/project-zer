# Policy Engine — OPA-based Authorization

Centralised, consistent authorization for the multi-tenant B2B SaaS platform using [Open Policy Agent (OPA)](https://www.openpolicyagent.org/).

## Architecture

```
                ┌─────────────────────────────┐
                │   Git Repo (Single Source)   │
                │   policy_engine/policies/    │
                │     common/tenant.rego       │
                │     rbac/roles.rego          │
                │     users/manage.rego        │
                │     sites/manage.rego        │
                │     budgets/manage.rego      │
                │     products/manage.rego     │
                │     vendors/manage.rego      │
                └──────────┬──────────────────┘
                           │  loaded at startup
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ OPA      │    │ OPA      │    │ OPA      │
    │ Sidecar  │    │ Sidecar  │    │ Sidecar  │
    │ :8181    │    │ :8182    │    │ :8183    │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
    ┌────▼─────┐    ┌────▼─────┐    ┌────▼─────┐
    │ Graph    │    │ Auth     │    │ Event    │
    │ Service  │    │ Service  │    │ Service  │
    └──────────┘    └──────────┘    └──────────┘
```

**Authentication** is centralised (Auth0 / JWT).
**Authorization** is decentralised: each service has its own OPA sidecar, all loading the same policies from Git.

## How It Works

1. **Request arrives** → `auth_service` middleware validates JWT → `UserContext`
2. **`require_policy(action, resource_type)`** extracts resource details from the request
3. **OPA input document** is assembled:
   ```json
   {
     "user":     { "user_id": "...", "org_id": "org_abc", "roles": ["org_manager"] },
     "action":   "create",
     "resource": { "type": "site", "org_id": "org_abc", "attributes": { "name": "HQ" } }
   }
   ```
4. **OPA evaluates** the Rego policy for that resource type
5. **Result**: `{"allow": true/false, "reasons": [...]}`
6. If denied → **403 Forbidden** with structured reasons

## Policy Mode

| Mode    | When                  | How it works                          |
|---------|-----------------------|---------------------------------------|
| `local` | Dev / tests           | Python evaluator mirrors Rego rules   |
| `opa`   | Staging / production  | HTTP call to OPA sidecar at `:8181`   |

Set via `POLICY_MODE` env var (defaults to `local`).

## Role Hierarchy

```
org_admin (40)  →  full CRUD on everything within their tenant
org_manager (30) →  create/read/update (no delete, no org settings)
org_member (20)  →  create/read on most resources
org_viewer (10)  →  read-only
```

Each higher role inherits all permissions from lower roles.

## Policies

| Domain   | Package             | Key rules                                      |
|----------|---------------------|-------------------------------------------------|
| Common   | `common.tenant`     | Tenant isolation — `same_tenant` check          |
| RBAC     | `rbac.roles`        | Role hierarchy, derived permissions             |
| Users    | `users.manage`      | Admin: full, Manager: create/read, Member: read |
| Sites    | `sites.manage`      | Admin: full, Manager: CRU, Member: CR           |
| Budgets  | `budgets.manage`    | Approval limits, amount-based constraints       |
| Products | `products.manage`   | Admin: full, Manager: CRU, Member: CR           |
| Vendors  | `vendors.manage`    | Manager+ to create/update, Member: read         |

## Usage in FastAPI

```python
from policy_engine.middleware import require_policy

@router.post("/sites")
async def create_site(
    body: SiteCreate,
    user: UserContext = Depends(require_policy("create", "site")),
):
    # If we reach here, the policy allowed the request.
    # user.org_id is the tenant context.
    ...
```

## OPA Sidecar (Docker)

Each service runs an OPA container as a sidecar:

```yaml
# docker-compose.yml
opa-graph:
  build:
    context: ./policy_engine
    dockerfile: opa_config/Dockerfile
  ports:
    - "8181:8181"
```

The OPA container loads all `.rego` files from `policies/` at startup with `--watch` for hot reload.

## Files

```
policy_engine/
├── __init__.py           # Public API
├── config.py             # POLICY_MODE, OPA_URL
├── client.py             # OPA HTTP client + dispatcher
├── local_evaluator.py    # Python mirror of Rego rules (dev/test)
├── middleware.py          # FastAPI Depends() — auth + policy in one call
├── opa_config/
│   ├── Dockerfile        # OPA sidecar image
│   └── config.yaml       # Bundle-based config (Git sync for prod)
└── policies/
    ├── common/
    │   └── tenant.rego   # Tenant isolation
    ├── rbac/
    │   └── roles.rego    # Role hierarchy
    ├── users/
    │   └── manage.rego
    ├── sites/
    │   └── manage.rego
    ├── budgets/
    │   └── manage.rego
    ├── products/
    │   └── manage.rego
    └── vendors/
        └── manage.rego
```

## Adding a New Policy

1. Create `policies/<domain>/manage.rego` with `default allow = false`
2. Import `data.common.tenant` and `data.rbac.roles`
3. Add evaluator function in `local_evaluator.py`
4. Register the resource type in `client.py` `_POLICY_PATH_MAP`
5. Use `require_policy("action", "resource_type")` in your routes

## CI/CD

```bash
# Validate policies
opa test ./policy_engine/policies

# Build and push OPA sidecar
docker build -t myregistry/opa-sidecar:latest -f policy_engine/opa_config/Dockerfile policy_engine/

# All services pull the same image → consistent policies everywhere
```
