# ZeroQue — Universal Ingestion & ERP Connectivity Roadmap

> **Status:** Gap analysis complete — build not started | **Last updated:** 2026-09-07
> Based on: *ZeroQue Universal Ingestion Layer* (product intent) and *ZeroQue Universal ERP Connectivity Findings* (Tom Hall, 1 Sep 2026)
> Companion analysis: `docs/` canvases — ingestion gap analysis (7 Sep 2026)

---

## 1. Vision (from the docs)

> "Never ask the customer to structure information that ZeroQue can structure for them."

- **Many front doors, one canonical model:** ERP connectors, files (CSV/XLSX), documents (invoices/POs), manual smart creation, vendor feeds — all converge on the same ZeroQue objects.
- **Pipeline:** Detect → Extract → Normalise → Resolve → Match → Enrich → De-duplicate → Validate. Human intervention only where confidence is insufficient.
- **AI interprets, it does not invent.** Prices, quantities, ERP statuses, supplier IDs and spend stay grounded in source data.
- **MCP belongs on the intelligence side.** Bulk ingestion stays deterministic (queues, workers, checkpoints). An LLM may choose which capability to invoke; it never moves the records.
- **Ownership is per object/field.** ERP owns native records and posted state; ZeroQue owns canonical identity, classification, policy and recommendations.

---

## 2. What We Already Have ✅

