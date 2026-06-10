"""
Intelligence Service — Query Router.

Pipeline:
  1. Classify   → 3-tier rule engine (regex → scoring → LLM hint)
                   determines which engine(s) are needed (sql/graph/vector/hybrid)
  2. Plan       → LLM generates SQL/Cypher/vector steps
                   - Intent-aware schema injection (only relevant schema portions)
                   - Few-shot grounded examples so LLM copies correct patterns
                   - Cached by (question_hash, tenant_id)
  3. Validate   → structural plan check (plan_validator)
  4. Schema     → validate table/label names against live schema (schema_validator)
                   if errors found → one retry with LLM correction
  5. Execute    → run steps, feed prior results as bound params to next steps
  6. Retry      → if a step fails at DB level, retry with error context
  7. Summarize  → LLM reads raw data + question → natural language answer

Design principle: LLM is used freely for planning and summarization.
Accuracy comes from grounding (real schema + examples) and validation,
NOT from avoiding LLM.
"""
import hashlib
import json
import time
from typing import Dict, Any, Optional, List, Tuple

from data_intelligence_service.core.llm import chat_json, chat
from data_intelligence_service.core.db import execute_readonly_sql, get_schema_description
from data_intelligence_service.core.graph import execute_readonly_cypher, get_graph_schema_description
from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.routing.classifier import classify
from data_intelligence_service.intelligence.routing.plan_validator import validate_plan, PlanValidationError
from data_intelligence_service.intelligence.routing.observability import (
    QueryTrace, StepTrace, now_ms, question_hash,
)
from data_intelligence_service.intelligence.routing.schema_validator import (
    validate_plan_schema, build_sql_schema_dict, parse_graph_schema,
)


# ---------------------------------------------------------------------------
# Plan cache
# ---------------------------------------------------------------------------
_plan_cache: Dict[str, Tuple[Dict, float]] = {}


def _cache_key(question: str, tenant_id: str) -> str:
    raw = f"{question.strip().lower()}|{tenant_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached_plan(question: str, tenant_id: str) -> Optional[Dict]:
    key = _cache_key(question, tenant_id)
    entry = _plan_cache.get(key)
    if entry:
        plan, expires_at = entry
        if time.monotonic() < expires_at:
            return plan
        del _plan_cache[key]
    return None


def _set_cached_plan(question: str, tenant_id: str, plan: Dict):
    key = _cache_key(question, tenant_id)
    _plan_cache[key] = (plan, time.monotonic() + SETTINGS.PLAN_CACHE_TTL_SECONDS)


# ---------------------------------------------------------------------------
# System prompt — grounded, few-shot, intent-aware
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """\
You are the query engine for ZeroQue, a B2B consumables procurement platform.

Your job: given a natural language question, produce an execution plan that
fetches the exact data needed to answer it accurately.

━━━ ABSOLUTE RULES ━━━
1. ONLY use tables and columns that appear in the schema below. Never invent names.
2. SQL  → SELECT only. No INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE.
3. Cypher → MATCH / RETURN / WITH / WHERE / OPTIONAL MATCH only.
         No CREATE / DELETE / SET / MERGE / REMOVE / DROP.
4. Always filter: tenant_id = :tenant_id (SQL) or {tenant_id: $tenant_id} (Cypher).
5. Always exclude deleted records: status = 'active' or status NOT IN ('deleted','cancelled').
6. Parameterise all user values: :param_name (SQL), $param_name (Cypher).
7. Never string-concatenate user input into a query.
8. Max 6 steps per plan.

━━━ ENGINE GUIDE ━━━
sql    → exact data: product details, spend amounts, counts, budgets, order history,
         approval chains, user lists, vendor lists, subscription info.
graph  → relationships: org hierarchy, who belongs to which org unit, user roles &
         permissions, governance policies, approved range assignments, vendor supply chains.
vector → semantic / fuzzy product search: "find gloves similar to X", "safety equipment
         for confined spaces", "eco-friendly cleaning products".
hybrid → combine two or more engines when one engine cannot fully answer the question.
         E.g.: graph to find which users are in an org → SQL to sum their spend.

━━━ HYBRID ORDERING ━━━
List steps so dependencies resolve top-to-bottom.
Use depends_on: <step_index> when a later step needs IDs from an earlier step.
Prior IDs are injected as :prior_ids (SQL) / $prior_ids (Cypher).

━━━ OUTPUT FORMAT ━━━
Return exactly this JSON and nothing else:
{
  "query_type": "sql" | "graph" | "vector" | "hybrid",
  "reasoning": "<one sentence explaining the routing decision>",
  "steps": [
    {
      "engine": "sql" | "graph" | "vector",
      "query": "<SQL or Cypher or semantic search text>",
      "description": "<what this step retrieves>",
      "depends_on": null | <step_index 0-based>
    }
  ]
}
"""

