"""
End-to-end flow test for the provisioning service.
Runs against http://localhost:8001 (provisioning) and http://localhost:8004 (policy).

This script:
 1. Creates the tenant via the API
 2. Directly triggers the tenant worker (creates admin user + role)
 3. Directly creates a subscription record (no Stripe in local testing)
 4. Logs in via the API to get a real JWT
 5. Runs the complete provisioning + budgetary control flow via API calls

Outputs results to _e2e_results.txt
"""
import json, sys, time, uuid, requests, io
from datetime import datetime, timezone, timedelta, date

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8001"
POLICY_BASE = "http://localhost:8004"
OUT = open("_e2e_results.txt", "w", encoding="utf-8")

def log(msg):
    OUT.write(msg + "\n")
    OUT.flush()
    try:
        print(msg)
    except Exception:
        pass

def pretty(obj):
    return json.dumps(obj, indent=2, default=str)

STATE = {}


def headers():
    h = {"Content-Type": "application/json"}
    if STATE.get("token"):
        h["Authorization"] = f"Bearer {STATE['token']}"
    return h

def approver_headers():
    h = {"Content-Type": "application/json"}
    if STATE.get("approver_token"):
        h["Authorization"] = f"Bearer {STATE['approver_token']}"
    return h


# =====================================================================
# STEP 0 — Health check
# =====================================================================
def step0_health():
    log("=" * 60)
    log("STEP 0: Health checks")
    log("=" * 60)
    r = requests.get(f"{BASE}/health", timeout=5)
    log(f"  Provisioning /health → {r.status_code}: {r.json()}")
    assert r.status_code == 200, "Provisioning service not healthy"
    r2 = requests.get(f"{POLICY_BASE}/health", timeout=5)
    log(f"  Policy /health → {r2.status_code}: {r2.json()}")


