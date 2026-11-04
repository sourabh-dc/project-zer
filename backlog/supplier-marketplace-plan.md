# ZeroQue Supplier Portal & Marketplace — Implementation Plan

> **Status:** Planning — revised against business spec
> **Date:** 2026-11-04 (supersedes 2026-10-26 version)
> **Based on:** *ZeroQue Supplier Portal — Page & Field Inventory v0.3* (50 pp, Director-reviewed, not locked), ZeroQue Suppliers B2B marketplace deck, and codebase validation (2026-11-04).
> **Scope lock (unchanged):** No payment authoring/settlement (PaymentRemittance is an ERP-sourced read model). No inventory management (availability is advisory only, never blocks orders).

---

## 1. What v0.3 changed vs the old version of this plan

| # | Delta | Impact on this plan |
|---|---|---|
| 1 | **Supplier commercial model defined**: 4 levels (Free / Professional / Business / Enterprise) + capability matrix + processing allowances | Old "supplier subscription tier" step replaced by full §4 model |
| 2 | **Self-registration is allowed** (Free). Only customer *relationships* are invite-only | Step 1 no longer ops-only; adds registration + company-claim flows |
| 3 | **Participation ≠ administration**. Invitation = relationship participant. Account admin needs verified administrator authority (`administration_status`: Unclaimed → Provisional → Verified) | New access layer (§5) |
| 4 | **Three record classes** with separate access tests: supplier-owned / customer relationship / discovery. Plans never appear in access checks | Replaces single "privacy wall" rule |
| 5 | **Compliance evidence library** with share grants + platform-verified badges | New major workstream (was absent) |
| 6 | **Bank details** = highest-risk page: maker/checker, payment hold, previous-contact notification, step-up MFA, masked display | Explicitly deferred to Release 4 (dependency) |
| 7 | **Invoices / credit notes** in scope (portal channel), payments are ERP read-only | Release 4, after ERP adapter read path |
| 8 | **RFQ & quotations** full lifecycle (inbox → clarifications → builder → award → governed price creation) | Release 2+; blocked on buyer-side RFQ spec (§19.5 of the doc) |
| 9 | **Integration workspace** (sources, schedules, transformations, EDI/cXML/API/MCP, failed records) | Professional tier, Release 3 |
| 10 | **Customer-funded capabilities**: funding + access held *per relationship*; one connection can serve many customers, each enablement has its own `funding_source` | Affects connection object design |
| 11 | **Allowances**: metered automation only. Trading, manual uploads, customer-requested uploads, funded traffic, work-in-progress — never metered. Downgrade/non-payment causes **no deletion** | Billing design rules |
| 12 | **Catalogue ingestion moved to Release 1** (Free baseline), not a later step | Re-sequenced |
| 13 | **Supplier roles**: atomic permissions grouped into default roles; `bank.submit` never bundled with `users.manage`; users unlimited + free (no per-seat) | Replaces 4-role plan |
| 14 | **Tokenised no-login order response** retained (D1) | **Already partially built** in orders_service — see §3 |

---

## 2. Vision (updated)

Extend ZeroQue from a buyer-only operating system into a two-sided marketplace where the **supplier portal is a supplier product with its own Free and paid levels** — not a buyer-tier feature.

- One canonical Supplier, one SupplierAccount, many customer relationships (`SupplierRelationship`, workspace-scoped).
- Platform facts maintained once (identity, reusable evidence, listings). Customer facts per relationship (terms, prices, orders, invoices, bank details, requirements).
- **The supplier supplies; the customer governs.** Suppliers submit — customers (or the platform, for shared identity) verify.
- **Commercial entitlement never confers data authority.** Plans buy capability; access is tested per record class.
- **Free participation is never degraded.** Anything a customer needs from a supplier to trade is Free forever.

---

## 3. Validated current state (codebase, 2026-11-04)

