"""
test_api.py — Comprehensive API test runner for the Provisioning Service
Usage:  python test_api.py
Requires: pip install requests
"""

import sys
import json
import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
BASE_URL  = "http://localhost:8000"
EMAIL     = "sebinsanthosh2016@gmail.com"
PASSWORD  = "SecurePass1"
TIMEOUT   = 10

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
PASS  = "\033[92m✔ PASS\033[0m"
FAIL  = "\033[91m✘ FAIL\033[0m"
SKIP  = "\033[93m⚠ SKIP\033[0m"
INFO  = "\033[94mℹ INFO\033[0m"

results = []   # (name, status, note)

def check(name, resp, expected_status, *, extract=None):
    """Assert HTTP status, optionally extract a value from JSON response."""
    ok = resp.status_code == expected_status
    note = f"HTTP {resp.status_code}"
    if not ok:
        try:
            body = resp.json()
            note += f" — {body.get('detail', body)}"
        except Exception:
            note += f" — {resp.text[:120]}"
    tag = PASS if ok else FAIL
    print(f"  {tag}  {name}  ({note})")
    results.append((name, "PASS" if ok else "FAIL", note))

    if ok and extract:
        try:
            data = resp.json()
            for key in extract.split("."):
                data = data[key]
            return data
        except Exception:
            return None
    return None


def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def info(msg):
    print(f"  {INFO}  {msg}")


def skip(name, reason=""):
    print(f"  {SKIP}  {name}  ({reason})")
    results.append((name, "SKIP", reason))


def url(path):
    return f"{BASE_URL}{path}"


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — reachability
# ─────────────────────────────────────────────────────────────────────────────
section("0 · Health check")
try:
    r = requests.get(url("/health"), timeout=TIMEOUT)
    check("GET /health", r, 200)
except requests.exceptions.ConnectionError:
    print(f"\n  {FAIL}  Cannot reach {BASE_URL}. Is the server running?")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — public endpoints (no auth)
# ─────────────────────────────────────────────────────────────────────────────
section("1 · Public endpoints")

r = requests.get(url("/plans/"), timeout=TIMEOUT)
check("GET /plans/", r, 200)

r = requests.get(url("/provisioning/tenants"), timeout=TIMEOUT)
check("GET /provisioning/tenants", r, 200)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — login
# ─────────────────────────────────────────────────────────────────────────────
section("2 · Authentication — Login")

r = requests.post(url("/onboarding/tenant-signin"), json={
    "email": EMAIL,
    "password": PASSWORD,
}, timeout=TIMEOUT)
check("POST /onboarding/tenant-signin", r, 200)

token       = None
tenant_id   = None
user_id     = None
refresh_tok = None

if r.status_code == 200:
    body        = r.json()
    token       = body.get("token")
    tenant_id   = body.get("tenant_id")
    user_id     = body.get("user_id")
    refresh_tok = body.get("refresh_token")
    info(f"Logged in as {body.get('email')}  tenant={tenant_id}  user={user_id}")
    info(f"Token obtained: {'yes' if token else 'NO — subsequent tests will fail'}")
else:
    info("Login failed — auth-protected tests will be skipped")

H = auth_headers(token) if token else {}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — authentication routes
# ─────────────────────────────────────────────────────────────────────────────
section("3 · Authentication routes")

