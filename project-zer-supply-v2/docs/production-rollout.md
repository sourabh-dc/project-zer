# Production Rollout

## Service topology

- Public apps:
  - vendor
  - order
  - procurement
  - fulfilment
  - dispute
  - invoice
  - ops
- Private workers:
  - notification worker
  - SLA worker
  - maintenance worker

## Shared platform dependencies

- Azure Database for PostgreSQL
- Azure Service Bus queue
- Azure Communication Services Email
- Azure Entra ID
- Azure Monitor / Application Insights
- OPA sidecar or policy service

## Service-to-service trust

- `SUPPLY_V2_INTERNAL_API_KEY`
  - shared internal key for worker-triggered endpoints.
- JWT for user traffic.
- RBAC permission gate first.
- OPA policy gate second.

## Deployment sequence

1. Provision Postgres, Service Bus, Email, Monitor, and Container Apps environment.
2. Apply DB migrations.
3. Deploy combined app or split apps with `SUPPLY_V2_APP_TARGET`.
4. Deploy workers.
5. Set internal API key across ops and workers.
6. Set App Insights connection string.
7. Run smoke flow.
8. Run load test.

## Validation checklist

- `/health` green on all apps.
- `/ready` green after DB and policy connectivity.
- `/metrics` visible.
- Swagger loads on combined app.
- Vendor email outbox processed.
- Dead-letter replay works.
- Internal maintenance endpoint works with internal key.
- Customer order to receipt to invoice flow completes.

## Live Azure helper commands

- Build published docs site:
  - `PYTHONPATH=src python3 scripts/build_docs_site.py`
- Generate Azure env from current RG resources:
  - `PYTHONPATH=src python3 scripts/azure_live_checks.py`
- Live Service Bus send:
  - `set -a && source .env.azure.live && set +a && PYTHONPATH=src python3 scripts/azure_servicebus_send.py`
- Live Azure email send:
  - `set -a && source .env.azure.live && export AZURE_EMAIL_TO=<target> && set +a && PYTHONPATH=src python3 scripts/azure_email_send.py`
- Live end-to-end email path:
  - `set -a && source .env.azure.live && export AZURE_EMAIL_TO=<target> && set +a && PYTHONPATH=src python3 scripts/azure_end_to_end_live.py`
- Live Entra token validation:
  - get consent first for Azure CLI to call the app resource
  - then `set -a && source .env.azure.live && export SUPPLY_V2_BEARER_TOKEN=<token> && set +a && PYTHONPATH=src python3 scripts/entra_token_check.py`
