# ZeroQue — ERP Connector Framework Plan

> **Status:** Implemented (E1–E7) | **Last updated:** 2026-08-20
> Goal: clients import products from their ERP/P2P system into ZeroQue catalog.
> Commercial hook: gated by `erp.integration` feature → Standard Pack (£150/mo) upsell.

---

## 1. Goals & Non-Goals

**Goals**
- One framework, many providers. New provider = one file, ~300 lines.
- Pull products from client ERP into `products` table. Upsert, never duplicate.
- Manual "sync now" + scheduled sync.
- Per-run audit: created / updated / skipped / errors.
- Credentials stored safely. Tenant-isolated.

**Non-goals (v1)**
- No write-back to ERP (no pushing POs/invoices). Import only.
- No real-time webhooks from ERPs (polling only).
- No Salesforce/AWS — not product masters. Revisit as export channels.
- No full PIM normalization (units/languages beyond basics).

---

## 2. Current-State Anchors (already in codebase)

| Asset | Where | Use |
|---|---|---|
| `Product.external_id` | `Models.py:844` | Dedup anchor — provider's item ID |
| Excel bulk upload | `catalog_routes.py:709` | Reference for insert logic; stays as manual fallback |
| `erp.integration` feature | seeded, Standard Pack | Gate all connector endpoints |
| Azure Key Vault client | `core/config.py` | Store client secrets (prod) |
| Service Bus outbox | `core/sb_client.py` | Dispatch sync jobs async |
| `check_user_authorization` | `core/user_auth.py` | Route auth |

---

## 3. Architecture

```text
┌────────────┐   ┌──────────────────────────────────────────────┐
│  Client UI │──▶│  Connector API (/v1/connections, /sync-runs) │
└────────────┘   └──────────────┬───────────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │   ConnectorRegistry    │
                    │  {"dynamics_bc": cls…} │
                    └───────────┬────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
      DynamicsBCConnector  SapB1Connector   NetSuiteConnector …
              │  BaseConnector interface:                  │
              │    authenticate() / test_connection()      │
              │    fetch_products(page)  → raw dicts       │
              │    normalize(raw)        → CanonicalItem   │
              └─────────────────┬──────────────────┘
                                ▼
                    ┌──────────────────────┐
                    │  SyncEngine           │
                    │  map → dedup → upsert │
                    │  → products table     │
                    │  → sync_runs audit    │
                    └──────────────────────┘
```

---

## 4. Data Model (new tables)

### `connector_providers` (seeded, static)
| col | notes |
|---|---|
| `provider_code` PK | `dynamics_bc`, `sap_b1`, `netsuite`, `oracle_erp` |
| `display_name` | "Microsoft Dynamics 365 Business Central" |
| `auth_type` | `oauth2` \| `basic` \| `token` |
| `config_schema` | JSONB — which fields the setup form needs (tenant_url, company, client_id…) |
| `default_field_map` | JSONB — provider field → canonical field |
| `is_active` | bool |

### `tenant_connections`
| col | notes |
|---|---|
| `connection_id` PK | uuid |
| `tenant_id` FK | |
| `provider_code` FK | |
| `name` | "Production SAP" |
| `config` | JSONB — non-secret config (base URL, company id) |
| `credentials_ref` | Key Vault secret name (prod) or `credentials_enc` JSONB (local dev) |
| `status` | `active` \| `error` \| `disabled` |
| `schedule_cron` | nullable, e.g. `0 2 * * *` nightly |
| `last_sync_at`, `last_sync_status` | denormalized for list UI |
| unique | (`tenant_id`, `provider_code`, `name`) |

### `sync_runs`
| col | notes |
|---|---|
| `sync_run_id` PK | |
| `connection_id` FK | |
| `trigger` | `manual` \| `scheduled` |
| `status` | `running` \| `success` \| `partial` \| `failed` |
| `started_at` / `finished_at` | |
| `created_count`, `updated_count`, `skipped_count`, `error_count` | |
| `error_summary` | JSONB — first N errors |

### `sync_run_items` (per-row detail, capped)
`sync_run_id` FK, `external_id`, `sku`, `action` (`created|updated|skipped|error`), `message`

### Product changes
- Reuse `Product.external_id` (already indexed).
- Add `Product.source_connection_id` FK nullable — traceability back to connection.

---

## 5. Connector Interface