if token:
    r = requests.get(url("/authentication/whoami"), headers=H, timeout=TIMEOUT)
    check("GET /authentication/whoami", r, 200)

    r = requests.get(url("/authentication/healthcheck"), headers=H, timeout=TIMEOUT)
    check("GET /authentication/healthcheck", r, 200)

    if refresh_tok and user_id:
        r = requests.post(url("/authentication/refresh-jwt"), json={
            "user_id": user_id,
            "refresh_token": refresh_tok,
        }, timeout=TIMEOUT)
        check("POST /authentication/refresh-jwt", r, 200)
        if r.status_code == 200:
            new_body    = r.json()
            token       = new_body.get("token", token)   # keep newest token
            refresh_tok = new_body.get("refresh_token", refresh_tok)
            H           = auth_headers(token)
            info("Token rotated via refresh-jwt")
    else:
        skip("POST /authentication/refresh-jwt", "no refresh_token returned at login")

    # forgot password — always returns 200 regardless of email
    r = requests.post(url("/authentication/forgot-password"), json={"email": EMAIL}, timeout=TIMEOUT)
    check("POST /authentication/forgot-password (email exists)", r, 200)

    r = requests.post(url("/authentication/forgot-password"), json={"email": "nobody@example.com"}, timeout=TIMEOUT)
    check("POST /authentication/forgot-password (unknown email)", r, 200)

    # reset-password with wrong current password → 401
    r = requests.post(
        url("/authentication/reset-password"),
        params={"user_id": user_id},
        json={"current_password": "WrongPass99", "new_password": "NewSecure2"},
        headers=H,
        timeout=TIMEOUT,
    )
    check("POST /authentication/reset-password (wrong current pw → 401)", r, 401)

    # reset-password/confirm with invalid token → 400
    r = requests.post(url("/authentication/reset-password/confirm"), json={
        "token": "invalid.token.here",
        "new_password": "NewSecure2",
    }, timeout=TIMEOUT)
    check("POST /authentication/reset-password/confirm (bad token → 400)", r, 400)

else:
    for name in [
        "GET /authentication/whoami",
        "GET /authentication/healthcheck",
        "POST /authentication/refresh-jwt",
        "POST /authentication/forgot-password (email exists)",
        "POST /authentication/forgot-password (unknown email)",
        "POST /authentication/reset-password (wrong current pw → 401)",
        "POST /authentication/reset-password/confirm (bad token → 400)",
    ]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — subscriptions
# ─────────────────────────────────────────────────────────────────────────────
section("4 · Subscriptions")

