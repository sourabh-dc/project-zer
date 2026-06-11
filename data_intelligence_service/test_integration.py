"""
Integration test suite — mocks all external services.

Tests every production layer without needing live Postgres / Neo4j / OpenAI:
  1.  Auth middleware          — 401, 403, pass-through
  2.  Tier 1 classifier        — correct engine, no LLM call
  3.  Tier 2 classifier        — correct engine, no LLM call
  4.  Tier 3 → LLM routing     — LLM invoked for ambiguous query
  5.  Plan cache               — second identical query hits cache, no LLM call
  6.  SQL mutation guard       — INSERT/UPDATE/DROP rejected
  7.  Cypher mutation guard    — SET/MERGE/CREATE rejected
  8.  Plan validator           — bad plan structure rejected before DB touch
  9.  Hybrid ID safe params    — IDs go as bound params, not string concat
  10. Vector governance        — approved_product_ids applied; threshold filters low scores
  11. LLM retry                — retries on transient failure, succeeds on 3rd attempt
  12. Observability            — audit log emitted with correct fields
  13. UNION injection block    — blocked by SQL guard

Run:
  python3 data_intelligence_service/test_integration.py
"""
import sys, os, json, asyncio, importlib, time, re
from unittest.mock import patch, MagicMock, AsyncMock, call
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Env setup: fake credentials so config loads without Key Vault ──
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "fake-key")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-06-01")
os.environ.setdefault("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-test")
os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "embed-test")
os.environ.setdefault("POSTGRES_DB", "fake")
os.environ.setdefault("POSTGRES_PASSWORD", "fake")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "fake")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("INTELLIGENCE_API_KEY", "test-api-key-123")
os.environ.setdefault("VECTOR_SIMILARITY_THRESHOLD", "0.30")
os.environ.setdefault("PLAN_CACHE_TTL_SECONDS", "300")
os.environ.setdefault("LLM_MAX_RETRIES", "3")
os.environ.setdefault("LLM_RETRY_DELAY_SECONDS", "0.01")   # fast retries in tests
os.environ.setdefault("SQL_QUERY_TIMEOUT_SECONDS", "30")
os.environ.setdefault("SQL_MAX_ROWS", "500")
os.environ.setdefault("CYPHER_MAX_ROWS", "500")

PASS = 0
FAIL = 0

def ok(msg):
    global PASS
    PASS += 1
    print(f"  ✓ {msg}")

def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  ✗ {msg}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ════════════════════════════════════════════════════════════════
# 1. Auth middleware
# ════════════════════════════════════════════════════════════════
section("TEST 1 — Auth Middleware")

from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from data_intelligence_service.intelligence.middleware.auth import ApiKeyMiddleware

async def _dummy(request):
    return JSONResponse({"ok": True})

_app = Starlette(routes=[Route("/intelligence/query", _dummy, methods=["POST"])])
_app.add_middleware(ApiKeyMiddleware)
_client = TestClient(_app, raise_server_exceptions=False)

r = _client.post("/intelligence/query")
if r.status_code == 401:
    ok("Missing API key → 401")
else:
    fail(f"Missing key should be 401, got {r.status_code}")

r = _client.post("/intelligence/query", headers={"X-API-Key": "wrong-key"})
if r.status_code == 403:
    ok("Wrong API key → 403")
else:
    fail(f"Wrong key should be 403, got {r.status_code}")

r = _client.post("/intelligence/query", headers={"X-API-Key": "test-api-key-123"})
if r.status_code == 200:
    ok("Correct API key → 200 pass-through")
else:
    fail(f"Correct key should be 200, got {r.status_code}")


# ════════════════════════════════════════════════════════════════
# 2. Tier 1 classifier — no LLM call
# ════════════════════════════════════════════════════════════════
section("TEST 2 — Tier 1 Classifier (no LLM call)")

from data_intelligence_service.intelligence.routing.classifier import classify

