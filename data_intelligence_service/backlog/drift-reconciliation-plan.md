# Drift Guard & Reconciliation Plan

**Status:** Backlog — planned, not started
**Priority:** High (pre-production requirement)
**Owner:** Data Intelligence Service
**Date:** 2026-11-02

## Background

The provisioning/orders → DIS pipeline is event-driven and lossy by design:

- Events flow through `outbox_event_delivery` rows polled by DIS.
- Handlers are best-effort: Neo4j or pgvector failures mark the delivery
  `failed`, but nothing re-drives them today.
- Bulk/import paths can bypass event emission entirely.
- Postgres is the source of truth; Neo4j (graph) and pgvector (embeddings)
  are derived read models that can silently drift.

Result: a product can exist in Postgres but be missing from the graph or
vector store, and no alert fires. Answers from AskQue then silently use stale
or incomplete context.

## Goals

1. Detect drift between Postgres, Neo4j, and pgvector within minutes, not days.
2. Auto-heal simple drift (missing nodes/embeddings) without manual intervention.
3. Surface unhealable drift (dead letters, schema mismatches) as alerts.

## Non-Goals

- Rebuilding historical data (covered by the one-off backfill job).
- Changing the event-delivery mechanism (polling → push) — separate effort.

---

## Workstream A — Dead-letter monitoring

### A1. Dead-letter promotion

Today a delivery row that exhausts retries stays `failed` forever.

- Add a `dead` status to `outbox_event_delivery`.
- The DIS outbox consumer marks a delivery `dead` after
  `max_retries` (currently 3) consecutive failures.
- Emit a Prometheus counter: `dis_outbox_dead_letters_total{event_type, service}`.

**Files:** `core/outbox_consumer.py`, migration `004_delivery_dead_status.sql`.

### A2. Dead-letter endpoint + metrics

- `GET /api/v1/admin/dead-letters` — list dead deliveries (event_type,
  tenant, error, age). JWT + admin permission.
- `POST /api/v1/admin/dead-letters/{id}/replay` — reset a dead delivery to
  `pending` for reprocessing (idempotent handlers make replay safe).
- Grafana alert: `dead_letter_growth > 0 over 15m` → notify.

**Files:** `intelligence/admin/routes.py` (new), `main.py`.

### A3. Poison-message quarantine

Messages that always fail (bad payload shape) replay forever. After replay
attempt #3, park them in a `quarantined` status with the raw payload stored
for inspection. Alert on quarantine growth.

---

## Workstream B — Count reconciliation job

A scheduled job that compares entity counts across the three stores and
heals simple gaps.

### B1. Reconciliation engine

New module: `data_intelligence_service/workers/reconciler.py`.

For each entity type, compare:

| Entity | Postgres (source of truth) | Neo4j | pgvector |
|---|---|---|---|
| Tenant | `tenants` | `(:Tenant)` | — |
| User | `users` | `(:User)` | — |
| OrgUnit | `org_units` | `(:OrgUnit)` | — |
| CostCentre | `cost_centres` | `(:CostCentre)` | — |
| Store | `stores` | `(:Store)` | — |
| Vendor | `vendors` | `(:Vendor)` | — |
| Product | `products` | `(:Product)` | `product_embeddings` |
| Category | `categories` | `(:Category)` | — |
| Policy | `approval_policies` | `(:Policy)` | — |
| ApprovedRange | `approved_ranges` | `(:ApprovedRange)` | — |

Scope per tenant, excluding soft-deleted rows (`status != 'deleted'`).

**Checks per entity:**

1. **Count check** — `pg_count == neo4j_count` (and `== vector_count` for products).
2. **ID-set diff** (only when counts differ) — fetch ID sets from both sides,
   compute `missing_in_graph` / `missing_in_vector` / `orphaned_in_graph`
   (in Neo4j but not Postgres — usually a missed delete event).
3. **Property spot-check** (sample of N=50) — compare `name`/`status` fields
   to catch stale updates that count checks miss.

### B2. Auto-heal

For each missing ID:

- **Missing in Neo4j** → re-fetch the row from Postgres, synthesise a
  `*.created` event, run it through the normal handler pipeline (reuse
  `handlers` registry — do not duplicate Cypher).
- **Missing in pgvector** → re-run the product embedding handler with the
  fetched row.
- **Orphaned in Neo4j** → soft-delete via the normal `*.deleted` handler path.
- Cap heals per run (e.g. 200/entity) to bound blast radius; remainder waits
  for the next run.

Record every heal action to a `reconciliation_log` table:
`(run_id, entity, tenant_id, object_id, action, detail, created_at)`.

### B3. Scheduling & metrics

- Run every **15 minutes** via the existing worker loop (`main.py` lifespan),
  guarded by a Redis lock so API + worker replicas don't double-run.
- Metrics per run:
  - `dis_reconcile_drift_total{entity, store}` — objects healed
  - `dis_reconcile_unhealed_total{entity}` — still drifting after heal attempt
  - `dis_reconcile_run_duration_seconds`
- Alert: `dis_reconcile_unhealed_total > 0 for 2 consecutive runs`.

### B4. Reporting endpoint

`GET /api/v1/admin/reconciliation/latest` — last run summary per entity:
counts per store, drift found, healed, unhealed. Feeds an ops dashboard.

---

## Workstream C — Emission-coverage guard (preventive)

Reconciliation heals drift; this prevents it.

- **C1. CI check:** script `scripts/check_event_coverage.py` that scans
  provisioning/orders route files for `db.add(<Model>)` / `db.commit()`
  patterns on event-relevant models and fails if no nearby
  `create_outbox_event` call exists. Runs in the services' CI workflow.
- **C2. Handler contract tests:** for every event type in
  `_DIS_CONSUMER_PREFIXES`, a DIS test asserting a registered handler exists
  and accepts a fixture payload (prevents "event emitted, handler missing").
- **C3. Payload schema registry:** versioned JSON schemas per event type in
  `shared/event_schemas/`; emitters validate before enqueue (dev mode: warn).

---

## Rollout

| Phase | Scope | Exit criteria |
|---|---|---|
| 1 | A1 + A2 (dead letters visible + replayable) | Alert fires on injected failure; replay heals it |
| 2 | B1 + B2 for Product only (highest-value entity) | Deleted product embedding detected + healed in test |
| 3 | B for all entities + B3 scheduling/metrics | 15-min runs stable for 1 week in dev |
| 4 | C1–C3 preventive guards | CI blocks a deliberately unemitted change |

## Acceptance criteria

1. Kill a handler mid-run (simulate Neo4j outage) → dead letters appear,
   alert fires, replay recovers them.
2. Manually delete a `(:Product)` node → next reconciliation run re-creates it
   and logs the heal.
3. Manually delete a pgvector row → next run re-embeds it.
4. Insert a product row directly in Postgres (bypassing API) → detected as
   drift and healed within one run interval.
5. Zero unhealed drift in dev for 1 consecutive week.

## Open questions

1. **Ordering on heal:** re-synthesised `created` events skip `updated` deltas
   that arrived later. Acceptable (next `updated` event or property spot-check
   converges), or do we need last-write-wins timestamps on nodes?
2. **Cross-service DB access:** reconciler reads provisioning tables directly.
   Keep direct reads (simple) or go through provisioning REST (cleaner
   boundary, slower)?
3. **Orphan policy:** soft-delete orphans immediately, or quarantine for N
   days first (protects against Postgres-side restore scenarios)?