# Few-shot examples covering the kinds of real human questions the system receives
_FEW_SHOT_EXAMPLES = """\
━━━ EXAMPLES ━━━

Q: "Is the leather work boot better value than product_id xyz-123?"
{
  "query_type": "hybrid",
  "reasoning": "Need product details from SQL plus vector similarity to compare semantics.",
  "steps": [
    {
      "engine": "sql",
      "query": "SELECT p.product_id, p.display_name, p.sku, p.item_code, c.name AS category, v.name AS vendor FROM products p LEFT JOIN categories c ON c.category_id = p.category_id LEFT JOIN vendors v ON v.vendor_id = p.vendor_id WHERE p.tenant_id = :tenant_id AND p.product_id = 'xyz-123' AND p.status = 'active'",
      "description": "Fetch details of the comparison product",
      "depends_on": null
    },
    {
      "engine": "vector",
      "query": "leather work boot durable safety footwear",
      "description": "Semantic search to find the referenced boot product",
      "depends_on": null
    }
  ]
}

Q: "Which gloves can I buy that fit within my remaining budget this month?"
{
  "query_type": "hybrid",
  "reasoning": "Vector search to find glove products, SQL to check user's remaining budget.",
  "steps": [
    {
      "engine": "vector",
      "query": "protective gloves safety hand protection",
      "description": "Find glove products semantically",
      "depends_on": null
    },
    {
      "engine": "sql",
      "query": "SELECT ubl.limit_amount - COALESCE(SUM(bt.amount), 0) AS remaining FROM user_budget_limits ubl LEFT JOIN budget_transactions bt ON bt.user_id = ubl.user_id AND bt.tenant_id = ubl.tenant_id AND bt.created_at >= DATE_TRUNC('month', NOW()) WHERE ubl.user_id = :user_id AND ubl.tenant_id = :tenant_id AND ubl.status = 'active' GROUP BY ubl.limit_amount",
      "description": "Get user's remaining budget for this month",
      "depends_on": null
    }
  ]
}

Q: "Who approved the last 3 large purchase requests over $500?"
{
  "query_type": "sql",
  "reasoning": "Approval workflow data is in PostgreSQL.",
  "steps": [
    {
      "engine": "sql",
      "query": "SELECT pr.id, pr.total_amount, pr.created_at, u.display_name AS requester, au.display_name AS approver, at2.decision, at2.decided_at FROM purchase_requests pr JOIN users u ON u.user_id = pr.user_id LEFT JOIN approval_workflows aw ON aw.purchase_request_id = pr.id LEFT JOIN approval_tasks at2 ON at2.workflow_id = aw.id AND at2.status = 'approved' LEFT JOIN users au ON au.user_id = at2.decided_by WHERE pr.tenant_id = :tenant_id AND pr.total_amount > 500 AND pr.status NOT IN ('deleted','cancelled') ORDER BY pr.created_at DESC LIMIT 3",
      "description": "Last 3 purchase requests over $500 with approver info",
      "depends_on": null
    }
  ]
}

Q: "Can users in the Finance team access medical supplies?"
{
  "query_type": "hybrid",
  "reasoning": "Graph to find Finance org unit's approved ranges, then check if medical supplies are included.",
  "steps": [
    {
      "engine": "graph",
      "query": "MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_ORG_UNIT]->(o:OrgUnit {status: 'active'}) WHERE toLower(o.name) CONTAINS 'finance' MATCH (o)-[:GOVERNED_BY]->(ar:ApprovedRange {status: 'active'})-[:INCLUDES_CATEGORY]->(c:Category {status: 'active'}) RETURN o.name AS org_unit, ar.name AS approved_range, collect(c.name) AS allowed_categories",
      "description": "Get approved product categories for Finance org unit",
      "depends_on": null
    }
  ]
}

Q: "Find safety respirators for confined space work"
{
  "query_type": "vector",
  "reasoning": "Semantic product search for a specific product type and use case.",
  "steps": [
    {
      "engine": "vector",
      "query": "safety respirator confined space breathing protection PPE",
      "description": "Semantic search for confined space respirator products",
      "depends_on": null
    }
  ]
}

Q: "Which of our vendors supply products to the Manchester store and haven't had an order in 60 days?"
{
  "query_type": "hybrid",
  "reasoning": "Graph to find vendors supplying the Manchester store, SQL to check order recency.",
  "steps": [
    {
      "engine": "graph",
      "query": "MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_SITE]->(:Site)-[:HAS_STORE]->(s:Store {status: 'active'}) WHERE toLower(s.name) CONTAINS 'manchester' MATCH (s)-[:STOCKS]->(p:Product {status: 'active'})<-[:SUPPLIES]-(v:Vendor {status: 'active'}) RETURN DISTINCT v.vendor_id AS vendor_id, v.name AS vendor_name",
      "description": "Find vendors supplying Manchester store",
      "depends_on": null
    },
    {
      "engine": "sql",
      "query": "SELECT v.name AS vendor, MAX(o.created_at) AS last_order, COUNT(o.id) AS total_orders FROM orders o JOIN vendors v ON v.vendor_id = o.vendor_id WHERE o.tenant_id = :tenant_id AND o.vendor_id = ANY(:prior_ids) AND o.status NOT IN ('deleted','cancelled') GROUP BY v.vendor_id, v.name HAVING MAX(o.created_at) < NOW() - INTERVAL '60 days' OR MAX(o.created_at) IS NULL",
      "description": "Check order recency for those vendors",
      "depends_on": 0
    }
  ]
}

Q: "What is the org unit hierarchy for the Operations department?"
{
  "query_type": "graph",
  "reasoning": "Org structure is a graph relationship query.",
  "steps": [
    {
      "engine": "graph",
      "query": "MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_ORG_UNIT]->(root:OrgUnit {status: 'active'}) WHERE toLower(root.name) CONTAINS 'operations' OPTIONAL MATCH (root)<-[:CHILD_OF*]-(child:OrgUnit {status: 'active'}) RETURN root.name AS root_org, collect(DISTINCT child.name) AS child_orgs, count(DISTINCT child) AS depth",
      "description": "Fetch Operations org hierarchy",
      "depends_on": null
    }
  ]
}
"""


