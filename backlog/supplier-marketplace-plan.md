# ZeroQue Suppliers — B2B Marketplace: Implementation Plan

> **Status:** Planning | **Date:** 2026-10-26
> Based on: *ZeroQue Suppliers · B2B marketplace* (docs/ZeroQue_Suppliers_B2B_Leadership.html)
> Scope lock: **No inventory management. No payments/settlement in v1.**

---

## 1. Vision

Extend ZeroQue from buyer-only operating system into a two-sided B2B marketplace:

- **Suppliers are independent organisations** (like Amazon sellers) — own tenant, own users, own catalogue, own order inbox.
- **Buyers stay governed** — budgets, approvals, approved ranges, PR → PO unchanged.
- **Canonical product identity** shared platform-wide — suppliers list against it, no per-tenant SKU cloning.
- Commercial facts (listing / offer / price) never sit on the legal entity or the canonical product.

---

## 2. Gap Analysis: Current State vs. Target

### Current State (provisioning_service)

| Area | What Exists | Gap vs. Target |
|---|---|---|
| **Vendor** | `vendors` table — **tenant-scoped row** owned by a buyer tenant. Has integration fields (api/cxml/edi/webhook), onboarding_status, payment_terms, tax_id, duns | ❌ Vendor is a record *inside* a tenant, not an independent org. No legal identity, no lifecycle, no discoverability |
| **Vendor users** | `vendor_users` — thin: email + password_hash + `vendor_admin`/`vendor_staff` roles, no real auth, no invite flow | ❌ Not real platform users. No Entra/CIAM login, no invite-based onboarding, no supplier_* roles |
| **Tenant** | `tenants.tenant_type` (retailer/brand/franchisee) | ❌ No `supplier` tenant type, no `LegalOrganisation` link |
| **Legal identity** | Nothing — reg/tax/duns fields scattered on `vendors` | ❌ No platform-scoped `legal_organisations` (reg, Companies House, screening) |
| **Products** | `products` — **tenant-scoped clones**, own sku/ean/mpn per tenant. Has matrix variants, packs (inner/outer), hazmat | ❌ No canonical product stack. Same RS line cloned per tenant. No shared classification spine, no explicit identifier grain |
| **Listing** | N/A — products link directly to `vendor_id` | ❌ No `supplier_product_listings` (supplier SKU → canonical pack, list price signal) |
| **Offer** | N/A | ❌ No `supplier_product_offers` (buyer workspace entitlement: MOQ, lead time — no price) |
| **Price** | `products.purchase_price_minor` per tenant | ❌ No `supplier_product_prices` + `_price_breaks` (sole home of workspace unit price) |
| **Orders** | PR → PO exists (buyer side) | ❌ No `supplier_orders` / `supplier_order_events` (supplier inbox: ack/ship/invoice visibility) |
| **Supplier plan** | Buyer tiers only (Starter→Enterprise) | ❌ No supplier subscription tier (catalogue limits, connectivity add-on) |
| **Governance** | approved_ranges, budgets, approval_policies, PR/PO, outbox audit | ✅ Reuse as-is |

### Key Gaps to Close

| Document Requirement | Gap |
|---|---|
| `LegalOrganisation` (platform-scoped real company) | Missing entirely |
| `tenant_type = supplier` + `SupplierProfile` (lifecycle draft → approved → suspended) | Missing |
| Supplier users via invite on the supplier org + 4 roles (supplier_admin, catalogue_manager, fulfilment, finance) | Only thin `vendor_users` |
| Canonical catalogue (product → variant → pack → identifier → classification) | Products are tenant-owned clones |
| Listing → Offer → Price separation | Price lives on tenant product row |
| Supplier order inbox (ack/ship/invoice, no pay) | Missing |
| Only **Approved** suppliers discoverable | No lifecycle exists |
| Supplier subscription tier + capability flags | Buyer plans only |
| Privacy wall: workspace never sees another's offer/price | To enforce in policy + APIs |

### What Maps Forward (Vendor ≈ Supplier)

- `vendors` integration fields (preferred_protocol, api/cxml/edi/webhook) → **seed** the supplier **connectivity profile** on `supplier_profiles`.
- `vendor_users` → **migrate** to real supplier users via invite flow (S4).
- Existing tenant-scoped `vendors` + `products` stay working during migration; S4 migrates per-tenant masters to canonical + listings.

---

## 3. Target Data Model (new tables)

```
legal_organisations            (platform)  legal_name, reg_no, country, screening
tenants (type=supplier) ──► supplier_profiles   lifecycle: draft→submitted→approved→suspended, trading_name, connectivity
users / roles / user_roles     supplier_admin, catalogue_manager, fulfilment, finance

canonical_products ──► canonical_product_variants ──► canonical_product_packs
product_identifiers (MPN/GTIN at explicit grain) · product_classifications

supplier_product_listings      supplier org scope — supplier_sku → pack_id, list price signal
supplier_product_offers        buyer workspace — listing entitlement (MOQ, lead time) — NO price
supplier_product_prices + supplier_product_price_breaks   buyer workspace — sole price home

supplier_orders · supplier_order_events    (inbox: ack/ship/invoice — no payment, no inventory)

(later) listing_ingest_batches · listing_ingest_candidates
```