| # | Foundation | Evidence |
|---|---|---|
| 1 | Adapter pattern + canonical model | `BaseConnector` + `CanonicalItem`; 4 adapters: Dynamics BC, SAP B1, NetSuite, Oracle ERP |
| 2 | Schema discovery + mapping validation | `discover_schema()` per adapter, stored on `TenantConnection.source_schema`; sync-time mapping warnings in `SyncRun.warnings` |
| 3 | Deterministic bulk sync | `engine.py` — pagination, upsert, deactivate-missing. No LLM in the data plane (matches the docs' core rule) |
| 4 | NetSuite OAuth 2.0 M2M | Certificate-JWT client assertion, token caching; TBA kept as fallback |
| 5 | Credential security | Key Vault in prod (`credentials_ref`), server-side only, never emitted |
| 6 | Tenant isolation + entitlement gating | Tenant-scoped connections; `erp.connectors` feature gate |
| 7 | Company identity services | Companies House (UK) + Creditsafe (global) proxies — building blocks for intelligent supplier creation |
| 8 | Scheduled sync | APScheduler in-process scheduler |
| 9 | Intelligence service exists | `data_intelligence_service` with query planner/graph — ready for governed ERP tools |

---

## 3. Gap Analysis

### 3.1 Ingestion routes (Doc 1)

| # | Route | Status | Gap |
|---|---|---|---|
| R1 | ERP connectors | ⚠️ Partial | Products only. Doc expects suppliers, locations, departments/cost centres, POs + lines, purchase history, supplier↔product relationships |
| R2 | Files (CSV/Excel) | ❌ Missing | Only simple `/catalog/products/bulk-upload`. No ingestion pipeline, no AI column mapping, no multi-object import |
| R3 | Documents (invoices/POs/PDF) | ❌ Missing | No extraction pipeline at all |
| R4 | Manual smart creation | ⚠️ Partial | Companies House/Creditsafe exist but not wired into a "search → pre-fill → add supplier" flow |
| R5 | Vendor connections (EDI/API/feeds) | ❌ Missing | Supplier-side catalogue feeds not started |

### 3.2 Canonical identity & AI layer (Doc 1)

| # | Capability | Status | Gap |
|---|---|---|---|
| C1 | Two-layer product identity | ❌ Missing | Sync upserts straight into tenant `Product`. No Canonical ZeroQue Product, no customer-record ↔ canonical match |
| C2 | Supplier identity resolution | ❌ Missing | No canonical supplier entity — "Metsa" / "METSÄ TISSUE LTD" would duplicate |
| C3 | De-duplication | ❌ Missing | Dedup by `external_id` within one run only; no fuzzy/AI matching |
| C4 | AI enrichment & classification | ❌ Missing | No attribute extraction ("NIT GLOVE BLU PF LG" → nitrile/blue/powder-free/L), no category classification in ingestion |
| C5 | Review queue | ❌ Missing | No low-confidence holding area for customer resolution |
| C6 | Raw payload preservation | ⚠️ Partial | `SyncRunItem` stores per-item status, not unaltered payload + content hash as evidence |

### 3.3 Universal connector contract (Doc 2 §5)

| # | Contract area | Status | Gap |
|---|---|---|---|
| K1 | Connection lifecycle | ⚠️ Partial | Have configure/test/discoverSchema. Missing: `discoverCapabilities`, `getHealth`, `revokeConnection` |
| K2 | Master data reads | ❌ Gap | Have `readProducts` only. Missing: suppliers, locations, org dimensions, supplier-product relationships |
| K3 | Procurement reads | ❌ Missing | No POs, PO lines, receipts, inventory, purchase history |
| K4 | Change capture | ❌ Missing | Full snapshot every run; cursor is a row offset, not a high-water mark. No `readChangesSince`, no deletion events |
| K5 | Execution control | ❌ Missing | No idempotency keys, correlation IDs, cancellation, replay |
| K6 | Source envelope | ❌ Missing | No standard envelope: identity / version / raw payload / extraction time / content hash / adapter version |
| K7 | Health reporting | ⚠️ Partial | `SyncRun` stats exist. No lag, throttle state, or reconciliation status per connection |
| K8 | Governed writes | ❌ Missing | Read-only today (correct), but none of the 4 gates exist: technical capability, tenant entitlement, role permission, workflow approval |
| K9 | Capability model | ❌ Missing | No machine-readable per-tenant capability response (doc Appendix A) |

### 3.4 Sync as a product capability (Doc 2 §7)

| # | Control | Status | Gap |
|---|---|---|---|
| S1 | Snapshot + durable checkpoint | ⚠️ Partial | Offset paging works; crash mid-run restarts from zero |
| S2 | Incremental sync | ❌ Missing | No high-water marks; every run re-reads everything |
| S3 | Rate-limit / throttle handling | ❌ Missing | Fixed timeout only; no ERP-aware backoff |
| S4 | Retry classification | ❌ Missing | No transient / permanent / auth / data-quality split |
| S5 | Dead-letter + replay | ❌ Missing | Failed records counted, not isolated for replay without duplication |
| S6 | Reconciliation | ❌ Missing | No counts/totals/gap sampling — cannot prove convergence |
| S7 | Adapter version tracking | ❌ Missing | Evidence not reproducible across adapter versions |
| S8 | Queue-based workers | ⚠️ Partial | APScheduler in-process — MVP-fine, not the target worker fleet |

---

## 4. Build Order (workstreams)

Aligned with the findings paper's proof sequence: **contract → harness → reads → writes last.**

### WS1 — Contract foundation
- [ ] 1.1 Define the **source envelope** model (identity, version, raw payload ref, extraction, integrity hash, adapter version, correlation ID)
- [ ] 1.2 Add `discover_capabilities()` to `BaseConnector` + per-tenant capability response (Appendix A shape)
- [ ] 1.3 Add `get_health()` (last success, lag, failed count) + `revoke_connection()`
- [ ] 1.4 Correlation IDs through sync runs; adapter version stamped on every run
- [ ] 1.5 MockERP adapter + shared behavioural test suite (contract testable without a live vendor account)

### WS2 — More master-data reads
- [ ] 2.1 `readSuppliers` (all 4 adapters) → feeds intelligent supplier creation
- [ ] 2.2 `readLocations` + `readOrganisationDimensions` (departments/cost centres)
- [ ] 2.3 `readSupplierProductRelationships`
- [ ] 2.4 Canonical models + field maps for each new object type

### WS3 — File ingestion (CSV/XLSX)
- [ ] 3.1 Upload endpoint + staging tables (raw rows preserved)
- [ ] 3.2 AI column mapping (LLM suggests source→canonical mapping, user confirms)
- [ ] 3.3 Multi-object import (vendors, items, PO history) through the same canonical pipeline as ERP sync
- [ ] 3.4 Per-row validation + error report

### WS4 — Incremental sync & checkpoints
- [ ] 4.1 High-water mark cursors per connection + object type
- [ ] 4.2 Durable checkpoints — resume a crashed run without duplicates
- [ ] 4.3 Deactivation/deletion semantics from source change events where available

### WS5 — Reliability layer
- [ ] 5.1 Retry classification (transient / permanent / auth / data-quality)
- [ ] 5.2 ERP-aware throttling + backoff behind a platform-neutral interface
- [ ] 5.3 Dead-letter isolation + replay from checkpoint
- [ ] 5.4 Reconciliation job: counts, key totals, gap sampling, measurable sync lag

### WS6 — Canonical identity & review
- [ ] 6.1 Canonical Product / Canonical Supplier entities + customer-record links
- [ ] 6.2 Supplier identity resolution (name normalisation + Companies House/Creditsafe evidence)
- [ ] 6.3 AI-assisted product matching + attribute extraction + classification
- [ ] 6.4 Review queue UI/API for low-confidence records
- [ ] 6.5 Wire company search into "add supplier" (search → pre-fill → create)

### WS7 — Procurement reads
- [ ] 7.1 `readPurchaseOrders` + lines
- [ ] 7.2 `readReceipts` + `readInventory`
- [ ] 7.3 `readPurchaseHistory` (spend intelligence feed)

### WS8 — Intelligence-plane ERP tools
- [ ] 8.1 Governed tool surface over the integration service (`erp.search_purchase_orders`, `erp.get_inventory`, `erp.get_supplier`)
- [ ] 8.2 MCP-style facade for the Intelligence Service query planner
- [ ] 8.3 Purpose-limited tools with user context + policy checks + attribution

### WS9 — Governed writes (LAST)
- [ ] 9.1 Write gate framework: capability declared → tenant entitlement → role permission → workflow approval
- [ ] 9.2 One named low-risk write (e.g. `acknowledge_receipt`) end-to-end with idempotency + audit
- [ ] 9.3 Denial reasons + reconciliation of write outcomes

### WS10 — Documents & vendor feeds (later)
- [ ] 10.1 Invoice/PO PDF extraction (vision/LLM) → canonical objects
- [ ] 10.2 Supplier catalogue feeds / EDI / cXML ingestion

---

## 5. Open Decisions (from the findings paper, for product owner)

| # | Question | Suggested position |
|---|---|---|
| D1 | Which ERP-owned objects make the first valuable onboarding? | Suppliers + products + locations |
| D2 | Which canonical mappings must be deterministic before AI interpretation? | Identity keys, units of measure, currency, deletion flags |
| D3 | Where can native change events be trusted vs mandatory reconciliation polling? | NetSuite/BC events where available; polling + reconciliation everywhere else |
| D4 | Minimum evidence to reproduce every canonical match? | Source envelope (K6) + adapter version + match confidence + reviewer action |
| D5 | First write capability to prove the gates? | `acknowledge_receipt` (low financial risk) |

---

## 6. Explicitly Out of Scope (for now)

- ZeroQue exposing its own MCP server to external AI systems — future architecture, not MVP
- LLM involvement in the deterministic data plane
- Generic `update_record`-style write surface — writes are named business capabilities only