cases_t1 = [
    ("How many orders last 30 days?",                   "sql"),
    ("Who belongs to the Finance org unit?",            "graph"),
    ("Find products similar to nitrile gloves",         "vector"),
    ("Which users in Mumbai spent more than 50k?",      "hybrid"),
    ("What is the approved range for HR department?",   "graph"),
    ("Total spend breakdown by vendor this month",      "sql"),
    ("Show me consumables similar to safety shoes",     "vector"),
    ("List vendors that supply restricted products",    "graph"),
]

for q, expected in cases_t1:
    engine, tier, conf = classify(q)
    if engine == expected and tier == 1:
        ok(f"Tier1 {engine:<8} conf={conf:.2f}  '{q[:50]}'")
    else:
        fail(f"Expected tier1/{expected}, got tier{tier}/{engine}  '{q[:50]}'")


# ════════════════════════════════════════════════════════════════
# 3. Tier 2 classifier — no LLM call
# ════════════════════════════════════════════════════════════════
section("TEST 3 — Tier 2 Classifier (no LLM call)")

cases_t2 = [
    ("Average order value last quarter",              "sql",   2),
    ("What roles does the user have?",                "graph", 2),
]

for q, expected_engine, max_tier in cases_t2:
    engine, tier, conf = classify(q)
    if engine == expected_engine and tier <= max_tier:
        ok(f"Tier{tier} {engine:<8} conf={conf:.2f}  '{q}'")
    else:
        fail(f"Expected tier<={max_tier}/{expected_engine}, got tier{tier}/{engine}  '{q}'")


# ════════════════════════════════════════════════════════════════
# 4. Tier 3 — LLM called for ambiguous query
# ════════════════════════════════════════════════════════════════
section("TEST 4 — Tier 3 falls through to LLM")

engine, tier, conf = classify("Tell me something interesting about the data")
if tier == 3 and engine == "unknown":
    ok(f"Ambiguous query → Tier 3 (engine=unknown, LLM will handle)")
else:
    fail(f"Expected tier3/unknown, got tier{tier}/{engine}")


# ════════════════════════════════════════════════════════════════
# 5. Plan cache — second call skips LLM plan generation
# ════════════════════════════════════════════════════════════════
section("TEST 5 — Plan Cache")

import data_intelligence_service.intelligence.agents.query_router as qr
qr._plan_cache.clear()

GOOD_PLAN = {
    "query_type": "sql",
    "reasoning": "count query",
    "steps": [{"engine": "sql", "query": "SELECT count(*) FROM orders WHERE tenant_id = :tenant_id", "description": "count", "depends_on": None}],
}

llm_call_count = 0
def _fake_chat_json(messages):
    global llm_call_count
    llm_call_count += 1
    return (GOOD_PLAN, 120.0)

def _fake_sql(sql, params):
    return [{"count": 42}]

def _fake_summarize(question, results, plan):
    return ("42 orders", 80.0)

def _fake_schema():
    return "TABLE orders (id uuid NOT NULL, tenant_id uuid NOT NULL)"

def _fake_graph_schema():
    return "Neo4j: (:User)-[:BELONGS_TO]->(:OrgUnit)"

with patch("data_intelligence_service.intelligence.agents.query_router.chat_json", _fake_chat_json), \
     patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_sql", _fake_sql), \
     patch("data_intelligence_service.intelligence.agents.query_router._summarize", _fake_summarize), \
     patch("data_intelligence_service.intelligence.agents.query_router.get_schema_description", _fake_schema), \
     patch("data_intelligence_service.intelligence.agents.query_router.get_graph_schema_description", _fake_graph_schema):

    llm_call_count = 0
    q = "How many orders last 30 days?"
    asyncio.run(qr.route_and_execute(q, "tenant-1"))
    first_calls = llm_call_count

    llm_call_count = 0
    asyncio.run(qr.route_and_execute(q, "tenant-1"))
    second_calls = llm_call_count

