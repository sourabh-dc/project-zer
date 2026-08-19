# ZeroQue — Pricing Architecture Implementation Roadmap

> **Status:** Implemented | **Last updated:** 2026-08-18
> Based on: *ZeroQue Pricing Architecture v1.2* (Internal Commercial Framework)

---

## 1. Core Principles

- ZeroQue is priced around **depth of governed procurement control**, not number of users.
- **Operating Scale** (one org running at scale) ≠ **Distributor Platform** (running many customer environments).
- Integration depth is a **paid lever** — not given away too early.
- Enterprise should never need Distributor Platform just to run its own sites or connect its own ERP.

---

## 2. The 5 Tiers

| Tier | Monthly | Users | Positioning |
|---|---|---|---|
| **Starter** | £149 | 5 | Simple controlled procurement |
| **Growth** | £399 | 15 | Governed procurement for SMEs |
| **Business** | From £950 | 40 | Multi-site control + supplier orchestration |
| **Enterprise** | From £2,750 | 100 | Full control-plane deployment |
| **Distributor Platform** | POA | Custom | Multi-tenant platform leverage |

---

## 3. Gap Analysis vs Current Codebase

| # | Requirement | Current State | Status |
|---|---|---|---|
| 1 | 5-tier plan structure | `load_plans.py` seeds 5 plans + 41 features + 113 mappings | ✅ Done |
| 2 | Capability-to-tier gating | Enforced at runtime via `require_policy` + quota loaders + `check_feature_limit` (Phase A2) | ✅ Done |
| 3 | Sub-tenant / multi-tenant model | `parent_tenant_id` + full sub-tenant CRUD + hierarchy endpoint (Phase C1) | ✅ Done |
| 4 | Integration packs (paid add-ons) | Modelled + Stripe checkout/webhooks (Phase B) | ✅ Done |
| 5 | Per-tier active-user enforcement (5/15/40/100) | `enforce_active_user_limit()` + seat blocks raise limit (Phase A1/D2) | ✅ Done |
| 6 | Operating Scale vs Distributor distinction | Distributor-only features gated: `multi.tenant.management`, `cross.tenant.analytics`, `white.label`, `shared.integration.hub` | ✅ Done |
| 7 | White-label / branded experience | `TenantBranding` model + branding API + frontend applies theme (Phase C3) | ✅ Done |
| 8 | Cross-tenant analytics | `GET /tenants/{id}/analytics/cross-tenant` aggregates sub-tenant usage (Phase C2) | ✅ Done |

---

## 4. Six Capability Groups (source of truth)

### Group 1 — Core Procurement Control (Starter+)
Request capture, approvals workflow, orders/PO orchestration, supplier records, product/service records, evidence & audit trail, organisational memory.

**Status:** ✅ Features seeded (`request.capture`, `approvals.workflow`, `orders.orchestration`, `supplier.records`, `product.records`, `evidence.trail`, `audit.trail`, `org.memory`)

### Group 2 — Governance & Control (Growth+, deeper at Business/Enterprise)
Cost centres, budget controls, approved ranges, approval policies, role-based permissions, commercial lock, compliance & audit, exception management, policy enforcement, risk rules & thresholds.

**Status:** ✅ Features seeded (`cost.centres`, `budget.control`, `approved.ranges`, `approval.policies`, `commercial.lock`, `role.permissions`, `exception.management`, `policy.enforcement`, `risk.rules`)

### Group 3 — Supplier Orchestration (Business+)
Email supplier workflows, supplier acknowledgements, delivery/fulfilment tracking, API integrations (paid at Business, included Enterprise), cXML/EDI (paid at Business, included Enterprise), marketplace handoff.

**Status:** ✅ Features seeded (`email.supplier`, `supplier.acknowledgements`, `fulfilment.tracking`, `api.integration`, `cxml.edi`, `marketplace.handoff`). ⚠️ Integration **packs** (pricing) not yet modelled.

### Group 4 — Intelligence Layer (Enterprise standard, optional Business)
Contextual intelligence, product comparisons, alternative suggestions, supplier risk insights, derived knowledge layer, graph relationship visibility, advanced reasoning/guided actions.

**Status:** ✅ Features seeded (`contextual.intelligence`, `product.comparisons`, `alternative.suggestions`, `supplier.risk`, `derived.knowledge`, `graph.visibility`, `advanced.reasoning`)

### Group 5 — Operating Scale (Business/Enterprise)
Multi-location, multi-site, ERP/finance integration, SSO & advanced security, high availability, custom workflow support, priority support/SLA.

