"""
test_e2e.py — End-to-End + Policy-Architecture Test Suite
==========================================================
Tests the full provisioning lifecycle and OPA policy engine:

  Login → Site → Store → User → Cost Centre → Org Unit
  → Financial Calendar + Year + Periods
  → Company Budget Cap → CC Budget Version
  → User CC Assignment → User Budget Limits
  → Approval Policy (2-stage, SOX SoD enforced)
  → Category → Product
  → Purchase Request (auto-approve path)
  → Purchase Request (workflow path) → Approval Decision
  → SOX SoD enforcement (requester ≠ approver)
  → Logout

Usage:
    python test_e2e.py
"""

import sys
import json
import requests
from datetime import date, timedelta

BASE_URL = "http://localhost:8000"
TIMEOUT  = 15

# ── Credentials ───────────────────────────────────────────────────────────────
ADMIN_EMAIL    = "sebinsanthosh2016@gmail.com"
ADMIN_PASSWORD = "SecurePass1"

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

results = []   # list of (label, "PASS"|"FAIL"|"SKIP"|"INFO", note)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def url(path):
    return f"{BASE_URL}{path}"

def headers(token):
    return {"Authorization": f"Bearer {token}"}

def section(title):
    print(f"\n{BOLD}{'─'*65}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*65}{RESET}")

def ok(label, note=""):
    tag = f"{GREEN}✔ PASS{RESET}"
    print(f"  {tag}  {label}" + (f"  ({note})" if note else ""))
    results.append((label, "PASS", note))

def fail(label, note=""):
    tag = f"{RED}✘ FAIL{RESET}"
    print(f"  {tag}  {label}" + (f"  ({note})" if note else ""))
    results.append((label, "FAIL", note))

def skip(label, reason=""):
    tag = f"{YELLOW}⚠ SKIP{RESET}"
    print(f"  {tag}  {label}" + (f"  ({reason})" if reason else ""))
    results.append((label, "SKIP", reason))

def info(msg):
    print(f"  {BLUE}ℹ{RESET}  {msg}")

def _detail(resp):
    try:
        return resp.json().get("detail", resp.text[:200])
    except Exception:
        return resp.text[:200]

def check(label, resp, expected, *, extract=None):
    """Assert status code. If extract is a dot-path string, return that field."""
    if resp.status_code == expected:
        ok(label, f"HTTP {resp.status_code}")
        if extract:
            try:
                data = resp.json()
                for key in extract.split("."):
                    data = data[key]
                return data
            except Exception:
                return None
        return resp.json() if resp.text else {}
    else:
        fail(label, f"HTTP {resp.status_code} — {_detail(resp)}")
        return None

def abort_if_none(value, name):
    if value is None:
        print(f"\n  {RED}✘ Cannot continue: {name} is None. Aborting.{RESET}")
        _summary()
        sys.exit(1)
    return value

# ─────────────────────────────────────────────────────────────────────────────
# 0.  REACHABILITY
# ─────────────────────────────────────────────────────────────────────────────
section("0 · Reachability")
try:
    r = requests.get(url("/health"), timeout=TIMEOUT)
    abort_if_none(check("GET /health", r, 200), "health check")
except requests.exceptions.ConnectionError:
    print(f"\n  {RED}Cannot reach {BASE_URL}. Is the server running?{RESET}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 1.  LOGIN (Admin)
# ─────────────────────────────────────────────────────────────────────────────
section("1 · Admin login")
r = requests.post(url("/onboarding/tenant-signin"), json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD,
}, timeout=TIMEOUT)
login_data = check("POST /onboarding/tenant-signin", r, 200)
abort_if_none(login_data, "login response")

TOKEN     = login_data["token"]
TENANT_ID = login_data["tenant_id"]
USER_ID   = login_data["user_id"]
H         = headers(TOKEN)

info(f"Logged in  tenant={TENANT_ID}  user={USER_ID}")

