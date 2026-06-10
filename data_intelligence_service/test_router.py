"""
Quick smoke-test for the query router pipeline.

Tests:
  1. Classifier (Tier 1 / Tier 2 / Tier 3)
  2. Entity extractor
  3. Template matching
  4. Full pipeline routing decision (no live DB needed)

Run from repo root:
  python -m data_intelligence_service.test_router
"""
import sys
import textwrap

# ------------------------------------------------------------------ colours
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"{GREEN}  ✓ {msg}{RESET}")
def warn(msg):print(f"{YELLOW}  ~ {msg}{RESET}")
def fail(msg):print(f"{RED}  ✗ {msg}{RESET}")
def hdr(msg): print(f"\n{BOLD}{CYAN}{msg}{RESET}")

# ------------------------------------------------------------------ imports
try:
    from data_intelligence_service.intelligence.routing.classifier import classify
    from data_intelligence_service.intelligence.routing.entity_extractor import extract_entities
    from data_intelligence_service.intelligence.routing.intent_templates import find_template
except ImportError as e:
    print(f"{RED}Import error: {e}{RESET}")
    sys.exit(1)

# ==========================================================================
# Test cases
# ==========================================================================

CLASSIFIER_CASES = [
    # (question, expected_engine, expected_tier)
    # -- SQL Tier 1
    ("How many products do we have?",                    "sql",    1),
    ("Total spend this month",                           "sql",    1),
    ("Top 10 products by spend last 30 days",            "sql",    1),
    ("Budget utilization report",                        "sql",    1),
    ("Order history for last quarter",                   "sql",    1),
    # -- Graph Tier 1
    ("Who belongs to the Finance org unit?",             "graph",  1),
    ("Show me the org hierarchy",                        "graph",  1),
    ("Who does Sarah report to?",                        "graph",  1),
    ("What roles does john@acme.com have?",              "graph",  1),
    ("What permissions does the admin role have?",       "graph",  1),
    ("Which users are in the procurement team?",         "graph",  1),
    ("What stores is alice@corp.com assigned to?",       "graph",  1),
    ("Which vendors supply cleaning products?",          "graph",  1),
    ("What governance policies apply?",                  "graph",  1),
    ("Show approved ranges for org unit",                "graph",  1),
    # -- Vector Tier 1
    ("Find products similar to latex gloves",            "vector", 1),
    ("Search for cleaning consumables",                  "vector", 1),
    ("Products like blue nitrile gloves",                "vector", 1),
    # -- Hybrid Tier 1
    ("Which org units have the most spend?",             "hybrid", 1),
    ("Spend by site last month",                         "hybrid", 1),
    # -- Tier 2 (should still classify, not fall to Tier 3)
    ("Give me a report on the procurement analytics",    "sql",    2),
    ("Show me the org structure relationship",           "graph",  2),
    # -- Tier 3 (genuinely ambiguous)
    ("What is the meaning of life?",                     "unknown",3),
    ("Help me understand our governance model",          "unknown",3),
]

ENTITY_CASES = [
    # (question, expected_entity_key, expected_value_contains)
    ("Show me all shoes",                           "product_name", "shoes"),
    ("List latex gloves products",                  "product_name", "latex gloves"),
    ("Who belongs to the Finance team?",            "org_name",     "finance"),
    ("Top 5 users by spend",                        "limit",        5),
    ("Total spend last 30 days",                    "date_filter",  "last_30_days"),
    ("Spend this month",                            "date_filter",  "this_month"),
    ("Budget utilization this year",                "date_filter",  "this_year"),
    ("User john@acme.com roles",                    "email",        "john@acme.com"),
    ("Users with more than 5000 spend",             "min_amount",   5000.0),
    ("Orders from vendor CleanCo",                  "vendor_name",  "cleanco"),
    ("What roles does user alice have?",            "user_name",    "alice"),
    ("Products in category safety",                 "category_name","safety"),
]

TEMPLATE_CASES = [
    # (question, expected_intent_or_None)
    ("Show me all products",                        "list_products"),
    ("List all shoes",                              "list_products"),
    ("How many products do we have?",               "count_products"),
    ("List all users",                              "list_users"),
    ("Show me all vendors",                         "list_vendors"),
    ("List all stores",                             "list_stores"),
    ("List all sites",                              "list_sites"),
    ("Show product categories",                     "list_categories"),
    ("Total spend this month",                      "total_spend"),
    ("Spend breakdown per user",                    "spend_by_user"),
    ("Top 5 products by spend",                     "top_products_by_spend"),
    ("Budget utilization",                          "budget_utilization"),
    ("Order history last 30 days",                  "order_history"),
    ("Show approved ranges",                        "list_approved_ranges"),
    ("Show me the org hierarchy",                   "org_hierarchy"),
    ("Who does sarah report to?",                   "reports_to"),
    ("What roles does john@acme.com have?",         "user_roles"),
    ("What permissions does the manager role have?","role_permissions"),
    ("Which stores is alice assigned to?",          "user_stores"),
    ("Who belongs to the finance org unit?",        "users_in_org"),
    ("Which vendors supply cleaning products?",     "vendor_products"),
    ("What is in the approved range?",              "approved_range_contents"),
    ("What governance policies apply?",             "governance_policies"),
    ("Find products similar to latex gloves",       "find_similar_products"),
    # These should NOT match any template (fall to LLM)
    ("Analyse procurement risk across all vendors", None),
    ("Compare this quarter vs last quarter spend",  None),
]


