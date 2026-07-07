"""
Intent template library.

Each IntentTemplate covers one precise intent with:
  - a regex matcher against the question
  - the engine it targets (sql | graph | vector)
  - a pre-written, parameterized SQL or Cypher query (no LLM)
  - a build_params() that maps extracted entities → safe bound params

Zero LLM involvement for any matched template.
Vector intents carry no query — the question text IS the search term.

REGISTRY order matters: more specific intents must come before general ones.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IntentTemplate:
    intent: str                              # unique slug
    engine: str                              # sql | graph | vector
    description: str                         # human-readable label
    matchers: List[str]                      # regex patterns (any match → hit)
    query: Optional[str]                     # SQL / Cypher; None for vector
    build_params: Callable[[Dict, str, Optional[str]], Dict[str, Any]]
    # ^ fn(entities, tenant_id, user_id) → bound params dict

    def matches(self, question: str) -> bool:
        ql = question.lower()
        return any(re.search(p, ql) for p in self.matchers)


# ---------------------------------------------------------------------------
# SQL date-filter helper
# ---------------------------------------------------------------------------

_DATE_SQL: Dict[str, str] = {
    "last_7_days":   "NOW() - INTERVAL '7 days'",
    "last_14_days":  "NOW() - INTERVAL '14 days'",
    "last_30_days":  "NOW() - INTERVAL '30 days'",
    "last_60_days":  "NOW() - INTERVAL '60 days'",
    "last_90_days":  "NOW() - INTERVAL '90 days'",
    "this_month":    "DATE_TRUNC('month', NOW())",
    "last_month":    "DATE_TRUNC('month', NOW() - INTERVAL '1 month')",
    "this_quarter":  "DATE_TRUNC('quarter', NOW())",
    "last_quarter":  "DATE_TRUNC('quarter', NOW() - INTERVAL '3 months')",
    "this_year":     "DATE_TRUNC('year', NOW())",
    "last_year":     "DATE_TRUNC('year', NOW() - INTERVAL '1 year')",
}


def _date_clause(entities: Dict) -> str:
    """Return a SQL WHERE fragment for the date filter, or empty string."""
    df = entities.get("date_filter")
    if df and df in _DATE_SQL:
        return f"AND created_at >= {_DATE_SQL[df]}"
    return ""


# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

def _list_products_params(entities, tenant_id, user_id):
    return {"tenant_id": tenant_id, "name_filter": f"%{entities.get('product_name', '')}%"}

def _list_products_query(entities) -> str:
    name = entities.get("product_name")
    name_clause = "AND (p.display_name ILIKE :name_filter OR p.sku ILIKE :name_filter)" if name else ""
    cat = entities.get("category_name")
    cat_clause = "AND c.name ILIKE :cat_filter" if cat else ""
    return f"""
SELECT p.product_id, p.display_name, p.sku, p.item_code,
       c.name AS category, v.name AS vendor, p.status
FROM   products p
LEFT JOIN categories c ON c.category_id = p.category_id
LEFT JOIN vendors v    ON v.vendor_id    = p.vendor_id
WHERE  p.tenant_id = :tenant_id
  AND  p.status    = 'active'
  {name_clause}
  {cat_clause}
