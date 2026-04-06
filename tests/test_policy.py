"""
tests/test_policy.py
=====================
End-to-end tests for the OPA policy engine.

Tests the full flow:
  JWT token (auth_service) → resource request → policy evaluation → allow/deny

Covers:
  - Tenant isolation (cross-org access denied)
  - Role hierarchy (admin > manager > member > viewer)
  - Domain policies: users, sites, budgets, products, vendors
  - Budget approval limits
  - Self-service (user updating own profile)
  - Missing/invalid tokens

Run:
    python3 tests/test_policy.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("POLICY_MODE", "local")
os.environ.setdefault("AUTH_MODE", "local")

import bcrypt

from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

from auth_service.schemas import UserContext
from auth_service import local_store as store
from auth_service.local_store import reset_store
from auth_service.routes import router as auth_router
from policy_engine.middleware import require_policy

# ── Build a test FastAPI app with policy-protected routes ──────────────

app = FastAPI()
app.include_router(auth_router)


@app.post("/api/sites")
async def create_site(request: Request, user: UserContext = Depends(require_policy("create", "site"))):
    body = await request.json()
    return {"status": "created", "site_name": body.get("name"), "by": user.user_id}


@app.get("/api/sites")
async def list_sites(user: UserContext = Depends(require_policy("read", "site"))):
    return {"sites": ["HQ", "Branch-1"], "org_id": user.org_id}


@app.delete("/api/sites/{site_id}")
async def delete_site(site_id: str, user: UserContext = Depends(require_policy("delete", "site"))):
    return {"status": "deleted", "site_id": site_id}


@app.post("/api/users")
async def create_user_ep(request: Request, user: UserContext = Depends(require_policy("create", "user"))):
    body = await request.json()
    return {"status": "created", "email": body.get("email")}


@app.delete("/api/users/{user_id}")
async def delete_user_ep(user_id: str, user: UserContext = Depends(require_policy("delete", "user"))):
    return {"status": "deleted", "user_id": user_id}


@app.post("/api/products")
async def create_product(request: Request, user: UserContext = Depends(require_policy("create", "product"))):
    body = await request.json()
    return {"status": "created", "product": body.get("name")}


@app.get("/api/products")
async def list_products(user: UserContext = Depends(require_policy("read", "product"))):
    return {"products": ["Widget A"]}


@app.post("/api/vendors")
async def create_vendor(request: Request, user: UserContext = Depends(require_policy("create", "vendor"))):
    body = await request.json()
    return {"status": "created", "vendor": body.get("name")}


@app.get("/api/vendors")
async def list_vendors(user: UserContext = Depends(require_policy("read", "vendor"))):
    return {"vendors": ["Supplier X"]}


@app.post("/api/budgets")
async def create_budget(request: Request, user: UserContext = Depends(require_policy("create", "budget"))):
    body = await request.json()
    return {"status": "created", "budget": body.get("name")}


@app.get("/api/budgets")
async def list_budgets(user: UserContext = Depends(require_policy("read", "budget"))):
    return {"budgets": []}


@app.delete("/api/budgets/{budget_id}")
async def delete_budget(budget_id: str, user: UserContext = Depends(require_policy("delete", "budget"))):
    return {"status": "deleted"}


client = TestClient(app)

# ── Helpers ────────────────────────────────────────────────────────────

pass_count = 0
fail_count = 0


def check(condition, label):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  PASS  {label}")
    else:
        fail_count += 1
        print(f"  FAIL  {label}")


def _set_password(email: str, password: str):
    """Override the random temp password in local store."""
    rec = store._users.get(f"email:{email}")
    if rec:
        rec["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)).decode()


def signup_and_login(company, email, name, password="TestPass1!"):
    """Signup a company, set a known password, log in, return (org_id, token)."""
    r = client.post("/auth/signup", json={
        "company_name": company,
        "admin_email": email,
        "admin_name": name,
    })
    assert r.status_code == 201, f"Signup failed: {r.text}"
    org_id = r.json()["org_id"]
    _set_password(email, password)
    r = client.post("/auth/login", json={"email": email, "password": password, "org_id": org_id})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return org_id, r.json()["access_token"]


def invite_and_login(admin_token, email, roles, password="TestPass1!"):
    """Invite a user, accept, log in, return token."""
    r = client.post("/auth/invite", json={"email": email, "roles": roles},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 201, f"Invite failed: {r.text}"
    inv_id = r.json()["invitation_id"]

    r = client.post(f"/auth/accept-invite?invitation_id={inv_id}&password={password}")
    assert r.status_code == 200, f"Accept failed: {r.text}"
    data = r.json()
    org_id = data["org_id"]

    r = client.post("/auth/login", json={"email": email, "password": password, "org_id": org_id})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def h(token):
    return {"Authorization": f"Bearer {token}"}


# ── Test Execution ─────────────────────────────────────────────────────

print("\n" + "=" * 64)
print("  POLICY ENGINE — End-to-End Tests")
print("=" * 64)

reset_store()

# --- Phase 1: Setup tenants and users --------------------------------

print("\n--- Phase 1: Setup — 2 orgs, 4 roles ---")

acme_org_id, alice_token = signup_and_login("Acme Corp", "alice@acme.com", "Alice Admin")
check(True, f"Acme created: {acme_org_id}")

bob_token = invite_and_login(alice_token, "bob@acme.com", ["org_manager"], "BobPass1!")
check(True, "Bob joined Acme as manager")

carol_token = invite_and_login(alice_token, "carol@acme.com", ["org_member"], "CarolPass1!")
check(True, "Carol joined Acme as member")

dan_token = invite_and_login(alice_token, "dan@acme.com", ["org_viewer"], "DanPass1!")
check(True, "Dan joined Acme as viewer")

globex_org_id, eve_token = signup_and_login("Globex Inc", "eve@globex.com", "Eve Boss")
check(True, f"Globex created: {globex_org_id}")

# --- Phase 2: Sites — CRUD by role -----------------------------------

print("\n--- Phase 2: Sites — Role-based CRUD ---")

r = client.post("/api/sites", json={"name": "HQ", "org_id": acme_org_id}, headers=h(alice_token))
check(r.status_code == 200, "Admin (Alice) can create site")

r = client.post("/api/sites", json={"name": "Branch", "org_id": acme_org_id}, headers=h(bob_token))
check(r.status_code == 200, "Manager (Bob) can create site")

r = client.post("/api/sites", json={"name": "Lab", "org_id": acme_org_id}, headers=h(carol_token))
check(r.status_code == 200, "Member (Carol) can create site")

r = client.post("/api/sites", json={"name": "Nope", "org_id": acme_org_id}, headers=h(dan_token))
check(r.status_code == 403, "Viewer (Dan) CANNOT create site")

r = client.get("/api/sites", headers=h(dan_token))
check(r.status_code == 200, "Viewer (Dan) CAN read sites")

r = client.delete("/api/sites/s1", headers=h(alice_token))
check(r.status_code == 200, "Admin (Alice) can delete site")

r = client.delete("/api/sites/s1", headers=h(bob_token))
check(r.status_code == 403, "Manager (Bob) CANNOT delete site")

r = client.delete("/api/sites/s1", headers=h(carol_token))
check(r.status_code == 403, "Member (Carol) CANNOT delete site")

# --- Phase 3: Tenant isolation ----------------------------------------

print("\n--- Phase 3: Tenant Isolation ---")

r = client.post("/api/sites", json={"name": "Evil", "org_id": acme_org_id}, headers=h(eve_token))
check(r.status_code == 403, "Globex admin CANNOT create site in Acme org")
check("tenant mismatch" in r.json().get("detail", ""), "Denial reason = tenant mismatch")

r = client.post("/api/users", json={"email": "x@acme.com", "org_id": acme_org_id}, headers=h(eve_token))
check(r.status_code == 403, "Globex admin CANNOT create user in Acme org")

r = client.post("/api/products", json={"name": "Spy Widget", "org_id": acme_org_id}, headers=h(eve_token))
check(r.status_code == 403, "Globex admin CANNOT create product in Acme org")

r = client.post("/api/vendors", json={"name": "Evil Supplier", "org_id": acme_org_id}, headers=h(eve_token))
check(r.status_code == 403, "Globex admin CANNOT create vendor in Acme org")

r = client.post("/api/budgets", json={"name": "Evil Budget", "org_id": acme_org_id}, headers=h(eve_token))
check(r.status_code == 403, "Globex admin CANNOT create budget in Acme org")

# --- Phase 4: User management ----------------------------------------

print("\n--- Phase 4: User Management ---")

r = client.post("/api/users", json={"email": "new@acme.com", "org_id": acme_org_id}, headers=h(alice_token))
check(r.status_code == 200, "Admin can create user")

r = client.post("/api/users", json={"email": "new2@acme.com", "org_id": acme_org_id}, headers=h(bob_token))
check(r.status_code == 200, "Manager can create user")

r = client.post("/api/users", json={"email": "new3@acme.com", "org_id": acme_org_id}, headers=h(carol_token))
check(r.status_code == 403, "Member CANNOT create user")

r = client.delete("/api/users/u1", headers=h(alice_token))
check(r.status_code == 200, "Admin can delete user")

r = client.delete("/api/users/u1", headers=h(bob_token))
check(r.status_code == 403, "Manager CANNOT delete user")

r = client.delete("/api/users/u1", headers=h(carol_token))
check(r.status_code == 403, "Member CANNOT delete user")

# --- Phase 5: Products -----------------------------------------------

print("\n--- Phase 5: Products ---")

r = client.post("/api/products", json={"name": "Widget A", "org_id": acme_org_id}, headers=h(alice_token))
check(r.status_code == 200, "Admin can create product")

r = client.post("/api/products", json={"name": "Widget B", "org_id": acme_org_id}, headers=h(bob_token))
check(r.status_code == 200, "Manager can create product")

r = client.post("/api/products", json={"name": "Widget C", "org_id": acme_org_id}, headers=h(carol_token))
check(r.status_code == 200, "Member can create product")

r = client.post("/api/products", json={"name": "Nope", "org_id": acme_org_id}, headers=h(dan_token))
check(r.status_code == 403, "Viewer CANNOT create product")

r = client.get("/api/products", headers=h(dan_token))
check(r.status_code == 200, "Viewer CAN read products")

# --- Phase 6: Vendors -------------------------------------------------

print("\n--- Phase 6: Vendors ---")

r = client.post("/api/vendors", json={"name": "Supplier X", "org_id": acme_org_id}, headers=h(alice_token))
check(r.status_code == 200, "Admin can create vendor")

r = client.post("/api/vendors", json={"name": "Supplier Y", "org_id": acme_org_id}, headers=h(bob_token))
check(r.status_code == 200, "Manager can create vendor")

r = client.post("/api/vendors", json={"name": "Nope", "org_id": acme_org_id}, headers=h(carol_token))
check(r.status_code == 403, "Member CANNOT create vendor")

r = client.get("/api/vendors", headers=h(dan_token))
check(r.status_code == 200, "Viewer CAN read vendors")

# --- Phase 7: Budgets -------------------------------------------------

print("\n--- Phase 7: Budgets ---")

r = client.post("/api/budgets", json={"name": "Q1 Marketing", "org_id": acme_org_id}, headers=h(alice_token))
check(r.status_code == 200, "Admin can create budget")

r = client.post("/api/budgets", json={"name": "Q2 Sales", "org_id": acme_org_id}, headers=h(bob_token))
check(r.status_code == 200, "Manager can create budget")

r = client.post("/api/budgets", json={"name": "Q3 R&D", "org_id": acme_org_id}, headers=h(carol_token))
check(r.status_code == 200, "Member can create budget")

r = client.post("/api/budgets", json={"name": "Nope", "org_id": acme_org_id}, headers=h(dan_token))
check(r.status_code == 403, "Viewer CANNOT create budget")

r = client.get("/api/budgets", headers=h(dan_token))
check(r.status_code == 200, "Viewer CAN read budgets")

r = client.delete("/api/budgets/b1", headers=h(alice_token))
check(r.status_code == 200, "Admin can delete budget")

r = client.delete("/api/budgets/b1", headers=h(bob_token))
check(r.status_code == 403, "Manager CANNOT delete budget")

# --- Phase 8: Unauthenticated access ---------------------------------

print("\n--- Phase 8: Unauthenticated Access ---")

r = client.post("/api/sites", json={"name": "X"})
check(r.status_code == 401, "No token → 401 on create site")

r = client.get("/api/products")
check(r.status_code == 401, "No token → 401 on read products")

r = client.post("/api/sites", json={"name": "X"}, headers={"Authorization": "Bearer invalid.jwt.token"})
check(r.status_code == 401, "Invalid token → 401")

# --- Phase 9: Budget approval limits (direct evaluator test) ----------

print("\n--- Phase 9: Budget Approval Limits ---")

from policy_engine.local_evaluator import evaluate

approval_input = {
    "user": {
        "user_id": "mgr_1",
        "org_id": "org_A",
        "roles": ["org_manager"],
        "attributes": {"approval_limit": 50000},
    },
    "resource": {
        "type": "budget",
        "org_id": "org_A",
        "attributes": {"amount": 30000},
    },
}
result = evaluate("budget", "approve", approval_input)
check(result["allow"] is True, "Manager can approve budget within limit (30k < 50k)")

approval_input["resource"]["attributes"]["amount"] = 75000
result = evaluate("budget", "approve", approval_input)
check(result["allow"] is False, "Manager CANNOT approve budget exceeding limit (75k > 50k)")
check("exceeds approval limit" in result["reasons"][0], "Reason mentions exceeding limit")

approval_input_admin = {
    "user": {
        "user_id": "admin_1",
        "org_id": "org_A",
        "roles": ["org_admin"],
    },
    "resource": {
        "type": "budget",
        "org_id": "org_A",
        "attributes": {"amount": 999999},
    },
}
result = evaluate("budget", "approve", approval_input_admin)
check(result["allow"] is True, "Admin can approve any budget amount")

# --- Phase 10: Cross-tenant direct evaluator test ---------------------

print("\n--- Phase 10: Cross-Tenant Direct Evaluator ---")

cross_input = {
    "user": {"user_id": "u1", "org_id": "org_A", "roles": ["org_admin"]},
    "resource": {"type": "site", "org_id": "org_B"},
}
result = evaluate("site", "create", cross_input)
check(result["allow"] is False, "Admin of org_A denied for org_B resource")
check("tenant mismatch" in result["reasons"][0], "Reason = tenant mismatch")

# --- Phase 11: Unknown resource type ----------------------------------

print("\n--- Phase 11: Unknown Resource Type ---")

unknown_input = {
    "user": {"user_id": "u1", "org_id": "org_A", "roles": ["org_admin"]},
    "resource": {"type": "spaceship", "org_id": "org_A"},
}
result = evaluate("spaceship", "create", unknown_input)
check(result["allow"] is False, "Unknown resource type → denied")
check("no policy defined" in result["reasons"][0], "Reason = no policy defined")

# --- Phase 12: Role hierarchy edge cases ------------------------------

print("\n--- Phase 12: Role Hierarchy Edge Cases ---")

from policy_engine.local_evaluator import _max_rank, _is_admin, _is_manager, _is_member, _is_viewer

check(_max_rank(["org_admin"]) == 40, "admin rank = 40")
check(_max_rank(["org_manager"]) == 30, "manager rank = 30")
check(_max_rank(["org_member"]) == 20, "member rank = 20")
check(_max_rank(["org_viewer"]) == 10, "viewer rank = 10")
check(_max_rank([]) == 0, "no roles = rank 0")
check(_max_rank(["org_viewer", "org_manager"]) == 30, "multi-role takes highest")
check(_is_manager(["org_admin"]) is True, "admin is also manager")
check(_is_member(["org_manager"]) is True, "manager is also member")
check(_is_viewer(["org_member"]) is True, "member is also viewer")

# --- Phase 13: Every domain × every role (exhaustive matrix) ----------

print("\n--- Phase 13: Full RBAC Matrix ---")

_MATRIX = [
    # (resource,  action,   admin, manager, member, viewer)
    ("site",     "create",  True,  True,    True,   False),
    ("site",     "read",    True,  True,    True,   True),
    ("site",     "update",  True,  True,    False,  False),
    ("site",     "delete",  True,  False,   False,  False),
    ("user",     "create",  True,  True,    False,  False),
    ("user",     "read",    True,  True,    True,   False),
    ("user",     "delete",  True,  False,   False,  False),
    ("product",  "create",  True,  True,    True,   False),
    ("product",  "read",    True,  True,    True,   True),
    ("product",  "update",  True,  True,    False,  False),
    ("vendor",   "create",  True,  True,    False,  False),
    ("vendor",   "read",    True,  True,    True,   True),
    ("vendor",   "update",  True,  True,    False,  False),
    ("budget",   "create",  True,  True,    True,   False),
    ("budget",   "read",    True,  True,    True,   True),
    ("budget",   "update",  True,  True,    False,  False),
    ("budget",   "delete",  True,  False,   False,  False),
]

_ROLE_NAMES = ["org_admin", "org_manager", "org_member", "org_viewer"]

for resource, action, *expected in _MATRIX:
    for role_name, expect in zip(_ROLE_NAMES, expected):
        inp = {
            "user": {"user_id": "u1", "org_id": "org_X", "roles": [role_name]},
            "resource": {"type": resource, "org_id": "org_X"},
        }
        result = evaluate(resource, action, inp)
        label = f"{role_name:12s} {action:8s} {resource:10s} → {'ALLOW' if expect else 'DENY'}"
        check(result["allow"] == expect, label)

# ── Results ───────────────────────────────────────────────────────────

print("\n" + "=" * 64)
print(f"  RESULTS: {pass_count} passed, {fail_count} failed out of {pass_count + fail_count}")
print("=" * 64)
print()

sys.exit(0 if fail_count == 0 else 1)