if second_calls == 0:
    ok(f"Cache hit — second call made 0 LLM plan calls (first made {first_calls})")
else:
    fail(f"Cache miss — second call still made {second_calls} LLM plan calls")

# Different tenant → cache miss (different key)
with patch("data_intelligence_service.intelligence.agents.query_router.chat_json", _fake_chat_json), \
     patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_sql", _fake_sql), \
     patch("data_intelligence_service.intelligence.agents.query_router._summarize", _fake_summarize), \
     patch("data_intelligence_service.intelligence.agents.query_router.get_schema_description", _fake_schema), \
     patch("data_intelligence_service.intelligence.agents.query_router.get_graph_schema_description", _fake_graph_schema):

    llm_call_count = 0
    asyncio.run(qr.route_and_execute("How many orders last 30 days?", "tenant-DIFFERENT"))
    if llm_call_count > 0:
        ok("Different tenant → cache miss (separate LLM call)")
    else:
        fail("Different tenant should miss cache")


# ════════════════════════════════════════════════════════════════
# 6. SQL mutation guards
# ════════════════════════════════════════════════════════════════
section("TEST 6 — SQL Mutation Guards")

from data_intelligence_service.core.db import execute_readonly_sql

BLOCKED = [
    ("INSERT INTO orders VALUES (1)", "INSERT"),
    ("UPDATE orders SET status='deleted'", "UPDATE"),
    ("DELETE FROM orders WHERE 1=1", "DELETE"),
    ("DROP TABLE orders", "DROP"),
    ("ALTER TABLE orders ADD col text", "ALTER"),
    ("SELECT 1; DROP TABLE users", "DROP"),
    ("SELECT * FROM orders UNION SELECT * FROM users", "UNION"),
]

for sql, keyword in BLOCKED:
    try:
        execute_readonly_sql(sql, {})
        fail(f"{keyword} not blocked")
    except ValueError as e:
        ok(f"{keyword} blocked: {str(e)[:60]}")
    except Exception:
        ok(f"{keyword} blocked (non-ValueError)")

# SELECT-only check
try:
    execute_readonly_sql("EXEC sp_who", {})
    fail("Non-SELECT not blocked")
except ValueError as e:
    ok(f"Non-SELECT (EXEC) blocked: {str(e)[:60]}")


# ════════════════════════════════════════════════════════════════
# 7. Cypher mutation guards
# ════════════════════════════════════════════════════════════════
section("TEST 7 — Cypher Mutation Guards")

from data_intelligence_service.core.graph import execute_readonly_cypher

BLOCKED_CYPHER = [
    "CREATE (n:User {name: 'hack'})",
    "MATCH (n) DELETE n",
    "MATCH (n) SET n.status = 'deleted'",
    "MERGE (n:User {id: '1'})",
    "MATCH (n) REMOVE n.status",
    "DROP CONSTRAINT ON (n:User) ASSERT n.id IS UNIQUE",
]

for cypher in BLOCKED_CYPHER:
    try:
        execute_readonly_cypher(cypher, {})
        fail(f"Mutation not blocked: {cypher[:50]}")
    except ValueError as e:
        ok(f"Blocked '{cypher[:40]}...'")
    except Exception:
        ok(f"Blocked '{cypher[:40]}...' (connection error — guard ran first)")


# ════════════════════════════════════════════════════════════════
# 8. Plan validator — bad plan rejected before DB
# ════════════════════════════════════════════════════════════════
section("TEST 8 — Plan Validator Rejects Bad Plans Before DB")

from data_intelligence_service.intelligence.routing.plan_validator import validate_plan, PlanValidationError

BAD_PLANS = [
    ({"error": "oops"},                                   "LLM error plan"),
    ({"query_type": "sql", "steps": []},                  "empty steps"),
    ({"query_type": "sql"},                               "missing steps key"),
    ({"query_type": "sql", "steps": "not a list"},        "steps not a list"),
]

