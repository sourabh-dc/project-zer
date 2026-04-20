"""
seed_policies.py
================
Seeds the 3 global policies the E2E test suite depends on.
Run this ONCE before running test_e2e.py.

  python seed_policies.py

The script is fully idempotent — safe to run multiple times.

Policy architecture seeded
--------------------------
1. global.allow_all  (priority 200, action_pattern "*")
   A universal fallback "allow" rule so no action ever hits the
   "no applicable policies found → deny" trap.

2. global.purchase_workflow  (priority 50, action_pattern "purchase_request.create")
   Routes purchase requests through the approval engine when the budget
   engine flags them as needing_approval.

3. global.sox_sod  (priority 10, action_pattern "purchase_request.decide")
   Enforces SOX Segregation of Duties: the person who submitted a request
   cannot also be the one who approves it.

All three are global (tenant_id = null) so every tenant inherits them.
"""

import sys
import json
import requests

PROV_URL = "http://localhost:8000"   # provisioning service
PE_URL   = "http://localhost:8004"   # policy engine
TIMEOUT  = 10

ADMIN_EMAIL    = "sebinsanthosh2016@gmail.com"
ADMIN_PASSWORD = "SecurePass1"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {GREEN}✔{RESET}  {msg}")
def err(msg): print(f"  {RED}✘{RESET}  {msg}")
def warn(msg):print(f"  {YELLOW}⚠{RESET}  {msg}")
def info(msg):print(f"  ·  {msg}")

# ─────────────────────────────────────────────────────────────────────────────
# 0. Verify both services are up
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}── Checking services ──{RESET}")
for label, url in [("Provisioning", f"{PROV_URL}/health"), ("Policy Engine", f"{PE_URL}/health")]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            ok(f"{label} is up")
        else:
            err(f"{label} returned HTTP {r.status_code}")
            sys.exit(1)
    except Exception as e:
        err(f"{label} unreachable: {e}")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin login → get JWT (works for both services — shared secret)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}── Admin login ──{RESET}")
r = requests.post(f"{PROV_URL}/onboarding/tenant-signin",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                  timeout=TIMEOUT)
if r.status_code != 200:
    err(f"Login failed: HTTP {r.status_code} — {r.text[:200]}")
    sys.exit(1)