if tenant_id:
    r = requests.get(url("/subscriptions/active"), params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /subscriptions/active", r, 200)
else:
    skip("GET /subscriptions/active", "no tenant_id")

if token:
    r = requests.get(url("/subscriptions/whoami"), headers=H, timeout=TIMEOUT)
    check("GET /subscriptions/whoami", r, 200)
else:
    skip("GET /subscriptions/whoami", "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — provisioning (tenants, sites, stores, users, vendors, cost centres,
#           org units, roles)
# ─────────────────────────────────────────────────────────────────────────────
section("5 · Provisioning — Tenants")

r = requests.get(url("/provisioning/tenants"), timeout=TIMEOUT)
check("GET /provisioning/tenants", r, 200)

if tenant_id:
    r = requests.get(url(f"/provisioning/tenants/{tenant_id}"), timeout=TIMEOUT)
    check("GET /provisioning/tenants/{tenant_id}", r, 200)
else:
    skip("GET /provisioning/tenants/{tenant_id}", "no tenant_id")

if token:
    # --- Sites ---
    section("5a · Provisioning — Sites")
    r = requests.get(url("/provisioning/sites"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/sites", r, 200)
    # Try to grab first site_id for detail test
    site_id = None
    if r.status_code == 200:
        sites = r.json().get("sites", [])
        if sites:
            site_id = sites[0].get("site_id")
    if site_id:
        r2 = requests.get(url(f"/provisioning/sites/{site_id}"), headers=H, timeout=TIMEOUT)
        check("GET /provisioning/sites/{site_id}", r2, 200)
    else:
        skip("GET /provisioning/sites/{site_id}", "no sites found")

    # --- Stores ---
    section("5b · Provisioning — Stores")
    r = requests.get(url("/provisioning/stores"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/stores", r, 200)
    store_id = None
    if r.status_code == 200:
        stores = r.json().get("stores", [])
        if stores:
            store_id = stores[0].get("store_id")
    if store_id:
        r2 = requests.get(url(f"/provisioning/stores/{store_id}"), headers=H, timeout=TIMEOUT)
        check("GET /provisioning/stores/{store_id}", r2, 200)
    else:
        skip("GET /provisioning/stores/{store_id}", "no stores found")

    # --- Users ---
    section("5c · Provisioning — Users")
    r = requests.get(url("/provisioning/users"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/users", r, 200)
    other_user_id = None
    if r.status_code == 200:
        users = r.json().get("users", [])
        if users:
            other_user_id = users[0].get("user_id")
    if other_user_id:
        r2 = requests.get(url(f"/provisioning/users/{other_user_id}"), headers=H, timeout=TIMEOUT)
        check("GET /provisioning/users/{user_id}", r2, 200)
    else:
        skip("GET /provisioning/users/{user_id}", "no users found")

    # --- Vendors ---
    section("5d · Provisioning — Vendors")
    r = requests.get(url("/provisioning/vendors"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/vendors", r, 200)
    vendor_id = None
    if r.status_code == 200:
        vendors = r.json().get("vendors", [])
        if vendors:
            vendor_id = vendors[0].get("vendor_id")
    if vendor_id:
        r2 = requests.get(url(f"/provisioning/vendors/{vendor_id}"), headers=H, timeout=TIMEOUT)
        check("GET /provisioning/vendors/{vendor_id}", r2, 200)
    else:
        skip("GET /provisioning/vendors/{vendor_id}", "no vendors found")

    # --- Cost Centres ---
    section("5e · Provisioning — Cost Centres")
    r = requests.get(url("/provisioning/cost-centres"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/cost-centres", r, 200)
    cc_id = None
    if r.status_code == 200:
        ccs = r.json().get("cost_centres", [])
        if ccs:
            cc_id = ccs[0].get("cost_centre_id")
    if cc_id:
        r2 = requests.get(url(f"/provisioning/cost-centres/{cc_id}"), headers=H, timeout=TIMEOUT)
        check("GET /provisioning/cost-centres/{cc_id}", r2, 200)
    else:
        skip("GET /provisioning/cost-centres/{cc_id}", "no cost centres found")

    # --- Org Units ---
    section("5f · Provisioning — Org Units")
    r = requests.get(url("/provisioning/org-units"), headers=H, params={"tenant_id": tenant_id}, timeout=TIMEOUT)
    check("GET /provisioning/org-units", r, 200)

    # --- Roles ---
    section("5g · Provisioning — Roles")
    r = requests.get(url("/provisioning/roles"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/roles", r, 200)

    r = requests.get(url("/provisioning/tenant-roles"), headers=H, timeout=TIMEOUT)
    check("GET /provisioning/tenant-roles", r, 200)

else:
    for name in ["GET /provisioning/sites", "GET /provisioning/stores",
                 "GET /provisioning/users", "GET /provisioning/vendors",
                 "GET /provisioning/cost-centres", "GET /provisioning/org-units",
                 "GET /provisioning/roles", "GET /provisioning/tenant-roles"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — catalog
# ─────────────────────────────────────────────────────────────────────────────
section("6 · Catalog")

if token:
    r = requests.get(url("/catalog/categories"), headers=H, timeout=TIMEOUT)
    check("GET /catalog/categories", r, 200)

    r = requests.get(url("/catalog/products"), headers=H, timeout=TIMEOUT)
    check("GET /catalog/products", r, 200)
    product_id = None
    if r.status_code == 200:
        prods = r.json().get("products", [])
        if prods:
            product_id = prods[0].get("product_id")

    r = requests.get(url("/catalog/store-products"), headers=H, timeout=TIMEOUT)
    check("GET /catalog/store-products", r, 200)

    if store_id:
        r = requests.get(url(f"/catalog/stores/{store_id}/products"), headers=H, timeout=TIMEOUT)
        check("GET /catalog/stores/{store_id}/products", r, 200)
    else:
        skip("GET /catalog/stores/{store_id}/products", "no store_id")

    # Duplicate SKU → 409
    r = requests.post(url("/catalog/categories"), headers=H, json={
        "tenant_id": tenant_id,
        "name": "Test Category",
        "code": "TEST_CAT_DUPE",
    }, timeout=TIMEOUT)
    first_cat = r.status_code
    r2 = requests.post(url("/catalog/categories"), headers=H, json={
        "tenant_id": tenant_id,
        "name": "Test Category Dupe",
        "code": "TEST_CAT_DUPE",
    }, timeout=TIMEOUT)
    if first_cat == 201:
        check("POST /catalog/categories (duplicate code → 409)", r2, 409)
    else:
        # code already existed, second call would also be 409
        check("POST /catalog/categories (duplicate code → 409)", r2, 409)

else:
    for name in ["GET /catalog/categories", "GET /catalog/products",
                 "GET /catalog/store-products",
                 "GET /catalog/stores/{store_id}/products",
                 "POST /catalog/categories (duplicate code → 409)"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — financial calendars
# ─────────────────────────────────────────────────────────────────────────────
section("7 · Financial Calendars")

if token:
    r = requests.get(url("/financial-calendars"), headers=H, timeout=TIMEOUT)
    check("GET /financial-calendars", r, 200)
    calendar_id = None
    year_id     = None
    if r.status_code == 200:
        cals = r.json().get("calendars", [])
        if cals:
            calendar_id = cals[0].get("calendar_id")

    if calendar_id:
        r = requests.get(url(f"/financial-calendars/{calendar_id}"), headers=H, timeout=TIMEOUT)
        check("GET /financial-calendars/{calendar_id}", r, 200)

        r = requests.get(url(f"/financial-calendars/{calendar_id}/years"), headers=H, timeout=TIMEOUT)
        check("GET /financial-calendars/{calendar_id}/years", r, 200)
        if r.status_code == 200:
            years = r.json().get("years", [])
            if years:
                year_id = years[0].get("year_id")

        if year_id:
            r = requests.get(url(f"/financial-calendars/{calendar_id}/years/{year_id}/periods"),
                             headers=H, timeout=TIMEOUT)
            check("GET /financial-calendars/{calendar_id}/years/{year_id}/periods", r, 200)
        else:
            skip("GET .../years/{year_id}/periods", "no year found")
    else:
        skip("GET /financial-calendars/{calendar_id}", "no calendars found")
        skip("GET /financial-calendars/{calendar_id}/years", "no calendars found")
        skip("GET .../years/{year_id}/periods", "no calendars found")
else:
    for name in ["GET /financial-calendars", "GET /financial-calendars/{id}",
                 "GET /financial-calendars/{id}/years", "GET .../years/{id}/periods"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — budgets
# ─────────────────────────────────────────────────────────────────────────────
section("8 · Budgets")

if token:
    r = requests.get(url("/budgets/company-caps"), headers=H, timeout=TIMEOUT)
    check("GET /budgets/company-caps", r, 200)

    r = requests.get(url("/budgets/cc-versions"), headers=H, timeout=TIMEOUT)
    check("GET /budgets/cc-versions", r, 200)
    budget_version_id = None
    if r.status_code == 200:
        versions = r.json().get("versions", [])
        if versions:
            budget_version_id = versions[0].get("version_id")

    if budget_version_id:
        r = requests.get(url(f"/budgets/cc-versions/{budget_version_id}"), headers=H, timeout=TIMEOUT)
        check("GET /budgets/cc-versions/{version_id}", r, 200)
    else:
        skip("GET /budgets/cc-versions/{version_id}", "no CC budget versions found")

    r = requests.get(url("/budgets/transactions"), headers=H, timeout=TIMEOUT)
    check("GET /budgets/transactions", r, 200)
else:
    for name in ["GET /budgets/company-caps", "GET /budgets/cc-versions",
                 "GET /budgets/cc-versions/{version_id}", "GET /budgets/transactions"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — user budgets
# ─────────────────────────────────────────────────────────────────────────────
section("9 · User Budgets")

if token:
    r = requests.get(url("/user-budgets/cc-assignments"), headers=H, timeout=TIMEOUT)
    check("GET /user-budgets/cc-assignments", r, 200)

    r = requests.get(url("/user-budgets/limits"), headers=H, timeout=TIMEOUT)
    check("GET /user-budgets/limits", r, 200)
else:
    for name in ["GET /user-budgets/cc-assignments", "GET /user-budgets/limits"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 — approval policies
# ─────────────────────────────────────────────────────────────────────────────
section("10 · Approval Policies")

if token:
    r = requests.get(url("/approval-policies"), headers=H, timeout=TIMEOUT)
    check("GET /approval-policies", r, 200)
else:
    skip("GET /approval-policies", "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — approved ranges
# ─────────────────────────────────────────────────────────────────────────────
section("11 · Approved Ranges")

if token:
    r = requests.get(url("/approved-ranges"), headers=H, timeout=TIMEOUT)
    check("GET /approved-ranges", r, 200)
    approved_range_id = None
    if r.status_code == 200:
        ars = r.json().get("approved_ranges", [])
        if ars:
            approved_range_id = ars[0].get("approved_range_id")

    if approved_range_id:
        r = requests.get(url(f"/approved-ranges/{approved_range_id}"), headers=H, timeout=TIMEOUT)
        check("GET /approved-ranges/{id}", r, 200)

        r = requests.get(url(f"/approved-ranges/{approved_range_id}/org-units"), headers=H, timeout=TIMEOUT)
        check("GET /approved-ranges/{id}/org-units", r, 200)

        r = requests.get(url(f"/approved-ranges/{approved_range_id}/products"), headers=H, timeout=TIMEOUT)
        check("GET /approved-ranges/{id}/products", r, 200)
    else:
        skip("GET /approved-ranges/{id}", "no approved ranges found")
        skip("GET /approved-ranges/{id}/org-units", "no approved ranges found")
        skip("GET /approved-ranges/{id}/products", "no approved ranges found")
else:
    for name in ["GET /approved-ranges", "GET /approved-ranges/{id}",
                 "GET /approved-ranges/{id}/org-units", "GET /approved-ranges/{id}/products"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 12 — purchase requests
# ─────────────────────────────────────────────────────────────────────────────
section("12 · Purchase Requests")

if token:
    r = requests.get(url("/purchase-requests"), headers=H, timeout=TIMEOUT)
    check("GET /purchase-requests", r, 200)
    pr_id = None
    if r.status_code == 200:
        prs = r.json().get("requests", [])
        if prs:
            pr_id = prs[0].get("request_id")

    r = requests.get(url("/purchase-requests/my-tasks"), headers=H, timeout=TIMEOUT)
    check("GET /purchase-requests/my-tasks", r, 200)

    if pr_id:
        r = requests.get(url(f"/purchase-requests/{pr_id}"), headers=H, timeout=TIMEOUT)
        check("GET /purchase-requests/{request_id}", r, 200)
    else:
        skip("GET /purchase-requests/{request_id}", "no purchase requests found")
else:
    for name in ["GET /purchase-requests", "GET /purchase-requests/my-tasks",
                 "GET /purchase-requests/{request_id}"]:
        skip(name, "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 13 — budget change requests
# ─────────────────────────────────────────────────────────────────────────────
section("13 · Budget Change Requests")

if token:
    r = requests.get(url("/budget-change-requests"), headers=H, timeout=TIMEOUT)
    check("GET /budget-change-requests", r, 200)
else:
    skip("GET /budget-change-requests", "no token")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 14 — onboarding: OTP (negative paths, no real email needed)
# ─────────────────────────────────────────────────────────────────────────────
section("14 · Onboarding — OTP flows")

# validate OTP that was never generated → 404
r = requests.post(url("/onboarding/otp/validate"), json={
    "email": "ghost_user_9999@example.com",
    "otp": "000000",
}, timeout=TIMEOUT)
check("POST /onboarding/otp/validate (no OTP stored → 404)", r, 404)

# generate OTP for email that ALREADY has a tenant → 404 (user exists)
r = requests.post(url("/onboarding/otp/generate"), json={"email": EMAIL}, timeout=TIMEOUT)
check("POST /onboarding/otp/generate (email already tenant → 404)", r, 404)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 15 — input validation errors
# ─────────────────────────────────────────────────────────────────────────────
section("15 · Input validation")

# Login with wrong password → 401
r = requests.post(url("/onboarding/tenant-signin"), json={
    "email": EMAIL,
    "password": "WrongPassword1",
}, timeout=TIMEOUT)
check("POST /onboarding/tenant-signin (wrong password → 401)", r, 401)

# Login with non-existent email → 401
r = requests.post(url("/onboarding/tenant-signin"), json={
    "email": "noone@nowhere.com",
    "password": "AnyPass123",
}, timeout=TIMEOUT)
check("POST /onboarding/tenant-signin (unknown email → 401)", r, 401)

# Tenant-signup with invalid type → 422
r = requests.post(url("/onboarding/tenant-signup"), json={
    "email": "new_test@example.com",
    "admin_email": "admin@example.com",
    "admin_firstname": "Test",
    "admin_lastname": "User",
    "password": "ValidPass1",
    "type": "invalid_type",
}, timeout=TIMEOUT)
check("POST /onboarding/tenant-signup (bad type → 422)", r, 422)

# Weak password → 422
r = requests.post(url("/onboarding/tenant-signup"), json={
    "email": "new_test@example.com",
    "admin_email": "admin@example.com",
    "admin_firstname": "Test",
    "admin_lastname": "User",
    "password": "weak",
    "type": "retailer",
}, timeout=TIMEOUT)
check("POST /onboarding/tenant-signup (weak password → 422)", r, 422)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 16 — unauthenticated access to protected routes → 401/403
# ─────────────────────────────────────────────────────────────────────────────
section("16 · Unauthenticated access (no token)")

NO_TOKEN = {}  # empty headers

for path, method in [
    ("/authentication/whoami", "GET"),
    ("/catalog/categories", "GET"),
    ("/catalog/products", "GET"),
    ("/purchase-requests", "GET"),
    ("/budgets/company-caps", "GET"),
    ("/financial-calendars", "GET"),
    ("/approved-ranges", "GET"),
]:
    fn = requests.get if method == "GET" else requests.post
    r = fn(url(path), headers=NO_TOKEN, timeout=TIMEOUT)
    expected = r.status_code in (401, 403, 422)
    tag = PASS if expected else FAIL
    note = f"HTTP {r.status_code}"
    label = f"{method} {path} (no token → 401/403)"
    print(f"  {tag}  {label}  ({note})")
    results.append((label, "PASS" if expected else "FAIL", note))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 17 — logout (last, so we don't lose the token early)
# ─────────────────────────────────────────────────────────────────────────────
section("17 · Logout")

if token and user_id:
    r = requests.post(url("/authentication/logout"), params={"user_id": user_id},
                      headers=H, timeout=TIMEOUT)
    check("POST /authentication/logout", r, 200)
else:
    skip("POST /authentication/logout", "no token/user_id")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
section("SUMMARY")

passed  = [r for r in results if r[1] == "PASS"]
failed  = [r for r in results if r[1] == "FAIL"]
skipped = [r for r in results if r[1] == "SKIP"]

print(f"\n  Total : {len(results)}")
print(f"  \033[92mPassed: {len(passed)}\033[0m")
print(f"  \033[91mFailed: {len(failed)}\033[0m")
print(f"  \033[93mSkipped: {len(skipped)}\033[0m")

if failed:
    print("\n  Failed tests:")
    for name, _, note in failed:
        print(f"    \033[91m✘\033[0m  {name}")
        print(f"       ↳ {note}")

if skipped:
    print("\n  Skipped tests:")
    for name, _, note in skipped:
        print(f"    \033[93m⚠\033[0m  {name}  ({note})")

print()
sys.exit(0 if not failed else 1)
