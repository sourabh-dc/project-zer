# ZeroQue Data Intelligence Service

The **single entry-point** for all data questions in ZeroQue.

A user types a natural language question into the search bar. This service figures out where the answer lives (PostgreSQL, Neo4j, or Vector Store), generates and validates the query, runs it, and returns a plain-English answer.

---

## What it does

```
User question
     │
     ▼
[Guardrails]  — block prompt injection, PII harvest, off-topic abuse
     │
     ▼
[Classifier]  — is this a SQL / Graph / Vector / Hybrid question? (deterministic)
     │
     ▼
[LLM Planner] — generate SQL / Cypher / search text (schema-grounded, few-shot)
     │
     ▼
[Schema Check]— validate every table/column/label exists. Retry if wrong.
     │
     ▼
[Executor]    — run against Postgres / Neo4j / pgvector
     │
     ▼
[Summarizer]  — LLM formats raw rows into a plain-English answer
     │
     ▼
Answer (+ conversation memory saved for follow-up questions)
```

---

## Folder structure

```
data_intelligence_service/
├── core/           — shared infrastructure: DB, graph, LLM, outbox, config
├── intelligence/   — the brain: routing, planning, agents, guardrails, memory
│   ├── routing/    — deterministic classification layer (no LLM)
│   └── agents/     — LangGraph orchestration + LLM layer
├── graph/          — Neo4j handlers (outbox-driven sync) + query modules
├── vector/         — pgvector embeddings + similarity search
├── workers/        — standalone outbox consumer process
└── main.py         — FastAPI app (REST API)
```

---

## How to run locally

```bash
cp .env.example .env
# fill in AZURE_OPENAI_*, POSTGRES_*, NEO4J_* values

pip install -r requirements.txt
uvicorn data_intelligence_service.main:app --reload --port 8004
```

---

## Key API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/intelligence/query` | Ask a natural language question |
| DELETE | `/intelligence/session/{id}` | Clear conversation memory |
| GET | `/intelligence/sessions/stats` | Diagnostic: active sessions |
| GET | `/graph/user-context/{user_id}` | Roles, permissions, org units from Neo4j |
| GET | `/graph/approved-products/{user_id}` | Products approved for a user |
| POST | `/vector/search` | Semantic product search |
| GET | `/health` | Health check |

---

## Data sources

| Source | Used for |
|--------|---------|
| **PostgreSQL** | Exact data — products, spend, orders, budgets, users, vendors |
| **Neo4j** | Relationships — org hierarchy, governance, approved ranges, policies |
| **pgvector** | Semantic search — "find something for cold storage" |

---

## Build plan

See the [build plan canvas](../.cursor/projects/Users-sourabh-Desktop-consumables-code/canvases/zeroque-intelligence-build-plan.canvas.tsx) for the full sprint roadmap toward production deployment.