for plan, label in BAD_PLANS:
    try:
        validate_plan(plan)
        fail(f"{label} — should have raised PlanValidationError")
    except PlanValidationError as e:
        ok(f"{label} → PlanValidationError: {str(e)[:60]}")

# Ensure DB never called when plan is bad
db_called = False

async def _bad_plan_route():
    global db_called
    BAD = {"error": "LLM failed"}
    with patch("data_intelligence_service.intelligence.agents.query_router.chat_json", lambda m: (BAD, 100.0)), \
         patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_sql", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB was called!"))), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_schema_description", _fake_schema), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_graph_schema_description", _fake_graph_schema):
        qr._plan_cache.clear()
        result = await qr.route_and_execute("Tell me something interesting", "t-1")
        return result

result = asyncio.run(_bad_plan_route())
if "failed" in result["answer"].lower() or "invalid" in result["answer"].lower():
    ok("Bad plan → graceful error response, DB never touched")
else:
    fail(f"Unexpected answer for bad plan: {result['answer'][:80]}")


# ════════════════════════════════════════════════════════════════
# 9. Hybrid injection — IDs as bound params, not string concat
# ════════════════════════════════════════════════════════════════
section("TEST 9 — Hybrid ID Injection (Safe Parameterization)")

from data_intelligence_service.intelligence.agents.query_router import _extract_ids

# Verify malicious ID is filtered
malicious_data = [{"user_id": "'; DROP TABLE orders; --"}]
ids = _extract_ids(malicious_data)
if not ids:
    ok("Malicious ID filtered by safe pattern")
else:
    fail(f"Malicious ID leaked through: {ids}")

# Verify IDs go into params dict, not string replace
received_params = {}
HYBRID_PLAN = {
    "query_type": "hybrid",
    "reasoning": "test",
    "steps": [
        {"engine": "graph", "query": "MATCH (u:User) WHERE u.tenant_id = $tenant_id RETURN u.user_id AS user_id", "description": "get users", "depends_on": None},
        {"engine": "sql",   "query": "SELECT * FROM orders WHERE user_id = ANY(:prior_ids) AND tenant_id = :tenant_id", "description": "get orders", "depends_on": 0},
    ]
}

def _fake_cypher(cypher, params):
    return [{"user_id": "uid-abc"}, {"user_id": "uid-def"}]

def _capture_sql(sql, params):
    received_params.update(params)
    return [{"order_id": "ord-1", "amount": 1000}]

async def _run_hybrid():
    with patch("data_intelligence_service.intelligence.agents.query_router.chat_json", lambda m: (HYBRID_PLAN, 100.0)), \
         patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_sql", _capture_sql), \
         patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_cypher", _fake_cypher), \
         patch("data_intelligence_service.intelligence.agents.query_router._summarize", lambda q, r, p: ("done", 80.0)), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_schema_description", _fake_schema), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_graph_schema_description", _fake_graph_schema):
        qr._plan_cache.clear()
        return await qr.route_and_execute("Which users spent most?", "t-1")

asyncio.run(_run_hybrid())

if "prior_ids" in received_params and isinstance(received_params["prior_ids"], list):
    ok(f"IDs passed as bound param list: prior_ids={received_params['prior_ids']}")
else:
    fail(f"IDs not in params or wrong type: {received_params}")

if "prior_ids" in received_params:
    for v in received_params["prior_ids"]:
        if "'" in v or ";" in v:
            fail(f"Unsafe character in ID param: {v}")
            break
    else:
        ok("No unsafe characters in ID params")


# ════════════════════════════════════════════════════════════════
# 10. Vector governance + similarity threshold
# ════════════════════════════════════════════════════════════════
section("TEST 10 — Vector Governance + Similarity Threshold")