| Area | What exists in code | v0.3 verdict |
|---|---|---|
| **Tokenised order response** (§1.4, D1) | `orders_service`: `purchase_requests.vendor_action_token` + `/vendor/{token}/accept|reject` HTML flow; single submission enforced (`vendor_response_status` guard) | ✅ **Partial match.** Gaps: **token never expires** (no expiry column — add ack SLA + 7d), no per-line confirmed qty/date, no "accept with changes", no supplier order ref / respondent capture, no comments. Extend, don't rebuild |
| **Supplier identity (old Step 1 / S0)** | **ALREADY BUILT**: `legal_organisations` (platform-scoped, unique reg index, screening fields), `supplier_profiles` (lifecycle draft→submitted→approved→suspended, connectivity JSONB), `tenant_supplier_connections`, `tenants.legal_org_id`, full routes (`suppliers_routes.py`: legal-org CRUD, supplier CRUD + lifecycle, connect/reconnect), migration `001_suppliers_s0.sql`, outbox events `supplier.created/updated/deleted/lifecycle` | ⚠️ **Extend, don't rebuild.** `LegalOrganisation` ≈ v0.3 canonical Supplier. Gaps vs v0.3: no `SupplierAccount` / `administration_status` (Unclaimed/Provisional/Verified), no claim flow, no entity_type/duns/LEI/parent fields, no two-axis verification (company vs administrator), no trading entities/addresses/contacts |
| **Vendor** | `vendors` — exists **twice**: rich model in `provisioning_service` (api/cxml/edi/webhook endpoints, creds, onboarding_status, payment_terms, lead time, MOQ, tax_id, duns) + thin copy in `orders_service` (id/tenant/name/email) | ⚠️ Tenant-scoped row, not an independent org — v0.3 rejects this. Integration config → seed future `SupplierConnection`. **Flag: two divergent vendor models must be unified in migration** |
| **Vendor users** | `vendor_users` — email+password_hash, roles `vendor_admin`/`vendor_staff` | ❌ Replace with PortalUser + invite flow; migration shim needed |
| **Tenant** | `tenants.tenant_type` — `'supplier'` **already in use** by `suppliers_routes.py` (create + lookup) | ⚠️ Done at model level. No `SupplierAccount` link yet |
| **Supplier events → DIS** | `supplier.*` outbox events emitted by `suppliers_routes.py`; DIS `vendor_handler` consumes `supplier.*` | ✅ Working (fixed Nov 4) |
| **Products** | `products` — tenant-scoped clones (sku/ean/mpn per tenant). `canonical_suppliers`/`canonical_products` exist but are **per-tenant ERP-connector dedupe identities** (deck slice 3), NOT the marketplace catalogue | ❌ No marketplace canonical stack (products→variants→packs, identifiers, classifications). **Name collision: `canonical_products` table already taken** — new marketplace tables need distinct names (e.g. `catalogue_products`) or the connector tables get renamed |
| **Canonical supplier (connector)** | `canonical_suppliers` — tenant-scoped name dedupe | ⚠️ Different concept from v0.3 canonical Supplier. Keep for connector; do not confuse in docs/code |
| **Price** | `products.purchase_price_minor` per tenant | ❌ v0.3: `SupplierProductPrice` (+ breaks), effective-dated, ingested via pipeline only — **never direct writes** |
| **Orders** | PR → PO exists buyer-side; `purchase_requests` has no PO-issue/dispatch objects | ❌ Need PurchaseOrder, SupplierAcknowledgement(+Line), OrderAmendment, Fulfilment… (all "New" per doc §18) |
| **Invoices** | Nothing | ❌ New (Release 4) |
| **Compliance** | Nothing | ❌ New: evidence library, share grants, badges, assessments |
| **RFQ** | Nothing | ❌ New (Release 2+, blocked on buyer-side RFQ spec) |
| **Supplier plan/billing** | Buyer tiers + integration packs only | ❌ New: SupplierSubscription, SupplierEntitlement, UsageMeter, SupplierBillingAccount |
| **Integration workspace** | `tenant_connections` (buyer ERP side) exists | ❌ Supplier-owned sources/connections/transformations are new |
| **Messages** | Nothing object-attached | ❌ New |
| **Outbox/audit, governance (budgets, approvals, ranges)** | Working, DIS pipeline fixed | ✅ Reuse as-is |
| **DIS (graph/vector/derived)** | Working after Nov fixes | ✅ Reuse for: assisted evidence extraction (proposal-only), discovery match reasons, embeddings. **LLM never authors facts, never calculates scorecard metrics** |

