# intelligence/routing/

Deterministic routing layer — decides WHERE to fetch data from, without using an LLM.

---

## Design philosophy

We want routing to be:
- **Fast** — < 1ms, deterministic, no network calls
- **Predictable** — same question always routes the same way
- **Conservative** — when uncertain, route to the LLM planner (Tier 3) rather than guess

The LLM (in `agents/agent.py`) uses the routing result as a *hint*, not a hard constraint.
It can override the hint if it has better context from the question.

---

## Files

### `classifier.py`
Three-tier classification:
1. **Tier 1 — Regex** (< 1ms): high-confidence single-signal rules. A match here is definitive.  
   e.g. "reports to" → graph, "how many" → sql, "similar to" → vector
2. **Tier 2 — Weighted scoring** (< 1ms): sum keyword weights per engine, pick best if score ≥ threshold.
3. **Tier 3 — LLM fallback** (100–500ms): returns `engine=unknown`, agent will use full LLM planning.

Returns `(engine, tier, confidence)`.

### `entity_extractor.py`
Extracts named entities using regex:
- `product_name`, `org_name`, `user_name`, `date_filter`, `email`
These are passed into the LLM plan as known values to parameterise queries correctly.

### `schema_validator.py`
After the LLM generates SQL/Cypher, this checks that every table, column, node label,
and relationship type actually exists in the live schema. Errors are fed back to the LLM
for one self-correction attempt. Catches ~80% of LLM hallucinations before they hit the DB.

### `plan_validator.py`
Validates the structural shape of the LLM-generated plan JSON
(required fields, step count limits, engine values).

### `intent_templates.py`
Legacy module: pre-written SQL/Cypher templates for the most common question patterns.
Kept for reference and potential future Tier-0 optimisation. Not in the main agent flow.

### `observability.py`
Logs each query with routing metadata for debugging and analytics.
Will be replaced by OpenTelemetry instrumentation in Sprint 1.
