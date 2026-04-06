# Auth Service

Multi-tenant authentication for ZeroQue using Auth0 Organizations. Each tenant (company) maps to one Auth0 Organization, providing complete data isolation, admin-controlled user onboarding, and organization-scoped roles.

## Architecture

```
┌──────────────────┐     ┌─────────────────────┐     ┌────────────────┐
│  Frontend / API  │────▶│    Auth Service      │────▶│     Auth0      │
│  Client          │     │                      │     │                │
│                  │     │  POST /auth/signup    │     │  Organizations │
│  Bearer JWT      │     │  POST /auth/login     │     │  Users         │
│  in every call   │     │  POST /auth/invite    │     │  Roles         │
│                  │     │  GET  /auth/me        │     │  JWKS          │
└──────────────────┘     └─────────────────────┘     └────────────────┘
         │
         │  JWT validated by middleware
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Middleware Layer                          │
│                                                                      │
│  require_auth       — validates JWT, returns UserContext              │
│  require_tenant     — ensures org_id present (tenant-scoped)         │
│  require_role("X")  — ensures user has role X in their org           │
└──────────────────────────────────────────────────────────────────────┘
```

## Auth0 Organization Model

```
Auth0 Tenant (zeroque-dev.auth0.com)
  │
  ├── Organization: acme-corp
  │     ├── Member: alice@acme.com  [org_admin]
  │     ├── Member: bob@acme.com    [org_manager]
  │     └── Member: carol@acme.com  [org_member]
  │
  ├── Organization: beta-inc
  │     ├── Member: dave@beta.com   [org_admin]
  │     └── Member: eve@beta.com    [org_member]
  │
  └── Roles (shared across orgs):
        ├── org_admin    — full tenant administration
        ├── org_manager  — manage team, approve orders
        ├── org_member   — standard user
        └── org_viewer   — read-only access
```

## Key Concepts

### Tenant Isolation

Every JWT includes an `org_id` claim. The middleware extracts it and makes it available as `user.org_id` / `user.tenant_id`. API routes use this to scope all database queries to the current tenant — users from Org A can never see Org B's data.

### Admin-Controlled Onboarding

Users don't self-register into organizations. The flow is:
1. Company admin signs up → creates org + gets admin account
2. Admin invites users via email
3. Invited user clicks link, sets password, joins the org
4. Admin assigns roles (admin, manager, member, viewer)

### JWT Claims

```json
{
  "sub": "auth0|abc123",
  "email": "alice@acme.com",
  "org_id": "org_xyz",
  "https://api.zeroque.io/roles": ["org_admin"],
  "permissions": ["create:sites", "manage:users"],
  "aud": "https://api.zeroque.io",
  "iss": "https://zeroque-dev.auth0.com/"
}
```

## Files

| File | Purpose |
|------|---------|
| `config.py` | Auth0 domain, client credentials, audience, auth mode |
| `management.py` | Auth0 Management API v2 wrapper (orgs, users, roles, invites) |
| `token.py` | JWT validation — Auth0 JWKS (RS256) or local mock (HS256) |
| `middleware.py` | FastAPI dependencies: `require_auth`, `require_tenant`, `require_role` |
| `routes.py` | Auth API endpoints (signup, login, invite, me, org management) |
| `schemas.py` | Pydantic request/response models and UserContext |
| `local_store.py` | In-memory mock for testing without Auth0 |
| `app.py` | Standalone FastAPI app (for independent deployment or testing) |

## Usage in API Routes

```python
from auth_service.middleware import require_auth, require_tenant, require_role
from auth_service.schemas import UserContext

@router.post("/provisioning/sites")
async def create_site(
    req: SiteRequest,
    user: UserContext = Depends(require_tenant),  # must belong to a tenant
    db: Session = Depends(get_db),
):
    # user.org_id is the tenant — scope all queries to this
    site = Site(tenant_id=user.org_id, name=req.name, ...)
    db.add(site)

    # Emit event (also scoped to tenant)
    emit(db, user.org_id, "site.created", {"site_id": str(site.id), ...})
    db.commit()

    return {"site_id": str(site.id)}


@router.post("/admin/settings")
async def update_settings(
    req: ...,
    user: UserContext = Depends(require_role("org_admin")),  # admin only
):
    ...
```

## Auth Modes

| Mode | When | How |
|------|------|-----|
| `local` | Local dev, CI, testing | In-memory user/org store, HS256 JWTs |
| `auth0` | Staging, production | Real Auth0 API, RS256 JWTs, JWKS validation |

Set via `AUTH_MODE` environment variable.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/signup` | None | Company signup — creates org + admin |
| POST | `/auth/login` | None | Authenticate, get JWT |
| GET | `/auth/me` | Bearer | Current user context |
| POST | `/auth/invite` | Admin/Manager | Invite user to org |
| POST | `/auth/accept-invite` | None | Accept invitation, set password |
| GET | `/auth/org/members` | Admin/Manager | List org members |
| POST | `/auth/org/roles` | Admin | Assign roles to member |
| GET | `/auth/org/info` | Tenant | Organization info |

## Testing

```bash
# Run the 51-test E2E suite (no Auth0 needed, uses local mode)
python -m tests.test_auth
```

## Auth0 Setup (Production)

1. Create Auth0 tenant → Settings → Enable Organizations
2. Create Machine-to-Machine app → grant Management API scopes
3. Create API audience (`https://api.zeroque.io`)
4. Set environment variables:
   ```
   AUTH_MODE=auth0
   AUTH0_DOMAIN=zeroque-dev.auth0.com
   AUTH0_CLIENT_ID=...
   AUTH0_CLIENT_SECRET=...
   AUTH0_AUDIENCE=https://api.zeroque.io
   ```