---

## 4. Commercial model (v0.3 §0.2 — binding)

### 4.1 Three separate decisions

1. **Buyer subscription** — what the customer bought (buyer plan).
2. **Supplier subscription** — what the supplier bought (SupplierSubscription on the supplier account).
3. **Access** — tested per record class. *A subscription never expands anyone's authority over data.*

Capability rule: capability = (supplier plan includes it **or** the customer funds it for that relationship) **and** customer supports the counterpart **and** the access test passes.

### 4.2 Supplier levels

| Level | Contents (summary) |
|---|---|
| **Free** | Activation + independent registration · discovery profile w/ verified badges (once verified + opted in) · unlimited colleagues · onboarding + required docs · compliance library + sharing · POs, acks, amendments, fulfilment, returns · messages · invited RFQ responses · manual catalogue/price/availability upload w/ mapping, validation, correction · invoices where customer supports |
| **Professional** | Quotation efficiency: saved responses, document packs, templates · standard API + MCP · supported EDI/cXML · scheduled/feed sources · automated catalogue maintenance + enrichment · reusable transformations · automated retry policies · processing allowances |
| **Business** | Quotation automation + internal quote approval · conversion analysis · account + catalogue analytics · demand collaboration (buyer-authorised) · opportunity matching, alerts, commercial analysis · higher allowances |
| **Enterprise** | Bespoke integrations · complex internal workflows · supplier-side SSO · dedicated service |

### 4.3 Allowances (binding rules)

1. Trading is **never** metered or blocked.
2. Customer-requested uploads **never** blocked (flagged on the batch; bypass the meter).
3. Customer-funded traffic measured against the **customer's** entitlement.
4. Nothing in progress is stranded.
5. Hitting an allowance **pauses automation only** — queued with warning, never silently rejected; Free manual route always available.
6. Technical limits (file size, rows/file, rate limits) are separate, equal at every level, published on the technical-limits page, never an upsell lever.
7. Downgrade/non-payment: entitlements change only — **no deletion**. Paid views restore on re-upgrade for data in retention.

### 4.4 Customer-funded capabilities (D16)

- Funding + access held **per relationship**. One `SupplierConnection` may serve several customers; each `SupplierConnectionEnablement` row carries its own `funding_source` + routing authorisation.
- Supplier sees "Funded by [Customer]"; funding customer sees usage for its relationship only.
- Ending is planned: notice + fallback (own plan or portal/email). Orders in flight never stranded.

---

## 5. Access & authority model (binding)

### 5.1 Record classes (one access check per class, at the API)

| Class | Examples | Access test |
|---|---|---|
| **Supplier-owned** | listings, library evidence (unshared), integration estate, quotation library, plan/billing, users | Supplier account membership + permission. Org-admin actions also need **verified administrator** |
| **Customer relationship** | orders, invoices, prices, requirements, assessments, customer docs, RFQs, messages | Customer authorised the relationship + record belongs to it + permission + `portal_access_policy` admits the user |
| **Discovery** | discoverable profile, verified badges, published opportunities, expressions of interest | Explicit publication by owner + viewer's discovery permission. **Only published fields visible** |

Records move between classes only by explicit owner act (share grant, price submission, quotation submission, enablement request, profile publishing). **Never by plan.**

### 5.2 Two separate verifications

| Check | States | Establishes |
|---|---|---|
| Company verification (Supplier identity) | Unverified / Verified | Registered details correct (register-backed or Supplier Data Operations) |
| Administrator authority (`SupplierAccount.administration_status`) | Unclaimed / Provisional / Verified | A named person may administer the account |

- Invitation activation creates a **relationship participant** only — never administration (D26).
- Admin authority via: email-domain match + (posted code | Companies House officer check | existing-customer confirmation) — D23; or authorisation by an existing verified administrator. Verified by **ZeroQue Supplier Data Operations**, target 2 working days manual review (D24).
- Actions needing a verified administrator: grant `users.manage`/admin roles & approve join requests · cross-relationship colleague access · account-wide evidence sharing policy · shared identity changes · publish discovery profile · buy/change/cancel plan · all-customer service accounts.