def _build_system_prompt(engine_hint: str) -> str:
    """Build the full system prompt, emphasising relevant schema sections."""
    hint_block = ""
    if engine_hint == "sql":
        hint_block = "\n⚑ ROUTING HINT: This question is most likely answered by SQL (PostgreSQL). Focus on the SQL schema below.\n"
    elif engine_hint == "graph":
        hint_block = "\n⚑ ROUTING HINT: This question is most likely answered by graph traversal (Neo4j). Focus on the Graph schema below.\n"
    elif engine_hint == "vector":
        hint_block = "\n⚑ ROUTING HINT: This question is most likely answered by semantic vector search. A single vector step is likely sufficient.\n"
    elif engine_hint == "hybrid":
        hint_block = "\n⚑ ROUTING HINT: This question likely requires multiple engines (hybrid). Plan 2–3 steps across sql/graph/vector.\n"

    return _BASE_SYSTEM_PROMPT + hint_block + "\n" + _FEW_SHOT_EXAMPLES


def _build_schema_block(engine_hint: str, sql_schema: str, graph_schema: str) -> str:
    """Return only the schema portions relevant to the engine hint."""
    if engine_hint == "sql":
        return f"PostgreSQL Schema (use ONLY these tables):\n{sql_schema}\n\n(Graph queries not needed for this question.)"
    elif engine_hint == "graph":
        return f"Neo4j Graph Schema (use ONLY these labels/relationships):\n{graph_schema}\n\n(SQL queries not needed for this question.)"
    elif engine_hint == "vector":
        return "(Vector search: no SQL or Cypher needed — provide a natural language search text as the query.)"
    else:
        return f"PostgreSQL Schema:\n{sql_schema}\n\n{graph_schema}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def route_and_execute(
    question: str,
    tenant_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process a natural language question end-to-end.

    Returns:
      answer       — Natural language summary
      data         — Raw step results
      query_plan   — The execution plan
      routing_meta — Tier, confidence, latencies
    """
    t_total_start = now_ms()

    trace = QueryTrace(
        question_hash=question_hash(question),
        tenant_id=tenant_id,
        has_user_id=bool(user_id),
        routing_tier=3,
        classified_engine="unknown",
        routing_confidence=0.0,
        plan_cache_hit=False,
    )

    try:
        # ── Step 1: Classify ──────────────────────────────────────────────
        engine_hint, tier, confidence = classify(question)
        trace.routing_tier = tier
        trace.classified_engine = engine_hint
        trace.routing_confidence = confidence
        logger.info(
            f"[Router] tier={tier} engine={engine_hint} conf={confidence:.2f} "
            f"tenant={tenant_id}"
        )

        # ── Step 2: Plan (cached) ─────────────────────────────────────────
        plan = _get_cached_plan(question, tenant_id)
        if plan:
            trace.plan_cache_hit = True
            logger.info("[Router] plan cache hit")
        else:
            sql_schema = get_schema_description()
            graph_schema = get_graph_schema_description()
            plan, llm_plan_ms = _generate_plan(
                question, tenant_id, engine_hint, sql_schema, graph_schema
            )
            trace.llm_plan_latency_ms = llm_plan_ms

            if "error" in plan:
                return _error_response(
                    f"Plan generation failed: {plan.get('error')}",
                    plan, trace, t_total_start,
                )

            # ── Step 3: Structural validation ─────────────────────────────
            try:
                warnings = validate_plan(plan)
                trace.validation_warnings = warnings
            except PlanValidationError as exc:
                return _error_response(str(exc), plan, trace, t_total_start)

            # ── Step 4: Schema validation + correction retry ───────────────
            sql_schema_dict = build_sql_schema_dict(sql_schema)
            graph_schema_dict = parse_graph_schema(graph_schema)
            schema_errors = validate_plan_schema(plan, sql_schema_dict, graph_schema_dict)

            if schema_errors:
                logger.warning(f"[Router] schema errors, retrying: {schema_errors}")
                plan, retry_ms = _correct_plan(
                    question, tenant_id, engine_hint, sql_schema, graph_schema,
                    plan, schema_errors,
                )
                trace.llm_plan_latency_ms += retry_ms
                trace.validation_warnings.extend([f"corrected: {e}" for e in schema_errors])

                if "error" in plan:
                    return _error_response(
                        f"Plan correction failed: {plan.get('error')}",
                        plan, trace, t_total_start,
                    )
                # Re-validate after correction
                try:
                    validate_plan(plan)
                except PlanValidationError as exc:
                    return _error_response(str(exc), plan, trace, t_total_start)

            _set_cached_plan(question, tenant_id, plan)

        # ── Step 5: Execute ───────────────────────────────────────────────
        step_results, step_traces = await _execute_plan(plan, tenant_id, user_id)
        trace.steps = step_traces

        # ── Step 6: Summarize ─────────────────────────────────────────────
        t_sum = now_ms()
        answer, _ = _summarize(question, step_results, plan)
        trace.llm_summarize_latency_ms = now_ms() - t_sum

        trace.total_latency_ms = now_ms() - t_total_start
        trace.emit()

        return {
            "answer": answer,
            "data": step_results,
            "query_plan": plan,
            "routing_meta": _meta(trace),
        }

    except Exception as exc:
        trace.error = str(exc)
        trace.total_latency_ms = now_ms() - t_total_start
        trace.emit()
        raise


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def _generate_plan(
    question: str,
    tenant_id: str,
    engine_hint: str,
    sql_schema: str,
    graph_schema: str,
) -> Tuple[Dict, float]:
    system_prompt = _build_system_prompt(engine_hint)
    schema_block = _build_schema_block(engine_hint, sql_schema, graph_schema)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"{schema_block}\n\n"
            f"Tenant ID: {tenant_id}\n\n"
            f"Question: {question}\n\n"
            "Generate the query plan as JSON."
        )},
    ]

    plan, latency_ms = chat_json(messages)
    logger.info(
        f"[Router] plan: type={plan.get('query_type')} "
        f"steps={len(plan.get('steps', []))} latency={latency_ms:.0f}ms"
    )
    return plan, latency_ms


def _correct_plan(
    question: str,
    tenant_id: str,
    engine_hint: str,
    sql_schema: str,
    graph_schema: str,
    bad_plan: Dict,
    errors: List[str],
) -> Tuple[Dict, float]:
    """Ask LLM to fix schema errors in a generated plan."""
    system_prompt = _build_system_prompt(engine_hint)
    schema_block = _build_schema_block(engine_hint, sql_schema, graph_schema)
    error_list = "\n".join(f"  - {e}" for e in errors)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"{schema_block}\n\n"
            f"Tenant ID: {tenant_id}\n\n"
            f"Question: {question}\n\n"
            "Generate the query plan as JSON."
        )},
        {"role": "assistant", "content": json.dumps(bad_plan)},
        {"role": "user", "content": (
            f"Your plan has schema errors. Fix it using ONLY the tables/labels listed above:\n"
            f"{error_list}\n\n"
            "Return the corrected plan as JSON."
        )},
    ]

    plan, latency_ms = chat_json(messages)
    logger.info(f"[Router] corrected plan: type={plan.get('query_type')} latency={latency_ms:.0f}ms")
    return plan, latency_ms


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

async def _execute_plan(
    plan: Dict[str, Any],
    tenant_id: str,
    user_id: Optional[str],
) -> Tuple[List[Dict], List[StepTrace]]:
    steps = plan.get("steps", [])
    step_results: List[Dict] = []
    step_traces: List[StepTrace] = []

    for i, step in enumerate(steps):
        engine = step.get("engine", "")
        query = step.get("query", "")
        t0 = now_ms()

        base_params: Dict[str, Any] = {"tenant_id": tenant_id}
        if user_id:
            base_params["user_id"] = user_id

        dep_idx = step.get("depends_on")
        if dep_idx is not None and isinstance(dep_idx, int) and dep_idx < len(step_results):
            prior = step_results[dep_idx]
            prior_ids = _extract_ids(prior.get("data", []))
            if prior_ids:
                base_params["prior_ids"] = prior_ids
            else:
                logger.warning(f"[Router] step {i} depends_on step {dep_idx} which returned no IDs")

        trace = StepTrace(
            step_index=i, engine=engine,
            description=step.get("description", ""),
            latency_ms=0.0, row_count=0,
        )

        data, err = await _run_step(engine, query, base_params, tenant_id, user_id)
        trace.latency_ms = now_ms() - t0
        trace.row_count = len(data)
        if err:
            trace.error = err

        step_results.append({
            "step": i, "engine": engine,
            "description": step.get("description", ""),
            "data": data, "row_count": len(data),
            **({"error": err} if err else {}),
        })
        step_traces.append(trace)

    return step_results, step_traces


async def _run_step(
    engine: str,
    query: str,
    params: Dict[str, Any],
    tenant_id: str,
    user_id: Optional[str],
) -> Tuple[List[Dict], Optional[str]]:
    """Execute one step. Returns (data, error_string_or_None)."""
    try:
        if engine == "sql":
            return execute_readonly_sql(query, params), None

        elif engine == "graph":
            graph_params = {k: v for k, v in params.items() if k in ("tenant_id", "prior_ids")}
            return execute_readonly_cypher(query, graph_params), None

        elif engine == "vector":
            return await _vector_search(query, tenant_id, user_id), None

        else:
            return [], f"Unknown engine: {engine}"

    except Exception as exc:
        logger.error(f"[Router] step execution failed engine={engine}: {exc}")
        return [], str(exc)


# ---------------------------------------------------------------------------
# Vector search with governance filter
# ---------------------------------------------------------------------------

async def _vector_search(
    query_text: str,
    tenant_id: str,
    user_id: Optional[str],
) -> List[Dict]:
    try:
        import data_intelligence_service.vector.embeddings as _emb_mod
        import data_intelligence_service.vector.pg_vector as _vec_mod
        import data_intelligence_service.graph.queries.approved_universe as _gov_mod

        query_embedding = _emb_mod.embed_text(query_text)

        approved_ids: Optional[List[str]] = None
        if user_id:
            try:
                result = _gov_mod.get_approved_product_ids(tenant_id, user_id, is_admin=False)
                approved_ids = ["__all__"] if result == "__all__" else result
            except Exception as exc:
                logger.warning(f"[Router] governance fetch failed for user {user_id}: {exc} — empty filter")
                approved_ids = []
        else:
            approved_ids = ["__all__"]

        raw = _vec_mod.similarity_search(
            tenant_id=tenant_id,
            query_embedding=query_embedding,
            approved_product_ids=approved_ids,
            top_k=20,
        )
        threshold = SETTINGS.VECTOR_SIMILARITY_THRESHOLD
        filtered = [r for r in raw if r.get("similarity", 0) >= threshold]
        logger.info(f"[Router] vector: {len(raw)} raw → {len(filtered)} above threshold {threshold}")
        return filtered

    except Exception as exc:
        logger.error(f"[Router] vector search failed: {exc}")
        return [{"error": f"Vector search failed: {exc}"}]


# ---------------------------------------------------------------------------
# ID extraction for hybrid chaining
# ---------------------------------------------------------------------------

def _extract_ids(data: List[Dict]) -> List[str]:
    _safe = __import__("re").compile(r'^[\w\-]{1,128}$')
    seen: set = set()
    ids: List[str] = []
    for row in data:
        for key, val in row.items():
            if "id" in key.lower() and val:
                s = str(val)
                if s not in seen and _safe.match(s):
                    seen.add(s)
                    ids.append(s)
    return ids


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

def _summarize(
    question: str,
    results: List[Dict],
    plan: Dict[str, Any],
) -> Tuple[str, float]:
    results_text = json.dumps(results, indent=2, default=str)
    if len(results_text) > 12_000:
        results_text = results_text[:12_000] + "\n... (truncated)"

    messages = [
        {"role": "system", "content": (
            "You are a data analyst for ZeroQue, a procurement platform.\n"
            "Summarize the query results in clear, concise natural language.\n"
            "Use bullet points for lists. Include specific names, numbers, and units.\n"
            "If a step returned an error, acknowledge what data is missing.\n"
            "If data is empty, say so clearly and explain what it means.\n"
            "NEVER make up data — only report what is in the results."
        )},
        {"role": "user", "content": (
            f"Question: {question}\n\n"
            f"Query plan: {json.dumps(plan, indent=2)}\n\n"
            f"Results:\n{results_text}\n\n"
            "Provide a clear, concise answer."
        )},
    ]
    return chat(messages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_response(
    message: str,
    plan: Dict,
    trace: "QueryTrace",
    t_start: float,
) -> Dict[str, Any]:
    trace.error = message
    trace.total_latency_ms = now_ms() - t_start
    trace.emit()
    return {
        "answer": message,
        "data": [],
        "query_plan": plan,
        "routing_meta": _meta(trace),
    }


def _meta(trace: "QueryTrace") -> Dict[str, Any]:
    return {
        "routing_tier": trace.routing_tier,
        "classified_engine": trace.classified_engine,
        "routing_confidence": trace.routing_confidence,
        "plan_cache_hit": trace.plan_cache_hit,
        "total_latency_ms": round(trace.total_latency_ms, 1),
        "llm_plan_latency_ms": round(trace.llm_plan_latency_ms, 1),
        "llm_summarize_latency_ms": round(trace.llm_summarize_latency_ms, 1),
        "validation_warnings": trace.validation_warnings,
    }
