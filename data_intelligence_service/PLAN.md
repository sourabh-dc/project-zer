# ZeroQue Intelligence Service — Engineering Build Plan

**Version:** 1.0  
**Branch:** `feature/intelligence-agent`  
**Spec alignment:** ZeroQue Intelligence Service v1.0; Engineering Lock.docx  
**Last updated:** June 2026  

---

## Architecture overview

```
User question (search bar)
         │
         ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  data_intelligence_service  (FastAPI, port 8004)                │
  │                                                                  │
  │  POST /intelligence/query                                        │
  │         │                                                        │
  │    [ApiKeyMiddleware]                                            │
  │         │                                                        │
  │    ┌────▼────────────────────────────────────────────────────┐  │
  │    │   LangGraph Agent  (intelligence/agents/agent.py)       │  │
  │    │                                                          │  │
  │    │  guardrail → classify → plan → schema_check → execute → summarize │
  │    │      │           │        │          │            │          │  │
  │    │  guardrails  classifier  LLM    validator      Postgres  LLM  │  │
  │    │  .py         .py         Azure  schema_       Neo4j           │  │
  │    │                          OpenAI validator     pgvector        │  │
  │    │                                 .py                           │  │
  │    └──────────────────────────────────────────────────────────┘  │
  │                                                                  │
  │  Background: outbox_consumer.py polls outbox_event_delivery      │
  │  → graph/handlers/* → Neo4j sync                                 │
  │  → vector/handlers/* → pgvector embedding sync                   │
  └─────────────────────────────────────────────────────────────────┘
         │
         ▼
   ┌───────────┐   ┌──────────────┐   ┌──────────────┐
   │ PostgreSQL│   │    Neo4j     │   │  pgvector    │
   │ (Postgres)│   │  (Graph DB) │   │ (Embeddings) │
   └───────────┘   └──────────────┘   └──────────────┘
```

---

## Current state (Sprint 0 — DONE)

### What's built and working

| Component | File | Status |
|-----------|------|--------|
| 3-tier intent classifier | `intelligence/routing/classifier.py` | Done |
| Entity extractor | `intelligence/routing/entity_extractor.py` | Done |
| Schema validator (SQL + Cypher) | `intelligence/routing/schema_validator.py` | Done |
| Plan structural validator | `intelligence/routing/plan_validator.py` | Done |
| LangGraph agent (8 nodes) | `intelligence/agents/agent.py` | Done |
| Safety guardrails (regex + LLM) | `intelligence/agents/guardrails.py` | Done |
| Conversation memory | `intelligence/agents/memory.py` | Done |
| Outbox consumer (18 prefixes) | `core/outbox_consumer.py` | Done |
| Graph handlers (15 entity types) | `graph/handlers/` | Done |
| Vector embeddings + pgvector search | `vector/pg_vector.py` | Done |
| User governance queries | `graph/queries/user_governance.py` | Done |
| Approved universe queries | `graph/queries/approved_universe.py` | Done |
| LangSmith tracing (partial) | `intelligence/agents/agent.py` | Done |
| README files (all folders) | `*/README.md` | Done |
| Outbox wiring fix | `provisioning_service + orders_service outbox_helpers.py` | Done |

### Known gaps vs Engineering Lock spec

1. No OpenTelemetry / LLM trace instrumentation → Sprint 1
2. No per-query explainability in API response → Sprint 1
3. Derived Knowledge Layer not built → Sprint 2
4. Permission enforcement (policy engine) not in agent flow → Sprint 3
5. AI Gateway / tiered model routing not built → Sprint 4
6. In-memory session store (not production-safe) → Sprint 5
7. No rate limiting → Sprint 5
8. No eval dataset / automated quality gate → Sprint 5
9. `data_intelligence_service` outbox delivery rows never created → FIXED Sprint 0

---

## Sprint 0 — Foundation & Documentation (DONE)

**Goal:** Clean folder, comments, READMEs, fix outbox wiring, remove stale code.

### Tasks completed
- [x] Add `README.md` to every module folder explaining what + why
- [x] Add `'why'` comments throughout all intelligence files (agent nodes, classifier tiers, memory, schema_validator, outbox_consumer)
- [x] Delete deprecated `query_router.py` (superseded by LangGraph agent)
- [x] Add `.env.example` with all required variables documented
- [x] **Fix outbox wiring:** Add `'data_intelligence_service'` consumer in `provisioning_service/core/helpers/outbox_helpers.py` (17 aggregate types) and `orders_service/core/helpers/outbox_helpers.py` (purchase_request, approval_task)
- [x] Create `PLAN.md` (this file)

---

## Sprint 1 — Observability & Explainability (CURRENT)

**Goal:** Full LLM trace visibility. Per-query explanation in API response. Grafana-ready metrics.

**Why now?** You can't optimise or debug what you can't see. Observability must be built before the system grows.