```python
# provisioning_service/core/connectors/base.py
class CanonicalItem(BaseModel):
    external_id: str
    sku: str
    name: str
    description: str | None = None
    category_name: str | None = None      # resolved/created by engine
    vendor_name: str | None = None        # resolved/created by engine
    purchase_price_minor: int | None = None
    currency: str = "GBP"
    unit: str | None = None
    ean: str | None = None
    is_active: bool = True
    raw: dict = {}                        # original payload, debug

class BaseConnector(ABC):
    provider_code: str

    def __init__(self, config: dict, credentials: dict): ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]: ...

    @abstractmethod
    def fetch_products(self, cursor: str | None) -> tuple[list[dict], str | None]:
        """One page. Returns (raw_items, next_cursor). next=None → done."""

    @abstractmethod
    def normalize(self, raw: dict, field_map: dict) -> CanonicalItem: ...
```

Registry:

```python
# provisioning_service/core/connectors/registry.py
CONNECTORS: dict[str, type[BaseConnector]] = {
    "dynamics_bc": DynamicsBCConnector,
    "sap_b1": SapB1Connector,
    "netsuite": NetSuiteConnector,
    "oracle_erp": OracleERPConnector,
}
```

---

## 6. Provider Specifics

### 6.1 Dynamics 365 Business Central (build first)
- **Auth:** OAuth2 client credentials (Entra ID). Token from `login.microsoftonline.com/{tenant}/oauth2/v2.0/token`.
- **API:** OData v4 — `GET {base}/api/v2.0/companies({companyId})/items`.
- **Pagination:** `@odata.nextLink`. Filter: `$filter=type eq 'Inventory' or type eq 'Non-Inventory'`.
- **Fields:** `number`→sku, `displayName`→name, `unitPrice`/`unitCost`, `itemCategoryCode`.
- **Pitfall:** sandbox vs prod base URL differs; company ID required.
- **Sandbox:** free BC trial tenant.

### 6.2 SAP Business One
- **Auth:** session login `POST /b1s/v1/Login` → cookie; or Service Layer with basic auth.
- **API:** `GET /b1s/v1/Items` (OData-ish).
- **Pagination:** `$skip`/`$top` (max 20 default — set `$top=100`).
- **Fields:** `ItemCode`→sku, `ItemName`→name, prices via `ItemPrices` (price list pick needed!).
- **Pitfall:** price lists — must pick one list in connection config. On-prem URL often needs VPN/allowlist.

### 6.3 NetSuite
- **Auth:** Token-Based Auth (TBA) — consumer key/secret + token key/secret, HMAC-SHA256 signed. Or OAuth 2.0 client credentials (newer).
- **API:** SuiteQL via `POST /services/rest/query/v1/suiteql` — `SELECT itemid, displayname, salesdescription, baseprice FROM item WHERE isinactive='F'`.
- **Pagination:** `LIMIT`/`OFFSET` in SuiteQL.
- **Pitfall:** TBA setup is fiddly for clients — setup wizard UI + docs needed. Concurrency limits per account.

### 6.4 Oracle ERP Cloud
- **Auth:** basic auth or OAuth2 (IDCS).
- **API:** `GET /fscmRestApi/resources/11.13.18.05/itemsV2`.
- **Pagination:** `offset`/`limit`, `totalResults` in response.
- **Pitfall:** versioned resource paths; org context (`OrganizationCode`) required.

---

## 7. Normalization & Field Mapping

- Each provider seeds `default_field_map` (provider field → canonical field).
- Tenant can override per connection (stored on `tenant_connections.field_map` JSONB).
- `normalize()` applies map → `CanonicalItem` → pydantic validation.
- Category/vendor resolution in engine (not connector):
  - `category_name` → find-or-create `Category` by (tenant, code).
  - `vendor_name` → find-or-create `Vendor` by (tenant, lower(name)).
  - Both respect `product.records` / `supplier.records` limits via existing `check_feature_limit`.

---

## 8. Dedup & Upsert

Match order per item:
1. `(tenant_id, external_id)` — exact provider match → **update**.
2. `(tenant_id, sku)` — same SKU, no external_id → **link + update** (set external_id).
3. No match → **create**.

Rules:
- Update only mapped fields; never wipe fields the provider doesn't send.
- Deactivation: item vanished from feed → mark `active=False` only if connection setting `deactivate_missing=true` (default false).
- All upserts inside one DB transaction per page (not per item) — page-level atomicity, run-level partial success.

---

## 9. Sync Engine

```text
trigger (manual POST | scheduler)
   → create sync_run (status=running)
   → loop pages:
        raw_page, cursor = connector.fetch_products(cursor)
        items = [normalize(r) for r in raw_page]
        upsert_page(items)          # one transaction
        log per-item results
   → finalize run (counts, status)
```

