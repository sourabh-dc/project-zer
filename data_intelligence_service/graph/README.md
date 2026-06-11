# graph/

Neo4j graph layer — keeps the governance knowledge graph in sync and exposes query functions.

---

## Why a graph database?

Relational databases answer "what is X?" — Neo4j answers "how is X connected to Y?".

ZeroQue needs both:
- "How much did Finance spend last month?" → PostgreSQL
- "Who are the approvers for Finance org unit purchases?" → Neo4j

The graph stores the full governance topology:
- Org unit hierarchy (who belongs to what)
- User roles and permissions
- Approved product ranges per org unit
- Policy assignments
- Vendor supply chains

---

## Sub-folders

### `handlers/`
One handler per entity type. Each handler is triggered by an outbox event (via `core/outbox_consumer.py`).  
When provisioning_service creates a new user, an outbox event fires → `user_handler.handle()` → Neo4j node created/updated.

This is why the graph is always up to date without polling or scheduled jobs.

**Handlers registered in `main.py`:**
tenant, site, store, store_product, user, org_unit, product, category, vendor, role, role_permission,
cost_centre, approved_range, policy, policy_rule, policy_assignment, mandate.

### `queries/`
Read-only query functions called by the intelligence agent during execution.

- **`user_governance.py`** — `get_user_context(user_id, tenant_id)` → roles, permissions, org units, policies  
  Used by the agent to filter results to what the user is allowed to see.

- **`approved_universe.py`** — `get_approved_product_ids(tenant_id, user_id)` → list of approved product IDs  
  Used to filter SQL WHERE clauses and vector search results.

- **`store_products.py`** — products at a store, stores carrying a product, full tenant topology
