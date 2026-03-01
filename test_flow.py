"""Full integration test — runs against local Docker services."""
import requests
import jwt
import datetime
import json
import time
import uuid

BASE = "http://localhost:8000"
POLICY = "http://localhost:8004"
GRAPH = "http://localhost:8005"
VECTOR = "http://localhost:8006"
INTEL = "http://localhost:8007"

DB_URL = "postgresql://zeroque:zeroque_dev_password@localhost:5432/zeroque_dev"

def make_token(uid, tid):
    return jwt.encode({
        "sub": uid, "tenant_id": tid,
        "email": "admin@testcorp.com",
        "roles": ["tenant_admin"], "permissions": ["*"],
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        "iss": "http://mock-idp", "aud": "zeroque-api",
    }, "mock-secret", algorithm="HS256")

print("="*60)
print("PHASE -1: TENANT SIGNUP")
print("="*60)

signup_resp = requests.post(f"{BASE}/onboarding/tenant-signup", json={
    "tenant_name": "Test Corp",
    "type": "customer",
    "email": "admin@testcorp.com",
    "admin_email": "admin@testcorp.com",
    "admin_firstname": "Admin",
    "admin_lastname": "User",
    "password": "SecurePass123!",
})
signup_data = signup_resp.json()
print(f"  Signup response (HTTP {signup_resp.status_code}):")
print(f"  {json.dumps(signup_data, indent=2)}")

TID = signup_data.get("tenant_id", "")
UID = signup_data.get("user_id", "")
if not TID or not UID:
    print("  FATAL: Tenant signup failed, cannot continue")
    exit(1)

TK = make_token(UID, TID)
H = {"Authorization": f"Bearer {TK}", "Content-Type": "application/json"}

passed = 0
failed = 0

def step(name, resp):
    global passed, failed
    code = resp.status_code
    try:
        d = resp.json()
    except:
        d = resp.text
    ok = code < 400
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"\n  [{'PASS' if ok else 'FAIL'}] {name} (HTTP {code})")
    txt = json.dumps(d, indent=2) if isinstance(d, (dict, list)) else str(d)
    for line in txt.split("\n")[:15]:
        print(f"    {line}")
    if len(txt.split("\n")) > 15:
        print(f"    ... ({len(txt.split(chr(10)))-15} more lines)")
    return d if ok else {}


# ── PHASE 0: BOOTSTRAP (direct SQL) ────────────────────────
print("\n" + "="*60)
print("PHASE 0: BOOTSTRAP (plan, features, subscription via SQL)")
print("="*60)

from sqlalchemy import create_engine, text as sql_text
engine = create_engine(DB_URL)

with engine.connect() as c:
    plan_exists = c.execute(sql_text("SELECT code FROM subscription_plans WHERE code = 'starter'")).fetchone()
    if not plan_exists:
        c.execute(sql_text("""
            INSERT INTO subscription_plans (plan_id, code, name, description, is_active, created_by, created_at, updated_at)
            VALUES (:id, 'starter', 'Starter Plan', 'Free starter plan', true, 'system', NOW(), NOW())
        """), {"id": str(uuid.uuid4())})
        print("  Created plan: starter")
    else:
        print("  Plan exists: starter")

    for feat in ["sites.manage","stores.manage","users.manage","products","variants","categories","org_units","cost_centres","vendors.manage","store_products"]:
        exists = c.execute(sql_text("SELECT id FROM features WHERE code = :c"), {"c": feat}).fetchone()
        if not exists:
            c.execute(sql_text("""
                INSERT INTO features (id, code, name, description, usage_type, reset_period, status, active, created_at)
                VALUES (:id, :code, :name, :desc, 'count', 'none', 'active', true, NOW())
            """), {"id": str(uuid.uuid4()), "code": feat, "name": feat.replace("_", " ").title(), "desc": f"{feat} feature"})
            print(f"  Created feature: {feat}")
        else:
            print(f"  Feature exists: {feat}")
        pf = c.execute(sql_text(
            "SELECT 1 FROM plan_features WHERE plan_code = 'starter' AND feature_code = :fc"
        ), {"fc": feat}).fetchone()
        if not pf:
            c.execute(sql_text("""
                INSERT INTO plan_features (id, plan_code, feature_code, enabled, limits, created_at, updated_at)
                VALUES (:id, 'starter', :fc, true, '{"max": 100}', NOW(), NOW())
            """), {"id": str(uuid.uuid4()), "fc": feat})

    sub = c.execute(sql_text("SELECT 1 FROM tenant_subscriptions WHERE tenant_id = :tid"), {"tid": TID}).fetchone()
    if not sub:
        c.execute(sql_text("""
            INSERT INTO tenant_subscriptions (tenant_id, plan_code, billing_cycle, current_period_start,
                current_period_end, is_active, is_trial, created_at)
            VALUES (:tid, 'starter', 'monthly', NOW(), NOW() + INTERVAL '30 days', true, false, NOW())
        """), {"tid": TID})
        print("  Subscribed tenant to starter plan")
    else:
        print("  Subscription already exists")

    c.commit()
    print("  Bootstrap complete")


# ── PHASE 1: POLICY SEEDING ────────────────────────────────
print("\n" + "="*60)
print("PHASE 1: SEED DEFAULT POLICIES")
print("="*60)
step("SEED POLICIES", requests.post(f"{POLICY}/policies/seed", headers=H))


# ── PHASE 2: CORE ENTITY CREATION ──────────────────────────
print("\n" + "="*60)
print("PHASE 2: CORE ENTITY CREATION")
print("="*60)

d = step("CREATE SITE", requests.post(f"{BASE}/provisioning/sites", headers=H,
    json={"name":"London HQ","type":"headquarters","currency":"GBP","timezone":"Europe/London","tenant_id":TID}))