ORDER BY p.display_name
LIMIT 200
""".strip()


TEMPLATE_LIST_PRODUCTS = IntentTemplate(
    intent="list_products",
    engine="sql",
    description="List products with optional name/category filter",
    matchers=[
        r'\b(?:show|list|give|get|fetch|display)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?products?\b',
        r'\blist\s+(?:all\s+)?(?:the\s+)?([\w\s]+?)\s+products?\b',
        r'\bwhat\s+products?\s+(?:do\s+we\s+have|are\s+available|exist)',
        r'\bshow\s+me\s+(?:all\s+)?([\w\s]+?)\s+products?\b',
        # Catch "list all shoes", "give me latex gloves", "show me safety equipment"
        # (only reached if users/vendors/stores/etc. templates didn't match first)
        r'\b(?:list|give|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?([\w][\w\s]{1,40})\s*$',
    ],
    query=None,  # built dynamically
    build_params=_list_products_params,
)
# Override matches to inject dynamic query
_orig_lp_matches = TEMPLATE_LIST_PRODUCTS.matches


def _lp_match_with_query(question: str) -> bool:
    return _orig_lp_matches(question)


# We'll resolve the query in the executor since it depends on entities.
# Store builder on the template so executor can call it.
TEMPLATE_LIST_PRODUCTS.query = "__dynamic__"
TEMPLATE_LIST_PRODUCTS.build_params = _list_products_params  # type: ignore
# attach query builder
TEMPLATE_LIST_PRODUCTS._build_query = _list_products_query  # type: ignore


# ---- count products -------------------------------------------------------

TEMPLATE_COUNT_PRODUCTS = IntentTemplate(
    intent="count_products",
    engine="sql",
    description="Count products with optional name/category filter",
    matchers=[
        r'\bhow\s+many\s+products?\b',
        r'\bcount\s+(?:of\s+)?(?:all\s+)?products?\b',
        r'\btotal\s+(?:number\s+of\s+)?products?\b',
    ],
    query="""
SELECT COUNT(*) AS total_products
FROM   products p
LEFT JOIN categories c ON c.category_id = p.category_id
WHERE  p.tenant_id = :tenant_id
  AND  p.status    = 'active'
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- list users -----------------------------------------------------------

