# intelligence/agents/

LLM-powered layer — plans, validates, executes, and summarises.

---

## `agent.py` — the LangGraph state machine

This is the main orchestrator. It wires all other components together into a directed graph of nodes.

```
guardrail → classify → plan → schema_check → execute → summarize
                         ↑          │
                         └── retry ─┘ (up to 2 attempts)
```

**State** flows through every node as `AgentState` (TypedDict).  
Each node reads from state, does its job, and writes back.

### Node responsibilities

| Node | What it does | Uses LLM? |
|------|-------------|-----------|
| `node_guardrail` | Block misuse (regex first, LLM if suspicious) | Sometimes |
| `node_classify` | Tag question with engine hint | No |
| `node_plan` | Generate SQL/Cypher/search plan (schema-grounded) | Yes |
| `node_schema_check` | Validate plan against real schema; retry if bad | No |
| `node_execute` | Run plan against Postgres / Neo4j / pgvector | No |
| `node_summarize` | Format raw rows into English answer | Yes |
| `node_error` | Terminal error — passes state through | No |

### Why schema grounding?
The LLM planner is given the *actual* table/column/label names from the DB before generating queries.
This, combined with few-shot examples, reduces hallucination to < 5% of queries. The schema validator
catches the rest and triggers a self-correction retry.

---

## `guardrails.py`

Two-tier safety system:
1. **Regex (Tier 1)** — instant, no network: blocks prompt injection, credential extraction, SQL injection, PII harvest, off-topic abuse.
2. **LLM (Tier 2)** — only triggered for long or suspicious questions: binary SAFE/UNSAFE classification.

We use two tiers because:
- Regex is fast and catches 95% of obvious attacks.
- LLM catches sophisticated prompt injection that regex misses.
- But LLM is slow, so we don't call it for every query.

---

## `memory.py`

Stores the last 6 question-answer turns per session in an in-memory dict.  
Injected into the LLM planner and summarizer so the model can resolve references like:
- "show me more about the first result"
- "same question but for last quarter"

**Current limitation:** in-memory only — does not survive process restart or multi-instance deployments.  
Upgrade to Redis-backed store in Sprint 5.

Session keys are `(tenant_id, session_id)` — conversations are tenant-isolated.
