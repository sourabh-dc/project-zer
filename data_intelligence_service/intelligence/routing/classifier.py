"""
Tiered query classifier.

WHY three tiers?
  - Tier 1 (regex): handles ~80% of queries instantly, deterministically.
    Fast regex rules fire on high-confidence signals like "who reports to"
    or "how many". No ambiguity, no cost.
  - Tier 2 (weighted scoring): handles ~15% of queries. Questions that have
    multiple signals (e.g. "spend" + "org unit") are scored per engine.
    Still < 1ms, still deterministic.
  - Tier 3 (LLM): the remaining ~5% are genuinely ambiguous. We return
    engine='unknown' and let the LLM planner decide from full context.

WHY not always use the LLM to classify?
  LLM classification adds 100–500ms per query. For 80% of questions that
  have an obvious answer (regex hits), this is pure waste. The 3-tier
  approach gets us < 1ms for most queries with LLM accuracy for the hard ones.

Returns (engine, tier, confidence):
  engine     — 'graph' | 'sql' | 'vector' | 'hybrid' | 'unknown'
  tier       — 1 | 2 | 3
  confidence — float 0.0–1.0 (1.0 for tier-1, computed for tier-2, 0.0 for tier-3)
"""
import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Tier 1: High-confidence single-signal regex rules
# Any match here → definitive classification, skip tiers 2+3.
#
# WHY these patterns and not others?
#   Each pattern represents a question fragment that is ONLY asked in one
#   context. "Reports to" only appears in org-hierarchy questions (graph).
#   "How many" only appears in count/aggregate questions (sql).
#   "Similar to" only appears in semantic product search (vector).
#
# WHY negative lookaheads in _T1_SQL?
#   "List all vendors" should go to graph (vendor relationships), not SQL.
#   The lookahead (?!...) prevents the broad "list/show/get" pattern from
#   swallowing graph-domain nouns that happen to match the generic structure.
# ---------------------------------------------------------------------------

_T1_HYBRID = [
    r"\b(users?|people).{0,20}(spend|spent|ordered|purchased).{0,20}(more|less)\s+than\b",
    r"\b(sites?|stores?|locations?).{0,20}(spend|budget|orders?)\b",
    r"\bwhich\s+(org|department|unit)s?.{0,20}(most|least|highest|lowest).{0,20}(spend|orders?|products?)\b",
    r"\b(products?|items?).{0,20}(ordered|purchased)\s+by.{0,20}(org|department|site)\b",
    r"\bspend.{0,20}(by|per)\s+(org|department|site|location|store)\b",
]

_T1_GRAPH = [
    r"\bwho\s+belongs\s+to\b",
    r"\borg[\s\-]?unit\s+hierarchy\b",
    r"\borg\s+hierarchy\b",
    r"\breports?\s+to\b",
    r"\bwhat\s+stores?.{0,20}(user|person|assigned)\b",
    r"\bwhich\s+stores?.{0,20}(user|person|assigned)\b",
    r"\bwhich\s+(users?|people)\s+(are\s+in|belong\s+to|work\s+at|assigned\s+to)\b",
    r"\brelationship\s+between\b",
    r"\bapproved\s+range.{0,20}org\b",
    r"\bwho\s+(has|have).{0,25}(role|permission)\b",
    r"\bparent\s+org\b",
    r"\bchild\s+org\b",
    r"\bgovernance\s+(policy|policies)\b",
    r"\bmanager\s+of\b",
    r"\bwho\s+manages\b",
    r"\btopology\b",
    r"\bapproved\s+range\b",
    r"\bvendors?\s+that\s+(supply|supplies)\b",
    r"\bwhich\s+vendors?\s+(supply|supplies)\b",
    r"\bworks?\s+at\b",
    r"\b(what|which)\s+roles?\s+(does|do|has|have)\b",
    r"\bwhat\s+permissions?\b",
]

_T1_SQL = [
    r"\bhow\s+many\b",
    r"\b(?:give|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?!(?:org|relationship|hierarch|topolog|governance|polic|approver|manager|permission|role|vendor|user|store|site|categor|approved)\b)[\w]",
    r"\btotal\s+(spend|spent|budget|cost|amount|orders?|revenue)\b",
    r"\b(count|sum|average|avg)\s+of\b",
    r"\blast\s+(30|60|90|7|14)\s+days?\b",
    r"\b(this|last)\s+(month|quarter|year)\b",
    r"\bspend\s+breakdown\b",
    r"\bbudget\s+(utilization|used|remaining|limit)\b",
    r"\btop\s+\d+\s+(products?|vendors?|users?|stores?)\s+by\b",
    r"\border\s+(history|volume|frequency|count)\b",
    r"\b(monthly|quarterly|weekly|daily)\s+(spend|report|summary|trend)\b",
]