TEMPLATE_LIST_USERS = IntentTemplate(
    intent="list_users",
    engine="sql",
    description="List active users for the tenant",
    matchers=[
        r'\b(?:show|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?users?\b',
        r'\bwho\s+are\s+the\s+users?\b',
        r'\blist\s+staff\b',
        r'\ball\s+users?\s+(?:in\s+the\s+)?(?:system|platform|tenant)?\b',
    ],
    query="""
SELECT u.user_id, u.email, u.display_name, u.status,
       s.name AS site, st.name AS store
FROM   users u
LEFT JOIN stores st ON st.store_id = u.store_id
LEFT JOIN sites  s  ON s.site_id   = st.site_id
WHERE  u.tenant_id = :tenant_id
  AND  u.status    = 'active'
ORDER BY u.display_name
LIMIT 500
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- list vendors ---------------------------------------------------------

TEMPLATE_LIST_VENDORS = IntentTemplate(
    intent="list_vendors",
    engine="sql",
    description="List active vendors",
    matchers=[
        r'\b(?:show|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?vendors?\b',
        r'\bwho\s+are\s+(?:our\s+)?vendors?\b',
        r'\bwhat\s+vendors?\s+(?:do\s+we\s+have|are\s+active|are\s+available)\b',
    ],
    query="""
SELECT v.vendor_id, v.name, v.contact_email, v.status
FROM   vendors v
WHERE  v.tenant_id = :tenant_id
  AND  v.status    = 'active'
ORDER BY v.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- list stores ----------------------------------------------------------

TEMPLATE_LIST_STORES = IntentTemplate(
    intent="list_stores",
    engine="sql",
    description="List stores under a site or all stores",
    matchers=[
        r'\b(?:show|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?stores?\b',
        r'\bwhat\s+stores?\s+(?:do\s+we\s+have|exist|are\s+there)\b',
        r'\ball\s+stores?\b',
    ],
    query="""
SELECT st.store_id, st.name AS store_name, st.store_type, st.status,
       s.name AS site_name
FROM   stores st
JOIN   sites  s ON s.site_id = st.site_id
WHERE  st.tenant_id = :tenant_id
  AND  st.status    = 'active'
ORDER BY s.name, st.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- list sites -----------------------------------------------------------

TEMPLATE_LIST_SITES = IntentTemplate(
    intent="list_sites",
    engine="sql",
    description="List all sites for tenant",
    matchers=[
        r'\b(?:show|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?sites?\b',
        r'\bwhat\s+sites?\s+(?:do\s+we\s+have|exist|are\s+there)\b',
        r'\ball\s+sites?\b',
    ],
    query="""
SELECT site_id, name, site_type, currency, timezone, status
FROM   sites
WHERE  tenant_id = :tenant_id
  AND  status    = 'active'
ORDER BY name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- list categories ------------------------------------------------------

TEMPLATE_LIST_CATEGORIES = IntentTemplate(
    intent="list_categories",
    engine="sql",
    description="List product categories",
    matchers=[
        r'\b(?:show|list|get|fetch)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?categor(?:y|ies)\b',
        r'\bwhat\s+categor(?:y|ies)\s+(?:do\s+we\s+have|exist)\b',
        r'\bproduct\s+categor(?:y|ies)\b',
        r'\bshow\s+(?:product\s+)?categor(?:y|ies)\b',
    ],
    query="""
SELECT category_id, name, code, status
FROM   categories
WHERE  tenant_id = :tenant_id
  AND  status    = 'active'
ORDER BY name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- total spend ----------------------------------------------------------

def _total_spend_query(entities) -> str:
    date_clause = _date_clause(entities)
    return f"""
SELECT COALESCE(SUM(pr.total_amount), 0) AS total_spend,
       COUNT(*)                           AS request_count
FROM   purchase_requests pr
WHERE  pr.tenant_id = :tenant_id
  AND  pr.status NOT IN ('deleted', 'cancelled')
  {date_clause}
""".strip()


TEMPLATE_TOTAL_SPEND = IntentTemplate(
    intent="total_spend",
    engine="sql",
    description="Total spend / budget consumed in a time period",
    matchers=[
        r'\btotal\s+spend\b',
        r'\btotal\s+spent\b',
        r'\bhow\s+much\s+(?:have\s+we\s+)?(?:spent|spend)\b',
        r'\boverall\s+spend\b',
        r'\bspend\s+to\s+date\b',
    ],
    query="__dynamic__",
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)
TEMPLATE_TOTAL_SPEND._build_query = _total_spend_query  # type: ignore


# ---- spend breakdown by user ---------------------------------------------

def _spend_by_user_query(entities) -> str:
    date_clause = _date_clause(entities)
    limit = entities.get("limit", 20)
    return f"""
SELECT u.display_name, u.email,
       COALESCE(SUM(pr.total_amount), 0) AS total_spend,
       COUNT(pr.id)                      AS request_count
FROM   purchase_requests pr
JOIN   users u ON u.user_id = pr.user_id
WHERE  pr.tenant_id = :tenant_id
  AND  pr.status NOT IN ('deleted', 'cancelled')
  {date_clause}
GROUP BY u.user_id, u.display_name, u.email
ORDER BY total_spend DESC
LIMIT {int(limit)}
""".strip()


TEMPLATE_SPEND_BY_USER = IntentTemplate(
    intent="spend_by_user",
    engine="sql",
    description="Spend breakdown per user",
    matchers=[
        r'\bspend\s+(?:per|by)\s+user\b',
        r'\bspend\s+breakdown\s+(?:per|by)\s+user\b',
        r'\bbreakdown\s+(?:per|by)\s+user\b',
        r'\bwho\s+(?:is\s+)?(?:spending|spent)\s+(?:the\s+)?(?:most|highest)\b',
        r'\buser\s+spend\s+breakdown\b',
        r'\btop\s+\d+\s+(?:users?|people)\s+by\s+spend\b',
    ],
    query="__dynamic__",
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)
TEMPLATE_SPEND_BY_USER._build_query = _spend_by_user_query  # type: ignore


# ---- top products by spend -----------------------------------------------

def _top_products_query(entities) -> str:
    date_clause = _date_clause(entities)
    limit = entities.get("limit", 10)
    return f"""
SELECT p.display_name, p.sku,
       COUNT(oi.id)           AS order_count,
       SUM(oi.quantity)       AS total_qty,
       SUM(oi.total_amount)   AS total_spend
FROM   order_items oi
JOIN   products    p  ON p.product_id   = oi.product_id
JOIN   orders      o  ON o.id           = oi.order_id
WHERE  o.tenant_id = :tenant_id
  AND  o.status NOT IN ('deleted', 'cancelled')
  {date_clause.replace('created_at', 'o.created_at')}
GROUP BY p.product_id, p.display_name, p.sku
ORDER BY total_spend DESC
LIMIT {int(limit)}
""".strip()


TEMPLATE_TOP_PRODUCTS = IntentTemplate(
    intent="top_products_by_spend",
    engine="sql",
    description="Top products by spend or order volume",
    matchers=[
        r'\btop\s+\d+\s+products?\s+by\b',
        r'\bmost\s+(?:ordered|purchased|bought)\s+products?\b',
        r'\bproducts?\s+(?:with\s+)?(?:highest|most)\s+spend\b',
        r'\bbest\s+selling\s+products?\b',
    ],
    query="__dynamic__",
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)
TEMPLATE_TOP_PRODUCTS._build_query = _top_products_query  # type: ignore


# ---- budget utilization --------------------------------------------------

TEMPLATE_BUDGET_UTIL = IntentTemplate(
    intent="budget_utilization",
    engine="sql",
    description="Budget utilization — cap vs spent",
    matchers=[
        r'\bbudget\s+utiliz(?:ation|ed)\b',
        r'\bbudget\s+(?:used|remaining|left|available)\b',
        r'\bhow\s+much\s+budget\s+(?:is\s+)?(?:left|remaining|available)\b',
        r'\bbudget\s+status\b',
    ],
    query="""
SELECT cc.name        AS cost_centre,
       cbv.total_budget,
       COALESCE(SUM(bt.amount), 0)                          AS spent,
       cbv.total_budget - COALESCE(SUM(bt.amount), 0)      AS remaining,
       ROUND(
         COALESCE(SUM(bt.amount), 0) / NULLIF(cbv.total_budget, 0) * 100, 2
       )                                                    AS utilization_pct
FROM   cost_centre_budget_versions cbv
JOIN   cost_centres cc ON cc.cost_centre_id = cbv.cost_centre_id
LEFT JOIN budget_transactions bt
       ON bt.cost_centre_id = cbv.cost_centre_id
      AND bt.tenant_id      = cbv.tenant_id
WHERE  cbv.tenant_id = :tenant_id
  AND  cbv.is_current = TRUE
  AND  cc.status = 'active'
GROUP BY cc.cost_centre_id, cc.name, cbv.total_budget
ORDER BY utilization_pct DESC NULLS LAST
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---- order history --------------------------------------------------------

def _order_history_query(entities) -> str:
    date_clause = _date_clause(entities)
    return f"""
SELECT pr.id, pr.status, pr.total_amount, pr.created_at,
       u.display_name AS requester, u.email
FROM   purchase_requests pr
JOIN   users u ON u.user_id = pr.user_id
WHERE  pr.tenant_id = :tenant_id
  AND  pr.status NOT IN ('deleted')
  {date_clause}
ORDER BY pr.created_at DESC
LIMIT 200
""".strip()


TEMPLATE_ORDER_HISTORY = IntentTemplate(
    intent="order_history",
    engine="sql",
    description="Purchase request / order history",
    matchers=[
        r'\border\s+history\b',
        r'\brecent\s+orders?\b',
        r'\bpast\s+orders?\b',
        r'\bpurchase\s+(?:request\s+)?history\b',
        r'\blist\s+(?:all\s+)?orders?\b',
    ],
    query="__dynamic__",
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)
TEMPLATE_ORDER_HISTORY._build_query = _order_history_query  # type: ignore


# ---- list approved ranges ------------------------------------------------

TEMPLATE_LIST_APPROVED_RANGES = IntentTemplate(
    intent="list_approved_ranges",
    engine="sql",
    description="List approved ranges for the tenant",
    matchers=[
        r'\b(?:show|list|get)\s+(?:all\s+)?approved\s+ranges?\b',
        r'\bwhat\s+approved\s+ranges?\s+(?:exist|are\s+there|do\s+we\s+have)\b',
    ],
    query="""
SELECT ar.approved_range_id, ar.name, ar.is_universal, ar.status
FROM   approved_ranges ar
WHERE  ar.tenant_id = :tenant_id
  AND  ar.status    = 'active'
ORDER BY ar.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---------------------------------------------------------------------------
# Graph (Cypher) templates
# ---------------------------------------------------------------------------

TEMPLATE_USERS_IN_ORG = IntentTemplate(
    intent="users_in_org",
    engine="graph",
    description="List users belonging to an org unit",
    matchers=[
        r'\bwho\s+belongs?\s+to\b',
        r'\bwhich\s+(?:users?|people)\s+(?:are\s+in|belong\s+to|work\s+at)\b',
        r'\bmembers?\s+of\s+(?:the\s+)?(?:org|department|unit|team)\b',
        r'\busers?\s+in\s+(?:the\s+)?(?:org|department|unit|team)\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_USER]->(u:User {status: 'active'})
      -[:BELONGS_TO]->(o:OrgUnit {status: 'active'})
WHERE ($org_name = '' OR toLower(o.name) CONTAINS toLower($org_name)
                      OR toLower(o.code) CONTAINS toLower($org_name))
RETURN u.user_id AS user_id, u.display_name AS name, u.email AS email,
       o.name AS org_unit, o.code AS org_code
ORDER BY o.name, u.display_name
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "org_name": e.get("org_name", ""),
    },
)


TEMPLATE_ORG_HIERARCHY = IntentTemplate(
    intent="org_hierarchy",
    engine="graph",
    description="Show org unit hierarchy (parent-child tree)",
    matchers=[
        r'\borg[\s\-]?unit\s+hierarchy\b',
        r'\borg\s+hierarchy\b',
        r'\borg(?:anization(?:al)?)?\s+structure\b',
        r'\bparent\s+(?:and\s+)?child\s+org\b',
        r'\btopology\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_ORG_UNIT]->(o:OrgUnit {status: 'active'})
OPTIONAL MATCH (o)-[:CHILD_OF]->(parent:OrgUnit {status: 'active'})
RETURN o.org_unit_id AS org_unit_id, o.name AS name, o.code AS code,
       o.level AS level, parent.name AS parent_name, parent.org_unit_id AS parent_id
ORDER BY o.level, o.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


TEMPLATE_REPORTS_TO = IntentTemplate(
    intent="reports_to",
    engine="graph",
    description="Who does a user report to (manager lookup)",
    matchers=[
        r'\breports?\s+to\b',
        r'\bwho\s+(?:is\s+)?(?:the\s+)?manager\s+of\b',
        r'\bwho\s+manages\b',
        r'\bmanager\s+of\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_USER]->(u:User {status: 'active'})
WHERE ($email = '' OR u.email = $email)
  AND ($user_name = '' OR toLower(u.display_name) CONTAINS toLower($user_name))
MATCH (u)-[:BELONGS_TO]->(o:OrgUnit {status: 'active'})
OPTIONAL MATCH (o)<-[:BELONGS_TO]-(manager:User {status: 'active'})
WHERE manager.user_id <> u.user_id
RETURN u.display_name AS user, u.email AS user_email,
       o.name AS org_unit, manager.display_name AS manager_name,
       manager.email AS manager_email
LIMIT 50
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "email": e.get("email", ""),
        "user_name": e.get("user_name", ""),
    },
)


TEMPLATE_USER_ROLES = IntentTemplate(
    intent="user_roles",
    engine="graph",
    description="Roles assigned to a user",
    matchers=[
        r'\b(?:what|which)\s+roles?\s+(?:does|do|has|have)\b',
        r'\bwho\s+(?:has|have)\s+(?:the\s+)?(?:role|permission)\b',
        r'\broles?\s+(?:for|of|assigned\s+to)\s+user\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_USER]->(u:User {status: 'active'})
WHERE ($email = '' OR u.email = $email)
  AND ($user_name = '' OR toLower(u.display_name) CONTAINS toLower($user_name))
MATCH (u)-[:HAS_ROLE]->(r:Role {status: 'active'})
RETURN u.display_name AS user, u.email AS email,
       r.name AS role_name, r.code AS role_code
ORDER BY u.display_name, r.name
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "email": e.get("email", ""),
        "user_name": e.get("user_name", ""),
    },
)


TEMPLATE_ROLE_PERMISSIONS = IntentTemplate(
    intent="role_permissions",
    engine="graph",
    description="Permissions granted by a role",
    matchers=[
        r'\bwhat\s+permissions?\b',
        r'\bpermissions?\s+for\s+(?:the\s+)?role\b',
        r'\bwhat\s+can\s+(?:the\s+)?role\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_ORG_UNIT|HAS_USER*0..2]->
      (r:Role {status: 'active'})
WHERE ($role_name = '' OR toLower(r.name)  CONTAINS toLower($role_name)
                       OR toLower(r.code)  CONTAINS toLower($role_name))
MATCH (r)-[:GRANTS]->(p:Permission)
RETURN r.name AS role_name, r.code AS role_code,
       collect(p.code) AS permissions
ORDER BY r.name
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "role_name": e.get("role_name", ""),
    },
)


TEMPLATE_USER_STORES = IntentTemplate(
    intent="user_stores",
    engine="graph",
    description="Which stores a user is assigned to",
    matchers=[
        r'\b(?:what|which)\s+stores?.{0,20}(?:user|person|assigned)\b',
        r'\b(?:which|what)\s+stores?\s+(?:is|does|are)\s+.{0,20}(?:assigned\s+to|work(?:ing)?\s+at)\b',
        r'\buser.{0,15}works?\s+at\b',
        r'\bworks?\s+at\s+(?:which|what)\s+stores?\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_USER]->(u:User {status: 'active'})
WHERE ($email = '' OR u.email = $email)
  AND ($user_name = '' OR toLower(u.display_name) CONTAINS toLower($user_name))
MATCH (u)-[:WORKS_AT]->(s:Store {status: 'active'})
RETURN u.display_name AS user, u.email AS email,
       s.name AS store_name, s.store_id AS store_id
ORDER BY u.display_name, s.name
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "email": e.get("email", ""),
        "user_name": e.get("user_name", ""),
    },
)


TEMPLATE_VENDOR_PRODUCTS = IntentTemplate(
    intent="vendor_products",
    engine="graph",
    description="Products supplied by a vendor",
    matchers=[
        r'\bvendors?\s+that\s+(?:supply|supplies)\b',
        r'\b(?:which|what)\s+vendors?\s+(?:supply|supplies)\b',
        r'\bwhat\s+(?:products?|items?)\s+(?:does|do)\s+vendor\b',
        r'\bproducts?\s+(?:from|by|supplied\s+by)\s+vendor\b',
        r'\bvendor.{0,20}supplies?\b',
    ],
    query="""
MATCH (v:Vendor {status: 'active'})-[:SUPPLIES]->(p:Product {status: 'active'})
WHERE ($vendor_name = '' OR toLower(v.name) CONTAINS toLower($vendor_name))
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_SITE]->(:Site)-[:HAS_STORE]->
      (:Store)-[:STOCKS]->(p)
RETURN v.name AS vendor, p.display_name AS product,
       p.sku AS sku, p.item_code AS item_code
ORDER BY v.name, p.display_name
LIMIT 200
""".strip(),
    build_params=lambda e, tid, uid: {
        "tenant_id": tid,
        "vendor_name": e.get("vendor_name", ""),
    },
)


TEMPLATE_APPROVED_RANGE_CONTENTS = IntentTemplate(
    intent="approved_range_contents",
    engine="graph",
    description="Categories / products inside an approved range",
    matchers=[
        r'\bapproved\s+range\b',
        r"\bwhat(?:'s|\s+is)?\s+in\s+(?:the\s+)?approved\s+range\b",
        r'\bapproved\s+(?:products?|categories)\b',
    ],
    query="""
MATCH (t:Tenant {tenant_id: $tenant_id})-[:HAS_APPROVED_RANGE]->(ar:ApprovedRange {status: 'active'})
MATCH (ar)-[:INCLUDES_CATEGORY]->(c:Category {status: 'active'})
RETURN ar.name AS approved_range, ar.is_universal AS is_universal,
       collect(c.name) AS categories
ORDER BY ar.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


TEMPLATE_GOVERNANCE_POLICIES = IntentTemplate(
    intent="governance_policies",
    engine="graph",
    description="Governance policies assigned to tenant/org units",
    matchers=[
        r'\bgovernance\s+(?:policy|policies)\b',
        r'\bwhat\s+(?:policies|policy)\s+(?:apply|applies|are\s+there)\b',
        r'\bpolicies?\s+(?:for|of)\s+(?:the\s+)?(?:org|department|tenant)\b',
    ],
    query="""
MATCH (p:Policy {status: 'active'})-[:ASSIGNED_TO]->(target)
WHERE (target:Tenant AND target.tenant_id = $tenant_id)
   OR (target:OrgUnit AND (:Tenant {tenant_id: $tenant_id})-[:HAS_ORG_UNIT]->(target))
RETURN p.name AS policy_name, p.code AS policy_code,
       p.policy_type AS policy_type, labels(target)[0] AS target_type,
       CASE WHEN target:Tenant THEN target.name
            WHEN target:OrgUnit THEN target.name
            ELSE 'unknown' END AS target_name
ORDER BY p.policy_type, p.name
""".strip(),
    build_params=lambda e, tid, uid: {"tenant_id": tid},
)


# ---------------------------------------------------------------------------
# Vector templates (query = None; question text is the search input)
# ---------------------------------------------------------------------------

TEMPLATE_FIND_SIMILAR_PRODUCTS = IntentTemplate(
    intent="find_similar_products",
    engine="vector",
    description="Semantic / fuzzy product search",
    matchers=[
        r'\bsimilar\s+to\b',
        r'\bproducts?\s+like\b',
        r'\bfind\s+(?:me\s+)?(?:products?|items?|consumables?)\b',
        r'\bsearch\s+for\s+(?:products?|items?)\b',
        r'\bsemantically\s+(?:similar|related)\b',
        r'\bnearest\s+(?:products?|matches?)\b',
        r'\bfuzzy\s+(?:search|match)\b',
    ],
    query=None,  # question text passed directly to vector search
    build_params=lambda e, tid, uid: {},
)


# ---------------------------------------------------------------------------
# Registry — order matters (specific before general)
# ---------------------------------------------------------------------------

REGISTRY: List[IntentTemplate] = [
    # --- SQL (specific entity lists before generic product list) ---
    TEMPLATE_COUNT_PRODUCTS,
    TEMPLATE_LIST_CATEGORIES,
    TEMPLATE_LIST_USERS,
    TEMPLATE_LIST_VENDORS,
    TEMPLATE_LIST_STORES,
    TEMPLATE_LIST_SITES,
    TEMPLATE_LIST_APPROVED_RANGES,
    TEMPLATE_LIST_PRODUCTS,         # generic last — catches remaining noun phrases
    TEMPLATE_TOTAL_SPEND,
    TEMPLATE_SPEND_BY_USER,
    TEMPLATE_TOP_PRODUCTS,
    TEMPLATE_BUDGET_UTIL,
    TEMPLATE_ORDER_HISTORY,
    # --- Graph ---
    TEMPLATE_ORG_HIERARCHY,
    TEMPLATE_REPORTS_TO,
    TEMPLATE_USER_ROLES,
    TEMPLATE_ROLE_PERMISSIONS,
    TEMPLATE_USER_STORES,
    TEMPLATE_USERS_IN_ORG,
    TEMPLATE_VENDOR_PRODUCTS,
    TEMPLATE_APPROVED_RANGE_CONTENTS,
    TEMPLATE_GOVERNANCE_POLICIES,
    # --- Vector ---
    TEMPLATE_FIND_SIMILAR_PRODUCTS,
]


def find_template(question: str) -> Optional[IntentTemplate]:
    """Return the first matching template or None if no match."""
    for template in REGISTRY:
        if template.matches(question):
            return template
    return None
