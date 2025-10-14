<!-- 72fcfecf-1f95-49d6-877e-df0d16adf7db 9810505e-ab41-4207-8c73-d2563fbe00bf -->

# ZeroQue Frontend V1 – Scope and Hiring Brief

## Objective

Deliver a production-grade frontend spanning three portals that integrates all ZeroQue services:

- Unified Admin Console (internal ops + merchant admin)
- Merchant Portal (catalog, pricing, orders, subscriptions, billing)
- End-Customer Portal (shopping, checkout/payments, order tracking, entry codes)

## Recommended Tech Stack (hiring baseline)

- Framework: Next.js 14 (App Router) + React 18 + TypeScript
- Styling: Tailwind CSS + Headless UI (Radix UI as needed), CSS Modules for edge cases
- State/Data: TanStack Query (server-cache), Zustand (local UI state)
- Forms/Validation: react-hook-form + zod
- API: REST-first via typed clients (openapi-typescript where available) or a typed fetch/axios wrapper
- Realtime: WebSocket/SSE (notifications/events service) via standardized hook
- Testing: Vitest + React Testing Library, Playwright (E2E), Storybook (components)
- Quality: ESLint (Airbnb+React+TS), Prettier, Husky + lint-staged, Commitlint (Conventional Commits)
- Observability: Sentry (errors) + Web Vitals (Perf), analytics via PostHog/GA4 (optional)
- CI/CD: GitHub Actions (PR checks, preview deploys), Vercel/Netlify (previews) or container deploy

## Environment & Integration

- Config: .env files per environment; central `config/env.ts` exporting service base URLs
- Local API routing: Next.js rewrites to backend ports (provisioning 8000, subscriptions 8212, entitlements 8003, catalog 8005, pricing 8007, payments, orders, identity, ledger, notifications, events, usage, etc.)
- Auth: JWT from identity service in httpOnly cookie + CSRF token; API key flows allowed in dev/demo
- Rate limits: UI throttling + exponential backoff; surface 429 user-friendly messages
- Multi-tenancy: Tenant context from JWT; explicit tenant selector for admins

## Information Architecture & Routes

- Admin Console (`/admin`)
- Overview dashboard (health, events, errors, rate limits) – embed metrics from observability/monitoring
- Tenants (/admin/tenants): list/create/manage; users & roles; sites/stores
- Approvals (/admin/approvals): chains, requests, resolutions
- Notifications (/admin/notifications): templates, deliveries, channels
- Service Registry (/admin/services): endpoints, health, versions
- Events & Outbox (/admin/events): bus activity, dead letters, retries
- Audit Logs (/admin/audit): filter by tenant/user/service
- Merchant Portal (`/merchant`)
- Catalog: products, variants, categories
- Pricing: pricebooks, rules; simulation tool
- Subscriptions & Entitlements: plans, assignments, usage
- Orders: list/details, fulfillment status
- Billing: invoices, settlements
- Reports: standard reports
- End-Customer (`/app`)
- Catalog browse/search
- Cart & Checkout (payments)
- Orders: history, status
- Entry Codes: issue/validate for pickup

## UX/Component Scope (high-level)

- Foundations: App shell (topbar/sidebar), breadcrumb, page header, layout grid, theme tokens
- Data components: DataTable (sorting/filter/pagination), Empty/Loading/Error states, JSON viewer for debug
- Forms: Create/Edit forms with RHF+zod; inline validation; optimistic updates where safe
- Feedback: Toaster, modal, drawer, stepper, skeletons
- Charts: Lightweight charts for KPIs (orders, revenue, usage)

## API Surface (consumed by frontend)

- Identity: login/refresh/logout, user profile, permissions
- Provisioning: tenants/sites/stores/users/roles CRUD
- Catalog: products/variants/categories
- Pricing: pricebooks/rules, price compute endpoint
- Orders: CRUD/list/detail, status transitions
- Payments: create payment intent, capture, refund
- Subscriptions: plans, subscribe/unsubscribe
- Entitlements/Usage: assignment, usage listing
- Billing: invoices, settlements
- Approvals: create/view/resolve
- Entry: issue/validate code
- Ledger: entry list/detail, entry creation events
- Notifications: templates, delivery events, websocket/SSE endpoint
- Events: event feed (for admin views)
- Reports: standard downloadable endpoints
- Service Registry/Monitoring/Observability: health/metrics endpoints for admin dashboards

Note: Implement a typed `apiClient` wrapper with:

- Base URL per service
- Auth headers from cookie/CSRF
- Automatic retry/backoff on 429/5xx
- Error normalization and logging hooks

## Security & Compliance

- JWT in httpOnly cookie + CSRF token header
- RBAC in UI: hide/disable actions without permission
- PII handling: avoid logging sensitive fields; mask in UI
- A11y: WCAG 2.1 AA (keyboard, color contrast, aria labels)
- i18n ready via i18next (en-US default)

## Performance Budgets

- FCP < 2.0s on 3G; TTI < 3.5s
- Route chunk < 200KB gzipped, above-the-fold < 100KB
- Image optimization via Next/Image; code-splitting for heavy modules

## Deliverables (V1)

- Three production-ready portals with navigation, auth, and core flows implemented
- Shared design system and component library
- Typed API client with service modules
- E2E smoke tests for critical flows (login, CRUD, checkout, entry code)
- CI pipeline with previews; env configs
- Runbook + README for local dev and deployments

## Milestones & Estimates

- Week 1: Project setup, auth, shell, API client, base routes
- Week 2: Admin Console (tenants, users/roles, events, audit)
- Week 3: Merchant (catalog, pricing, orders)
- Week 4: Merchant (subscriptions, entitlements, billing)
- Week 5: End-Customer (catalog/checkout/orders/entry)
- Week 6: Hardening (tests, perf, accessibility, docs)

## Hiring Profile (Job Description Snippet)

- 5+ years building React/Next.js apps with TypeScript
- Strong with TanStack Query, React Hook Form, zod
- Comfortable with REST APIs, auth (JWT, CSRF), RBAC
- Experience integrating complex backends/microservices
- Realtime UX (WebSocket/SSE), optimistic UI, background sync
- Testing at multiple layers (unit/integration/E2E), Storybook
- Performance, accessibility, and security best practices
- Nice-to-have: Tailwind, Headless UI/Radix, Sentry, Vercel, OpenAPI tooling

## Acceptance Criteria

- Auth flows secure with httpOnly cookies + CSRF; roles enforced in UI
- All core pages render data from live services with loading/error handling
- Critical CRUD and checkout flows pass E2E tests
- Observability hooks in place (Sentry, Web Vitals)
- Meets performance and accessibility targets

### To-dos

- [ ] Scaffold Next.js 14 TS app, base layout, Tailwind, ESLint/Prettier/Husky
- [ ] Implement identity JWT login, CSRF, session refresh, RBAC UI gates
- [ ] Admin pages for tenants, users/roles, events, audit, service registry
- [ ] Merchant catalog, pricing, orders pages with CRUD and data tables
- [ ] Subscriptions, entitlements, invoices, settlements pages
- [ ] Customer browse, cart/checkout, orders, entry codes UI
- [ ] Create typed API client modules for all services with retries/errors
- [ ] WebSocket/SSE hooks to notifications/events services
- [ ] Design system components with Storybook and tests
- [ ] Vitest unit tests, Playwright E2E, GitHub Actions CI
- [ ] Performance budgets, accessibility audits and fixes
- [ ] Dev README, env configs, runbook, onboarding guide
