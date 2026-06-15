"""
Role-based intent boundaries for the ZeroQue intelligence agent.

WHY intent boundaries?
  Having the intelligence.query permission means you can USE the service.
  It does NOT mean you can ask ANY question. A shop-floor Requester should not
  be able to ask "show me global supplier concentration risk" — that data is
  sensitive, strategic, and outside their role scope.

  This module classifies the INTENT of a question into one of four categories,
  then checks whether the user's highest role allows that category.

Intent categories (aligned to spec §9):
  LOOKUP      — simple factual lookups about specific items (product details, price)
  OPERATIONAL — questions about own work: my orders, my approvals, my budget
  ANALYTICAL  — aggregations, trends, comparisons, team/department scope
  STRATEGIC   — org-wide risk, supplier concentration, global spend, executive views

Role hierarchy (most permissive wins when user has multiple roles):
  requester           → LOOKUP, OPERATIONAL
  buyer               → LOOKUP, OPERATIONAL, ANALYTICAL
  procurement_manager → LOOKUP, OPERATIONAL, ANALYTICAL
  finance             → LOOKUP, OPERATIONAL, ANALYTICAL, STRATEGIC
  executive           → all
  admin               → all
  system              → all

WHY use role CODE not name?
  Role codes are stable identifiers (set by the system). Names are display
  strings that admins can rename. We match on code.

HOW to add a new role or category:
  1. Add the role code to ROLE_ALLOWED_INTENTS
  2. Add intent patterns to STRATEGIC_PATTERNS / ANALYTICAL_PATTERNS as needed
"""
import re
from typing import Dict, List, Optional, Set

from data_intelligence_service.core.logger import logger


# ---------------------------------------------------------------------------
# Intent categories
# ---------------------------------------------------------------------------

class IntentCategory:
    LOOKUP      = "lookup"
    OPERATIONAL = "operational"
    ANALYTICAL  = "analytical"
    STRATEGIC   = "strategic"


# ---------------------------------------------------------------------------
# Role → allowed intent categories
# ---------------------------------------------------------------------------

# Map role CODE (lowercase) → set of allowed intent categories
# "all" shorthand means all four categories
ROLE_ALLOWED_INTENTS: Dict[str, Set[str]] = {
    # Requesters can look things up and ask about their own work
    "requester":           {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL},
    "employee":            {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL},
    "staff":               {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL},

    # Buyers can also do team-level analytics
    "buyer":               {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},
    "junior_buyer":        {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},
    "senior_buyer":        {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},

    # Procurement roles: full analytical access
    "procurement_manager": {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},
    "procurement":         {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},
    "category_manager":    {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL, IntentCategory.ANALYTICAL},

    # Finance and senior management: can see strategic data
    "finance":             {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL,
                            IntentCategory.ANALYTICAL, IntentCategory.STRATEGIC},
    "finance_manager":     {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL,
                            IntentCategory.ANALYTICAL, IntentCategory.STRATEGIC},

    # Executive and admin: unrestricted
    "executive":           "all",
    "director":            "all",
    "cfo":                 "all",
    "cpo":                 "all",
    "admin":               "all",
    "system_admin":        "all",
    "system":              "all",
    "intelligence_admin":  "all",
}

_ALL_INTENTS = {
    IntentCategory.LOOKUP, IntentCategory.OPERATIONAL,
    IntentCategory.ANALYTICAL, IntentCategory.STRATEGIC,
}

# Default for unknown roles — LOOKUP + OPERATIONAL only (conservative)
_DEFAULT_ALLOWED = {IntentCategory.LOOKUP, IntentCategory.OPERATIONAL}


# ---------------------------------------------------------------------------
# Pattern-based intent classifier
# ---------------------------------------------------------------------------

# Strategic patterns — org-wide, multi-tenant scope, risk analysis
_STRATEGIC_PATTERNS = [
    r"\bsupplier.{0,20}concentration\b",
    r"\bsupplier.{0,20}risk\b",
    r"\bglobal\b.{0,30}\b(spend|supplier|risk|contract)\b",
    r"\borg.{0,10}wide\b",
    r"\bcompany.?wide\b",
    r"\bstrategic.{0,20}(sourcing|supplier|review)\b",
    r"\bcontract.{0,20}(interpret|review|analysis)\b",
    r"\bspend.{0,20}(risk|optimis|consolidat)\b",
    r"\bsupplier.{0,20}(base|strateg|portfolio)\b",
    r"\b(board|executive|c-suite).{0,20}(report|dashboard|view)\b",
    r"\borganisation.{0,20}(risk|spend|health)\b",
    r"\bcategory.{0,20}savings.{0,20}opportunit\b",
    r"\bmulti.?supplier\b",
    r"\bcross.?departm\b",
    r"\btotal.{0,15}supplier.{0,15}(count|list|overview)\b",
]

