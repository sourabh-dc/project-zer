# ZeroQue — Sprint 1 (Billing + Entitlements)

Fresh scaffold (builds on Sprint 0) with **Billing** and **Entitlements** implemented.

- Postgres: host **5000** (container 5432)
- Redis: host **4000** (container 6379)

## What’s implemented in Sprint 1
- Plans/Features/PlanFeatures (Core/Pro/Enterprise) with seed script
- Trade Account onboarding
- Stripe subscribe endpoint (dev-friendly: real key -> hits Stripe; no key -> returns stubbed IDs)
- Subscriptions table and webhook endpoint (dev-stub-safe)
- Entitlements service returns effective features/limits for a tenant/site

## Quick start
```bash
docker compose -f infra/docker-compose.dev.yml up -d
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ./packages/zeroque_common
cp .env.example .env

python ops/seed/seed_sprint1.py

uvicorn services.billing.main:app --reload --port 8101
# new shell
uvicorn services.entitlements.main:app --reload --port 8102

# Trade example
curl -X POST "http://localhost:8101/billing/tenants/tenant-1/trade-account" -H "Content-Type: application/json" -d '{"ar_customer_code":"ACME-AR-001","terms":"NET30"}'
curl -X POST "http://localhost:8101/billing/tenants/tenant-1/subscribe" -H "Content-Type: application/json" -d '{"plan":"core","payment_method":"trade"}'

# Entitlements
curl "http://localhost:8102/entitlements?tenant_id=tenant-1"
```