### Files created/modified

| File | Action | What it does |
|------|--------|-------------|
| `intelligence/observability/__init__.py` | Create | Package marker |
| `intelligence/observability/otel.py` | Create | OpenTelemetry tracer setup + span helpers |
| `intelligence/observability/metrics.py` | Create | Prometheus counters/histograms |
| `intelligence/observability/trace.py` | Create | Per-query trace dataclass (explainability) |
| `intelligence/agents/agent.py` | Modify | Instrument all 8 nodes with OTel spans + build trace |
| `main.py` | Modify | Add `GET /metrics` endpoint + `trace` field in QueryResponse |

### Framework decisions

| Need | Tool | Reason |
|------|------|--------|
| Instrumentation | OpenTelemetry SDK | Portable, no vendor lock-in. OTel GenAI semconv. |
| Dev traces | LangSmith (already wired) | Deepest LangGraph integration. 3 env vars. |
| Staging/Prod traces | Langfuse (self-hosted) | Open-source, OTel-native, self-hostable, UI |
| Infrastructure metrics | Prometheus + Grafana | If Grafana already in infra — zero extra cost |

### Per-query explainability (trace field in API response)

Every `/intelligence/query` response will include:

```json
{
  "answer": "...",
  "trace": {
    "engine": "hybrid",
    "tier": 1,
    "confidence": 1.0,
    "guardrail_passed": true,
    "plan_attempts": 1,
    "steps": [
      {"engine": "graph", "description": "Find vendor IDs for Manchester stores", "rows": 3},
      {"engine": "sql", "description": "Get orders for those vendors", "rows": 47}
    ],
    "latency_ms": 1240,
    "tokens_used": 850
  }
}
```

### Langfuse setup (local)

```bash
# Run Langfuse self-hosted (Sprint 1 delivers docker-compose.observability.yml)
docker compose -f docker-compose.observability.yml up -d

# Then add to .env:
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_HOST=http://localhost:3000
```

---

## Sprint 2 — Derived Knowledge Layer

**Goal:** Precomputed, versioned business facts so LLM reasons over summaries, not raw data.

**Why?** Some questions ("what's our spend trend?") require expensive multi-table aggregations. Precomputing them means instant answers and consistent metrics across queries.

### Files to create

| File | What it does |
|------|-------------|
| `intelligence/derived/__init__.py` | Package marker |
| `intelligence/derived/models.py` | `DerivedFact` dataclass (fact_type, tenant_id, payload, version, computed_at) |
| `intelligence/derived/facts.py` | Fact computation functions (top categories, approval summaries, budget status) |
| `intelligence/derived/handlers.py` | Outbox handlers: `approved_range.*`, `budget.*`, `policy.*` → recompute facts |
| `intelligence/derived/store.py` | Postgres `derived_knowledge` table: read/write/version facts |
| `intelligence/derived/README.md` | Explanation of the layer |

### Fact types to precompute

| Fact type | Trigger | Source | Used by |
|-----------|---------|--------|---------|
| `top_categories_by_spend` | Any `purchase_request.*` | SQL aggregation | LLM planner |
| `approval_policy_summary` | `policy.*`, `approved_range.*` | Neo4j + SQL | LLM planner |
| `org_unit_budget_status` | `budget.*` | SQL | LLM planner |
| `approved_product_list` | `approved_range.*` | Neo4j | LLM planner + vector filter |
| `vendor_activity_summary` | `purchase_request.*` | SQL | LLM planner |

### Integration with existing outbox

Reuses `core/outbox_consumer.py` — just register new handlers in `main.py`:
```python
register_handler("approved_range", derived_handlers.handle_approved_range)
register_handler("budget", derived_handlers.handle_budget)
register_handler("policy", derived_handlers.handle_policy)
```

---

## Sprint 3 — Permission Enforcement

**Goal:** Every query enforced by existing policy engine + RBAC. Results scoped to approved universe.

**Why?** Currently, any authenticated API caller can see any tenant's data. We need row-level governance.

### Integration points (all existing code)

| Integration | Existing file | What we do |
|-------------|--------------|------------|
| User context | `graph/queries/user_governance.get_user_context()` | Call in `node_guardrail`, inject into `AgentState` |
| Policy check | `shared/policy_engine/evaluator.evaluate()` | Call with `action='intelligence.query'` — block if `deny` |
| Approved products | `graph/queries/approved_universe.get_approved_product_ids()` | Already called in `_vector_search`, extend to SQL WHERE |
| OPA Rego | `shared/opa_policies/zeroque/` | Add `intelligence.rego` — simple `has_permission('intelligence.query')` |

### Changes to `agent.py`