### 5.3 Relationship access policy (`SupplierRelationship.portal_access_policy`)

- **Supplier-managed** (default): verified admin adds colleagues; customer notified, can revoke.
- **Customer-approved**: additions need a customer user with `supplier.portal.invite`.
- Until the account has a verified administrator, everything follows Customer-approved.
- Customer can always revoke a user. Removing a user removes all customer access at once.

### 5.4 Supplier-side roles (atomic permissions, default role bundles)

Portal admin (verified admin) · Relationship participant (invitation default) · Account manager · Order desk · Warehouse/dispatch · Accounts receivable · Catalogue manager · QHSE/compliance · Bid/sales manager · Integration manager · Billing administrator · Read-only.

Binding: (1) `bank.submit` **never** bundled with `users.manage`; (2) granting `bank.submit` needs a second portal admin or customer confirmation; (3) customer access follows the relationship policy; (4) `billing.manage` separate from `users.manage`; (5) machine principals (ServiceAccount) never get `bank.submit`, `users.manage`, `billing.manage`; (6) users unlimited, no per-seat charge (D13).

---

## 6. Target object model (doc §18, mapped)

**Accounts / access / commercial:**
`Supplier` (canonical, register-backed — old plan's LegalOrganisation maps here) · `SupplierAccount` (1:1, plan, administration_status) · `SupplierAccountClaim` (append-only) · `PortalUser` (platform, → many SupplierContact) · `ServiceAccount` (API/MCP/webhook principals) · `RelationshipParticipation` (effective-dated) · PortalRole + supplier-side permissions · `SupplierInvitation` (workspace, purpose, expiry, onboarding due date) · `SupplierRelationship.portal_access_policy` · `SupplierSubscription` · `SupplierEntitlement` (single source UI+API read) · `CustomerFundedEntitlement` (workspace) · `UsageMeter`/`UsageRecord` · `SupplierBillingAccount`.

**Profile / identity / evidence:**
`SupplierProfile` (description, logo, turnover/employee bands, discovery_opt_in) · `SupplierChangeRequest` (fan-out, before/after) · `SupplierIdentityChangeRequest` · `EvidenceShareGrant` (reusable evidence → one relationship) · `EvidenceBadge` (platform verification, independent of customer assessment).

**Trading:**
`PurchaseOrder`/`…Line` (version-bound) · `SupplierAcknowledgement`/`…Line` · `OrderAmendment` · `FulfilmentAcknowledgement`/`FulfilmentLine` (batch/lot capture — needed for safety events) · `ReceiptDiscrepancy`, `ReturnRequest` · `Invoice`/`InvoiceLine`, `CreditNote`/`…Line` · `PaymentRemittance` (**ERP read model, never authored**) · `RFQ`, `RFQLine`, `RFQDocument`, `RFQInvitation`, `RFQClarification`, `RFQAddendum` · `Quotation`/`QuotationLine`/`QuotationLinePriceBreak`/`QuotationAlternative` (versioned) · `RFQAward`/`…Line` → feeds `SupplierProductPrice` (`price_source = Quotation`) · `Opportunity`, `OpportunityInterest` · `DemandShare` · `MessageThread`/`Message` (object-attached only).

**Catalogue (from old plan, still valid):**
`canonical_products` → `canonical_product_variants` → `canonical_product_packs` · `product_identifiers` (MPN/GTIN at explicit grain) · `product_classifications` · `supplier_product_listings` (supplier SKU → pack, supplier-asserted identifiers S-verified) · `supplier_product_offers` (workspace entitlement, MOQ/lead time, **no price**) · `supplier_product_prices` + `_price_breaks` (sole price home, effective-dated) · `SupplierProductAvailability` (advisory).

**Integration:**
`IntegrationSource`, `IntegrationSchedule` · `TransformationDefinition` (versioned; generalises ProductIngestionRule to supplier ownership) · `SupplierConnection` + `SupplierConnectionEnablement` (workspace row, own `funding_source`) · `IntegrationRun`, `FailedRecord`.

**Buyer-side counterpart screens (main app):** invite-to-portal · access policy · change-request queue · evidence verification queue · bank verification queue · acknowledgement exceptions · price variance review · RFQ creation/evaluation/award · discovery settings + directory · demand sharing settings · funded capabilities · Supplier Data Operations queues (identity, claims, badges).

---

## 7. Implementation plan (re-sequenced to doc §21 build order)

### Release 1 — Free foundation *(useful product for every invited supplier)*

| # | Workstream | Tasks | Notes |
|---|---|---|---|
| R1.1 | **Extend S0 identity → v0.3 model** | **Build on existing** `legal_organisations`/`supplier_profiles`/`tenant_supplier_connections`/routes. Add: entity fields (entity_type, duns, LEI, parent, country already there), `identity_verification_status` (Unverified/Verified) alongside screening_status; `SupplierAccount` (1:1, `administration_status` Unclaimed/Provisional/Verified, plan, settings); `SupplierTradingEntity`, `SupplierAddress`, `SupplierContact`; keep `supplier.*` outbox events | S0 exists — extend. Platform-ops create; self-service arrives R2 |
| R1.2 | **Invitation activation** (§1.1–1.3) | `SupplierInvitation` (token, purpose, expiry 14d default, onboarding_due_date); landing page API; PortalUser + MFA (mandatory — bank details route); existing-account detection → link, don't duplicate; activation = `RelationshipParticipation` for inviting customer only; account created `Unclaimed` | Reuse buyer invite pattern |
| R1.3 | **Administrator verification for invitation accounts** (§1.6) | `SupplierAccountClaim` (append-only): role, declaration, method (domain match + code/officer check/customer confirmation D23), evidence refs, status; Supplier Data Operations queue; alternative: existing verified admin authorises | Until live, colleague additions follow Customer-approved route |
| R1.4 | **Colleagues, roles, access policy** (§12.1–12.2) | Supplier-side permission set + default roles (§5.4); `portal_access_policy` on relationship; invite/edit user with customer multi-select scoped to admin's reach; binding rules 1–4 | Replaces `portal_access_level` enum |
| R1.5 | **Orders: list, detail, acknowledge, amendments** (§7.1–7.4) | `PurchaseOrder`/`…Line` (version-bound), `SupplierAcknowledgement(+Line)` (per-line qty/date/substitute/charges; controlled rejection reasons), `OrderAmendment`; supplier-facing status mapping (§17); PO issue from existing PR flow | Extends current PR → vendor flow. "Accept as issued" → Commercially Locked |
| R1.6 | **Tokenised order response hardening** (§1.4) | Add token expiry column (ack SLA + 7d) — single-submission already enforced; per-line confirmed qty/date; supplier order ref; respondent name/email (evidence, not login); comments; "create portal account" prompt | **Build on existing orders_service code** |
| R1.7 | **Basic onboarding** (§3.1–3.2, §4.1, §4.3–4.4, §5.3) | Readiness-driven onboarding overview per customer; wizard (find company → identity → capabilities → addresses → contacts → tax → [bank, deferred] → docs → submit); addresses/contacts with fan-out selector (per-relationship audited changes); customer requirements view + customer-specific docs | Readiness endpoint is the driver — portal never builds its own requirement list |
| R1.8 | **Manual catalogue ingestion** (§9.1–9.6) | Canonical stack (products/variants/packs/identifiers/classifications); `supplier_product_listings` CRUD; `ProductIngestionBatch` pipeline: upload → interactive column mapping (saved maps) → validation preview → batch → row outcomes → in-browser correction → error report; price files effective-dated, no backdating; offers/prices objects (no direct writes) | Free baseline. Old Steps 3–5 + upload UX |
| R1.9 | **Messages** (§11.1) | `MessageThread`/`Message` object-attached; bank-detail pattern scan → redirect to §4.6 | No free-floating chat |
| R1.10 | **Plan overview (Free)** (§15.1) | `SupplierSubscription` (Free), `SupplierEntitlement` resolver (single read source for UI + API) | Billing screens come R3 |

### Release 2 — Free completion

| # | Workstream | Tasks |
|---|---|---|
| R2.1 | **Dispatch, delivery, returns** (§7.5–7.7) | `FulfilmentAcknowledgement`/`FulfilmentLine` (partial dispatch, batch/lot mandatory where required, serials, expiry, origin), POD, goods-receipt read model + `ReceiptDiscrepancy`, `ReturnRequest` (RMA flow) |
| R2.2 | **Compliance library + sharing** (§5.1–5.4) | `SupplierComplianceEvidence` (controlled doc types, reusability default), versioning (renew never overwrites), `EvidenceShareGrant` (per relationship, revoke keeps assessed versions), sharing policy (auto/ask/private), customer requirement match preview, assisted extraction via DIS (**proposal-only, supplier confirms**) |
| R2.3 | **Independent registration + all claim routes + identity change** (§1.5, §1.6, §4.1) | Self-registration (Free; creates account only — no relationship, no visibility); duplicate check; join requests; shared identity changes (S): register-backed auto-apply vs Supplier Data Operations review; succession link for legal-personality change; customer notifications + per-relationship response rules |
| R2.4 | **Invited RFQ response** (§13.1–13.5) | RFQ inbox/detail (docs viewer + watermark), NDA gate, clarifications (public-by-default answers, asker anonymised — D17), addenda ack, quotation builder + revisions (unlimited before deadline), no-bid per line, alternatives, CSV line-sheet upload, sealed-bid flag (D18), outcome + award feedback | **Blocked on buyer-side RFQ spec (§19.5) — write it first** |

### Release 3 — Professional + Free discovery

| # | Workstream | Tasks |
|---|---|---|
| R3.1 | **Plan, usage, billing** (§15) | Levels + entitlement matrix; `UsageMeter`/`UsageRecord` (automation-only meters, §4.3 rules); downgrade impact preview + binding downgrade behaviour; retention policy (no deletion); `SupplierBillingAccount` + ZeroQue invoices; needs verified administrator for plan changes |
| R3.2 | **Quotation library** (§13.6 Pro rows) | `QuotationSavedResponse`, `DocumentPack`, `QuotationTemplate` |
| R3.3 | **Discovery profile + verified badges** (§4.9, §5.5) | Opt-in (verified admin only, eligibility check); published-field selection; buyer preview; never-published list (§16 of doc §4.9); `EvidenceBadge` (Supplier Data Operations verifies against issuer registers; wording "Verified: …", never "Certified"); buyer-side directory |
| R3.4 | **Integration workspace** (§14) | `IntegrationSource` (SFTP/feed/API-push/email-in/EDI-PRICAT/PIM), `IntegrationSchedule`, `TransformationDefinition` (versioned, test-against-sample), `IntegrationRun`/`FailedRecord` (plain-language errors, retry); API keys/MCP clients/webhooks as `ServiceAccount` (human confirmation for quote submission + changed acks — D22); health overview |
| R3.5 | **EDI/cXML connections + customer funding** (§14.5) | `SupplierConnection` + per-relationship `SupplierConnectionEnablement` (funding_source, routing status Requested→Testing→Live); test harness; routing change requests to customer; `CustomerFundedEntitlement`; "Funded by [Customer]" surfacing |

### Release 4 — dependency-led

| # | Workstream | Tasks | Dependency |
|---|---|---|---|
| R4.1 | **Bank details** (§4.6) | `SupplierBankDetail` (encrypted, modulus/IBAN checks, masked last-4 only), versioning, maker/checker (`verified_by ≠ created_by` structural), automatic payment hold, previous-contact notification (cannot be switched off), step-up MFA to open + submit, 14-day contact-change risk flag (D5), never-shown internals (fingerprints, unmask counts, verifier, target) | Buyer-side maker/checker + payment hold + notification proven |
| R4.2 | **Invoices, credit notes, payments view** (§8) | `Invoice`/`InvoiceLine` (create-from-PO default, tolerance flags, duplicate check, remit-to from verified default, **bank account never editable on invoice**), `CreditNote`, status across channels (Portal/Email PDF/Peppol/EDI), `PaymentRemittance` ERP read model, statement of account | ERP adapter read path. Free once delivered |

### Release 5 — Business & Enterprise

| # | Workstream | Tasks |
|---|---|---|
| R5.1 | Quotation automation (auto-fill, confirm-before-submit), internal quote approval, conversion analysis (§13.6 Business rows) |
| R5.2 | Account + catalogue analytics (§10.2–10.3) — own transactions with authorising customers only; buyer search activity only where customer shares |
| R5.3 | Demand collaboration (`DemandShare`, §10.4) |
| R5.4 | Opportunity matching, alerts, commercial analysis (`Opportunity`, `OpportunityInterest`, §13.7) — buyer publishes; Graph-based match reasons over declared data + verified badges |
| R5.5 | Scorecard (§10.1) — **only after metric definitions locked**; deterministic governed views, never LLM-calculated; per customer, no cross-customer ranking |
| R5.6 | Enterprise: bespoke integrations, multi-entity quote workflows, supplier-side SSO, dedicated service |

**Gate (unchanged principle):** no open buyer discovery until supplier verification + listing→canonical match quality are solid.

---

## 8. Hard rules (updated, all binding)

1. Suppliers are independent orgs — never a row inside a buyer tenant. Self-registered accounts are fine; **relationships only ever come from a customer action**.
2. Commercial facts never on the legal entity or canonical product. Offer carries no price; price lives only in effective-dated `SupplierProductPrice`.
3. **Plans never appear in access checks.** Access = record class test (§5.1). Capability = plan/funding + counterpart support + access.
4. Supplier submits, customer/platform verifies — maker/checker everywhere (bank, evidence, prices, shared identity). `verified_by ≠ created_by` structurally.
5. Free trading is never degraded, metered or blocked; downgrade/non-payment never deletes.
6. Only verified, opted-in suppliers discoverable; badges state document currency only — never "approved supplier", never a customer's acceptance.
7. No payment authoring (ERP read model only). No inventory management (availability advisory).
8. The supplier never sees the §17 list: risk tiers, screening results, internal approvals, credit balance/headroom, hold reasons (raw), bank-control internals, benchmarks/competitor offers, other suppliers' RFQ activity, other customers' existence, buyer-internal data. Enforced at the API, not the UI.
9. Intelligence Service proposes, never authors: extraction is proposal-only with human confirmation; scorecards are deterministic; discovery match reasons come from declared data + verified badges only.
10. Everything audited via outbox; fan-out edits land as separate per-relationship audited changes.

---

## 9. Open items carried from the doc

- **Buyer-side RFQ specification (§19.5)** — must be written before Release 2 RFQ work (creation → clarification → quotation → evaluation → award → governed price creation). Owner: product + backend.
- **Cross-doc changes (§19.1–19.4)** — Supplier Schema v1.2, Product Schema, Pricing Architecture (supplier product line, customer-funded connectivity, RFQ buyer tier = Growth+ proposed — D19), Roles architecture (supplier-side roles, Supplier Data Operations platform role).
- **Open decisions:** D19 buyer RFQ tier · D20 residual (can Free suppliers browse opportunities manually — recommend not v1) · D7 account-reference label · D6 reference-mode bank pass-through (not v1) · D10 contract e-signature (not v1).
- **Metric definitions** (OTIF, acknowledgement compliance) must be locked before scorecard (R5.5).

---

## 10. Migration (legacy vendors) — unchanged goals, re-sequenced

- **Two `vendors` models exist** (rich in `provisioning_service`, thin in `orders_service`) — unify during migration; orders_service rows must resolve to the same identity.
- `vendors` integration config (api/cxml/edi/webhook) → seed `SupplierConnection` on the supplier account.
- `vendor_users` → invited PortalUsers (read-only shim during transition).
- Tenant `vendors`/`products` → canonical Supplier + listings (dedupe on identifiers) via ingestion batches/candidates.
- **Table-name collision:** marketplace catalogue tables must not reuse `canonical_products`/`canonical_suppliers` (taken by the ERP-connector dedupe slice) — pick distinct names (e.g. `catalogue_products`) or rename connector tables first.
- Existing S0 objects (`legal_organisations`, `supplier_profiles`, `tenant_supplier_connections`) carry forward into R1.1 as-is.
- Runs alongside R3–R5; existing buyer-side vendor flow keeps working until cutover.
