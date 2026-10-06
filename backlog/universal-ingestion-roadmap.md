# ZeroQue — Universal Ingestion & ERP Connectivity Roadmap

> **Status:** Aligned to leadership deck — build in progress | **Last updated:** 2026-10-05
> **Final plan:** `docs/ZeroQue_Universal_Ingestion_Leadership.html` (supersedes earlier findings papers)
> Core rule: *"Never ask the customer to structure information that ZeroQue can structure for them."*

---

## 1. Architecture (locked — deck slide 04)

**One system. Three paths. ERP only on ingest read and buy write.**

| Path | Flow | ERP involvement |
|---|---|---|
| **1. Ingest** | ERP → adapter → integration_service → 8-step AI → ZeroQue tables | **Read only** |
| **2. Ask** | User → Intelligence chatbot → Postgres / Neo4j / pgvector | **None** (our DBs only, no ERP tools in v1) |
| **3. Buy** | Approve on ZeroQue → named ERP write (`createPurchaseOrder`) + EDI to vendor | **Write: createPurchaseOrder only** |

- Vendor hop (EDI / CData) is **separate from ERP write**.
- MCP is **not** the sync path. Spike proved the adapter boundary only.

---

## 2. Scope (locked — deck slide 05)

### Pull (master data)
- Suppliers, products / items
- Supplier–product relationships
- Departments / org units, cost centres
- Locations (only when used for ship-to / stock site)

### Do NOT pull
- Historical POs, lines, receipts, purchase history
- Inventory as a live query path
- Vendor settlement into the ERP

### Ownership
- **ERP owns** native ids (copied as evidence) and posted state
- **ZeroQue owns** canonical identity, ranges, budgets, and the new PO
- **EDI owns** vendor send

---

## 3. AI rules (locked — deck slide 13)

**AI organises business truth. It does not invent it.**

| May | Must not |
|---|---|
| Clean descriptions; normalise supplier names | Invent prices, qty, ERP statuses, supplier ids, spend |
| Suggest multi-name suppliers are one identity | Change native ids or mint legal identity |
| Match tenant items to canonical products | Match below review threshold; merge on low confidence |
| Flag duplicates; highlight uncertain records | Choose what to pull; author adapters; run sync |
| (Later doors) infer columns; extract document text | — |

Low confidence → **review queue**, never auto-canonical. No silent merges.

---

## 4. The eight ingest steps (locked — deck slide 12)

**Detect → Extract → Normalise → Resolve → Match → Enrich → De-dupe → Validate**

Tenant SKUs and relationships stay as evidence. No silent canonical create.

---

## 5. Connector contract (locked — deck slide 15)

Same adapter surface for every ERP. One envelope per object.

- **Lifecycle:** configure, test, capabilities, schema, health, revoke
- **Reads:** suppliers, products, locations, org dimensions, supplier–product, changesSince
- **Write:** `createPurchaseOrder` only (slice 5)
- **Envelope:** identity · version · unaltered payload · extraction metadata · integrity (hash, schema, warnings, provenance)

### Write gates (4) — deck slide 14
**Declared** (adapter) → **Entitled** (tenant) → **Authorised** (principal) → **Approved** (workflow)

Write failure semantics: ERP write fail → ZeroQue PO stands, retry write. EDI fail → dispatch retry only. **Never claim ERP success until ack.**

---

## 6. Build plan — six slices (locked — deck slide 07)

> Exit each slice before starting the next.

### Slice 1 — Contract foundation
**Build:** Contract, envelope, MockERP, behavioural suite
**Exit:** Rules pass with no live ERP

Six workstreams (deck slide 16): Envelope · Capabilities · Protocol · MockERP · Suite · HTTP
Bounds: FastAPI / Pydantic / pytest. No catalog writes. No Intelligence change. Writes hidden.

- [ ] 1.1 Source envelope model (identity, version, raw payload ref, extraction metadata, integrity hash, schema, warnings, provenance, adapter version, correlation ID)
- [ ] 1.2 `discover_capabilities()` on BaseConnector + per-tenant capability response
- [ ] 1.3 `get_health()` (last success, lag, failed count) + `revoke_connection()`
- [ ] 1.4 Correlation IDs through sync runs; adapter version stamped per run
- [ ] 1.5 MockERP adapter + shared behavioural test suite
- [ ] 1.6 HTTP surface for the contract (integration_service endpoints)