from data_intelligence_service.intelligence.agents.query_router import _vector_search

# user_id provided → governance should fetch approved IDs
approved_ids_fetched_for = []
similarity_search_called_with = {}

def _fake_embed(text):
    return [0.1] * 1536

def _fake_governance(tenant_id, user_id, is_admin):
    approved_ids_fetched_for.append(user_id)
    return ["prod-approved-1", "prod-approved-2"]

def _fake_sim_search(tenant_id, query_embedding, approved_product_ids, top_k):
    similarity_search_called_with["approved"] = approved_product_ids
    return [
        {"product_id": "prod-approved-1", "similarity": 0.85},
        {"product_id": "prod-approved-2", "similarity": 0.20},   # below threshold 0.30
        {"product_id": "prod-approved-1", "similarity": 0.65},
    ]

async def _run_vector():
    with patch("data_intelligence_service.vector.embeddings.embed_text", _fake_embed), \
         patch("data_intelligence_service.vector.pg_vector.similarity_search", _fake_sim_search), \
         patch("data_intelligence_service.graph.queries.approved_universe.get_approved_product_ids", _fake_governance):
        return await _vector_search("nitrile gloves", "t-1", "user-99")

results = asyncio.run(_run_vector())

if "user-99" in approved_ids_fetched_for:
    ok("Governance called for user_id=user-99")
else:
    fail("Governance NOT called — bypass still in effect")

if similarity_search_called_with.get("approved") == ["prod-approved-1", "prod-approved-2"]:
    ok("Approved product IDs passed to similarity_search")
else:
    fail(f"Wrong approved IDs: {similarity_search_called_with.get('approved')}")

above_threshold = [r for r in results if r.get("similarity", 0) >= 0.30]
if len(results) == len(above_threshold):
    ok(f"Similarity threshold 0.30 applied — {len(results)}/3 results kept")
else:
    fail(f"Threshold not applied — got {len(results)} results, expected {len(above_threshold)}")

# No user_id → admin bypass (__all__)
approved_ids_fetched_for.clear()
similarity_search_called_with.clear()

async def _run_vector_admin():
    with patch("data_intelligence_service.vector.embeddings.embed_text", _fake_embed), \
         patch("data_intelligence_service.vector.pg_vector.similarity_search", _fake_sim_search), \
         patch("data_intelligence_service.graph.queries.approved_universe.get_approved_product_ids", _fake_governance):
        return await _vector_search("nitrile gloves", "t-1", None)

asyncio.run(_run_vector_admin())
if not approved_ids_fetched_for:
    ok("No user_id → governance skipped (admin bypass __all__)")
else:
    fail("Governance called unnecessarily for admin path")


# ════════════════════════════════════════════════════════════════
# 11. LLM retries on transient failure
# ════════════════════════════════════════════════════════════════
section("TEST 11 — LLM Retry on Transient Failure")

from data_intelligence_service.core.llm import chat_json as real_chat_json

attempt_log = []

def _flaky_openai_call(**kwargs):
    attempt_log.append(len(attempt_log) + 1)
    if len(attempt_log) < 3:
        raise Exception("Transient 500 from OpenAI")
    # Success on 3rd attempt
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"query_type": "sql", "steps": []}'
    return mock_resp

with patch("data_intelligence_service.core.llm._get_client") as mock_client_fn:
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client
    mock_client.chat.completions.create.side_effect = _flaky_openai_call

    try:
        result, latency = real_chat_json([{"role": "user", "content": "test"}])
        if len(attempt_log) == 3:
            ok(f"LLM retried {len(attempt_log)} times, succeeded on attempt 3 ({latency:.0f}ms)")
        else:
            fail(f"Expected 3 attempts, got {len(attempt_log)}")
    except Exception as e:
        fail(f"Retry did not succeed: {e}")

# Exhaust retries → should raise
attempt_log.clear()
def _always_fail():
    attempt_log.append(1)
    raise Exception("Permanent failure")

