# intelligence/permissions/

Permission enforcement for intelligence queries.

---

## What this does

Every intelligence query goes through a permission check in `node_guardrail` (before any LLM or DB call). The check:

1. Fetches the user's governance context from the Neo4j graph (roles, permissions, org units)
2. Fetches the user's approved product IDs (their allowed procurement universe)
3. Checks the user has `intelligence.query` permission
4. Writes the decision to the `policy_decisions` audit table
5. Passes `approved_ids` down to SQL and vector execution for data filtering

---

## Why reuse graph queries instead of shared/policy_engine?

The `shared/policy_engine.evaluate()` requires:
- A SQLAlchemy session to the shared Postgres DB (subject enrichment)
- An OPA sidecar running on `OPA_URL` (HTTP call)
- A Rego policy package for `intelligence.*` actions (doesn't exist yet)

The DIS already has all governance data in Neo4j. `get_user_context()` in `graph/queries/user_governance.py` performs a single Cypher traversal that returns roles, permissions, org units and policies — everything needed for permission checking.

This avoids adding OPA as a hard dependency for every intelligence query.

---

## Files

| File | Purpose |
|------|---------|
| `context.py` | Builds and caches user permission context from graph. Fetches approved product IDs. |
| `policy_client.py` | Checks `intelligence.query` permission. Writes to `policy_decisions` audit table. |

---

## Data flow

```
QueryRequest (user_id, tenant_id, question)
         │
         ▼
node_guardrail
  │  build_user_permission_context(user_id, tenant_id)
  │    → get_user_context()    [Neo4j: roles, permissions, org units]
  │    → get_approved_product_ids()  [Neo4j: approved universe]
  │  check_intelligence_permission(user_ctx, question)
  │    → has_permission(ctx, "intelligence.query")
  │    → _write_audit_log() → policy_decisions table
  │
  ▼
AgentState { user_context, approved_ids }
  │
  ▼
node_execute
  │  SQL: params["approved_ids"] = approved_ids
  │       LLM query can use AND product_id = ANY(:approved_ids)
  │
  │  vector: approved_ids → pg_vector.similarity_search(approved_product_ids=...)
  │          → SQL WHERE product_id = ANY(:pids)
  │
  ▼
Results are automatically filtered to user's approved universe
```

---

## Fail-open semantics

If Neo4j is unavailable:
- `user_context` defaults to empty (no roles/permissions known)
- `approved_ids` defaults to `"__all__"` (no product filter)
- Permission check still passes (API key is sufficient gate)

Rationale: this is a READ-ONLY query service. Denying all queries when
the graph is temporarily down would be too disruptive. The API key at
the middleware level (`middleware/auth.py`) is the primary auth gate.

---

## Adding OPA support later

1. Create `shared/opa_policies/zeroque/intelligence.rego`
2. Add `("intelligence.", "zeroque/intelligence")` to `_PREFIX_PACKAGE` in `shared/policy_engine/evaluator.py`
3. Set `OPA_URL` in DIS environment
4. Replace `_write_audit_log()` in `policy_client.py` with a call to `shared.policy_engine.evaluate()`

---

## Audit trail

All permission decisions are written to the `policy_decisions` table (same table as `shared/policy_engine`). Compliance teams can query:

```sql
SELECT user_id, action, decision, reason, evaluated_at
FROM policy_decisions
WHERE action = 'intelligence.query'
ORDER BY evaluated_at DESC;
```