- **Execution:** v1 = in-process `asyncio` task via FastAPI `BackgroundTasks` for manual runs; outbox + Service Bus for scheduled runs (worker pattern already exists).
- **Scheduling:** v1 = `APScheduler` AsyncIOScheduler in the service, jobs loaded from `tenant_connections.schedule_cron` at startup + refreshed on connection save. (No Celery — overkill now.)
- **Locking:** one running sync per connection — DB row lock (`SELECT … FOR UPDATE` on sync_runs) or status check.
- **Retries:** page fetch fails → 3 attempts, exponential backoff. Run fails → status `failed`, keep partial counts.
- **Rate limits:** per-connector polite delay (e.g. 200 ms between pages); respect `Retry-After`.

---

## 10. Security

- **Credentials:** prod → Azure Key Vault (client exists in `config.py`); store only secret name in `credentials_ref`. Local dev → JSONB column, marked dev-only.
- Never return credentials from API. Config responses mask secrets (`***`).
- OAuth2 providers: client credentials grant (server-to-server) — no redirect dance needed for BC/Oracle. NetSuite TBA = 4 tokens, entered in setup form.
- Tenant isolation: every query scoped by `tenant_id` from JWT ctx; routes use `check_user_authorization("catalog.manage")` + feature gate.

---

## 11. Entitlement Gating

- All connection endpoints: `erp.integration` in `load_tenant_features()` → else 403 with upsell message ("Standard Integration Pack").
- Sync engine: `check_feature_limit(db, tenant_id, "product.records", count=len(new_items))` before create — imported products count against catalog quota.
- This makes connectors the delivery mechanism for the already-priced Standard Pack.

---

## 12. API Surface

```text
GET    /v1/connector-providers                     list available providers + config schema
POST   /v1/tenants/{tid}/connections               create connection (validates + test_connection)
GET    /v1/tenants/{tid}/connections               list (masked)
GET    /v1/tenants/{tid}/connections/{id}          detail + last run
PATCH  /v1/tenants/{tid}/connections/{id}          update config/schedule/field_map
DELETE /v1/tenants/{tid}/connections/{id}          disable (keep history)
POST   /v1/tenants/{tid}/connections/{id}/test     re-test credentials
POST   /v1/tenants/{tid}/connections/{id}/sync     manual run → {sync_run_id}
GET    /v1/tenants/{tid}/sync-runs                 list runs (filter by connection)
GET    /v1/tenants/{tid}/sync-runs/{run_id}        run detail + item errors
```

New files:
```text
provisioning_service/services/connector_routes.py
provisioning_service/core/connectors/__init__.py
provisioning_service/core/connectors/base.py
provisioning_service/core/connectors/registry.py
provisioning_service/core/connectors/dynamics_bc.py
provisioning_service/core/connectors/sap_b1.py
provisioning_service/core/connectors/netsuite.py
provisioning_service/core/connectors/oracle_erp.py
provisioning_service/core/connectors/engine.py      # sync engine
provisioning_service/core/connectors/scheduler.py   # APScheduler wiring
```

---

## 13. Frontend

- New dashboard tab "Integrations" (admin-only):
  - provider picker → dynamic setup form from `config_schema`
  - connection list: status pill, last sync, sync now button
  - run history drawer: counts + error table
- Reuse existing CSS vars; no new deps.

---

## 14. Testing

- **Unit:** normalize() per provider against recorded JSON fixtures (capture real API responses once, commit as fixtures).
- **Integration:** mock `httpx` responses; run engine against test DB; assert upsert/dedup/deactivate rules.
- **Sandbox:** BC trial + NetSuite trial accounts for manual E2E.
- **Load:** 10k-item fixture — assert page transactions + memory flat.

---

## 15. Rollout Phases

| Phase | Scope | Effort |
|---|---|---|
| E1 | Models + migrations + providers seed + registry + base + engine + routes (mock connector) | 2–3 days |
| E2 | Dynamics BC connector + tests + frontend tab | 2 days |
| E3 | SAP B1 connector | 1–2 days |
| E4 | NetSuite connector (TBA wizard) | 2 days |
| E5 | Oracle ERP connector | 1–2 days |
| E6 | Scheduler (APScheduler) + scheduled-run worker | 1 day |
| E7 | Hardening: rate limits, deactivate_missing, run item caps, docs | 1–2 days |

E1+E2 = usable MVP (~1 week).

---

## 16. Open Decisions

1. Scheduler: in-process APScheduler (simple) vs Azure Container Apps Job (robust, extra deploy). **Recommend APScheduler v1.**
2. Credential storage for local dev: plain JSONB vs local Fernet key. **Recommend JSONB + `ENV=local` guard.**
3. Price-list selection for SAP B1: config field vs "cheapest list" heuristic. **Recommend config field.**
4. Deactivate-missing default off — confirm.
5. Do imported products need approval workflow before going live in catalog? **Recommend no v1; flag `active=true` directly.**