# Analytical patterns — team/dept scope, trends, comparisons
_ANALYTICAL_PATTERNS = [
    r"\bspend.{0,20}(trend|over time|by month|by quarter|last \d+ months)\b",
    r"\b(top|rank|highest|lowest).{0,20}(spend|vendor|supplier|category|department)\b",
    r"\bcompare\b",
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\b(all|every).{0,10}(department|org.?unit|team)\b",
    r"\bsupplier.{0,20}(performance|metric|score|analysis)\b",
    r"\bapproval.{0,20}(rate|pattern|trend|behaviour)\b",
    r"\baverage.{0,20}(lead time|delivery|spend)\b",
    r"\boutstanding.{0,15}(approval|order|request)\b",
    r"\bhow many.{0,20}(vendor|supplier|product|user|order)\b",
    r"\btotal\b.{0,20}(spend|orders|requests)\b",
    r"\bbudget.{0,20}(utiliz|status|overview|all)\b",
]

# Operational patterns — own work, specific objects
_OPERATIONAL_PATTERNS = [
    r"\bmy\b",
    r"\bour\b",
    r"\bi\b.{0,5}(need|want|have|submitted|approved)\b",
    r"\bfor me\b",
    r"\bmy (team|department|org.?unit)\b",
    r"\bI.{0,10}submitted\b",
    r"\bI.{0,10}approved\b",
    r"\bpending.{0,10}(approval|review)\b",
    r"\boverdue\b",
]


def classify_intent(question: str) -> str:
    """Classify the intent category of a question.

    Returns one of: IntentCategory.LOOKUP | OPERATIONAL | ANALYTICAL | STRATEGIC

    Priority: STRATEGIC > ANALYTICAL > OPERATIONAL > LOOKUP
    """
    q = question.lower()

    for pattern in _STRATEGIC_PATTERNS:
        if re.search(pattern, q):
            return IntentCategory.STRATEGIC

    for pattern in _ANALYTICAL_PATTERNS:
        if re.search(pattern, q):
            return IntentCategory.ANALYTICAL

    for pattern in _OPERATIONAL_PATTERNS:
        if re.search(pattern, q):
            return IntentCategory.OPERATIONAL

    return IntentCategory.LOOKUP


def get_allowed_intents_for_user(user_context: Optional[Dict]) -> Set[str]:
    """Return the set of allowed intent categories for a user.

    Looks at all role codes the user has and returns the UNION (most permissive).
    If user_context is None (no user, API-key-only call), defaults to full access
    (API keys are issued to trusted systems, not end users).
    """
    if user_context is None:
        return _ALL_INTENTS

    roles: List[Dict] = user_context.get("roles", [])
    if not roles:
        # No roles in graph — fail-open with conservative default
        return _DEFAULT_ALLOWED

    allowed: Set[str] = set()
    for role in roles:
        code = str(role.get("code", "")).lower().strip()
        role_perms = ROLE_ALLOWED_INTENTS.get(code)
        if role_perms == "all":
            return _ALL_INTENTS   # short-circuit — can't get more permissive
        if role_perms:
            allowed |= role_perms

    return allowed if allowed else _DEFAULT_ALLOWED


def check_intent_boundary(
    question: str,
    user_context: Optional[Dict],
) -> Dict:
    """Check if this user may ask this type of question.

    Returns:
      {"allowed": True, "intent": "analytical", "reason": None}
      {"allowed": False, "intent": "strategic", "reason": "Your role does not permit strategic queries."}
    """
    intent = classify_intent(question)
    allowed_intents = get_allowed_intents_for_user(user_context)

    if intent in allowed_intents:
        logger.debug(f"[IntentBoundary] allowed: intent={intent}")
        return {"allowed": True, "intent": intent, "reason": None}

    # Determine which roles would be needed
    needed_roles = [
        code for code, perms in ROLE_ALLOWED_INTENTS.items()
        if perms == "all" or (isinstance(perms, set) and intent in perms)
    ][:3]  # show up to 3 role examples

    reason = (
        f"This question requires {intent}-level access. "
        f"Your current role does not permit {intent} queries. "
        f"Roles with this access include: {', '.join(needed_roles)}."
    )
    logger.info(f"[IntentBoundary] BLOCKED: intent={intent} user_roles={[r.get('code') for r in (user_context or {}).get('roles', [])]}")
    return {"allowed": False, "intent": intent, "reason": reason}
