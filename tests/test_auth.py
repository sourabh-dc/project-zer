"""
Auth Service — Comprehensive E2E Test
======================================
Tests the full multi-tenant auth flow using local mode (no Auth0 needed):

    1. Company signup → creates org + admin
    2. Admin login → gets JWT with org_id
    3. JWT decoded → user context has correct claims
    4. Admin invites a user → invitation created
    5. Invitee accepts → gets their own JWT
    6. Tenant isolation → user from org A cannot access org B
    7. Role enforcement → only admins can access admin routes
    8. Multiple tenants → separate orgs, separate users

Usage:
    cd project-zer-new
    python -m tests.test_auth
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AUTH_MODE"] = "local"

from fastapi.testclient import TestClient
from auth_service.app import app
from auth_service import local_store as store

client = TestClient(app)

pass_count = 0
fail_count = 0
errors = []


def check(name, condition, detail=None):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  PASS  {name}")
    else:
        fail_count += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(name)
    return condition


def h(token):
    return {"Authorization": f"Bearer {token}"}


print("\n" + "=" * 64)
print("  AUTH SERVICE — MULTI-TENANT E2E TEST")
print("=" * 64)

# ── Phase 0: Reset ────────────────────────────────────────────────
store.reset_store()
print("\n--- Phase 0: Reset ---")
print("  Store cleared")

# ── Phase 1: Company A Signup ─────────────────────────────────────
print("\n--- Phase 1: Company A Signup ---")

r = client.post("/auth/signup", json={
    "company_name": "Acme Corp",
    "admin_email": "alice@acme.com",
    "admin_name": "Alice Admin",
    "industry": "Retail",
})
check("Signup returns 201", r.status_code == 201, f"status={r.status_code}")
data_a = r.json()
org_a = data_a.get("org_id")
admin_a_id = data_a.get("admin_user_id")
check("Org ID returned", org_a is not None)
check("Admin user ID returned", admin_a_id is not None)
check("Org name = Acme Corp", data_a.get("org_name") == "Acme Corp")

# ── Phase 2: Company A Admin Login ────────────────────────────────
print("\n--- Phase 2: Admin Login ---")

r = client.post("/auth/login", json={"email": "alice@acme.com", "password": store._users.get(f"email:alice@acme.com", {}).get("password_hash", "")})
check("Login fails with wrong password", r.status_code == 401)

pw_a = list(store._users.values())[0]
actual_email = "alice@acme.com"
user_record = store._users.get(f"email:{actual_email}")

r = client.post("/auth/login", json={"email": actual_email, "password": "wrong"})
check("Wrong password → 401", r.status_code == 401)

store._users[f"email:{actual_email}"]["password_hash"] = (
    __import__("bcrypt").hashpw(b"SecurePass1!", __import__("bcrypt").gensalt(10)).decode()
)

r = client.post("/auth/login", json={"email": "alice@acme.com", "password": "SecurePass1!"})
check("Login with correct password → 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
token_data = r.json()
token_a = token_data.get("access_token")
check("Access token returned", token_a is not None)
check("org_id in login response", token_data.get("org_id") == org_a, f"org_id={token_data.get('org_id')}")

# ── Phase 3: JWT Decoding / /me ──────────────────────────────────
print("\n--- Phase 3: JWT Claims & /me ---")

r = client.get("/auth/me", headers=h(token_a))
check("/me returns 200", r.status_code == 200)
me = r.json()
check("user_id in /me", me.get("user_id") == admin_a_id, f"user_id={me.get('user_id')}")
check("email in /me", me.get("email") == "alice@acme.com")
check("org_id in /me", me.get("org_id") == org_a)
check("org_admin role in /me", "org_admin" in me.get("roles", []), f"roles={me.get('roles')}")
check("is_admin = True", me.get("is_admin") is True)

# ── Phase 4: No Auth → 401 ───────────────────────────────────────
print("\n--- Phase 4: Unauthenticated Access ---")

r = client.get("/auth/me")
check("/me without token → 401", r.status_code == 401)

r = client.get("/auth/org/members")
check("/org/members without token → 401", r.status_code == 401)

r = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
check("Invalid token → 401", r.status_code == 401)

# ── Phase 5: Admin Invites User ──────────────────────────────────
print("\n--- Phase 5: Admin Invites User ---")

r = client.post("/auth/invite", headers=h(token_a), json={
    "email": "bob@acme.com",
    "roles": ["org_member"],
})
check("Invite returns 201", r.status_code == 201, f"status={r.status_code}")
inv_data = r.json()
invitation_id = inv_data.get("invitation_id")
check("Invitation ID returned", invitation_id is not None)
check("Invite status = invited", inv_data.get("status") == "invited")

# ── Phase 6: Accept Invitation ───────────────────────────────────
print("\n--- Phase 6: Accept Invitation ---")

r = client.post(f"/auth/accept-invite?invitation_id={invitation_id}&password=BobPass123!")
check("Accept invite → 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
accept_data = r.json()
bob_user_id = accept_data.get("user_id")
bob_token = accept_data.get("access_token")
check("Bob gets user_id", bob_user_id is not None)
check("Bob gets access_token", bob_token is not None)
check("Bob is in org A", accept_data.get("org_id") == org_a)

# ── Phase 7: Bob's Permissions ───────────────────────────────────
print("\n--- Phase 7: Bob's Access Control ---")

r = client.get("/auth/me", headers=h(bob_token))
check("Bob /me returns 200", r.status_code == 200)
bob_me = r.json()
check("Bob has org_member role", "org_member" in bob_me.get("roles", []))
check("Bob is not admin", bob_me.get("is_admin") is False)

r = client.get("/auth/org/members", headers=h(bob_token))
check("Bob cannot list members (not admin/manager)", r.status_code == 403)

r = client.post("/auth/invite", headers=h(bob_token), json={"email": "carol@acme.com", "roles": ["org_member"]})
check("Bob cannot invite (not admin/manager)", r.status_code == 403)

# ── Phase 8: Admin Can List Members ──────────────────────────────
print("\n--- Phase 8: Admin Organization Management ---")

r = client.get("/auth/org/members", headers=h(token_a))
check("Admin can list members", r.status_code == 200)
members = r.json().get("members", [])
check(f"Org has 2 members", len(members) == 2, f"count={len(members)}")

member_emails = [m["email"] for m in members]
check("Alice in members", "alice@acme.com" in member_emails)
check("Bob in members", "bob@acme.com" in member_emails)

# ── Phase 9: Org Info ────────────────────────────────────────────
print("\n--- Phase 9: Organization Info ---")

r = client.get("/auth/org/info", headers=h(token_a))
check("Org info returns 200", r.status_code == 200)
org_info = r.json()
check("Org name = acme-corp", "acme" in org_info.get("name", "").lower())
check("Member count = 2", org_info.get("member_count") == 2)

# ── Phase 10: Company B (Tenant Isolation) ────────────────────────
print("\n--- Phase 10: Company B — Tenant Isolation ---")

r = client.post("/auth/signup", json={
    "company_name": "Beta Inc",
    "admin_email": "dave@beta.com",
    "admin_name": "Dave Director",
    "industry": "Manufacturing",
})
check("Company B signup → 201", r.status_code == 201)
data_b = r.json()
org_b = data_b.get("org_id")
check("Different org ID", org_b != org_a)

store._users[f"email:dave@beta.com"]["password_hash"] = (
    __import__("bcrypt").hashpw(b"DavePass1!", __import__("bcrypt").gensalt(10)).decode()
)
r = client.post("/auth/login", json={"email": "dave@beta.com", "password": "DavePass1!"})
check("Dave login → 200", r.status_code == 200)
token_b = r.json().get("access_token")

r = client.get("/auth/me", headers=h(token_b))
dave_me = r.json()
check("Dave's org_id = org B", dave_me.get("org_id") == org_b)
check("Dave's org_id ≠ org A", dave_me.get("org_id") != org_a)

# Dave cannot see Acme's members
r = client.get("/auth/org/members", headers=h(token_b))
check("Dave can list his org's members", r.status_code == 200)
dave_members = r.json().get("members", [])
check("Dave's org has 1 member (only himself)", len(dave_members) == 1)
check("Acme members not visible to Dave",
      all(m.get("email") != "alice@acme.com" for m in dave_members))

# ── Phase 11: Assign Roles ───────────────────────────────────────
print("\n--- Phase 11: Role Assignment ---")

r = client.post("/auth/org/roles", headers=h(token_a), json={
    "user_id": bob_user_id,
    "roles": ["org_manager"],
})
check("Admin assigns manager role to Bob", r.status_code == 200)

# Bob re-logs in to get updated token
r = client.post("/auth/login", json={"email": "bob@acme.com", "password": "BobPass123!"})
bob_token_new = r.json().get("access_token")

r = client.get("/auth/me", headers=h(bob_token_new))
bob_new_me = r.json()
check("Bob now has org_manager role", "org_manager" in bob_new_me.get("roles", []))
check("Bob is now a manager", bob_new_me.get("is_manager") is True)

r = client.get("/auth/org/members", headers=h(bob_token_new))
check("Bob (now manager) can list members", r.status_code == 200)

# ── Phase 12: Health ──────────────────────────────────────────────
print("\n--- Phase 12: Service Health ---")

r = client.get("/health")
check("Health returns 200", r.status_code == 200)
check("Auth mode = local", r.json().get("auth_mode") == "local")

# ── Results ───────────────────────────────────────────────────────
print("\n" + "=" * 64)
print(f"  RESULTS: {pass_count} passed, {fail_count} failed out of {pass_count + fail_count}")
if errors:
    print(f"  FAILED: {errors}")
print("=" * 64 + "\n")

sys.exit(0 if fail_count == 0 else 1)