login_data = r.json()
TOKEN = login_data["token"]
H = {"Authorization": f"Bearer {TOKEN}"}
ok(f"Logged in as {ADMIN_EMAIL}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Helper — create policy + global assignment, skip if code already exists
# ─────────────────────────────────────────────────────────────────────────────

def policy_exists(code: str) -> bool:
    """Return True if a global policy with this code already exists."""
    r = requests.get(f"{PE_URL}/policies", params={"is_active": "true"}, timeout=TIMEOUT)
    if r.status_code != 200:
        return False
    for p in r.json().get("policies", []):
        if p["code"] == code and p["tenant_id"] is None:
            return True
    return False


def create_policy(payload: dict, action_pattern: str) -> bool:
    """
    POST /policies, then POST /policies/{id}/assignments.
    Returns True on success, False on failure.
    """
    code = payload["code"]

    # --- create policy ---
    r = requests.post(f"{PE_URL}/policies", json=payload, headers=H, timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        err(f"Create policy '{code}' → HTTP {r.status_code}: {r.text[:300]}")
        return False

    policy_id = r.json()["policy_id"]
    ok(f"Created policy '{code}' ({policy_id})")

    # --- create global assignment ---
    assignment = {
        "scope_type": "global",
        "scope_id": None,
        "action_pattern": action_pattern,
        "is_active": True,
    }
    r2 = requests.post(f"{PE_URL}/policies/{policy_id}/assignments",
                       json=assignment, headers=H, timeout=TIMEOUT)
    if r2.status_code not in (200, 201):
        err(f"  Assignment for '{code}' → HTTP {r2.status_code}: {r2.text[:200]}")
        return False

    ok(f"  Assignment → scope=global  action_pattern='{action_pattern}'")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Seed the 3 global policies
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}── Seeding global policies ──{RESET}")

POLICIES = [
    # ── 1. Universal allow fallback ──────────────────────────────────────────
    # Makes every action "applicable" so the engine never hits the
    # default-deny "no policies found" path.  Always fires last (priority 200).
    {
        "payload": {
            "code":        "global.allow_all",
            "name":        "Global Allow Fallback",
            "description": "Ensures all provisioning and governance actions have at least "
                           "one matching policy, preventing default-deny. "
                           "Higher-priority deny/require_approval rules override this.",
            "policy_type": "access",
            "priority":    200,
            "is_active":   True,
            "status":      "active",
            "rules": [
                {
                    "rule_order":            0,
                    "name":                  "Allow by default",
                    "condition_expression":  "True",
                    "effect":                "allow",
                    "is_active":             True,
                }
            ],
        },
        "action_pattern": "*",
    },

    # ── 2. Purchase request → approval workflow ───────────────────────────────
    # Triggers when the budget engine sets needs_approval = True on the request.
    # Priority 50 — evaluated before the global allow (200) but after SOX (10).
    {
        "payload": {
            "code":        "global.purchase_workflow",
            "name":        "Purchase Request Approval Routing",
            "description": "Routes purchase requests through the multi-stage approval "
                           "workflow when the requester's budget limit is exceeded or "
                           "the budget engine flags the request for review.",
            "policy_type": "approval",
            "priority":    50,
            "is_active":   True,
            "status":      "active",
            "rules": [
                {
                    "rule_order":            0,
                    "name":                  "Budget limit exceeded — route to approval",
                    "condition_expression":  "resource.needs_approval == True",
                    "effect":                "require_approval",
                    "denial_reason":         "Purchase request exceeds your budget limit and requires manager approval.",
                    "is_active":             True,
                }
            ],
        },
        "action_pattern": "purchase_request.create",
    },

    # ── 3. SOX Segregation of Duties ─────────────────────────────────────────
    # Highest priority (10) — evaluated first.
    # Denies when the approver is also the requester and SoD is enforced.
    {
        "payload": {
            "code":        "global.sox_sod",
            "name":        "SOX Segregation of Duties",
            "description": "Enforces SOX compliance: the employee who submitted a purchase "
                           "request may not be the one who approves it. Applies whenever "
                           "the approval policy has sox_sod_enforced = True.",
            "policy_type": "access",
            "priority":    10,
            "is_active":   True,
            "status":      "active",
            "rules": [
                {
                    "rule_order":            0,
                    "name":                  "Self-approval denied (SOX SoD)",
                    "condition_expression":  "resource.sox_sod_enforced == True and resource.requester_id == subject.user_id",
                    "effect":                "deny",
                    "denial_reason":         "SOX Segregation of Duties violation: you cannot approve a request you submitted.",
                    "is_active":             True,
                }
            ],
        },
        "action_pattern": "purchase_request.decide",
    },
]

all_ok = True
for entry in POLICIES:
    code = entry["payload"]["code"]
    if policy_exists(code):
        warn(f"Policy '{code}' already exists — skipping")
    else:
        if not create_policy(entry["payload"], entry["action_pattern"]):
            all_ok = False

# ─────────────────────────────────────────────────────────────────────────────
# 4. Verify — list all global policies
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}── Verifying seeded policies ──{RESET}")
r = requests.get(f"{PE_URL}/policies", timeout=TIMEOUT)
if r.status_code == 200:
    data = r.json()
    global_policies = [p for p in data["policies"] if p["tenant_id"] is None]
    info(f"Total global policies: {len(global_policies)}")
    for p in global_policies:
        ver = p.get("current_version") or {}
        rules = ver.get("rules", [])
        effects = ", ".join(r["effect"] for r in rules)
        info(f"  [{p['priority']:>4}] {p['code']}  →  rules: [{effects}]")
else:
    warn(f"Could not list policies: HTTP {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Smoke test — dry-run evaluate for site.create
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}── Smoke test (dry-run: site.create) ──{RESET}")
tenant_id = login_data.get("tenant_id", "")
user_id   = login_data.get("user_id", "")

r = requests.post(f"{PE_URL}/evaluate/dry-run", json={
    "action":    "site.create",
    "subject":   {"user_id": user_id, "tenant_id": tenant_id, "roles": ["tenant_admin"], "permissions": ["*"]},
    "resource":  {"tenant_id": tenant_id, "feature_code": "sites.manage", "subscription_active": True},
    "tenant_id": tenant_id,
}, timeout=TIMEOUT)

if r.status_code == 200:
    result = r.json()
    decision = result.get("decision")
    reason   = result.get("reason", "")
    matched  = len(result.get("matched_policies", []))
    if decision == "allow":
        ok(f"site.create → {decision}  ({matched} matched policies)")
    else:
        err(f"site.create → {decision}: {reason}")
        all_ok = False
else:
    err(f"Dry-run failed: HTTP {r.status_code}: {r.text[:200]}")
    all_ok = False

# ─────────────────────────────────────────────────────────────────────────────
print()
if all_ok:
    print(f"{BOLD}{GREEN}✔ Policy seeding complete — ready to run test_e2e.py{RESET}\n")
else:
    print(f"{BOLD}{RED}✘ Some steps failed — review errors above{RESET}\n")
    sys.exit(1)
