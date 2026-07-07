"""
Entity extractor for natural language queries.

Regex-based, deterministic, zero LLM dependency.
Extracts typed entities from a question so intent templates can
bind them directly into parameterized SQL / Cypher.

Returned dict keys (all optional):
  email         str   — user@domain.com
  product_name  str   — raw string from question (e.g. "shoes", "latex gloves")
  category_name str   — category string
  org_name      str   — org unit name/code
  store_name    str   — store name
  vendor_name   str   — vendor name
  role_name     str   — role code / name
  user_name     str   — display name or partial email prefix
  date_filter   str   — one of: last_7_days | last_30_days | last_60_days |
                        last_90_days | this_month | last_month | this_quarter | this_year
  limit         int   — top-N value
  min_amount    float — lower bound for spend/cost
  max_amount    float — upper bound for spend/cost
"""
import re
from typing import Dict, Any


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "all", "some", "any", "me", "us", "a", "an", "my", "our",
    "from", "in", "at", "on", "of", "with", "for", "to", "by", "that",
    "this", "those", "these", "and", "or", "is", "are", "was", "were",
    "be", "been", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "can", "may", "might", "shall",
    "please", "i", "you", "we", "they", "he", "she", "it",
}


def _clean(token: str) -> str:
    return token.strip().strip("\"'")


