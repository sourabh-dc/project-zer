# intelligence/

The brain of ZeroQue — takes a natural language question and returns an answer.

---

## How it works (flow)

```
question
   │
   ├─ routing/classifier.py   → deterministic engine hint (sql/graph/vector/hybrid)
   │   "Is this a graph question or a SQL question?"
   │   No LLM. Pure regex + scoring. < 1ms.
   │
   ├─ routing/entity_extractor.py  → extract named entities (product_name, date, etc.)
   │
   ├─ agents/agent.py (LangGraph)  → orchestrate the full pipeline
   │   ├─ node_guardrail   → block misuse (regex + LLM safety check)
   │   ├─ node_classify     → call classifier above
   │   ├─ node_plan         → LLM generates SQL/Cypher/vector plan (schema-grounded)
   │   ├─ node_schema_check → validate plan against live schema; retry if wrong
   │   ├─ node_execute      → run plan against Postgres/Neo4j/pgvector
   │   └─ node_summarize    → LLM formats raw data into English answer
   │
   ├─ agents/guardrails.py  → safety layer (see above)
   └─ agents/memory.py      → per-session conversation history
```

---

## Sub-folders

### `routing/`
Deterministic layer — no LLM calls.
- `classifier.py` — 3-tier classifier: regex → scoring → LLM fallback hint
- `entity_extractor.py` — extracts product names, dates, org names from the question
- `schema_validator.py` — validates LLM-generated SQL/Cypher against real schema
- `plan_validator.py` — validates the structural shape of the LLM plan JSON
- `intent_templates.py` — legacy pre-written query templates (kept for reference)
- `observability.py` — basic query logging

### `agents/`
LLM-powered layer.
- `agent.py` — the LangGraph state machine (main orchestrator)
- `guardrails.py` — two-tier safety: fast regex + LLM classification
- `memory.py` — in-memory session store (upgrade to Redis in Sprint 5)

---

## Why LLM for planning but not routing?

Routing is deterministic — regex and keyword scoring are fast and predictable.
But generating correct SQL or Cypher requires understanding the question's nuance and
mapping it to the exact schema. LLMs do this well when grounded with real schema info
and few-shot examples. The schema validator then catches hallucinations before they hit the DB.