### Slice 2 — NetSuite read
**Build:** NetSuite read · snapshot / incremental · checkpoint · health
**Exit:** Resume after fail · no duplicate rows

- [ ] 2.1 `readSuppliers` + `readSupplierProductRelationships`
- [ ] 2.2 `readOrganisationDimensions` (departments / cost centres) + `readLocations` (ship-to)
- [ ] 2.3 High-water mark cursors per connection + object type (`readChangesSince`)
- [ ] 2.4 Durable checkpoints — resume crashed run without duplicates
- [ ] 2.5 Retry classification (transient / permanent / auth / data-quality) + ERP-aware backoff
- [ ] 2.6 Reconciliation: counts, key totals, gap sampling, measurable lag
- [ ] 2.7 Canonical models + field maps for each new object type

### Slice 3 — Ingestion AI engine
**Build:** Eight-step ingest + review · AI on meaning
**Exit:** Match when confident · money/ids unchanged

- [ ] 3.1 Canonical Product / Canonical Supplier entities + tenant-record links
- [ ] 3.2 Supplier identity resolution (name normalisation + Companies House / Creditsafe evidence)
- [ ] 3.3 AI product matching + attribute extraction ("NIT GLOVE BLU PF LG" → nitrile/blue/powder-free/L) + classification
- [ ] 3.4 Review queue API/UI for low-confidence records
- [ ] 3.5 Persist raw payload + content hash as evidence (per envelope)
- [ ] 3.6 Wire company search into "add supplier" (search → pre-fill → create)

### Slice 4 — Buy on ingested catalog
**Build:** Buy against ingested catalog
**Exit:** ZeroQue PO from pulled items

- [ ] 4.1 Order flow validated end-to-end on ERP-pulled products/suppliers
- [ ] 4.2 Ranges / budgets / approvals operate on ingested data

### Slice 5 — Governed write: createPurchaseOrder
**Build:** createPurchaseOrder · four gates
**Exit:** No false ERP success · PO stands on retry

- [ ] 5.1 Write gate framework: Declared → Entitled → Authorised → Approved
- [ ] 5.2 `createPurchaseOrder` in NetSuite adapter with idempotency + audit
- [ ] 5.3 Denial reasons + reconciliation of write outcomes

### Slice 6 — Vendor EDI dispatch
**Build:** Vendor EDI dispatch
**Exit:** Dispatch fail = vendor retry only

- [ ] 6.1 EDI/cXML dispatch of approved ZeroQue PO to vendor
- [ ] 6.2 Dispatch retry isolated from ERP write state

---

## 7. What we already have ✅

| # | Foundation | Evidence |
|---|---|---|
| 1 | Adapter pattern + canonical model | `BaseConnector` + `CanonicalItem`; NetSuite adapter live (BC/SAP/Oracle shelved per deck) |
| 2 | Schema discovery + mapping validation | `discover_schema()` stored on `TenantConnection.source_schema`; sync-time mapping warnings |
| 3 | Deterministic bulk sync (products) | `engine.py` — pagination, upsert, deactivate-missing. No LLM in data plane |
| 4 | NetSuite OAuth 2.0 M2M | Certificate-JWT client assertion, token caching; TBA fallback |
| 5 | Credential security | Key Vault in prod, server-side only, PEM validation on upload |
| 6 | Tenant isolation + entitlement gating | Tenant-scoped connections; `erp.integration` feature gate |
| 7 | Company identity services | Companies House + Creditsafe proxies (slice 3 building blocks) |
| 8 | Scheduled sync | APScheduler in-process |
| 9 | Table catalogue + sample preview | `list_tables()` + `preview_table()` with 24h cache + curated fallback |
| 10 | Intelligence service live | `data_intelligence_service` — Ask path already running on our DBs |
| 11 | Buy path foundations | Orders, approvals, budgets, ranges live on ZeroQue data |

---

## 8. Non-goals (locked — deck slide 08)

**Defer:** SAP and other front doors (files, docs, manual, vendor feeds) · live `erp.get_*` in Intelligence · MCP as sync engine or platform connector · generic ERP writes

**Reject:** Bulk sync through the chat planner · per-tenant product tables · customer field-mapping as default onboarding · CData as the tenant ERP pipe · AI-authored adapters / AI as reliability path

---

## 9. Ongoing test contract (deck slide 16)

- MockERP behavioural suite runs on every adapter change
- No duplicate rows on replay
- Intelligence never calls ERP
- Writes stay hidden until slice 5