**Status:** ✅ Features seeded (`multi.location`, `multi.site`, `erp.integration`, `sso.security`, `high.availability`, `custom.workflow`, `priority.support`)

### Group 6 — Distributor Platform (Distributor only)
Multi-tenant management, customer-environment management, shared integration hub, cross-tenant analytics, white-label/branded experience.

**Status:** ✅ Features seeded (`tenant.subtenant.model`, `multi.tenant.management`, `customer.environment.management`, `shared.integration.hub`, `cross.tenant.analytics`, `white.label`)

---

## 5. Full Capability-to-Tier Matrix

| Capability | Starter | Growth | Business | Enterprise | Distributor |
|---|---|---|---|---|---|
| Basic purchase requests | Yes | Yes | Yes | Yes | Yes |
| Basic approvals | Yes | Yes | Yes | Yes | Yes |
| Supplier records | Basic | Yes | Yes | Yes | Yes |
| Evidence trail | Basic | Basic | Advanced | Advanced | Advanced |
| Cost centres | Limited | Yes | Yes | Yes | Yes |
| Budget control | No/light | Yes | Yes | Advanced | Advanced |
| Approved ranges | No/light | Yes | Yes | Advanced | Advanced |
| Approval policies | Basic | Yes | Advanced | Advanced | Advanced |
| Commercial lock | Limited | Yes | Yes | Advanced | Advanced |
| Audit trail | Basic | Yes | Advanced | Advanced | Advanced |
| Supplier acknowledgements | No/limited | Yes | Advanced | Yes | Yes |
| Fulfilment acknowledgements | No | Limited | Yes | Advanced | Advanced |
| API / cXML / EDI | No | Optional | Paid add-on | Included | Included |
| Multi-location / multi-site | No/limited | Limited | Yes | Advanced | Advanced |
| ERP / finance integration | No | Optional | Optional | Yes/Advanced | Yes |
| SSO & advanced security | No | No | Optional | Included | Included |
| High availability | No | No | No | Included | Included |
| Intelligence in context | Basic/none | Optional add-on | Optional | Yes/Advanced | Advanced |
| Graph relationship visibility | Limited | Limited | Limited | Yes | Advanced |
| Tenant / sub-tenant model | No | No | Limited | Optional | **Core** |
| Custom workflow support | No | Limited | Yes | Advanced | Advanced |
| Security / SLA / support | Standard | Standard | Enhanced | Premium | Premium |
| Implementation support | Light | Guided | Project-based | Platform rollout | Platform rollout |
| Multi-tenant management | No | No | No | No | **Defining** |
| Customer-environment management | No | No | No | No | **Defining** |
| White-label / branded experience | No | No | No | No | **Defining** |

---

## 6. Integration Logic (paid lever)

| Tier | Included | Paid Add-On |
|---|---|---|
| Starter | — | None |
| Growth | Basic (email/PDF/CSV) | Standard Pack: ERP connector + structured import, **from £150/mo** |
| Business | Standard Pack | Advanced Pack: API/cXML/EDI/marketplace, **from £400/mo** |
| Enterprise | Advanced Pack (standard) | Enterprise Pack: custom middleware + monitoring, **£1,000-£3,000+/mo** |
| Distributor | Shared integration hub | Per-scope connections, quoted |

**Status:** ⚠️ Partial — integration packs are now modelled as billable add-ons (B1) with features bundled under Standard/Advanced (B2), but are NOT yet wired to Stripe checkout/webhook (B3). Currently `api.integration`, `cxml.edi`, `marketplace.handoff` are boolean features gated by pack subscription rather than by a priced Stripe add-on.

---

## 7. Remaining Work (Roadmap)

### Phase A — Runtime Feature Enforcement (high priority)
| Step | Task | Status |
|---|---|---|
| A1 | Enforce `active.users` limit per plan (5/15/40/100) — block user creation when exceeded | ✅ `enforce_active_user_limit()` counts real user rows; wired into `POST /provisioning/invitations` + invitation-accept path in `auth_routes.py` |
| A2 | Gate features by plan at runtime (OPA or middleware) | ✅ Vendors → `supplier.records` (10/25/100/500); Cost centres → `cost.centres` (2/10/50/200); Sites → `multi.site` (first-free); Stores → `multi.location` (first-free); Catalog → `product.records`. Feature codes aligned with seeded plans in `resource_loaders.py` / `catalog_routes.py` / `provisioning_routes.py` |
| A3 | Expose plan features in sign-in response for frontend gating | ✅ `subscription.features`, `subscription.feature_limits` (with `active.users` reflecting real seat count) and `rbac.feature_flags` returned on login + `whoami`; full login response now persisted client-side |