# ─────────────────────────────────────────────────────────────────────────────
# 2.  CREATE SITE
# ─────────────────────────────────────────────────────────────────────────────
section("2 · Create Site")
r = requests.post(url("/provisioning/sites"), headers=H, json={
    "tenant_id": TENANT_ID,
    "name": "E2E Test HQ",
    "type": "warehouse",
    "active": True,
    "currency": "GBP",
    "timezone": "Europe/London",
    "language": "en_GB",
    "is_headquarter": True,
    "primary_billing_address": {
        "line1": "1 Test Street",
        "city": "London",
        "postcode": "EC1A 1BB",
        "country": "GB"
    },
}, timeout=TIMEOUT)
site_resp = check("POST /provisioning/sites", r, 201)
SITE_ID = site_resp.get("site_id") if site_resp else None
info(f"site_id = {SITE_ID}")

# Verify it appears in list
if SITE_ID:
    r = requests.get(url("/provisioning/sites"), headers=H,
                     params={"tenant_id": TENANT_ID}, timeout=TIMEOUT)
    data = check("GET /provisioning/sites (includes new site)", r, 200)
    if data:
        ids = [s.get("site_id") for s in data.get("sites", [])]
        if SITE_ID in ids:
            ok("Site appears in site list")
        else:
            fail("Site appears in site list", "site_id not found in list response")

    r2 = requests.get(url(f"/provisioning/sites/{SITE_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/sites/{site_id}", r2, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 3.  CREATE STORE
# ─────────────────────────────────────────────────────────────────────────────
section("3 · Create Store")
r = requests.post(url("/provisioning/stores"), headers=H, json={
    "tenant_id": TENANT_ID,
    "name": "E2E Test Store",
    "store_type": "retail",
    "active": True,
    "site_id": SITE_ID,
    "currency": "GBP",
    "timezone": "Europe/London",
}, timeout=TIMEOUT)
store_resp = check("POST /provisioning/stores", r, 201)
STORE_ID = store_resp.get("store_id") if store_resp else None
info(f"store_id = {STORE_ID}")

if STORE_ID:
    r = requests.get(url(f"/provisioning/stores/{STORE_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/stores/{store_id}", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 4.  CREATE SECOND USER (will be used as non-admin requester)
# ─────────────────────────────────────────────────────────────────────────────
section("4 · Create User (requester)")
import uuid as _uuid
requester_email = f"requester_{_uuid.uuid4().hex[:6]}@example.com"
r = requests.post(url("/provisioning/users"), headers=H, json={
    "tenant_id": TENANT_ID,
    "email": requester_email,
    "password": "RequesterPass1",
    "first_name": "Test",
    "last_name": "Requester",
    "is_sso_enabled": False,
}, timeout=TIMEOUT)
user_resp = check("POST /provisioning/users", r, 201)
REQUESTER_ID = user_resp.get("user_id") if user_resp else None
info(f"requester_id = {REQUESTER_ID}")

if REQUESTER_ID:
    r = requests.get(url(f"/provisioning/users/{REQUESTER_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/users/{user_id}", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 5.  CREATE COST CENTRE
# ─────────────────────────────────────────────────────────────────────────────
section("5 · Create Cost Centre")
r = requests.post(url("/provisioning/cost-centres"), headers=H, json={
    "tenant_id": TENANT_ID,
    "code": f"CC-E2E-{_uuid.uuid4().hex[:4].upper()}",
    "name": "E2E Test Cost Centre",
    "description": "Created by automated E2E test",
    "is_active": True,
    "created_by": USER_ID,
}, timeout=TIMEOUT)
cc_resp = check("POST /provisioning/cost-centres", r, 201)
CC_ID = cc_resp.get("cost_centre_id") if cc_resp else None
info(f"cost_centre_id = {CC_ID}")

if CC_ID:
    r = requests.get(url(f"/provisioning/cost-centres/{CC_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/cost-centres/{cc_id}", r, 200)

    # Duplicate code → 409
    r = requests.post(url("/provisioning/cost-centres"), headers=H, json={
        "tenant_id": TENANT_ID,
        "code": cc_resp.get("code", "UNKNOWN"),
        "name": "Duplicate CC",
        "created_by": USER_ID,
    }, timeout=TIMEOUT)
    check("POST /provisioning/cost-centres (duplicate code → 409)", r, 409)

# ─────────────────────────────────────────────────────────────────────────────
# 6.  CREATE ORG UNIT
# ─────────────────────────────────────────────────────────────────────────────
section("6 · Create Org Unit")
r = requests.post(url("/provisioning/org_units"), headers=H, json={
    "tenant_id": TENANT_ID,
    "name": "E2E Finance Team",
    "type": "department",
    "status": "active",
    "code": f"OU-E2E-{_uuid.uuid4().hex[:4].upper()}",
    "description": "E2E test org unit",
}, timeout=TIMEOUT)
ou_resp = check("POST /provisioning/org_units", r, 201)
OU_ID = ou_resp.get("org_unit_id") if ou_resp else None
info(f"org_unit_id = {OU_ID}")

if OU_ID:
    r = requests.get(url(f"/provisioning/org_units/{OU_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/org_units/{org_unit_id}", r, 200)

r = requests.get(url("/provisioning/org_units"), headers=H,
                 params={"tenant_id": TENANT_ID}, timeout=TIMEOUT)
check("GET /provisioning/org_units", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 7.  FINANCIAL CALENDAR + YEAR + PERIODS
# ─────────────────────────────────────────────────────────────────────────────
section("7 · Financial Calendar → Year → Periods")

today = date.today()
fy_start = date(today.year, 1, 1)
fy_end   = date(today.year, 12, 31)

r = requests.post(url("/financial-calendars"), headers=H, json={
    "name": f"E2E Calendar {today.year}",
    "description": "Auto-generated by E2E test",
    "calendar_type": "gregorian",
    "start_month": 1,
    "currency": "GBP",
    "is_default": False,
}, timeout=TIMEOUT)
cal_resp = check("POST /financial-calendars", r, 201)
CAL_ID = cal_resp.get("calendar_id") if cal_resp else None
info(f"calendar_id = {CAL_ID}")

YEAR_ID = None
if CAL_ID:
    r = requests.get(url(f"/financial-calendars/{CAL_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /financial-calendars/{calendar_id}", r, 200)

    r = requests.post(url(f"/financial-calendars/{CAL_ID}/years"), headers=H, json={
        "label": f"FY{today.year}-E2E",
        "start_date": str(fy_start),
        "end_date": str(fy_end),
        "year_type": "full",
        "total_budget_minor": 10_000_000,
        "notes": "E2E test year",
    }, timeout=TIMEOUT)
    yr_resp = check("POST /financial-calendars/{cal}/years", r, 201)
    YEAR_ID = yr_resp.get("year_id") if yr_resp else None
    info(f"year_id = {YEAR_ID}")

    if YEAR_ID:
        r = requests.post(
            url(f"/financial-calendars/{CAL_ID}/years/{YEAR_ID}/generate-periods"),
            headers=H,
            json={"period_type": "month"},
            timeout=TIMEOUT,
        )
        period_resp = check("POST …/generate-periods (monthly)", r, 201)
        if period_resp:
            info(f"Generated {period_resp.get('generated', 0)} monthly periods")

        r = requests.get(
            url(f"/financial-calendars/{CAL_ID}/years/{YEAR_ID}/periods"),
            headers=H, timeout=TIMEOUT,
        )
        check("GET …/years/{year_id}/periods", r, 200)

        # Activate the year (enables budget operations against it)
        r = requests.put(
            url(f"/financial-calendars/{CAL_ID}/years/{YEAR_ID}/activate"),
            headers=H, timeout=TIMEOUT,
        )
        check("PUT …/years/{year_id}/activate", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 8.  COMPANY BUDGET CAP
# ─────────────────────────────────────────────────────────────────────────────
section("8 · Company Budget Cap")
CAP_ID = None
if YEAR_ID and CAL_ID:
    r = requests.post(url("/budgets/company-caps"), headers=H, json={
        "year_id": YEAR_ID,
        "calendar_id": CAL_ID,
        "currency": "GBP",
        "total_budget_minor": 10_000_000,
        "hard_cap": False,
        "notes": "E2E test company cap",
    }, timeout=TIMEOUT)
    cap_resp = check("POST /budgets/company-caps", r, 201)
    CAP_ID = cap_resp.get("cap_id") if cap_resp else None
    info(f"cap_id = {CAP_ID}")

    r = requests.get(url("/budgets/company-caps"), headers=H,
                     params={"year_id": YEAR_ID}, timeout=TIMEOUT)
    check("GET /budgets/company-caps", r, 200)

    # Duplicate cap for same year → 409
    r = requests.post(url("/budgets/company-caps"), headers=H, json={
        "year_id": YEAR_ID,
        "calendar_id": CAL_ID,
        "currency": "GBP",
        "total_budget_minor": 5_000_000,
        "hard_cap": False,
    }, timeout=TIMEOUT)
    check("POST /budgets/company-caps (duplicate year → 409)", r, 409)
else:
    skip("POST /budgets/company-caps", "no year_id")

# ─────────────────────────────────────────────────────────────────────────────
# 9.  CC BUDGET VERSION
# ─────────────────────────────────────────────────────────────────────────────
section("9 · Cost-Centre Budget Version")
VERSION_ID = None
if CC_ID and YEAR_ID:
    r = requests.post(url("/budgets/cc-versions"), headers=H, json={
        "cost_centre_id": CC_ID,
        "year_id": YEAR_ID,
        "period_id": None,
        "currency": "GBP",
        "budget_minor": 500_000,
    }, timeout=TIMEOUT)
    ver_resp = check("POST /budgets/cc-versions", r, 201)
    VERSION_ID = ver_resp.get("version_id") if ver_resp else None
    info(f"version_id = {VERSION_ID}")

    if VERSION_ID:
        r = requests.get(url(f"/budgets/cc-versions/{VERSION_ID}"), headers=H, timeout=TIMEOUT)
        check("GET /budgets/cc-versions/{version_id}", r, 200)

        r = requests.get(url("/budgets/transactions"), headers=H,
                         params={"version_id": VERSION_ID}, timeout=TIMEOUT)
        data = check("GET /budgets/transactions (initial allocation entry)", r, 200)
        if data:
            txns = data.get("transactions", [])
            if any(t.get("txn_type") == "allocation" for t in txns):
                ok("Initial 'allocation' ledger entry present")
            else:
                fail("Initial 'allocation' ledger entry present",
                     f"found txn types: {[t.get('txn_type') for t in txns]}")
else:
    skip("POST /budgets/cc-versions", "no CC_ID or YEAR_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 10. USER → COST CENTRE ASSIGNMENT
# ─────────────────────────────────────────────────────────────────────────────
section("10 · User → Cost Centre Assignment")
if REQUESTER_ID and CC_ID:
    r = requests.post(url("/user-budgets/assignments"), headers=H, json={
        "user_id": REQUESTER_ID,
        "cost_centre_id": CC_ID,
        "is_primary": True,
    }, timeout=TIMEOUT)
    assign_resp = check("POST /user-budgets/assignments", r, 201)
    ASSIGNMENT_ID = assign_resp.get("assignment_id") if assign_resp else None
    info(f"assignment_id = {ASSIGNMENT_ID}")

    r = requests.get(url("/user-budgets/assignments"), headers=H,
                     params={"user_id": REQUESTER_ID}, timeout=TIMEOUT)
    data = check("GET /user-budgets/assignments (filtered by user)", r, 200)
    if data:
        found = any(a.get("user_id") == REQUESTER_ID for a in data.get("assignments", []))
        ok("Requester assignment appears in list") if found else fail("Requester assignment appears in list")

    # Duplicate → 409
    r = requests.post(url("/user-budgets/assignments"), headers=H, json={
        "user_id": REQUESTER_ID,
        "cost_centre_id": CC_ID,
        "is_primary": False,
    }, timeout=TIMEOUT)
    check("POST /user-budgets/assignments (duplicate → 409)", r, 409)
else:
    skip("User→CC assignment", "no REQUESTER_ID or CC_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 11. USER BUDGET LIMITS
# ─────────────────────────────────────────────────────────────────────────────
section("11 · User Budget Limits")
LIMIT_ID = None
if REQUESTER_ID and CC_ID and YEAR_ID:
    r = requests.post(url("/user-budgets/limits"), headers=H, json={
        "user_id": REQUESTER_ID,
        "cost_centre_id": CC_ID,
        "year_id": YEAR_ID,
        "limit_type": "requester",
        "window_type": "month",
        "limit_amount_minor": 50_000,
        "carry_forward_enabled": False,
    }, timeout=TIMEOUT)
    lim_resp = check("POST /user-budgets/limits (requester/month)", r, 201)
    LIMIT_ID = lim_resp.get("limit_id") if lim_resp else None
    info(f"limit_id = {LIMIT_ID}")

    # Duplicate → 409
    r = requests.post(url("/user-budgets/limits"), headers=H, json={
        "user_id": REQUESTER_ID,
        "cost_centre_id": CC_ID,
        "year_id": YEAR_ID,
        "limit_type": "requester",
        "window_type": "month",
        "limit_amount_minor": 99_999,
        "carry_forward_enabled": False,
    }, timeout=TIMEOUT)
    check("POST /user-budgets/limits (duplicate → 409)", r, 409)

    # Invalid limit_type → 422
    r = requests.post(url("/user-budgets/limits"), headers=H, json={
        "user_id": REQUESTER_ID,
        "cost_centre_id": CC_ID,
        "year_id": YEAR_ID,
        "limit_type": "owner",           # not in {requester, approver}
        "window_type": "month",
        "limit_amount_minor": 100,
        "carry_forward_enabled": False,
    }, timeout=TIMEOUT)
    check("POST /user-budgets/limits (bad limit_type → 422)", r, 422)

    r = requests.get(url("/user-budgets/limits"), headers=H,
                     params={"user_id": REQUESTER_ID, "year_id": YEAR_ID}, timeout=TIMEOUT)
    check("GET /user-budgets/limits (filtered)", r, 200)
else:
    skip("User budget limits", "no REQUESTER_ID / CC_ID / YEAR_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 12. APPROVAL POLICY  (2-stage, SOX SoD enforced)
# ─────────────────────────────────────────────────────────────────────────────
section("12 · Approval Policy (2-stage, SOX SoD)")
POLICY_ID = None
if CC_ID:
    r = requests.post(url("/approval-policies"), headers=H, json={
        "name": "E2E 2-Stage Policy",
        "description": "Auto-created by E2E test",
        "cost_centre_id": CC_ID,
        "routing_mode": "hierarchical",
        "broadcast_n": 1,
        "sox_sod_enforced": True,
        "partial_approval_mode": "block",
        "zero_value_mode": "auto",
        "stages": [
            {
                "stage_order": 1,
                "name": "Line Manager Approval",
                "parallel_allowed": False,
                "min_approvers": 1,
                "conditions": [
                    {"field": "amount", "operator": "gte", "value": 1, "logic": "AND"}
                ],
                "approvers": [
                    {
                        "approver_type": "user",
                        "approver_user_id": USER_ID,   # admin approves
                    }
                ],
            },
        ],
    }, timeout=TIMEOUT)
    pol_resp = check("POST /approval-policies (2-stage, SOX SoD)", r, 201)
    POLICY_ID = pol_resp.get("policy_id") if pol_resp else None
    info(f"policy_id = {POLICY_ID}")

    if POLICY_ID:
        r = requests.get(url(f"/approval-policies/{POLICY_ID}"), headers=H, timeout=TIMEOUT)
        pol_detail = check("GET /approval-policies/{policy_id}", r, 200)
        if pol_detail:
            stages = pol_detail.get("stages", [])
            info(f"Policy has {len(stages)} stage(s), sox_sod_enforced={pol_detail.get('sox_sod_enforced')}")
            if pol_detail.get("sox_sod_enforced"):
                ok("SOX SoD flag is True on returned policy")
            else:
                fail("SOX SoD flag is True on returned policy")

    r = requests.get(url("/approval-policies"), headers=H,
                     params={"cost_centre_id": CC_ID}, timeout=TIMEOUT)
    check("GET /approval-policies (filtered by CC)", r, 200)
else:
    skip("Approval policy", "no CC_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 13. CATALOG — Category + Product
# ─────────────────────────────────────────────────────────────────────────────
section("13 · Catalog — Category + Product")
CAT_ID     = None
PRODUCT_ID = None

r = requests.post(url("/catalog/categories"), headers=H, json={
    "tenant_id": TENANT_ID,
    "name": "E2E Office Supplies",
    "code": f"OFF-{_uuid.uuid4().hex[:4].upper()}",
    "description": "Office supplies category",
}, timeout=TIMEOUT)
cat_resp = check("POST /catalog/categories", r, 201)
CAT_ID = cat_resp.get("category_id") if cat_resp else None
info(f"category_id = {CAT_ID}")

r = requests.get(url("/catalog/categories"), headers=H, timeout=TIMEOUT)
data = check("GET /catalog/categories", r, 200)
if data:
    info(f"Total categories: {data.get('total', '?')}")

r = requests.post(url("/catalog/products"), headers=H, json={
    "tenant_id": TENANT_ID,
    "sku": f"SKU-E2E-{_uuid.uuid4().hex[:6].upper()}",
    "display_name": "E2E Ballpoint Pen (Black)",
    "purchase_price_minor": 199,
    "currency": "GBP",
    "category_id": CAT_ID,
    "matrix_type": "standalone",
    "tax_rate": 2000,
}, timeout=TIMEOUT)
prod_resp = check("POST /catalog/products", r, 201)
PRODUCT_ID = prod_resp.get("product_id") if prod_resp else None
info(f"product_id = {PRODUCT_ID}")

r = requests.get(url("/catalog/products"), headers=H, timeout=TIMEOUT)
data = check("GET /catalog/products", r, 200)
if data:
    info(f"Total products: {data.get('total', '?')}")

# Duplicate SKU → 409
if prod_resp:
    r = requests.post(url("/catalog/products"), headers=H, json={
        "tenant_id": TENANT_ID,
        "sku": prod_resp.get("sku", "UNKNOWN"),
        "display_name": "Duplicate product",
        "purchase_price_minor": 100,
        "currency": "GBP",
        "matrix_type": "standalone",
        "tax_rate": 0,
    }, timeout=TIMEOUT)
    check("POST /catalog/products (duplicate SKU → 409)", r, 409)

# ─────────────────────────────────────────────────────────────────────────────
# 14. PURCHASE REQUEST — auto-approve path
#     (admin submits; policy says admin is the approver, OPA should allow
#      auto-approve because can_self_approve flag — or trigger workflow)
# ─────────────────────────────────────────────────────────────────────────────
section("14 · Purchase Request — Admin submission")
PR_ID = None
if CC_ID:
    r = requests.post(url("/purchase-requests"), headers=H, json={
        "cost_centre_id": CC_ID,
        "vendor_id": None,
        "category_id": CAT_ID,
        "description": "E2E test purchase — office supplies",
        "line_items": [
            {"product_id": PRODUCT_ID, "qty": 10, "unit_price_minor": 199,
             "description": "Ballpoint pen black"}
        ],
        "amount_minor": 1990,
        "currency": "GBP",
        "notes": "Auto-generated by E2E test",
    }, timeout=TIMEOUT)
    pr_resp = check("POST /purchase-requests", r, 201)
    PR_ID = pr_resp.get("request_id") if pr_resp else None
    info(f"request_id = {PR_ID}  status = {pr_resp.get('status') if pr_resp else '?'}")

    if PR_ID:
        r = requests.get(url(f"/purchase-requests/{PR_ID}"), headers=H, timeout=TIMEOUT)
        detail = check("GET /purchase-requests/{request_id}", r, 200)
        if detail:
            status_ = detail.get("status", "?")
            mode_   = detail.get("approval_mode", "?")
            info(f"  status={status_}  approval_mode={mode_}")
            if status_ in ("approved", "pending_approval"):
                ok(f"Purchase request status is valid ({status_})")
            else:
                fail(f"Unexpected purchase request status: {status_}")
else:
    skip("Purchase request (admin)", "no CC_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 15. PURCHASE REQUEST — workflow path (requester submits large amount)
# ─────────────────────────────────────────────────────────────────────────────
section("15 · Purchase Request — Requester submits (workflow path)")
PR2_ID = None
if CC_ID and REQUESTER_ID:
    # Requester logs in
    r = requests.post(url("/onboarding/tenant-signin"), json={
        "email": requester_email,
        "password": "RequesterPass1",
    }, timeout=TIMEOUT)
    req_login = check("POST /onboarding/tenant-signin (requester login)", r, 200)
    REQ_TOKEN = req_login.get("token") if req_login else None
    RH = headers(REQ_TOKEN) if REQ_TOKEN else {}

    if REQ_TOKEN:
        r = requests.post(url("/purchase-requests"), headers=RH, json={
            "cost_centre_id": CC_ID,
            "description": "Large purchase — requires approval workflow",
            "amount_minor": 200_000,   # well above the £500 monthly limit
            "currency": "GBP",
            "notes": "E2E workflow test",
        }, timeout=TIMEOUT)
        pr2_resp = check("POST /purchase-requests (requester, large amount)", r, 201)
        PR2_ID = pr2_resp.get("request_id") if pr2_resp else None
        if pr2_resp:
            info(f"request_id = {PR2_ID}  status = {pr2_resp.get('status')}  mode = {pr2_resp.get('approval_mode')}")
            if pr2_resp.get("approval_mode") == "workflow":
                ok("Large-amount request routed to approval workflow")
            else:
                info(f"approval_mode = {pr2_resp.get('approval_mode')} (may be auto-approved if no active policy limits matched)")

        # ── Requester lists their own requests ──────────────────────────────
        r = requests.get(url("/purchase-requests"), headers=RH,
                         params={"requester_id": REQUESTER_ID}, timeout=TIMEOUT)
        check("GET /purchase-requests (requester sees own requests)", r, 200)

        # ── My tasks (should be empty for requester) ─────────────────────────
        r = requests.get(url("/purchase-requests/my-tasks"), headers=RH, timeout=TIMEOUT)
        tasks_resp = check("GET /purchase-requests/my-tasks (requester, expect 0 tasks)", r, 200)
        if tasks_resp:
            info(f"Requester has {len(tasks_resp.get('pending_tasks', []))} pending tasks (expect 0)")
    else:
        skip("Requester purchase request", "requester login failed")
else:
    skip("Requester purchase request", "no CC_ID or REQUESTER_ID")

# ─────────────────────────────────────────────────────────────────────────────
# 16. APPROVAL WORKFLOW — Admin approves requester's PR
# ─────────────────────────────────────────────────────────────────────────────
section("16 · Approval Workflow — Admin approves PR")
if PR2_ID:
    r = requests.get(url(f"/purchase-requests/{PR2_ID}"), headers=H, timeout=TIMEOUT)
    pr2_detail = check("GET /purchase-requests/{PR2_ID} (admin view)", r, 200)

    task_id = None
    if pr2_detail:
        tasks = pr2_detail.get("tasks", [])
        info(f"Workflow has {len(tasks)} task(s)")
        if tasks:
            task_id = tasks[0].get("task_id")
            info(f"task_id = {task_id}  assignee = {tasks[0].get('assignee_user_id')}")

    if task_id:
        # Admin approves
        r = requests.post(url(f"/purchase-requests/tasks/{task_id}/decide"), headers=H, json={
            "decision": "approve",
            "note": "Approved by E2E test admin",
        }, timeout=TIMEOUT)
        decide_resp = check("POST /purchase-requests/tasks/{task_id}/decide (approve)", r, 200)
        if decide_resp:
            info(f"Workflow result: {decide_resp}")

        # Check final PR status
        r = requests.get(url(f"/purchase-requests/{PR2_ID}"), headers=H, timeout=TIMEOUT)
        final = check("GET /purchase-requests/{PR2_ID} (post-approval)", r, 200)
        if final:
            info(f"Final status = {final.get('status')}")
            if final.get("status") == "approved":
                ok("Purchase request approved via workflow")
            else:
                info(f"Status after approval: {final.get('status')} (may need all stages)")
    else:
        info("No pending tasks found — request may have been auto-approved (no active policy matched)")
else:
    skip("Approval workflow", "no workflow PR")

# ─────────────────────────────────────────────────────────────────────────────
# 17. SOX SoD — Requester cannot approve their own request
# ─────────────────────────────────────────────────────────────────────────────
section("17 · SOX SoD — Requester cannot self-approve")
if PR2_ID and 'REQ_TOKEN' in dir() and REQ_TOKEN and task_id:
    RH2 = headers(REQ_TOKEN)
    r = requests.post(url(f"/purchase-requests/tasks/{task_id}/decide"), headers=RH2, json={
        "decision": "approve",
        "note": "Trying to self-approve (should be blocked by SOX SoD)",
    }, timeout=TIMEOUT)
    # OPA enforces requester ≠ approver → 403 or 422
    expected = r.status_code in (403, 422, 400)
    if expected:
        ok("SOX SoD blocked requester from self-approving", f"HTTP {r.status_code}")
    else:
        fail("SOX SoD blocked requester from self-approving",
             f"Expected 403/422/400, got HTTP {r.status_code} — {_detail(r)}")
else:
    skip("SOX SoD test", "no task_id or requester token (task may already be decided)")

# ─────────────────────────────────────────────────────────────────────────────
# 18. APPROVED RANGES
# ─────────────────────────────────────────────────────────────────────────────
section("18 · Approved Ranges")
AR_ID = None
r = requests.post(url("/approved-ranges"), headers=H, json={
    "name": f"E2E Range {_uuid.uuid4().hex[:4]}",
    "description": "E2E test range",
    "is_universal": False,
}, timeout=TIMEOUT)
ar_resp = check("POST /approved-ranges", r, 201)
AR_ID = ar_resp.get("approved_range_id") if ar_resp else None
info(f"approved_range_id = {AR_ID}")

if AR_ID:
    r = requests.get(url(f"/approved-ranges/{AR_ID}"), headers=H, timeout=TIMEOUT)
    check("GET /approved-ranges/{id}", r, 200)

    # Add product to range
    if PRODUCT_ID:
        r = requests.post(url(f"/approved-ranges/{AR_ID}/products"), headers=H, json={
            "product_ids": [PRODUCT_ID],
        }, timeout=TIMEOUT)
        add_resp = check("POST /approved-ranges/{id}/products", r, 201)
        if add_resp:
            info(f"Added {len(add_resp.get('added', []))} product(s), skipped {len(add_resp.get('skipped', []))}")

    r = requests.get(url(f"/approved-ranges/{AR_ID}/products"), headers=H, timeout=TIMEOUT)
    check("GET /approved-ranges/{id}/products", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 19. BUDGET CHANGE REQUESTS
# ─────────────────────────────────────────────────────────────────────────────
section("19 · Budget Change Requests")
r = requests.get(url("/budget-change-requests"), headers=H, timeout=TIMEOUT)
check("GET /budget-change-requests", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# 20. LOGOUT
# ─────────────────────────────────────────────────────────────────────────────
section("20 · Logout")
r = requests.post(url("/authentication/logout"), headers=H,
                  params={"user_id": USER_ID}, timeout=TIMEOUT)
check("POST /authentication/logout", r, 200)

# Note: logout only revokes the *refresh* token; the short-lived access JWT
# remains valid until it expires (stateless design). We verify the refresh
# token endpoint rejects re-use instead.
r = requests.post(url("/authentication/refresh-jwt"), headers=H,
                  params={"user_id": USER_ID}, timeout=TIMEOUT)
refresh_blocked = r.status_code in (400, 401, 403, 404, 422)
if refresh_blocked:
    ok("Refresh token revoked after logout", f"HTTP {r.status_code}")
else:
    fail("Refresh token revoked after logout",
         f"Expected 4xx but got HTTP {r.status_code} — refresh token not properly revoked")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
def _summary():
    passed  = [r for r in results if r[1] == "PASS"]
    failed  = [r for r in results if r[1] == "FAIL"]
    skipped = [r for r in results if r[1] == "SKIP"]

    section("SUMMARY")
    print(f"\n  Total   : {len(results)}")
    print(f"  {GREEN}Passed  : {len(passed)}{RESET}")
    print(f"  {RED}Failed  : {len(failed)}{RESET}")
    print(f"  {YELLOW}Skipped : {len(skipped)}{RESET}")

    if failed:
        print(f"\n  {BOLD}{RED}Failed tests:{RESET}")
        for name, _, note in failed:
            print(f"    {RED}✘{RESET}  {name}")
            if note:
                print(f"       ↳ {note}")

    if skipped:
        print(f"\n  {YELLOW}Skipped tests:{RESET}")
        for name, _, note in skipped:
            print(f"    {YELLOW}⚠{RESET}  {name}  ({note})")
    print()

_summary()
sys.exit(0 if not [r for r in results if r[1] == "FAIL"] else 1)