# ==========================================================================
# Runners
# ==========================================================================

def run_classifier():
    hdr("=== 1. CLASSIFIER ===")
    passed = failed = 0
    for q, exp_engine, exp_tier in CLASSIFIER_CASES:
        engine, tier, conf = classify(q)
        prefix = textwrap.shorten(q, 55).ljust(55)
        info = f"tier={tier} engine={engine:<8} conf={conf:.2f}"
        if engine == exp_engine and tier == exp_tier:
            ok(f"{prefix}  {info}")
            passed += 1
        elif engine == exp_engine:
            warn(f"{prefix}  {info}  (expected tier={exp_tier})")
            passed += 1
        else:
            fail(f"{prefix}  {info}  (expected engine={exp_engine} tier={exp_tier})")
            failed += 1
    print(f"\n  Classifier: {passed} passed, {failed} failed")
    return failed


def run_entity_extractor():
    hdr("=== 2. ENTITY EXTRACTOR ===")
    passed = failed = 0
    for q, key, expected in ENTITY_CASES:
        entities = extract_entities(q)
        val = entities.get(key)
        prefix = textwrap.shorten(q, 50).ljust(50)
        if val is None:
            fail(f"{prefix}  missing '{key}' (got {entities})")
            failed += 1
        elif isinstance(expected, float):
            if val == expected:
                ok(f"{prefix}  {key}={val}")
                passed += 1
            else:
                fail(f"{prefix}  {key}={val!r} (expected {expected})")
                failed += 1
        elif isinstance(expected, int):
            if val == expected:
                ok(f"{prefix}  {key}={val}")
                passed += 1
            else:
                fail(f"{prefix}  {key}={val!r} (expected {expected})")
                failed += 1
        else:
            if expected.lower() in str(val).lower():
                ok(f"{prefix}  {key}={val!r}")
                passed += 1
            else:
                fail(f"{prefix}  {key}={val!r} (expected contains '{expected}')")
                failed += 1
    print(f"\n  Extractor: {passed} passed, {failed} failed")
    return failed


def run_template_matching():
    hdr("=== 3. TEMPLATE MATCHING ===")
    passed = failed = 0
    for q, expected_intent in TEMPLATE_CASES:
        tmpl = find_template(q)
        got_intent = tmpl.intent if tmpl else None
        prefix = textwrap.shorten(q, 55).ljust(55)
        if got_intent == expected_intent:
            if got_intent is None:
                ok(f"{prefix}  → (no template — falls to LLM)  ✓")
            else:
                engine = tmpl.engine
                ok(f"{prefix}  → {got_intent} [{engine}]")
            passed += 1
        else:
            fail(f"{prefix}  → {got_intent!r} (expected {expected_intent!r})")
            failed += 1
    print(f"\n  Templates: {passed} passed, {failed} failed")
    return failed


def run_routing_decision():
    """Show the full routing decision (classify + template) without hitting DB."""
    hdr("=== 4. FULL ROUTING DECISION (no DB) ===")
    questions = [
        "Give me all the shoes",
        "List latex gloves",
        "How many products do we have?",
        "Total spend last 30 days",
        "Top 5 products by spend",
        "Who belongs to the finance org unit?",
        "Show me the org hierarchy",
        "Who does alice@acme.com report to?",
        "What roles does the procurement manager have?",
        "Find products similar to blue nitrile gloves size medium",
        "Which vendors supply cleaning products?",
        "Budget utilization report",
        "Compare our Q1 and Q2 vendor spend by category and region",
    ]
    for q in questions:
        engine, tier, conf = classify(q)
        entities = extract_entities(q)
        tmpl = find_template(q)

        path = "TEMPLATE → direct SQL/Cypher" if tmpl else "LLM plan"
        intent = tmpl.intent if tmpl else "—"
        ent_str = ", ".join(f"{k}={v!r}" for k, v in entities.items()) if entities else "none"

        print(f"\n  {BOLD}Q:{RESET} {q}")
        print(f"     tier={tier} engine={engine} conf={conf:.2f}")
        print(f"     entities: {ent_str}")
        print(f"     path: {CYAN}{path}{RESET}  intent={intent}")


# ==========================================================================
# Main
# ==========================================================================

if __name__ == "__main__":
    total_failures = 0
    total_failures += run_classifier()
    total_failures += run_entity_extractor()
    total_failures += run_template_matching()
    run_routing_decision()

    hdr("=== SUMMARY ===")
    if total_failures == 0:
        print(f"{GREEN}{BOLD}  All tests passed.{RESET}")
    else:
        print(f"{RED}{BOLD}  {total_failures} test(s) failed.{RESET}")
        sys.exit(1)