_T1_VECTOR = [
    r"\bsimilar\s+to\b",
    r"\bproducts?\s+like\b",
    r"\bfind\s+(me\s+)?(products?|items?|consumables?)\b",
    r"\bsearch\s+for\b",
    r"\bsemantically\s+(similar|related|close)\b",
    r"\bnearest\s+(products?|matches?)\b",
    # Descriptive / adjective-led product searches — user describes what they need
    r"\b(eco[\s\-]?friendly|sustainable|biodegradable|green)\b.{0,30}(product|clean|supply|item)",
    r"\b(antibacterial|antimicrobial|disinfect|sanitiz\w*)\b",
    r"\bsomething\s+(for|to)\b.{0,30}(clean|protect|safe|stor|wash|wipe|sanitiz)",
    r"\bwhat\s+(can\s+i\s+use|do\s+we\s+have)\b.{0,30}(for|to)\b",
    r"\bi\s+need\s+something\s+(for|to)\b",
    r"\b(product|item|supply|consumable)s?\s+(for|to)\b",
]

# ---------------------------------------------------------------------------
# Tier 2: Weighted multi-signal scoring
# Wider signal vocabulary with per-signal weights (higher = stronger signal).
#
# WHY weights instead of counts?
#   "org unit" (weight 3) is a much stronger graph signal than "who" (weight 1).
#   Simple keyword counts would treat them equally. Weights let us encode domain
#   knowledge about signal strength without complex rule logic.
#
# WHY _T2_MIN_SCORE = 4 and _T2_MIN_CONFIDENCE = 0.55?
#   Score < 4 means only 1-2 weak signals matched — not enough to be sure.
#   Confidence < 0.55 means two engines scored similarly — that's hybrid or
#   unknown, not a clear winner. Both thresholds were tuned on real questions.
# ---------------------------------------------------------------------------

_T2_SIGNALS: dict = {
    "graph": [
        ("who", 1), ("belong", 2), ("hierarchy", 3), ("org unit", 3), ("org_unit", 3),
        ("role", 2), ("permission", 2), ("policy", 2), ("governance", 2),
        ("approver", 2), ("manager", 2), ("relationship", 3), ("connected", 2),
        ("works at", 3), ("member of", 2), ("assigned to", 2), ("approved range", 3),
        ("which users", 2), ("which people", 2), ("vendor supply", 2), ("supplies", 2),
        ("topology", 3), ("org structure", 3), ("reporting line", 3),
    ],
    "sql": [
        ("how many", 3), ("count", 2), ("total", 2), ("sum", 2), ("average", 2),
        ("spend", 2), ("spent", 2), ("budget", 2), ("amount", 1), ("cost", 1),
        ("orders", 2), ("last month", 3), ("last quarter", 3), ("this year", 2),
        ("breakdown", 2), ("utilization", 2), ("statistics", 2), ("analytics", 2),
        ("trend", 2), ("report", 2), ("aggregate", 2), ("between", 1),
        ("revenue", 2), ("invoice", 2), ("purchase", 1), ("payment", 2),
    ],
    "vector": [
        ("similar to", 3), ("products like", 3), ("search", 2), ("find products", 3),
        ("describe", 1), ("description", 2), ("semantic", 3), ("related to", 2),
        ("match", 1), ("closest", 2), ("nearest", 2), ("fuzzy", 3),
        ("what is", 1), ("tell me about", 2),
    ],
}

_HYBRID_COMBOS = [
    ({"graph", "sql"}, 4),
    ({"graph", "vector"}, 3),
    ({"sql", "vector"}, 3),
]

# Minimum score for Tier-2 to commit to a single engine
_T2_MIN_SCORE = 4
_T2_MIN_CONFIDENCE = 0.55


def classify(question: str) -> Tuple[str, int, float]:
    """Classify a question. Returns (engine, tier, confidence)."""
    q = question.lower()

    # --- Tier 1 ---
    for pattern in _T1_HYBRID:
        if re.search(pattern, q):
            return ("hybrid", 1, 1.0)
    for pattern in _T1_GRAPH:
        if re.search(pattern, q):
            return ("graph", 1, 1.0)
    for pattern in _T1_SQL:
        if re.search(pattern, q):
            return ("sql", 1, 1.0)
    for pattern in _T1_VECTOR:
        if re.search(pattern, q):
            return ("vector", 1, 1.0)

    # --- Tier 2 ---
    scores: dict = {"graph": 0.0, "sql": 0.0, "vector": 0.0}
    for engine, signals in _T2_SIGNALS.items():
        for keyword, weight in signals:
            if keyword in q:
                scores[engine] += weight

    # Check hybrid combos first
    active = {e for e, s in scores.items() if s >= 3}
    for combo, _bonus in _HYBRID_COMBOS:
        if combo.issubset(active):
            return ("hybrid", 2, 0.85)

    total = sum(scores.values())
    if total > 0:
        best = max(scores, key=scores.get)
        best_score = scores[best]
        confidence = best_score / total

        if best_score >= _T2_MIN_SCORE and confidence >= _T2_MIN_CONFIDENCE:
            return (best, 2, round(confidence, 3))

    # --- Tier 3: send to LLM ---
    return ("unknown", 3, 0.0)