```python
# node_guardrail — add after existing checks:
user_ctx = get_user_context(state["user_id"], state["tenant_id"])
state["user_context"] = user_ctx

policy_result = await evaluate(
    db=...,
    action="intelligence.query",
    subject={"user_id": state["user_id"], "roles": user_ctx["roles"], ...},
    resource={"question": state["question"]},
    tenant_id=state["tenant_id"],
)
if not policy_result["allowed"]:
    return {**state, "error": "Access denied", "next": "error"}
```

### Changes to `agent.py` node_execute (SQL)

```python
# Append approved product filter to SQL steps automatically
if engine == "sql" and approved_ids != "__all__":
    query = inject_approved_filter(query, approved_ids)
```

---

## Sprint 4 — AI Gateway & Tiered Model Routing

**Goal:** Route each query to the cheapest model that can answer it accurately.

**Why?** gpt-5-nano (reasoning model) is expensive and slow. Simple lookups ("how many products?") don't need a reasoning model.

### Model tiers

| Tier | Model | When | Latency | Cost |
|------|-------|------|---------|------|
| ZERO | No LLM | Template match (Tier 0) | < 1ms | Free |
| FAST | gpt-4o-mini | Classifier confidence > 0.85, simple query | ~200ms | Low |
| REASON | gpt-5-nano | Complex, multi-hop, low confidence | ~2000ms | High |

### Files to create

| File | What it does |
|------|-------------|
| `intelligence/gateway/__init__.py` | Package marker |
| `intelligence/gateway/router.py` | `ModelTier` enum + routing decision function |
| `intelligence/gateway/README.md` | Tier decision logic |

### Routing decision logic

```python
def choose_tier(engine_hint: str, tier: int, confidence: float, plan_attempts: int) -> ModelTier:
    if tier == 0:  # template match
        return ModelTier.ZERO
    if confidence >= 0.85 and engine_hint in ("sql", "graph") and tier <= 2:
        return ModelTier.FAST
    return ModelTier.REASON  # default — always safe
```

---

## Sprint 5 — Production Hardening

**Goal:** Production-safe memory, rate limits, eval dataset, async execution, Docker/K8s configs.

### Memory — Redis upgrade

**File:** `intelligence/agents/memory.py`

Replace the `_store: Dict` backend with Redis:
```python
import redis
_redis = redis.Redis(host=SETTINGS.REDIS_HOST, decode_responses=True)

def save_turn(tenant_id, session_id, question, answer, engine):
    key = f"session:{tenant_id}:{session_id}"
    _redis.rpush(key, json.dumps(Turn(...).__dict__))
    _redis.ltrim(key, -MAX_TURNS, -1)  # keep last N turns
    _redis.expire(key, SESSION_TTL)
```

### Rate limiting

**File:** `intelligence/middleware/auth.py`

Redis sliding window counter per tenant:
```python
# X requests per minute per tenant
key = f"ratelimit:{tenant_id}:{minute_bucket}"
count = redis.incr(key)
redis.expire(key, 60)
if count > SETTINGS.RATE_LIMIT_RPM:
    raise HTTPException(429, "Rate limit exceeded")
```

### Eval dataset

**File:** `intelligence/evals/dataset.jsonl`

50 curated question → expected_engine + expected_answer pairs:
```json
{"question": "How many products do we have?", "expected_engine": "sql", "expected_answer_contains": ["count", "products"]}
{"question": "Who does Alice report to?", "expected_engine": "graph"}
{"question": "Find eco-friendly cleaning products", "expected_engine": "vector"}
```

**File:** `intelligence/evals/run_evals.py`

LangSmith eval runner — measures routing accuracy, answer quality (LLM judge), latency.

### Async hybrid execution

For hybrid queries where steps are independent (no `depends_on`), run them in parallel:
```python
# node_execute — parallel execution for independent steps
independent = [s for s in steps if s.get("depends_on") is None]
results = await asyncio.gather(*[_run_step(s, ...) for s in independent])
```

### Deployment

**Files to create:**
- `docker-compose.yml` — Postgres + Neo4j + Redis + app + worker
- `docker-compose.observability.yml` — Langfuse + Prometheus + Grafana
- `k8s/deployment.yaml` — app deployment + worker deployment
- `k8s/service.yaml` — ClusterIP service
- `k8s/configmap.yaml` — env config (secrets via Key Vault)
- `k8s/hpa.yaml` — horizontal pod autoscaler (CPU-based, web only)

---

## Infrastructure — Local Development

### Docker Compose (create Sprint 1)

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: zeroque
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password

  neo4j:
    image: neo4j:5
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/password

  app:
    build: .
    ports: ["8004:8004"]
    env_file: .env
    depends_on: [postgres, neo4j]

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    env_file: .env
    depends_on: [postgres, neo4j]