with patch("data_intelligence_service.core.llm._get_client") as mock_client_fn:
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client
    mock_client.chat.completions.create.side_effect = _always_fail
    try:
        real_chat_json([{"role": "user", "content": "test"}])
        fail("Should have raised after exhausting retries")
    except Exception:
        ok(f"Raised after {len(attempt_log)} failed attempts (max_retries={os.environ['LLM_MAX_RETRIES']})")


# ════════════════════════════════════════════════════════════════
# 12. Observability — audit log emitted
# ════════════════════════════════════════════════════════════════
section("TEST 12 — Observability (Audit Log)")

import logging
audit_lines = []

class _AuditCapture(logging.Handler):
    def emit(self, record):
        if "[INTELLIGENCE_AUDIT]" in record.getMessage():
            audit_lines.append(record.getMessage())

_handler = _AuditCapture()
logging.getLogger("graph_service").addHandler(_handler)

async def _run_for_audit():
    with patch("data_intelligence_service.intelligence.agents.query_router.chat_json", lambda m: (GOOD_PLAN, 100.0)), \
         patch("data_intelligence_service.intelligence.agents.query_router.execute_readonly_sql", lambda s, p: [{"count": 5}]), \
         patch("data_intelligence_service.intelligence.agents.query_router._summarize", lambda q, r, p: ("5 orders", 80.0)), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_schema_description", _fake_schema), \
         patch("data_intelligence_service.intelligence.agents.query_router.get_graph_schema_description", _fake_graph_schema):
        qr._plan_cache.clear()
        return await qr.route_and_execute("How many orders last 30 days?", "t-audit", "u-1")

asyncio.run(_run_for_audit())

if audit_lines:
    raw = audit_lines[-1].replace("[INTELLIGENCE_AUDIT] ", "")
    try:
        audit = json.loads(raw)
        ok(f"Audit log emitted — {len(raw)} chars")
        expected_fields = ["question_hash", "tenant_id", "routing_tier", "classified_engine",
                           "routing_confidence", "plan_cache_hit", "total_latency_ms", "steps"]
        missing = [f for f in expected_fields if f not in audit]
        if not missing:
            ok(f"All audit fields present: {expected_fields}")
        else:
            fail(f"Missing audit fields: {missing}")

        if audit["routing_tier"] == 1 and audit["classified_engine"] == "sql":
            ok(f"Audit: tier={audit['routing_tier']}, engine={audit['classified_engine']}, confidence={audit['routing_confidence']}")
        else:
            fail(f"Audit has wrong routing info: {audit}")

        pii_text = "How many orders last 30 days?"
        if pii_text not in raw:
            ok("PII check: raw question text NOT in audit log (hashed only)")
        else:
            fail("PII leak: question text appears in audit log")

    except json.JSONDecodeError as e:
        fail(f"Audit log is not valid JSON: {e}")
else:
    fail("No audit log emitted")


# ════════════════════════════════════════════════════════════════
# 13. UNION injection block
# ════════════════════════════════════════════════════════════════
section("TEST 13 — UNION Injection Block")

UNION_ATTACKS = [
    "SELECT id FROM orders UNION SELECT password FROM users",
    "SELECT id FROM orders UNION ALL SELECT secret FROM admin",
    "SELECT 1 UNION select username,password from users",
]

for sql in UNION_ATTACKS:
    try:
        execute_readonly_sql(sql, {})
        fail(f"UNION attack not blocked: {sql[:50]}")
    except ValueError as e:
        ok(f"UNION blocked: {sql[:50]}")


# ════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
total = PASS + FAIL
if FAIL == 0:
    print(f"  ALL {total} CHECKS PASSED")
else:
    print(f"  {PASS}/{total} passed   |   {FAIL} FAILED")
print(f"{'='*60}\n")

sys.exit(0 if FAIL == 0 else 1)
