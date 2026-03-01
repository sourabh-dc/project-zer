"""
Intelligence Service — Query Router Agent.

This is the brain of the intelligence layer. It takes a natural language
question from an admin, classifies it, and routes it to the right engine(s):

  1. Graph (Neo4j) — for relationship/topology questions
  2. SQL (Postgres) — for exact numbers, aggregations, filtering
  3. Vector (pgvector) — for fuzzy text/semantic matching
  4. Hybrid — combines multiple engines for complex questions

The LLM generates the query, executes it, then summarizes the results
in natural language.
"""
import json
from typing import Dict, Any, Optional

import httpx

from intelligence_service.core.llm import chat_json, chat
from intelligence_service.core.db import execute_readonly_sql, get_schema_description
from intelligence_service.core.graph import execute_readonly_cypher, get_graph_schema_description
from intelligence_service.core.config import SETTINGS
from intelligence_service.core.logger import logger

ROUTER_SYSTEM_PROMPT = """You are a query routing agent for ZeroQue, a governance platform for consumables procurement.

Given a natural language question from an admin, you must:
1. Classify the query type
2. Generate the appropriate query/queries
3. Return a JSON object

Query types:
- "graph": For relationship questions (who belongs to what, what products are in which range, org hierarchy, etc.)
- "sql": For exact numbers, counts, sums, date ranges, budget figures, spending analysis
- "vector": For fuzzy text search (find products similar to X, search by description)
- "hybrid": When you need data from multiple sources (e.g., "which users in Mumbai spent more than 50k" needs graph for Mumbai users + SQL for spending)

Your response MUST be a JSON object with this structure:
{
  "query_type": "graph" | "sql" | "vector" | "hybrid",
  "reasoning": "Brief explanation of why this route was chosen",
  "steps": [
    {
      "engine": "graph" | "sql" | "vector",
      "query": "The actual Cypher/SQL/search query",
      "description": "What this step retrieves",
      "depends_on": null or step_index (0-based) if this step needs results from a prior step
    }
  ]
}

IMPORTANT RULES:
- For SQL: Only generate SELECT statements. Never INSERT/UPDATE/DELETE. Use :tenant_id as parameter for tenant filtering.
- For Cypher: Only generate MATCH/RETURN queries. Never CREATE/DELETE/SET/MERGE. Use $tenant_id as parameter.
- For Vector: The query field should be the search text (natural language).
- For hybrid queries: Order steps so dependencies are resolved first.
- Always filter by tenant_id when available.
- Always filter for active records (status = 'active' in graph, status != 'deleted' in SQL).
- Use parameterized queries where possible.

You MUST always return a valid JSON with query_type, reasoning, and steps. Never return an empty object.
"""


async def route_and_execute(
    question: str,
    tenant_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process a natural language question end-to-end.

    Returns a dict with:
      - answer: Natural language summary
      - data: Raw query results
      - query_plan: The routing plan the LLM chose
    """
    sql_schema = get_schema_description()
    graph_schema = get_graph_schema_description()

    plan = _generate_plan(question, tenant_id, sql_schema, graph_schema)

    if "error" in plan:
        return {"answer": f"Failed to generate query plan: {plan.get('error')}", "data": [], "query_plan": plan}

    results = await _execute_plan(plan, tenant_id, user_id)

    answer = _summarize(question, results, plan)

    return {
        "answer": answer,
        "data": results,
        "query_plan": plan,
    }


def _generate_plan(question: str, tenant_id: str, sql_schema: str, graph_schema: str) -> Dict[str, Any]:
    """Use the LLM to generate a query execution plan."""
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Database Schema (PostgreSQL):
{sql_schema}

{graph_schema}

Tenant ID for this query: {tenant_id}

Admin's question: {question}

Generate the query plan as JSON."""},
    ]

    plan = chat_json(messages)
    logger.info(f"Query plan: type={plan.get('query_type')}, steps={len(plan.get('steps', []))}")
    return plan


async def _execute_plan(plan: Dict[str, Any], tenant_id: str, user_id: Optional[str]) -> list:
    """Execute each step in the plan, feeding results forward for dependencies."""
    steps = plan.get("steps", [])
    step_results = []

    for i, step in enumerate(steps):
        engine = step.get("engine", "")
        query = step.get("query", "")

        dep_idx = step.get("depends_on")
        if dep_idx is not None and isinstance(dep_idx, int) and dep_idx < len(step_results):
            prior = step_results[dep_idx]
            query = _inject_prior_results(query, prior)

        try:
            if engine == "sql":
                sql_params = {"tenant_id": tenant_id}
                if user_id:
                    sql_params["user_id"] = user_id
                data = execute_readonly_sql(query, sql_params)
            elif engine == "graph":
                data = execute_readonly_cypher(query, {"tenant_id": tenant_id})
            elif engine == "vector":
                data = await _vector_search(query, tenant_id, user_id)
            else:
                data = [{"error": f"Unknown engine: {engine}"}]

            step_results.append({
                "step": i,
                "engine": engine,
                "description": step.get("description", ""),
                "data": data,
                "row_count": len(data),
            })
        except Exception as exc:
            logger.error(f"Step {i} ({engine}) failed: {exc}")
            step_results.append({
                "step": i,
                "engine": engine,
                "description": step.get("description", ""),
                "error": str(exc),
                "data": [],
                "row_count": 0,
            })

    return step_results


def _inject_prior_results(query: str, prior_result: dict) -> str:
    """Replace placeholder references to prior step results in a query.

    Convention: the LLM can use {{step_N_ids}} to reference a list of IDs
    from a prior step. We replace it with the actual values.
    """
    data = prior_result.get("data", [])
    if not data:
        return query

    all_ids = set()
    for row in data:
        for key, val in row.items():
            if "id" in key.lower() and val:
                all_ids.add(str(val))

    if all_ids:
        id_list = "'" + "','".join(all_ids) + "'"
        for placeholder in [f"{{{{step_{prior_result['step']}_ids}}}}", "{{prior_ids}}"]:
            query = query.replace(placeholder, id_list)

    return query


async def _vector_search(query_text: str, tenant_id: str, user_id: Optional[str]) -> list:
    """Call the vector service for semantic search."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{SETTINGS.VECTOR_SERVICE_URL}/vector/search",
                json={
                    "query": query_text,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "top_k": 20,
                    "skip_governance": True,
                },
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])
            return [{"error": f"Vector service returned {resp.status_code}"}]
    except Exception as exc:
        return [{"error": f"Vector service unavailable: {exc}"}]


def _summarize(question: str, results: list, plan: Dict[str, Any]) -> str:
    """Use the LLM to summarize the query results in natural language."""
    results_text = json.dumps(results, indent=2, default=str)
    if len(results_text) > 8000:
        results_text = results_text[:8000] + "\n... (truncated)"

    messages = [
        {"role": "system", "content": """You are a data analyst for ZeroQue.
Summarize the query results in clear, concise natural language.
Use bullet points for lists. Include specific numbers and names.
If there are errors in the results, mention them.
If the data is empty, say so clearly.
Do not make up data — only report what is in the results."""},
        {"role": "user", "content": f"""Question: {question}

Query plan used: {json.dumps(plan, indent=2)}

Results:
{results_text}

Provide a clear, concise answer to the admin's question based on these results."""},
    ]

    return chat(messages)