---

## 4. Implementation Plan (Sequenced by Dependency)

### Step 1: Supplier CRUD Endpoints (FIRST DELIVERABLE — Phase S0 core)

**Goal:** LegalOrganisation + supplier tenant + SupplierProfile fully creatable, readable, updatable, listable via API.
**Estimate: 1.5–2 weeks**

| # | Task | Files |
|---|---|---|
| 1.1 | Add `LegalOrganisation` model (legal_name, reg_no, country, reg_authority, screening_status, screening_facts JSONB, timestamps) | `provisioning_service/Models.py` |
| 1.2 | Add `supplier` to allowed `tenants.tenant_type` values; add `legal_org_id` FK on tenants (nullable) | `Models.py` + schema update |
| 1.3 | Add `SupplierProfile` model (supplier_tenant_id FK, legal_org_id FK, trading_name, lifecycle_status `draft/submitted/approved/suspended`, connectivity JSONB seeded from vendor integration fields, timestamps) | `Models.py` |
| 1.4 | Pydantic schemas: LegalOrgCreate/Update/Response, SupplierCreate/Update/Response, SupplierProfileUpdate | `provisioning_service/Schemas.py` |
| 1.5 | **CRUD routes — LegalOrganisations:** `POST/GET/GET{id}/PUT/DELETE /provisioning/legal-organisations` (platform-ops only) | `services/suppliers_routes.py` (new) |
| 1.6 | **CRUD routes — Suppliers:** `POST /suppliers` (creates supplier tenant + profile + legal org link atomically), `GET /suppliers` (filter by lifecycle_status), `GET /suppliers/{id}`, `PUT /suppliers/{id}` (profile/trading/connectivity), `DELETE /suppliers/{id}` (soft — suspend) | `services/suppliers_routes.py` |
| 1.7 | Lifecycle transition endpoint: `POST /suppliers/{id}/lifecycle` (submit → approve → suspend, platform-ops approve) | `services/suppliers_routes.py` |
| 1.8 | Permissions: `suppliers.manage`, `suppliers.approve`, `legal_orgs.manage` — seed + OPA policies | `core/helpers/load_permissions.py`, policy files |
| 1.9 | Outbox events: `supplier.created/updated/approved/suspended`, `legal_org.created` | reuse `create_outbox_event` |
| 1.10 | Register router in app; metrics labels per operation | `provisioning_service/main.py` |
| 1.11 | Tests: CRUD happy path, lifecycle transitions, permission denial, unique legal reg_no | `provisioning_service/tests/` |

**Done when:** platform ops can create a legal org, create a supplier org against it, walk it draft → approved, and list/filter suppliers — all audited.

---

### Step 2: Supplier Auth, Users & Roles

**Goal:** Real logins on the supplier org, invite-based, 4 supplier roles. Retire thin `vendor_users` pattern for new suppliers.
**Estimate: 1.5–2 weeks**

| # | Task |
|---|---|
| 2.1 | Seed supplier roles: `supplier_admin`, `catalogue_manager`, `fulfilment`, `finance` + permission matrix |
| 2.2 | Extend invite flow to supplier tenants (reuse buyer invite pattern) |
| 2.3 | Entra/CIAM app registration or multi-tenant policy for supplier logins; JWT tenant_type=supplier claim |
| 2.4 | Hard walls in OPA: supplier tokens cannot read buyer budgets/approvals/offers of other workspaces |
| 2.5 | Migration shim: read-only view mapping legacy `vendor_users` for existing tenants |

---

### Step 3: Canonical Catalogue (Product → Variant → Pack → Identifier)

**Goal:** Platform-scoped product identity suppliers list against.
**Estimate: 2–3 weeks**

| # | Task |
|---|---|
| 3.1 | Models: `canonical_products`, `canonical_product_variants` (axis_values, default), `canonical_product_packs` (qty, UoM, conversion) |
| 3.2 | `product_identifiers` (type: MPN/GTIN/EAN, value, grain: product/variant/pack) + uniqueness per grain |
| 3.3 | `product_classifications` — ZeroQue category spine (platform-scoped, reusable) |
| 3.4 | CRUD routes `/catalogue/canonical/...` (platform-curated; supplier-suggested later) |
| 3.5 | Classification seed + link to existing `categories` |
| 3.6 | Documents/compliance evidence attachable at canonical level, reusable across workspaces |

---

### Step 4: Supplier Product Listings CRUD

**Goal:** Supplier org manages its sell-side catalogue.
**Estimate: 1.5–2 weeks**

