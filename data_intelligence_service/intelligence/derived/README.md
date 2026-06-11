# intelligence/derived/

Derived Knowledge Layer — precomputed, versioned business facts.

---

## Why this exists

Some questions require expensive multi-table aggregation queries:
- "What are our top spend categories this quarter?" — 4-table JOIN with GROUP BY
- "What is the budget utilization for each org unit?" — budget JOIN org_units with math

Running these queries live on every LLM request is slow and expensive. The derived knowledge layer precomputes these facts when the underlying data changes (via outbox events) and caches the results in Postgres.

The LLM planner then gets a compact text summary as business context, instead of having to plan and execute the full aggregation itself.

---

## How it works

```
Outbox event fires (e.g. purchase_request.submitted)
         │
         ▼
handlers.py (handle_purchase_request)
         │
         ▼
facts.py (compute_top_categories_by_spend, compute_vendor_activity_summary)
         │  — runs SQL aggregation against Postgres
         ▼
store.py (save_fact)
         │  — writes to derived_knowledge table with version++
         ▼
derived_knowledge table (tenant_id, fact_type, payload JSONB, version, computed_at)
```

At query time:
```
agent.py (node_plan)
         │  — calls store.get_facts_for_query(tenant_id, relevant_fact_types)
         ▼
Facts injected into LLM planner prompt as "BUSINESS CONTEXT" block
         │  — LLM uses context to generate more accurate queries
         ▼
Better, faster answer
```

---

## Files

| File | Purpose |
|------|---------|
| `models.py` | `DerivedFact` dataclass, fact type constants, trigger/relevance maps |
| `store.py` | Postgres read/write with 5-min in-memory cache |
| `facts.py` | Computation functions, one per fact type |
| `handlers.py` | Outbox event handlers that trigger recomputation |

---

## Fact types

| Fact type | Trigger events | Source | Payload summary |
|-----------|---------------|--------|----------------|
| `top_categories_by_spend` | `purchase_request.*` | SQL | Top 10 categories by spend this quarter |
| `approval_policy_summary` | `policy.*`, `approved_range.*` | SQL | Active policies + thresholds |
| `org_unit_budget_status` | `budget.*`, `org_unit.*` | SQL | Utilization % per org unit |
| `vendor_activity_summary` | `purchase_request.*` | SQL | Order counts + last order date per vendor |
| `approved_product_count` | `approved_range.*` | Neo4j | Product counts per approved range |

---

## Database table

```sql
CREATE TABLE IF NOT EXISTS derived_knowledge (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    fact_type   VARCHAR(100) NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    version     INTEGER NOT NULL DEFAULT 1,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_derived_tenant_type ON derived_knowledge (tenant_id, fact_type);
```

Table is created automatically at startup (`store.ensure_table_exists()`).  
For staging/prod use the migration in `migrations/derived_knowledge.sql`.

---

## Adding a new fact type

1. Add a constant to `models.py` (e.g. `FACT_SUPPLIER_RISK = "supplier_risk"`)
2. Add trigger mapping to `FACT_TRIGGERS` and engine relevance to `FACT_ENGINE_RELEVANCE`
3. Add a `compute_supplier_risk(tenant_id)` function to `facts.py`
4. Register it in `_COMPUTERS` in `facts.py`
5. Add or extend a handler in `handlers.py`
6. Register the handler in `main.py`
