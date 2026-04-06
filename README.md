# ZeroQue Platform — `project-zer-new`

Multi-tenant B2B SaaS platform with event-driven architecture, centralised authentication, and OPA-based policy engine.

## Architecture

```
                    ┌───────────────────────┐
                    │  Central Auth Service  │  ← Auth0 (JWT)
                    │    auth_service/       │
                    └───────────┬───────────┘
                                │ JWT token
                    ┌───────────▼───────────┐
                    │   Policy Engine (OPA)  │  ← Rego policies from Git
                    │   policy_engine/       │
                    └───────────┬───────────┘
                                │ allow / deny
    ┌───────────────────────────┼───────────────────────────┐
    │                           │                           │
    ▼                           ▼                           ▼
┌──────────┐  OPA        ┌──────────┐  OPA          ┌──────────┐  OPA
│ Graph    │◄─sidecar──▶ │ Event    │◄─sidecar────▶ │  Other   │◄─sidecar
│ Service  │  :8181      │ Service  │  :8183        │ Services │  :818X
└──────────┘             └──────────┘               └──────────┘
     │                        │
     ▼                        ▼
   Neo4j             PostgreSQL + Service Bus
```

## Project Structure

```
project-zer-new/
├── shared/                         # Shared config, DB, ORM models
│   ├── config.py                   # Environment-based configuration
│   ├── db.py                       # SQLAlchemy engine + session factory
│   ├── models.py                   # OutboxEvent ORM model
│   └── init_db.py                  # Create outbox_events table
│
├── event_service/                  # Event pipeline (emitter + publisher + consumer)
│   ├── emitter.py                  # emit() — write event to outbox
│   ├── publisher.py                # Claim pending → publish → mark published
│   ├── transport.py                # LocalTransport / ServiceBusTransport
│   ├── local_runner.py             # Run full pipeline locally (no Azure)
│   ├── publisher_func/             # Azure Function — Timer trigger (publisher)
│   └── consumer_func/              # Azure Function — SB triggers (consumers)
│       ├── router.py               # Event → handler routing
│       └── handlers/               # graph, vector, notification handlers
│
├── auth_service/                   # Multi-tenant auth (Auth0 + Organizations)
│   ├── routes.py                   # Signup, login, invite, accept, RBAC
│   ├── middleware.py               # require_auth, require_tenant, require_role
│   ├── token.py                    # JWT validation (RS256 / HS256)
│   ├── management.py               # Auth0 Management API wrapper
│   ├── local_store.py              # In-memory mock for dev/test
│   └── schemas.py                  # Pydantic models
│
├── onboarding_service/             # Tenant signup + entity CRUD
│   ├── models.py                   # Tenant, User, Site, Store, Role, OrgUnit, etc.
│   ├── schemas.py                  # Pydantic request/response models
│   ├── routes.py                   # 23 endpoints (signup + CRUD)
│   ├── worker.py                   # Admin provisioning (role + 8 perms)
│   └── app.py                      # Standalone FastAPI application
│
├── graph_service/                  # Neo4j topology projection
│   ├── main.py                     # POST /graph/ingest, GET /graph/topology/{tid}
│   ├── handlers.py                 # Cypher handlers per entity type
│   └── neo4j_client.py             # Neo4j driver management
│
├── policy_engine/                  # OPA-based authorization
│   ├── policies/                   # Rego policies (Git = source of truth)
│   │   ├── common/tenant.rego      # Tenant isolation rules
│   │   ├── rbac/roles.rego         # Role hierarchy + derived permissions
│   │   ├── users/manage.rego       # User CRUD policies
│   │   ├── sites/manage.rego       # Site CRUD policies
│   │   ├── budgets/manage.rego     # Budget policies + approval limits
│   │   ├── products/manage.rego    # Product CRUD policies
│   │   └── vendors/manage.rego     # Vendor CRUD policies
│   ├── client.py                   # OPA HTTP client + local dispatcher
│   ├── local_evaluator.py          # Python mirror of Rego rules (dev/test)
│   ├── middleware.py               # require_policy("action", "resource")
│   └── opa_config/                 # OPA sidecar Docker + bundle config
│
├── tests/
│   ├── test_pipeline.py            # 54 tests — event pipeline E2E
│   ├── test_auth.py                # 51 tests — multi-tenant auth E2E
│   ├── test_policy.py              # 129 tests — policy engine E2E
│   └── test_onboarding.py          # 79 tests — onboarding service E2E
│
├── docker-compose.yml              # Postgres + Neo4j + OPA sidecars
├── requirements.txt
└── .env
```

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Install Python deps
pip install -r requirements.txt

# 3. Initialize database
python3 -m shared.init_db

# 4. Run all tests (313 total, no Docker/Azure needed)
python3 tests/test_pipeline.py    # 54 tests — event pipeline
python3 tests/test_auth.py        # 51 tests — authentication
python3 tests/test_policy.py      # 129 tests — policy engine
python3 tests/test_onboarding.py  # 79 tests — onboarding service

# 5. Run local event pipeline
python3 -m event_service.local_runner
```

## Key Design Decisions

| Concern          | Decision                                | Why                                    |
|------------------|-----------------------------------------|----------------------------------------|
| Authentication   | Auth0 with Organizations                | Multi-tenant isolation via org_id      |
| Authorization    | OPA sidecars (per service)              | Fast local checks, centralised rules   |
| Policy source    | Git repo (policies/ folder)             | Auditable, PR-reviewed, CI-tested      |
| Event delivery   | Transactional outbox → Service Bus      | At-least-once, atomic with DB writes   |
| Local dev        | POLICY_MODE=local, AUTH_MODE=local      | Full testing without OPA/Auth0         |
| Graph projection | Cypher MERGE                            | Idempotent, handles out-of-order       |

## Role Hierarchy

```
org_admin (40)   — full CRUD on everything within tenant
org_manager (30) — create/read/update (no delete except own scope)
org_member (20)  — create/read on most resources
org_viewer (10)  — read-only access
```