```

To start:
```bash
# Start Docker Desktop first
docker compose up -d postgres neo4j
# Wait ~20s for Neo4j to initialise
docker compose up -d app worker
```

### Azure connections (for staging/production)

When `ENVIRONMENT != local`, config.py reads from Azure Key Vault automatically.  
Required secrets in Key Vault:
```
azureOpenaiApiKey
azureOpenaiEndpoint
dbName / dbPassword / dbHost / dbUsername
neo4jUri / neo4jUser / neo4jPassword
```

---

## Testing

### Unit tests (no DB required)

```bash
cd data_intelligence_service
python3 test_router.py        # classifier + entity extractor + templates
```

### Integration tests (LLM only, DB falls back to static schema)

```bash
python3 test_agent.py         # full agent with real LLM, static schema fallback
python3 test_agent.py --question "How many products do we have?"
```

### Full system tests (requires Postgres + Neo4j)

```bash
docker compose up -d postgres neo4j
python3 test_integration.py
```

---

## File map — complete

```
data_intelligence_service/
├── .env.example                    ← copy to .env, fill in secrets
├── README.md                       ← service overview
├── PLAN.md                         ← this file
├── main.py                         ← FastAPI app
├── Dockerfile                      ← web server image
├── Dockerfile.worker               ← outbox worker image
│
├── core/
│   ├── README.md
│   ├── config.py                   ← pydantic settings (env / Key Vault)
│   ├── db.py                       ← Postgres pool + schema cache
│   ├── graph.py                    ← Neo4j helpers
│   ├── llm.py                      ← Azure OpenAI factory
│   ├── logger.py                   ← structured logger
│   ├── neo4j_client.py             ← driver init + constraints
│   └── outbox_consumer.py          ← polls outbox_event_delivery
│
├── intelligence/
│   ├── README.md
│   │
│   ├── routing/
│   │   ├── README.md
│   │   ├── classifier.py           ← 3-tier engine classifier
│   │   ├── entity_extractor.py     ← regex entity extraction
│   │   ├── schema_validator.py     ← SQL/Cypher validation
│   │   ├── plan_validator.py       ← plan JSON structure validation
│   │   ├── intent_templates.py     ← legacy templates (reference)
│   │   └── observability.py        ← basic query logger
│   │
│   ├── agents/
│   │   ├── README.md
│   │   ├── agent.py                ← LangGraph orchestrator (main brain)
│   │   ├── guardrails.py           ← safety layer
│   │   └── memory.py               ← session conversation memory
│   │
│   ├── observability/              ← [Sprint 1]
│   │   ├── otel.py                 ← OpenTelemetry setup + helpers
│   │   ├── metrics.py              ← Prometheus metrics
│   │   └── trace.py                ← per-query trace dataclass
│   │
│   ├── derived/                    ← [Sprint 2]
│   │   ├── models.py               ← DerivedFact dataclass
│   │   ├── facts.py                ← computation functions
│   │   ├── handlers.py             ← outbox-triggered recomputation
│   │   └── store.py                ← Postgres derived_knowledge table
│   │
│   ├── gateway/                    ← [Sprint 4]
│   │   └── router.py               ← model tier selection
│   │
│   └── evals/                      ← [Sprint 5]
│       ├── dataset.jsonl            ← 50 curated Q&A pairs
│       └── run_evals.py             ← LangSmith eval runner
│
├── graph/
│   ├── README.md
│   ├── handlers/                   ← one file per entity type
│   └── queries/
│       ├── approved_universe.py
│       ├── user_governance.py
│       └── store_products.py
│
├── vector/
│   ├── README.md
│   ├── embeddings.py
│   ├── pg_vector.py
│   └── handlers/
│       └── product_embedding_handler.py
│
└── workers/
    ├── README.md
    └── consumer_standalone.py
```

---

## Decision log

| Decision | Chosen | Alternatives considered | Reason |
|----------|--------|------------------------|--------|
| LLM orchestration | LangGraph | CrewAI, raw async | State machine with conditional retry edges |
| LLM provider | Azure OpenAI | OpenAI direct | Enterprise compliance, Key Vault integration |
| Observability | OTel + Langfuse | LangSmith only, Datadog | OTel = portable; Langfuse = open-source, self-hostable |
| Knowledge graph | Neo4j (existing) | GraphQL, DGraph | Already in codebase, rich Cypher query support |
| Permission enforcement | OPA (existing) | Custom RBAC | Already running, Rego policies cover all domains |
| Memory (now) | In-memory dict | Redis | Simplest for single instance |
| Memory (Sprint 5) | Redis | PostgreSQL JSONB | TTL support, cross-instance, standard choice |
| Vector search | pgvector | Pinecone, Weaviate | Already in Postgres — no extra infra |
| Derived knowledge | Postgres table | Redis cache | Versioning, audit trail, no extra infra |
| Model routing (Sprint 4) | Custom tier logic | LiteLLM, AI proxy | Simpler, already have AzureChatOpenAI |
