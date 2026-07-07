# core/

Shared infrastructure for the Data Intelligence Service.

Every module here is a **singleton** — imported once and reused across the app.

---

## Files

### `config.py`
Centralised settings using pydantic-settings.  
- Reads from `.env` locally, Azure Key Vault in deployed environments.  
- Single `SETTINGS` object imported everywhere — no `os.getenv()` scattered through the code.

### `db.py`
PostgreSQL connection pool + helpers.  
- `execute_readonly_sql(sql, params)` — runs parameterised queries with a row-count guard.  
- `get_schema_description()` — returns table/column definitions (cached 10 min) so the LLM planner always knows the exact schema without hitting the DB on every request.

### `graph.py`
Neo4j connection + helpers.  
- `execute_readonly_cypher(cypher, params)` — same pattern as SQL, read-only.  
- `get_graph_schema_description()` — returns node labels and relationship types. Falls back to a static description if Neo4j is unreachable (allows local dev without Neo4j).

### `llm.py`
Azure OpenAI client factory.  
- Used by the intelligence layer only. `core/db.py` and `core/graph.py` never touch the LLM.

### `logger.py`
Structured logger. Import `logger` from here — do not create new loggers elsewhere.

### `neo4j_client.py`
Low-level Neo4j driver init and constraint setup.  
Called once at startup (`init_constraints()`), then `core/graph.py` wraps it for all queries.

### `outbox_consumer.py`
Polls `outbox_event_delivery` rows for `consumer='data_intelligence_service'`.  
- Handlers are registered at startup in `main.py`.  
- Keeps the graph, vector index, and (future) derived knowledge layer in sync with changes from other services.

---

## Why a separate `core/` layer?

All the other modules (`intelligence/`, `graph/`, `vector/`) depend on these primitives.  
Keeping them in `core/` means: one place to change DB credentials, one place to swap the LLM provider, one place to update logging format.
