"""
probe_policy_engine.py
======================
Discovers the policy engine's API so we can seed tenant policies.
Run this once: python probe_policy_engine.py
"""
import json
import requests

PE = "http://localhost:8004"
TIMEOUT = 5

TENANT_ID = "8a2b5d70-29df-44d3-83e9-9013dd78a2e0"   # from the login output
ADMIN_USER_ID = "db44b6f9-6fe3-4c7f-95cf-579921926588"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def probe(method, path, **kwargs):
    try:
        r = getattr(requests, method)(f"{PE}{path}", timeout=TIMEOUT, **kwargs)
        print(f"  {GREEN}{method.upper()} {path}{RESET} → HTTP {r.status_code}")
        if r.text and len(r.text) < 2000:
            try:
                print(f"    {json.dumps(r.json(), indent=2)[:1500]}")
            except Exception:
                print(f"    {r.text[:500]}")
        return r
    except Exception as e:
        print(f"  {RED}{method.upper()} {path}{RESET} → ERROR: {e}")
        return None

print(f"\n{BOLD}── Policy Engine API Discovery  ({PE}) ──{RESET}\n")

print(f"\n{BOLD}[1] OpenAPI / Swagger docs{RESET}")
probe("get", "/openapi.json")
probe("get", "/docs")
probe("get", "/redoc")

print(f"\n{BOLD}[2] Common root / health endpoints{RESET}")
probe("get", "/")
probe("get", "/health")
probe("get", "/api/v1")

print(f"\n{BOLD}[3] Policy management endpoints{RESET}")
probe("get", "/policies")
probe("get", f"/policies?tenant_id={TENANT_ID}")
probe("get", "/api/v1/policies")
probe("get", f"/api/v1/policies?tenant_id={TENANT_ID}")
probe("get", "/rules")
probe("get", f"/rules?tenant_id={TENANT_ID}")

print(f"\n{BOLD}[4] OPA native endpoints (if this is bare OPA){RESET}")
probe("get", "/v1/data")
probe("get", "/v1/policies")
probe("get", "/v1/data/authz")

print(f"\n{BOLD}[5] Test evaluate (to confirm the request shape){RESET}")
probe("post", "/evaluate", json={
    "action": "site.create",
    "subject": {
        "user_id": ADMIN_USER_ID,
        "tenant_id": TENANT_ID,
        "roles": ["admin"],
        "permissions": ["*"],
        "email": "sebinsanthosh2016@gmail.com",
    },
    "resource": {
        "tenant_id": TENANT_ID,
        "feature_code": "sites.manage",
        "subscription_active": True,
    },
    "tenant_id": TENANT_ID,
})

print(f"\n{BOLD}[6] Try seed / bootstrap endpoints{RESET}")
probe("get", "/seed")
probe("get", "/admin")
probe("get", "/admin/policies")
probe("post", "/admin/seed", json={"tenant_id": TENANT_ID})