def _valid(token: str) -> bool:
    return bool(token) and token.lower() not in _STOPWORDS and len(token) > 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_entities(question: str) -> Dict[str, Any]:
    """Extract named entities from a natural language question.

    Returns a dict of found entities.  Missing entities are absent from the
    dict (not None) so callers can use `in` checks cleanly.
    """
    q = question.strip()
    ql = q.lower()
    entities: Dict[str, Any] = {}

    # ------------------------------------------------------------------ email
    m = re.search(r'\b[\w.+-]+@[\w-]+\.\w+\b', q)
    if m:
        entities["email"] = m.group()

    # -------------------------------------------------------------- date range
    date_map = [
        (r'\blast\s+7\s+days?\b',               "last_7_days"),
        (r'\blast\s+14\s+days?\b',              "last_14_days"),
        (r'\blast\s+30\s+days?\b',              "last_30_days"),
        (r'\blast\s+60\s+days?\b',              "last_60_days"),
        (r'\blast\s+90\s+days?\b',              "last_90_days"),
        (r'\bthis\s+month\b',                   "this_month"),
        (r'\blast\s+month\b',                   "last_month"),
        (r'\bthis\s+(?:quarter|q[1-4])\b',     "this_quarter"),
        (r'\blast\s+(?:quarter|q[1-4])\b',     "last_quarter"),
        (r'\bthis\s+year\b',                    "this_year"),
        (r'\blast\s+year\b',                    "last_year"),
    ]
    for pattern, label in date_map:
        if re.search(pattern, ql):
            entities["date_filter"] = label
            break

    # ----------------------------------------------------------------- top-N
    m = re.search(r'\btop\s+(\d+)\b', ql)
    if m:
        entities["limit"] = int(m.group(1))

    # ------------------------------------------------------------- amount bounds
    m = re.search(r'\b(?:more|greater|over|above)\s+than\s+[\$£€]?([\d,]+(?:\.\d+)?)', ql)
    if m:
        entities["min_amount"] = float(m.group(1).replace(",", ""))

    m = re.search(r'\b(?:less|under|below)\s+than\s+[\$£€]?([\d,]+(?:\.\d+)?)', ql)
    if m:
        entities["max_amount"] = float(m.group(1).replace(",", ""))

    # ---------------------------------------------------------- product / item
    # e.g. "show me all shoes", "list latex gloves", "find cleaning products"
    product_patterns = [
        r'\b(?:show|list|give|get|fetch|display)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?([\w][\w\s]*?)(?:\s+products?|\s+items?|\s+consumables?)?\s*$',
        r'\bproducts?\s+(?:called|named|matching)\s+([\w][\w\s]+)',
        r'\bsearch\s+for\s+([\w][\w\s]+?)(?:\s+products?|\s+items?)?$',
        r'\bfind\s+(?:me\s+)?([\w][\w\s]+?)(?:\s+products?|\s+items?)',
    ]
    for pat in product_patterns:
        m = re.search(pat, ql)
        if m:
            candidate = _clean(m.group(1))
            if _valid(candidate):
                entities["product_name"] = candidate
                break

    # ---------------------------------------------------------------- category
    m = re.search(
        r'\b(?:in\s+)?category\s+["\']?([\w][\w\s]+?)["\']?(?:\s|$)', ql
    )
    if m:
        candidate = _clean(m.group(1))
        if _valid(candidate):
            entities["category_name"] = candidate

    # --------------------------------------------------------------- org unit
    org_patterns = [
        r'\borg(?:\s+unit)?\s+["\']?([\w][\w\s]*?)["\']?\s+(?:hierarchy|users?|members?|people)',
        r'\b(?:in|for|at|of)\s+(?:the\s+)?(?:org(?:\s+unit)?|department|unit)\s+["\']?([\w][\w\s]*?)["\']?(?:\s|$)',
        r'\bteam\s+["\']?([\w][\w\s]*?)["\']?\s*(?:\?|$)',
        r'\bwho\s+belongs?\s+to\s+(?:the\s+)?([\w][\w\s]*?)(?:\s+org(?:\s+unit)?|\s+team|\s+department)?(?:\s|$)',
    ]
    for pat in org_patterns:
        m = re.search(pat, ql)
        if m:
            candidate = _clean(m.group(1))
            if _valid(candidate):
                entities["org_name"] = candidate
                break

    # --------------------------------------------------------------- store
    store_patterns = [
        r'\b(?:in|at|for)\s+store\s+["\']?([\w][\w\s]*?)["\']?(?:\s|$)',
        r'\bstore\s+["\']?([\w][\w\s]*?)["\']?\s+(?:products?|users?|staff|stock)',
        r'\bwhat\s+stores?\s+(?:does|do|is|are)\s+([\w][\w\s]*?)\s+(?:assigned|work)',
    ]
    for pat in store_patterns:
        m = re.search(pat, ql)
        if m:
            candidate = _clean(m.group(1))
            if _valid(candidate):
                entities["store_name"] = candidate
                break

    # -------------------------------------------------------------- vendor
    vendor_patterns = [
        r'\bvendor\s+["\']?([\w][\w\s]*?)["\']?\s+(?:supplies|products?|contract|active)',
        r'\bfrom\s+vendor\s+["\']?([\w][\w\s]*?)["\']?(?:\s|$)',
        r'\bvendors?\s+that\s+(?:supply|supplies)\s+([\w][\w\s]*?)(?:\s|$)',
    ]
    for pat in vendor_patterns:
        m = re.search(pat, ql)
        if m:
            candidate = _clean(m.group(1))
            if _valid(candidate):
                entities["vendor_name"] = candidate
                break

    # --------------------------------------------------------------- role
    role_patterns = [
        r'\busers?\s+with\s+(?:the\s+)?role\s+["\']?([\w][\w\s]*?)["\']?(?:\s|$)',
        r'\brole\s+["\']?([\w][\w\s]*?)["\']?\s+(?:has|permissions?|users?)',
        r'\bwho\s+has\s+(?:the\s+)?([\w][\w\s]*?)\s+role\b',
    ]
    for pat in role_patterns:
        m = re.search(pat, ql)
        if m:
            candidate = _clean(m.group(1))
            if _valid(candidate):
                entities["role_name"] = candidate
                break

    # -------------------------------------------------------------- user name
    if "email" not in entities:
        user_patterns = [
            r'\buser\s+["\']?([\w][\w\s@.]*?)["\']?\s+(?:belongs?|reports?|works?|ha(?:s|ve))',
            r'\b(?:for|about)\s+user\s+["\']?([\w][\w\s@.]*?)["\']?(?:\s|$)',
            r'\bmanager\s+of\s+["\']?([\w][\w\s@.]*?)["\']?(?:\s|$)',
            r'\bwho\s+manages?\s+([\w][\w\s@.]*?)(?:\s|$)',
        ]
        for pat in user_patterns:
            m = re.search(pat, ql)
            if m:
                candidate = _clean(m.group(1))
                if _valid(candidate):
                    entities["user_name"] = candidate
                    break

    return entities
