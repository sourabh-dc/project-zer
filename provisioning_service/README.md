# Provisioning Service

Provisioning Service is a FastAPI app that manages tenants, plans, catalog, budgets, approvals, subscriptions, and internal admin operations. On startup it:
- Starts the Service Bus messaging client (best effort).
- Initializes database tables.
- Runs a safe outbox_events migration.
- Loads static permissions/features from CSV.


## Quick Start (Local)

1. Set environment variables (see Environment section below).
2. Start dependencies (Postgres, OPA, Redis optional).
3. Start the API:

```bash
uvicorn provisioning_service.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```


## Application Startup (Uvicorn)

The API app lives in `provisioning_service.main:app`.

- Local dev:

```bash
uvicorn provisioning_service.main:app --host 0.0.0.0 --port 8000 --reload
```

- Docker default (from Dockerfile):

```bash
uvicorn provisioning_service.main:app --host 0.0.0.0 --port 80
```


## Dependencies and How to Start Them

### 1) PostgreSQL (Required)
Used for all domain data and policy evaluation context.

Env vars (local mode):
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`

Example (Docker):

```bash
docker run --name zq-postgres -e POSTGRES_DB=zeroque -e POSTGRES_USER=zeroque -e POSTGRES_PASSWORD=zeroque -p 5432:5432 -d postgres:15
```

### 2) OPA Policy Engine (Required unless bypassed)
The service evaluates policies through the shared in-process policy engine which calls an OPA sidecar at `OPA_URL` (default: `http://localhost:8181`).

Start OPA with policies mounted (example):

```bash
docker run --name zq-opa -p 8181:8181 -v /path/to/opa_policies:/policies openpolicyagent/opa:latest run --server /policies
```

You can bypass policy evaluation for local dev with:
- `POLICY_ENGINE_BYPASS=true`

### 3) Redis (Optional)
Used for caching in the policy engine. If unavailable, the service still runs.

```bash
docker run --name zq-redis -p 6379:6379 -d redis:7
```

### 4) Azure Service Bus (Optional, required for outbox worker)
The API can run without Service Bus; it will log a warning and continue. If you run the outbox worker, you need:
- `SERVICE_BUS_CONNECTION_STRING`

### 5) Outbox Worker (Optional)
Processes async work from the outbox queue (tenant/user/product handlers). Run this separately if you need async provisioning flows:

```bash
python provisioning_service/core/helpers/outbox_worker.py
```

### 6) Graph Service / Vector Service (Optional)
Outbox events create delivery rows for `graph_service` and `vector_service`. If you want those events consumed, start those services too.

### 7) Stripe (Optional)
Payments and webhook validation require:
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`

### 8) Azure Email (Optional)
Used for email delivery:
- `AZURE_EMAIL_CONNECTION_STRING`

### 9) Azure Key Vault (Non-local environments)
If `ENVIRONMENT` is not `local`, secrets are pulled from Key Vault using `DefaultAzureCredential`:
- `KEYVAULT_NAME` (vault name only, not URL)
- Azure identity configured for Key Vault access

### 10) Event Grid (Optional)
Used for tenant.created events:
- `EVENT_GRID_TOPIC_ENDPOINT`
- `EVENT_GRID_TOPIC_KEY`


## Environment

The service loads `.env` if present and then reads Key Vault when `ENVIRONMENT != local`.

Common local variables:

```env
ENVIRONMENT=local
POSTGRES_DB=zeroque
POSTGRES_USER=zeroque
POSTGRES_PASSWORD=zeroque
POSTGRES_HOST=localhost
REDIS_URL=redis://localhost:6379/0
JWT_ISSUER=http://mock-idp
JWT_AUDIENCE=zeroque-api
JWT_ALGORITHM=HS256
JWT_SECRET=mock-secret
POLICY_ENGINE_BYPASS=false
OPA_URL=http://localhost:8181
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
AZURE_EMAIL_CONNECTION_STRING=...
SERVICE_BUS_CONNECTION_STRING=...
EVENT_GRID_TOPIC_ENDPOINT=...
EVENT_GRID_TOPIC_KEY=...
AIFI_BASE_URL=...
AIFI_API_KEY=...
AIFI_STORE_ID=...
AIFI_LOCATION_ID=...
```


## Testing the Service End-to-End

1. Start Postgres and OPA (and Redis if you want caching).
2. Export env vars (or create a .env).
3. Start the API with Uvicorn.
4. (Optional) Start the outbox worker if you need async tasks.
5. Call health:

```bash
curl http://localhost:8000/health
```


## Notes

- The service auto-creates tables at startup and loads permissions/features from CSV.
- Policy evaluation calls OPA; set `POLICY_ENGINE_BYPASS=true` to skip for local work.
- If Service Bus is not configured, the API still runs but outbox queue dispatch will be skipped.