| # | Task |
|---|---|
| 4.1 | Model: `supplier_product_listings` (supplier_tenant_id, canonical_pack_id FK, supplier_sku, list_price_minor signal, currency, status, media) |
| 4.2 | CRUD routes `/suppliers/{id}/listings` — scoped to caller's supplier org (`catalogue_manager`) |
| 4.3 | Listing → canonical pack match validation (block publish without match) |
| 4.4 | Listing status lifecycle (draft → active → retired); only active listings of **approved** suppliers visible |
| 4.5 | Blob storage for listing media |
| 4.6 | Outbox events `listing.created/updated/activated` |

---

### Step 5: Buyer Entitlement — Offers & Prices

**Goal:** Workspace-scoped commercial layer, privacy-walled.
**Estimate: 2 weeks**

| # | Task |
|---|---|
| 5.1 | Models: `supplier_product_offers` (buyer_tenant_id, listing_id, moq, lead_time_days, status — **no price**) |
| 5.2 | Models: `supplier_product_prices` (offer_id, unit_price_minor, currency, effective_from/to) + `supplier_product_price_breaks` (min_qty, unit_price_minor) |
| 5.3 | CRUD routes `/offers`, `/offers/{id}/prices` — supplier proposes, buyer accepts (or platform sets) |
| 5.4 | Privacy: OPA + query scoping — workspace sees only its own offers/prices; search/assistant included |
| 5.5 | Remove price authority from `products.purchase_price_minor` for marketplace buys (keep for legacy path) |

---

### Step 6: Buyer Discovery APIs

**Goal:** Buyers find approved suppliers + listings.
**Estimate: 1.5–2 weeks**

| # | Task |
|---|---|
| 6.1 | `GET /discovery/suppliers` — approved only, filter by category/region |
| 6.2 | `GET /discovery/listings` — search canonical catalogue with listing availability |
| 6.3 | Approved-range integration: buy path checks offer + range before PR |
| 6.4 | Intelligence delta: embeddings/search for discovery (never invents price, never approves) |

---

### Step 7: Supplier Order Inbox

**Goal:** PR → PO → supplier messaging without payment or inventory.
**Estimate: 2–3 weeks**

| # | Task |
|---|---|
| 7.1 | Models: `supplier_orders` (po_ref, buyer_tenant_id, supplier_tenant_id, status) + `supplier_order_events` (ack/ship/invoice-metadata) |
| 7.2 | Supplier inbox API: list, ack, ship notice, invoice metadata (`fulfilment`/`finance` roles) |
| 7.3 | PO dispatch into supplier inbox (reuse procurement dispatch concepts) |
| 7.4 | Buyer-side visibility of ack/ship/invoice status on PR/PO |
| 7.5 | **Explicit exclusion check:** no payment fields, no stock fields |

---

### Step 8: Bulk Ingest, Connectivity & Migration (S4)

**Goal:** Scale onboarding, migrate legacy vendors.
**Estimate: 3–4 weeks**

| # | Task |
|---|---|
| 8.1 | `listing_ingest_batches` + `listing_ingest_candidates` — CSV/API bulk listing with match-quality scoring |
| 8.2 | API/EDI connectivity activation from connectivity profile (higher supplier tier) |
| 8.3 | Migration job: per-tenant `vendors` → LegalOrg + supplier tenant + profile; `vendor_users` → invited supplier users |
| 8.4 | Migration job: tenant `products` → canonical products + listings (dedupe on identifiers) |
| 8.5 | Supplier subscription tier in plan matrix (catalogue limits, connectivity add-on) — `load_plans.py` |

---

## 5. Delivery Phases (from deck)

| Phase | Content | Plan Steps | Weeks |
|---|---|---|---|
| S0 | LegalOrg · supplier tenant · auth/roles · lifecycle | Steps 1–2 | 3–4 |
| S1 | Portal shell · profile · Listing CRUD → canonical | Steps 3–4 | 5–7 |
| S2 | Discovery · Offer/Price · range on buy | Steps 5–6 | 4–6 |
| S3 | Order inbox · ack/ship/invoice (no payment) | Step 7 | 4–5 |
| S4 | Bulk ingest · API/EDI · migrate per-tenant masters · supplier plan | Step 8 | 6–8 |

**Gate:** No open buyer discovery until supplier approval + listing→canonical match quality are solid.

---

## 6. Hard Rules (all steps)

1. Suppliers are independent orgs — never a row inside a buyer tenant.
2. Commercial facts (listing/offer/price) never on legal entity or canonical product.
3. Offer carries no price. Price lives only in `supplier_product_prices`.
4. One workspace never sees another's offer/price — enforce in API, search, and assistant.
5. Only **approved** suppliers discoverable.
6. **No inventory tables. No payment/settlement tables.**
7. Everything audited via outbox. Governance (budgets, approvals, ranges) unchanged and reused.