### Phase B — Integration Packs as Billable Add-Ons (high priority)
| Step | Task | Status |
|---|---|---|
| B1 | Model integration packs (Standard/Advanced/Enterprise) as purchasable add-ons | ✅ `IntegrationPack` / `IntegrationPackFeature` / `TenantIntegrationPack` models + `INTEGRATION_PACKS` + `INTEGRATION_PACK_FEATURES` seeds + `/v1/integration-packs` routes (auth wired via `check_user_authorization`) |
| B2 | Bundle API/cXML/EDI/marketplace under the Advanced Pack | ✅ Advanced Pack → `api.integration`, `cxml.edi`, `marketplace.handoff`; Standard Pack → `erp.integration`. `load_tenant_features()` merges pack features at runtime |
| B3 | Add pack pricing to Stripe subscription flow | ✅ Checkout endpoint (`POST /payments/create-pack-checkout-session`) + webhook routing (`checkout.session.completed`, `customer.subscription.updated/deleted`, `invoice.paid/failed`) + cancel endpoint. Pack prices seeded (£150/£400/£1,000). **Requires real Stripe `price_xxx` IDs** in `load_plans.py` + webhook registration |

### Phase C — Distributor Platform (medium priority)
| Step | Task | Status |
|---|---|---|
| C1 | Complete sub-tenant CRUD + hierarchy management | ✅ `POST/GET/PATCH/DELETE /tenants/{id}/sub-tenants` + `GET /tenants/{id}/hierarchy`; depth guard (1 level); gated on `multi.tenant.management` |
| C2 | Cross-tenant analytics | ✅ `GET /tenants/{id}/analytics/cross-tenant` — per-sub-tenant users/sites/stores/vendors/cost-centres/PR spend + totals; gated on `cross.tenant.analytics` |
| C3 | White-label / branded experience | ✅ `TenantBranding` model + `GET/PUT/DELETE /tenants/{id}/branding` + `GET /public/branding?domain=`; gated on `white.label`; frontend applies colours/logo/name after login |
| C4 | Shared integration hub | ✅ `shared_with_subtenants` flag on `TenantIntegrationPack`; `POST .../integration-packs/{code}/share` toggle; `load_tenant_features()` merges parent's shared packs into sub-tenants |

### Phase D — Commercial Posture (when going live)
| Step | Task | Status |
|---|---|---|
| D1 | Annual discount + "two months free" anchor | ✅ Yearly price = 10 × monthly (16.67% off); plans API returns `pricing.yearly.anchor` + `savings_minor`; frontend shows savings line |
| D2 | Additional-user block pricing | ✅ `TenantSeatBlock` + per-plan `seat_block_size`/`seat_block_price_minor` seeds; `POST /payments/create-seat-block-checkout-session` + list/cancel + webhook handlers; blocks raise `enforce_active_user_limit()` effective limit |
| D3 | Implementation fee guardrails | ✅ `implementation_fee_minor` on `PlanPrice` (£0/£0/£1,500/£5,000/POA); added to checkout metadata; one-time Stripe invoice item on checkout completion; surfaced in plans API + frontend |
| D4 | Public vs sales-only pricing decision | ✅ `is_public` flag on plans (Starter/Growth/Business public; Enterprise/Distributor sales-only); `GET /plans` filters by default, `?include_private=true` to override |

---

## 8. Open Decisions (from v1.2 — still unresolved)

1. Should Starter/Growth pricing be publicly listed on the website?
2. What volume bands should be finalised?
3. What additional-user block pricing?
4. Should advanced intelligence be a standard Business add-on, or sales-led upsell?
5. Implementation fee ranges for Business/Enterprise/Distributor?
6. Annual contract discount structure?
7. Is "two months free" the right annual anchor?
8. When to review pricing?
9. Revisit after first 5–10 prospect conversations per tier?

---

## 9. Summary

| Metric | Value |
|---|---|
| **Tier model** | ✅ Done (5 plans, 41 features, 113 mappings) |
| **Capability groups** | ✅ All 6 groups seeded |
| **Runtime enforcement** | ✅ Done (Phase A — user limits + feature gating) |
| **Integration packs** | ✅ Done (Phase B — billable via Stripe) |
| **Distributor Platform** | ✅ Done (Phase C — sub-tenants, analytics, white-label, shared hub) |
| **Commercial posture** | ✅ Done (Phase D — annual anchor, seat blocks, implementation fees, plan visibility) |
| **Remaining ops work** | Register Stripe webhook endpoint; verify seeded Stripe `price_xxx` IDs; DNS/SSL for white-label custom domains |