SID = d.get("site_id", "")

d = step("CREATE STORE", requests.post(f"{BASE}/provisioning/stores", headers=H,
    json={"name":"London Store","store_type":"retail","active":True,"site_id":SID,"tenant_id":TID}))
STID = d.get("store_id", "")

d = step("CREATE ORG UNIT", requests.post(f"{BASE}/provisioning/org_units", headers=H,
    json={"name":"London Office","type":"department","code":"LDN","tenant_id":TID}))
OUID = d.get("org_unit_id", "")

d = step("CREATE COST CENTRE", requests.post(f"{BASE}/provisioning/cost-centres", headers=H,
    json={"name":"IT Budget","code":"IT-001","tenant_id":TID,"budget_amount_minor":5000000,"created_by":UID}))
CCID = d.get("cost_centre_id", "")

d = step("CREATE VENDOR", requests.post(f"{BASE}/provisioning/vendors", headers=H,
    json={"name":"Office Depot","tenant_id":TID}))
VID = d.get("vendor_id", "")

d = step("CREATE CATEGORY", requests.post(f"{BASE}/catalog/categories", headers=H,
    json={"name":"Office Supplies","code":"OFFICE","description":"General office supplies"}))
CATID = d.get("category_id", "")

PIDS = []
products_data = [
    ("Ballpoint Pen Pack 10", "SKU-PEN01", "Smooth writing blue ballpoint pens for everyday use"),
    ("A4 Copier Paper 500 Sheets", "SKU-PAPER", "Premium white A4 80gsm copier paper"),
    ("Heavy Duty Stapler", "SKU-STPLR", "Metal stapler handles up to 50 sheets"),
    ("Whiteboard Markers Set", "SKU-WMARK", "Assorted colors dry erase whiteboard markers"),
]
for name, sku, desc in products_data:
    d = step(f"CREATE PRODUCT '{name}'", requests.post(f"{BASE}/catalog/products", headers=H,
        json={"display_name":name,"sku":sku,"item_code":sku.replace("SKU-","IT-"),
              "category_id":CATID,"purchase_price_minor":750,"sales_description":desc}))
    pid = d.get("product_id", "")
    if pid:
        PIDS.append(pid)


# ── PHASE 3: APPROVED RANGE GOVERNANCE ─────────────────────
print("\n" + "="*60)
print("PHASE 3: APPROVED RANGE GOVERNANCE")
print("="*60)

resp = requests.post(f"{BASE}/approved-ranges/", headers=H,
    json={"name":"Standard Office Range","description":"Office supplies for all offices","is_universal":False})
d = step("CREATE APPROVED RANGE", resp)
ARID = d.get("approved_range_id", "")

if OUID and ARID:
    step("MAP ORG UNIT TO RANGE", requests.post(f"{BASE}/approved-ranges/{ARID}/org-units", headers=H,
        json={"org_unit_ids": [OUID]}))

if PIDS and ARID:
    step("ADD PRODUCTS TO RANGE (first 3)", requests.post(f"{BASE}/approved-ranges/{ARID}/products", headers=H,
        json={"product_ids": PIDS[:3]}))


print("\n  ... Waiting 8s for outbox → graph + vector projection ...")
time.sleep(8)


# ── PHASE 4: GRAPH SERVICE ─────────────────────────────────
print("\n" + "="*60)
print("PHASE 4: GRAPH SERVICE QUERIES")
print("="*60)

step("GRAPH: HEALTH", requests.get(f"{GRAPH}/health"))
step("GRAPH: TENANT TOPOLOGY", requests.get(f"{GRAPH}/graph/tenant/{TID}/topology"))
step("GRAPH: APPROVED PRODUCTS FOR USER", requests.get(
    f"{GRAPH}/graph/approved-products/{UID}", params={"tenant_id": TID, "is_admin": "true"}))


# ── PHASE 5: VECTOR SEARCH ─────────────────────────────────
print("\n" + "="*60)
print("PHASE 5: VECTOR SEMANTIC SEARCH")
print("="*60)

step("VECTOR: HEALTH", requests.get(f"{VECTOR}/health"))
step("VECTOR: SEARCH 'writing supplies'", requests.post(f"{VECTOR}/vector/search",
    json={"query":"writing supplies","tenant_id":TID,"top_k":10,"skip_governance":True}))
step("VECTOR: SEARCH 'paper for printing'", requests.post(f"{VECTOR}/vector/search",
    json={"query":"paper for printing","tenant_id":TID,"top_k":10,"skip_governance":True}))


# ── PHASE 6: INTELLIGENCE (GraphRAG) ──────────────────────
print("\n" + "="*60)
print("PHASE 6: INTELLIGENCE SERVICE (GraphRAG)")
print("="*60)

step("INTEL: HEALTH", requests.get(f"{INTEL}/health"))
step("INTEL: 'How many products?'", requests.post(f"{INTEL}/intelligence/query",
    json={"question":"How many products do we have in the system?","tenant_id":TID}))
step("INTEL: 'Which products in office range?'", requests.post(f"{INTEL}/intelligence/query",
    json={"question":"Which products are in the Standard Office Range?","tenant_id":TID}))


# ── SUMMARY ────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"TEST SUMMARY: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
print(f"  Tenant:        {TID}")
print(f"  User:          {UID}")
print(f"  Site:          {SID}")
print(f"  Store:         {STID}")
print(f"  OrgUnit:       {OUID}")
print(f"  CostCentre:    {CCID}")
print(f"  Vendor:        {VID}")
print(f"  Category:      {CATID}")
print(f"  Products:      {PIDS}")
print(f"  ApprovedRange: {ARID}")