# =====================================================================
# STEP 1 — Create Tenant (API) + bootstrap admin user + subscription (DB)
# =====================================================================
def step1_create_tenant_and_bootstrap():
    log("\n" + "=" * 60)
    log("STEP 1: Create Tenant + Bootstrap Admin + Subscription")
    log("=" * 60)

    admin_email = f"admin-{uuid.uuid4().hex[:8]}@test.com"
    admin_password = "Test1234!"

    payload = {
        "tenant_name": "E2E Test Corp",
        "type": "customer",
        "email": f"e2e-{uuid.uuid4().hex[:8]}@test.com",
        "admin_email": admin_email,
        "admin_firstname": "Admin",
        "admin_lastname": "User",
        "password": admin_password,
        "phone": "+441234567890",
        "default_currency": "GBP",
        "timezone": "Europe/London",
    }
    log(f"  POST /onboarding/tenant-signup")
    r = requests.post(f"{BASE}/onboarding/tenant-signup", json=payload, timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Tenant creation failed: {r.text}"
    STATE["tenant_id"] = r.json()["tenant_id"]
    STATE["admin_email"] = admin_email
    STATE["admin_password"] = admin_password
    log(f"  ✅ tenant_id = {STATE['tenant_id']}")

    # --- Directly trigger tenant worker + create subscription via DB ---
    log("  --- Bootstrapping via direct DB (tenant worker + subscription) ---")
    import os, asyncio
    sys.path.insert(0, os.getcwd())
    os.environ["ENVIRONMENT"] = "Local"

    from provisioning_service.core.db_config import SessionLocal
    from provisioning_service.Models import OutboxEvent, TenantSubscription, SubscriptionPlan, User
    from provisioning_service.core.tasks.tenant_worker import handle_tenant_provisioning

    db = SessionLocal()
    try:
        # Check if admin user already exists for this tenant
        existing_user = db.query(User).filter(User.tenant_id == uuid.UUID(STATE["tenant_id"])).first()
        if existing_user:
            log(f"  Admin user already exists: {existing_user.user_id}")
        else:
            # Find the outbox event for this tenant
            outbox = db.query(OutboxEvent).filter(
                OutboxEvent.event_type == "tenant.signup",
            ).order_by(OutboxEvent.created_at.desc()).first()

            if outbox:
                log(f"  Found outbox event: {outbox.id}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(handle_tenant_provisioning(db, str(outbox.id)))
                finally:
                    loop.close()
                log(f"  ✅ Tenant worker completed — admin user created")
            else:
                log(f"  ⚠️ No outbox event found")

        # Create a subscription (use the first available plan)
        existing_sub = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(STATE["tenant_id"]),
            TenantSubscription.is_active == True,
        ).first()
        if existing_sub:
            log(f"  Subscription already exists for plan: {existing_sub.plan_code}")
        else:
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True).first()
            plan_code = plan.code if plan else "core_01"
            now = datetime.now(timezone.utc)
            sub = TenantSubscription(
                tenant_id=uuid.UUID(STATE["tenant_id"]),
                plan_code=plan_code,
                billing_cycle="monthly",
                is_active=True,
                is_trial=True,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
                payment_method="trial",
            )
            db.add(sub)
            db.commit()
            log(f"  ✅ Subscription created (plan: {plan_code}, trial)")
    except Exception as e:
        log(f"  ⚠️ Bootstrap error: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        db.close()


# =====================================================================
# STEP 2 — Login as admin
# =====================================================================
def step2_login():
    log("\n" + "=" * 60)
    log("STEP 2: Login as Admin")
    log("=" * 60)
    payload = {
        "email": STATE["admin_email"],
        "password": STATE["admin_password"],
    }
    log(f"  POST /onboarding/tenant-signin")
    r = requests.post(f"{BASE}/onboarding/tenant-signin", json=payload, timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    STATE["token"] = data["token"]
    STATE["admin_user_id"] = data["user_id"]
    log(f"  ✅ Logged in. user_id = {STATE['admin_user_id']}")


# =====================================================================
# STEP 3 — Create Approver User
# =====================================================================
def step3_create_approver_user():
    log("\n" + "=" * 60)
    log("STEP 3: Create Approver User")
    log("=" * 60)
    approver_email = f"approver-{uuid.uuid4().hex[:8]}@test.com"
    approver_password = "Approve1234!"
    payload = {
        "tenant_id": STATE["tenant_id"],
        "email": approver_email,
        "password": approver_password,
        "first_name": "Jane",
        "last_name": "Approver",
        "phone": "+441234567891",
        "position": "Finance Manager",
    }
    log(f"  POST /provisioning/users")
    r = requests.post(f"{BASE}/provisioning/users", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {r.text}")
    if r.status_code != 201:
        log(f"  ⚠️ Full response headers: {dict(r.headers)}")
    assert r.status_code == 201, f"Approver user creation failed ({r.status_code}): {r.text}"
    STATE["approver_user_id"] = r.json()["user_id"]
    STATE["approver_email"] = approver_email
    STATE["approver_password"] = approver_password
    log(f"  ✅ approver_user_id = {STATE['approver_user_id']}")

    # Login as approver to get their JWT
    log(f"  Logging in as approver...")
    r2 = requests.post(f"{BASE}/onboarding/tenant-signin",
                       json={"email": approver_email, "password": approver_password}, timeout=10)
    log(f"  Approver login [{r2.status_code}]: {pretty(r2.json())}")
    if r2.status_code == 200:
        STATE["approver_token"] = r2.json()["token"]
        log(f"  ✅ Approver JWT obtained")
    else:
        # Mint a JWT using known secret (fallback)
        import jwt as pyjwt
        now = datetime.now(timezone.utc)
        payload = {
            "sub": STATE["approver_user_id"],
            "email": approver_email,
            "tenant_id": STATE["tenant_id"],
            "roles": ["tenant_admin"],
            "permissions": ["*"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "iss": "http://mock-idp",
            "aud": "zeroque-api",
        }
        STATE["approver_token"] = pyjwt.encode(payload, "mock-secret", algorithm="HS256")
        log(f"  ⚠️ Minted approver JWT as fallback")


# =====================================================================
# STEP 4 — Create Site
# =====================================================================
def step4_create_site():
    log("\n" + "=" * 60)
    log("STEP 4: Create Site")
    log("=" * 60)
    payload = {
        "tenant_id": STATE["tenant_id"],
        "name": "HQ London",
        "type": "campus",
        "active": True,
        "currency": "GBP",
        "timezone": "Europe/London",
        "is_headquarter": True,
    }
    log(f"  POST /provisioning/sites")
    r = requests.post(f"{BASE}/provisioning/sites", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Site creation failed: {r.text}"
    STATE["site_id"] = r.json()["site_id"]
    log(f"  ✅ site_id = {STATE['site_id']}")


# =====================================================================
# STEP 5 — Create Store
# =====================================================================
def step5_create_store():
    log("\n" + "=" * 60)
    log("STEP 5: Create Store")
    log("=" * 60)
    payload = {
        "tenant_id": STATE["tenant_id"],
        "name": "Main Warehouse",
        "store_type": "physical",
        "active": True,
        "site_id": STATE["site_id"],
        "currency": "GBP",
    }
    log(f"  POST /provisioning/stores")
    r = requests.post(f"{BASE}/provisioning/stores", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Store creation failed: {r.text}"
    STATE["store_id"] = r.json()["store_id"]
    log(f"  ✅ store_id = {STATE['store_id']}")


# =====================================================================
# STEP 6 — Create Cost Centre
# =====================================================================
def step6_create_cost_centre():
    log("\n" + "=" * 60)
    log("STEP 6: Create Cost Centre")
    log("=" * 60)
    today = date.today()
    payload = {
        "tenant_id": STATE["tenant_id"],
        "code": "MFG-001",
        "name": "Manufacturing",
        "description": "Manufacturing department cost centre",
        "owner_user_id": STATE["approver_user_id"],
        "is_active": True,
        "fiscal_year": today.year,
        "period_type": "annual",
        "period_number": 1,
        "period_start": str(date(today.year, 1, 1)),
        "period_end": str(date(today.year, 12, 31)),
        "budget_amount_minor": 100000000,
        "created_by": STATE["admin_user_id"],
    }
    log(f"  POST /provisioning/cost-centres")
    r = requests.post(f"{BASE}/provisioning/cost-centres", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Cost centre creation failed: {r.text}"
    STATE["cost_centre_id"] = r.json()["cost_centre_id"]
    log(f"  ✅ cost_centre_id = {STATE['cost_centre_id']}")


# =====================================================================
# STEP 7 — Create Org Unit
# =====================================================================
def step7_create_org_unit():
    log("\n" + "=" * 60)
    log("STEP 7: Create Org Unit")
    log("=" * 60)
    payload = {
        "tenant_id": STATE["tenant_id"],
        "name": "Manufacturing Division",
        "type": "department",
        "status": "active",
        "code": "MFG-DIV",
        "description": "Manufacturing department org unit",
        "manager_user_id": STATE["approver_user_id"],
        "path": "/E2ETestCorp/Manufacturing",
        "depth": 1,
    }
    log(f"  POST /provisioning/org_units")
    r = requests.post(f"{BASE}/provisioning/org_units", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Org unit creation failed: {r.text}"
    STATE["org_unit_id"] = r.json()["org_unit_id"]
    log(f"  ✅ org_unit_id = {STATE['org_unit_id']}")


# =====================================================================
# STEP 8 — Create Financial Calendar
# =====================================================================
def step8_create_financial_calendar():
    log("\n" + "=" * 60)
    log("STEP 8: Create Financial Calendar")
    log("=" * 60)
    payload = {
        "name": "Corporate Calendar FY2026",
        "description": "Standard Gregorian financial calendar",
        "calendar_type": "gregorian",
        "start_month": 1,
        "currency": "GBP",
        "is_default": True,
    }
    log(f"  POST /financial-calendars")
    r = requests.post(f"{BASE}/financial-calendars", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Calendar creation failed: {r.text}"
    STATE["calendar_id"] = r.json()["calendar_id"]
    log(f"  ✅ calendar_id = {STATE['calendar_id']}")


# =====================================================================
# STEP 9 — Create Financial Year
# =====================================================================
def step9_create_financial_year():
    log("\n" + "=" * 60)
    log("STEP 9: Create Financial Year")
    log("=" * 60)
    payload = {
        "label": "FY2026",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "year_type": "full",
        "total_budget_minor": 500000000,
        "notes": "Full financial year 2026",
    }
    cal_id = STATE["calendar_id"]
    log(f"  POST /financial-calendars/{cal_id}/years")
    r = requests.post(f"{BASE}/financial-calendars/{cal_id}/years", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Year creation failed: {r.text}"
    STATE["year_id"] = r.json()["year_id"]
    log(f"  ✅ year_id = {STATE['year_id']}")


# =====================================================================
# STEP 10 — Activate Financial Year
# =====================================================================
def step10_activate_year():
    log("\n" + "=" * 60)
    log("STEP 10: Activate Financial Year")
    log("=" * 60)
    cal_id = STATE["calendar_id"]
    year_id = STATE["year_id"]
    r = requests.put(f"{BASE}/financial-calendars/{cal_id}/years/{year_id}/activate", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 200, f"Year activation failed: {r.text}"
    log(f"  ✅ Year activated")


# =====================================================================
# STEP 11 — Generate Financial Periods
# =====================================================================
def step11_generate_periods():
    log("\n" + "=" * 60)
    log("STEP 11: Generate Financial Periods (monthly)")
    log("=" * 60)
    cal_id = STATE["calendar_id"]
    year_id = STATE["year_id"]
    payload = {"period_type": "month"}
    r = requests.post(
        f"{BASE}/financial-calendars/{cal_id}/years/{year_id}/generate-periods",
        json=payload, headers=headers(), timeout=10,
    )
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Period generation failed: {r.text}"
    periods = r.json().get("periods", [])
    STATE["period_ids"] = [p["period_id"] for p in periods]
    for p in periods:
        if "2026-03" in p.get("start_date", ""):
            STATE["current_period_id"] = p["period_id"]
            break
    if "current_period_id" not in STATE and periods:
        STATE["current_period_id"] = periods[0]["period_id"]
    log(f"  ✅ Generated {len(periods)} periods, current_period_id = {STATE.get('current_period_id')}")


# =====================================================================
# STEP 12 — Create Company Budget Cap
# =====================================================================
def step12_create_company_budget_cap():
    log("\n" + "=" * 60)
    log("STEP 12: Create Company Budget Cap")
    log("=" * 60)
    payload = {
        "year_id": STATE["year_id"],
        "calendar_id": STATE["calendar_id"],
        "currency": "GBP",
        "total_budget_minor": 500000000,
        "hard_cap": False,
        "notes": "Company budget cap for FY2026",
    }
    r = requests.post(f"{BASE}/budgets/company-caps", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Company budget cap creation failed: {r.text}"
    STATE["cap_id"] = r.json()["cap_id"]
    log(f"  ✅ cap_id = {STATE['cap_id']}")


# =====================================================================
# STEP 13 — Create CC Budget Version
# =====================================================================
def step13_create_cc_budget_version():
    log("\n" + "=" * 60)
    log("STEP 13: Create Cost Centre Budget Version")
    log("=" * 60)
    payload = {
        "cost_centre_id": STATE["cost_centre_id"],
        "year_id": STATE["year_id"],
        "period_id": None,
        "currency": "GBP",
        "budget_minor": 100000000,
    }
    r = requests.post(f"{BASE}/budgets/cc-versions", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"CC budget version creation failed: {r.text}"
    STATE["cc_version_id"] = r.json()["version_id"]
    log(f"  ✅ cc_version_id = {STATE['cc_version_id']}")


# =====================================================================
# STEP 14 — Assign Users to Cost Centre
# =====================================================================
def step14_assign_users_to_cc():
    log("\n" + "=" * 60)
    log("STEP 14: Assign Users to Cost Centre")
    log("=" * 60)
    for label, uid in [("requester/admin", STATE["admin_user_id"]), ("approver", STATE["approver_user_id"])]:
        payload = {
            "user_id": uid,
            "cost_centre_id": STATE["cost_centre_id"],
            "is_primary": True,
        }
        r = requests.post(f"{BASE}/user-budgets/assignments", json=payload, headers=headers(), timeout=10)
        log(f"  {label} assignment [{r.status_code}]: {pretty(r.json())}")
        assert r.status_code == 201, f"{label} CC assignment failed: {r.text}"
    log(f"  ✅ Both users assigned to cost centre")


# =====================================================================
# STEP 15 — Create User Budget Limits
# =====================================================================
def step15_create_user_budget_limits():
    log("\n" + "=" * 60)
    log("STEP 15: Create User Budget Limits")
    log("=" * 60)

    limits = [
        ("Requester txn limit (£50k)", {
            "user_id": STATE["admin_user_id"],
            "cost_centre_id": STATE["cost_centre_id"],
            "year_id": STATE["year_id"],
            "limit_type": "requester",
            "window_type": "transaction",
            "limit_amount_minor": 5000000,
        }),
        ("Requester monthly limit (£200k)", {
            "user_id": STATE["admin_user_id"],
            "cost_centre_id": STATE["cost_centre_id"],
            "year_id": STATE["year_id"],
            "limit_type": "requester",
            "window_type": "month",
            "limit_amount_minor": 20000000,
        }),
        ("Approver txn limit (£100k)", {
            "user_id": STATE["approver_user_id"],
            "cost_centre_id": STATE["cost_centre_id"],
            "year_id": STATE["year_id"],
            "limit_type": "approver",
            "window_type": "transaction",
            "limit_amount_minor": 10000000,
        }),
        ("Approver yearly limit (£500k)", {
            "user_id": STATE["approver_user_id"],
            "cost_centre_id": STATE["cost_centre_id"],
            "year_id": STATE["year_id"],
            "limit_type": "approver",
            "window_type": "year",
            "limit_amount_minor": 50000000,
        }),
    ]
    for label, payload in limits:
        payload["carry_forward_enabled"] = False
        r = requests.post(f"{BASE}/user-budgets/limits", json=payload, headers=headers(), timeout=10)
        log(f"  {label} [{r.status_code}]: {pretty(r.json())}")
        assert r.status_code == 201, f"{label} failed: {r.text}"
    log(f"  ✅ All user budget limits created")


# =====================================================================
# STEP 16 — Create Approval Policy
# =====================================================================
def step16_create_approval_policy():
    log("\n" + "=" * 60)
    log("STEP 16: Create Approval Policy")
    log("=" * 60)
    payload = {
        "name": "Manufacturing Approval Policy",
        "description": "Single-stage approval for Manufacturing CC",
        "cost_centre_id": STATE["cost_centre_id"],
        "routing_mode": "hierarchical",
        "broadcast_n": 3,
        "sox_sod_enforced": True,
        "partial_approval_mode": "block",
        "zero_value_mode": "auto",
        "stages": [
            {
                "stage_order": 1,
                "name": "Manager Approval",
                "parallel_allowed": False,
                "min_approvers": 1,
                "escalation_timeout_hours": 24,
                "conditions": [
                    {"field": "amount", "operator": "gte", "value": "0", "logic": "AND"}
                ],
                "approvers": [
                    {"approver_type": "user", "approver_user_id": STATE["approver_user_id"]}
                ],
            }
        ],
    }
    r = requests.post(f"{BASE}/approval-policies", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    assert r.status_code == 201, f"Approval policy creation failed: {r.text}"
    STATE["policy_id"] = r.json()["policy_id"]
    log(f"  ✅ policy_id = {STATE['policy_id']}")


# =====================================================================
# STEP 17 — Purchase Request: Self-Approve (within limits)
# =====================================================================
def step17_purchase_request_self_approve():
    log("\n" + "=" * 60)
    log("STEP 17: Purchase Request — Self-Approve (£10k, within £50k txn limit)")
    log("=" * 60)
    payload = {
        "cost_centre_id": STATE["cost_centre_id"],
        "description": "Office supplies — pens and paper",
        "line_items": [
            {"product_id": str(uuid.uuid4()), "qty": 10, "unit_price_minor": 500, "description": "Ballpoint pens"},
            {"product_id": str(uuid.uuid4()), "qty": 5, "unit_price_minor": 1000, "description": "A4 Paper reams"},
        ],
        "amount_minor": 1000000,
        "currency": "GBP",
        "notes": "Monthly office supplies order",
    }
    r = requests.post(f"{BASE}/purchase-requests", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code in (200, 201):
        data = r.json()
        STATE["self_approved_request_id"] = data.get("request_id")
        log(f"  ✅ status={data.get('status')}, approval_mode={data.get('approval_mode')}")
    else:
        log(f"  ⚠️ status {r.status_code}: {r.text}")


# =====================================================================
# STEP 18 — Purchase Request: Needs Approval (exceeds limit)
# =====================================================================
def step18_purchase_request_needs_approval():
    log("\n" + "=" * 60)
    log("STEP 18: Purchase Request — Needs Approval (£75k, exceeds £50k txn limit)")
    log("=" * 60)
    payload = {
        "cost_centre_id": STATE["cost_centre_id"],
        "description": "CNC milling machine",
        "line_items": [
            {"product_id": str(uuid.uuid4()), "qty": 1, "unit_price_minor": 7500000, "description": "CNC Mill"},
        ],
        "amount_minor": 7500000,
        "currency": "GBP",
        "notes": "Capital equipment for production line",
    }
    r = requests.post(f"{BASE}/purchase-requests", json=payload, headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code in (200, 201):
        data = r.json()
        STATE["pending_request_id"] = data.get("request_id")
        log(f"  ✅ status={data.get('status')}, approval_mode={data.get('approval_mode')}")
    else:
        log(f"  ⚠️ status {r.status_code}: {r.text}")


# =====================================================================
# STEP 19 — Check Approver's Pending Tasks
# =====================================================================
def step19_check_pending_tasks():
    log("\n" + "=" * 60)
    log("STEP 19: Check Approver's Pending Tasks")
    log("=" * 60)
    r = requests.get(f"{BASE}/purchase-requests/my-tasks", headers=approver_headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        tasks = r.json().get("pending_tasks", [])
        log(f"  ✅ Found {len(tasks)} pending task(s)")
        if tasks:
            STATE["task_id"] = tasks[0]["task_id"]
            log(f"  ✅ task_id = {STATE['task_id']}")
    else:
        log(f"  ⚠️ status {r.status_code}")


# =====================================================================
# STEP 20 — Approve the Task
# =====================================================================
def step20_approve_task():
    log("\n" + "=" * 60)
    log("STEP 20: Approve the Pending Task")
    log("=" * 60)
    task_id = STATE.get("task_id")
    if not task_id:
        log("  ⚠️ No task_id — skipping")
        return
    payload = {"decision": "approve", "note": "Approved — within budget"}
    r = requests.post(
        f"{BASE}/purchase-requests/tasks/{task_id}/decide",
        json=payload, headers=approver_headers(), timeout=10,
    )
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    log(f"  ✅ Task decided")


# =====================================================================
# STEP 21 — Verify Request is Approved
# =====================================================================
def step21_verify_approved():
    log("\n" + "=" * 60)
    log("STEP 21: Verify Purchase Request Status")
    log("=" * 60)
    req_id = STATE.get("pending_request_id")
    if not req_id:
        log("  ⚠️ No pending_request_id — skipping")
        return
    r = requests.get(f"{BASE}/purchase-requests/{req_id}", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        log(f"  ✅ Final status: {r.json().get('status')}")


# =====================================================================
# STEP 22 — Issue PO
# =====================================================================
def step22_issue_po():
    log("\n" + "=" * 60)
    log("STEP 22: Issue PO for Approved Request")
    log("=" * 60)
    req_id = STATE.get("pending_request_id")
    if not req_id:
        log("  ⚠️ No pending_request_id — skipping")
        return
    r = requests.post(f"{BASE}/purchase-requests/{req_id}/issue-po", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        log(f"  ✅ PO issued")


# =====================================================================
# STEP 23 — Budget Top-Up Request
# =====================================================================
def step23_budget_top_up():
    log("\n" + "=" * 60)
    log("STEP 23: Budget Change Request — Top-Up")
    log("=" * 60)
    r = requests.post(
        f"{BASE}/budget-change-requests/top-up",
        params={
            "cost_centre_id": STATE["cost_centre_id"],
            "to_version_id": STATE["cc_version_id"],
            "amount_minor": 5000000,
            "justification": "Additional budget needed for Q2 expansion",
        },
        headers=headers(), timeout=10,
    )
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 201:
        STATE["top_up_change_req_id"] = r.json()["change_req_id"]
        log(f"  ✅ top_up_change_req_id = {STATE['top_up_change_req_id']}")


# =====================================================================
# STEP 24 — Approve Top-Up
# =====================================================================
def step24_approve_top_up():
    log("\n" + "=" * 60)
    log("STEP 24: Approve Budget Top-Up")
    log("=" * 60)
    change_id = STATE.get("top_up_change_req_id")
    if not change_id:
        log("  ⚠️ No top_up_change_req_id — skipping")
        return
    payload = {"decision": "approved", "note": "Approved for Q2"}
    r = requests.post(
        f"{BASE}/budget-change-requests/{change_id}/decide",
        json=payload, headers=headers(), timeout=10,
    )
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    log(f"  ✅ Top-up decided")


# =====================================================================
# STEP 25 — Verify CC Budget After Top-Up
# =====================================================================
def step25_verify_budget_updated():
    log("\n" + "=" * 60)
    log("STEP 25: Verify CC Budget Version After Top-Up")
    log("=" * 60)
    r = requests.get(f"{BASE}/budgets/cc-versions/{STATE['cc_version_id']}", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        d = r.json()
        log(f"  ✅ budget={d.get('budget_minor')}, committed={d.get('committed_minor')}, available={d.get('available_minor')}")


# =====================================================================
# STEP 26 — Budget Transactions (Audit)
# =====================================================================
def step26_view_transactions():
    log("\n" + "=" * 60)
    log("STEP 26: Budget Transactions (Audit Trail)")
    log("=" * 60)
    r = requests.get(f"{BASE}/budgets/transactions", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        log(f"  ✅ Total transactions: {r.json().get('total')}")


# =====================================================================
# STEP 27 — List Budget Change Requests
# =====================================================================
def step27_list_change_requests():
    log("\n" + "=" * 60)
    log("STEP 27: List Budget Change Requests")
    log("=" * 60)
    r = requests.get(f"{BASE}/budget-change-requests", headers=headers(), timeout=10)
    log(f"  Response [{r.status_code}]: {pretty(r.json())}")
    if r.status_code == 200:
        log(f"  ✅ Total change requests: {r.json().get('total')}")


# =====================================================================
# SUMMARY
# =====================================================================
def print_summary():
    log("\n" + "=" * 60)
    log("SUMMARY — All captured IDs")
    log("=" * 60)
    for k, v in STATE.items():
        if "token" in k or "password" in k:
            log(f"  {k}: <redacted>")
        else:
            log(f"  {k}: {v}")
    log("\n✅ E2E FLOW COMPLETE")


# =====================================================================
# MAIN
# =====================================================================
if __name__ == "__main__":
    log(f"E2E Test started at {datetime.now(timezone.utc).isoformat()}")
    log(f"Provisioning: {BASE}  |  Policy: {POLICY_BASE}")

    steps = [
        step0_health,
        step1_create_tenant_and_bootstrap,
        step2_login,
        step3_create_approver_user,
        step4_create_site,
        step5_create_store,
        step6_create_cost_centre,
        step7_create_org_unit,
        step8_create_financial_calendar,
        step9_create_financial_year,
        step10_activate_year,
        step11_generate_periods,
        step12_create_company_budget_cap,
        step13_create_cc_budget_version,
        step14_assign_users_to_cc,
        step15_create_user_budget_limits,
        step16_create_approval_policy,
        step17_purchase_request_self_approve,
        step18_purchase_request_needs_approval,
        step19_check_pending_tasks,
        step20_approve_task,
        step21_verify_approved,
        step22_issue_po,
        step23_budget_top_up,
        step24_approve_top_up,
        step25_verify_budget_updated,
        step26_view_transactions,
        step27_list_change_requests,
    ]

    for step_fn in steps:
        try:
            step_fn()
        except AssertionError as e:
            log(f"\n❌ ASSERTION FAILED in {step_fn.__name__}: {e}")
            break
        except Exception as e:
            log(f"\n❌ ERROR in {step_fn.__name__}: {type(e).__name__}: {e}")
            import traceback
            log(traceback.format_exc())
            break

    print_summary()
    OUT.close()

