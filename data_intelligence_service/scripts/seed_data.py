"""
Seed script — populate Postgres + Neo4j with realistic ZeroQue test data.

Run from repo root:
  cd data_intelligence_service
  python -m scripts.seed_data

What gets created:
  Postgres:
    1 tenant, 3 org units, 4 users, 3 vendors, 10 products, 3 categories,
    2 policies, 1 budget, 20 orders + order_items, 10 purchase_requests

  Neo4j:
    Tenant, OrgUnit hierarchy, Users with Roles + Permissions,
    Vendors, Products with category links, ApprovedRange, CostCentre

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING for Postgres.
Neo4j: MERGE on primary key to avoid duplicates.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ── Load .env ──────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Fixed UUIDs for reproducibility
# ---------------------------------------------------------------------------

TENANT_ID   = "11111111-1111-1111-1111-111111111111"
SITE_ID     = "22222222-2222-2222-2222-222222222222"
STORE_ID    = "33333333-3333-3333-3333-333333333333"

ORG_OPS     = "aaaa0001-0000-0000-0000-000000000001"
ORG_FINANCE = "aaaa0001-0000-0000-0000-000000000002"
ORG_PROCURE = "aaaa0001-0000-0000-0000-000000000003"

USER_ALICE   = "bbbb0001-0000-0000-0000-000000000001"   # admin / exec
USER_BOB     = "bbbb0001-0000-0000-0000-000000000002"   # buyer (procurement)
USER_CHARLIE = "bbbb0001-0000-0000-0000-000000000003"   # requester (operations)
USER_DIANA   = "bbbb0001-0000-0000-0000-000000000004"   # finance manager

VENDOR_CLEANPRO = "cccc0001-0000-0000-0000-000000000001"
VENDOR_SAFEKIT  = "cccc0001-0000-0000-0000-000000000002"
VENDOR_BULKMART = "cccc0001-0000-0000-0000-000000000003"

CAT_PPE       = "dddd0001-0000-0000-0000-000000000001"
CAT_CLEANING  = "dddd0001-0000-0000-0000-000000000002"
CAT_PACKAGING = "dddd0001-0000-0000-0000-000000000003"

PRODUCTS = [
    ("eeee0001-0000-0000-0000-000000000001", "Nitrile Gloves S", "NIT-S-100", CAT_PPE, "box", 1500, VENDOR_SAFEKIT),
    ("eeee0001-0000-0000-0000-000000000002", "Nitrile Gloves M", "NIT-M-100", CAT_PPE, "box", 1500, VENDOR_SAFEKIT),
    ("eeee0001-0000-0000-0000-000000000003", "Latex Gloves M", "LAT-M-50", CAT_PPE, "box", 900, VENDOR_SAFEKIT),
    ("eeee0001-0000-0000-0000-000000000004", "Safety Goggles", "GOG-CLEAR-1", CAT_PPE, "each", 800, VENDOR_SAFEKIT),
    ("eeee0001-0000-0000-0000-000000000005", "Hi-Vis Vest L", "VIS-L-001", CAT_PPE, "each", 1200, VENDOR_SAFEKIT),
    ("eeee0001-0000-0000-0000-000000000006", "Antibac Surface Cleaner 5L", "CLN-ABC-5L", CAT_CLEANING, "each", 2200, VENDOR_CLEANPRO),
    ("eeee0001-0000-0000-0000-000000000007", "Floor Cleaner Concentrate 10L", "CLN-FLR-10", CAT_CLEANING, "each", 3500, VENDOR_CLEANPRO),
    ("eeee0001-0000-0000-0000-000000000008", "Eco Cleaning Wipes x200", "CLN-WIP-200", CAT_CLEANING, "pack", 1800, VENDOR_CLEANPRO),
    ("eeee0001-0000-0000-0000-000000000009", "Bubble Wrap Roll 100m", "PKG-BUB-100", CAT_PACKAGING, "roll", 4500, VENDOR_BULKMART),
    ("eeee0001-0000-0000-0000-000000000010", "Cardboard Box 30x20x15 (x25)", "PKG-BOX-SML", CAT_PACKAGING, "pack", 2800, VENDOR_BULKMART),
]

POLICY_ID = "ffff0001-0000-0000-0000-000000000001"
BUDGET_ID = "ffff0002-0000-0000-0000-000000000001"
RANGE_ID  = "ffff0003-0000-0000-0000-000000000001"

ROLE_ADMIN     = "role-admin-0000-0000-000000000001"
ROLE_BUYER     = "role-buyy-0000-0000-000000000002"
ROLE_REQUESTER = "role-reqq-0000-0000-000000000003"
ROLE_FINANCE   = "role-finn-0000-0000-000000000004"

PERM_INTEL  = "perm-int-0000-0000-000000000001"
PERM_BUY    = "perm-buy-0000-0000-000000000002"
PERM_VIEW   = "perm-viw-0000-0000-000000000003"


# ---------------------------------------------------------------------------
# Postgres seed
# ---------------------------------------------------------------------------

def seed_postgres():
    pg_url = (
        f"postgresql://{os.getenv('POSTGRES_USER','postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD','postgres')}@"
        f"{os.getenv('POSTGRES_HOST','localhost')}:5432/"
        f"{os.getenv('POSTGRES_DB','zeroque')}"
    )
    engine = create_engine(pg_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    print("=== Seeding Postgres ===")

    # Create tables if they don't exist (minimal schema for testing)
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id UUID PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS org_units (
            org_unit_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            name TEXT NOT NULL,
            code TEXT,
            status TEXT DEFAULT 'active',
            parent_id UUID
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            org_unit_id UUID,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS categories (
            category_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS products (
            product_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            category_id UUID,
            vendor_id UUID,
            name TEXT NOT NULL,
            sku TEXT,
            unit_of_measure TEXT DEFAULT 'each',
            unit_price_minor INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS policies (
            policy_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            name TEXT NOT NULL,
            approval_required BOOLEAN DEFAULT TRUE,
            auto_approve_threshold_minor INTEGER,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS budgets (
            budget_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            org_unit_id UUID NOT NULL,
            allocated_minor BIGINT DEFAULT 0,
            spent_minor BIGINT DEFAULT 0,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            vendor_id UUID,
            requester_id UUID,
            status TEXT DEFAULT 'pending',
            total_amount_minor BIGINT DEFAULT 0,
            order_date DATE,
            expected_delivery_date DATE,
            actual_delivery_date DATE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS order_items (
            item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL,
            product_id UUID NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price NUMERIC(10,2) DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS purchase_requests (
            request_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            requester_id UUID,
            title TEXT,
            total_amount_minor BIGINT DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """))
    session.commit()

    # ── Tenant ──────────────────────────────────────────────────────────────
    session.execute(text("""
        INSERT INTO tenants (tenant_id, name) VALUES (:id, :name)
        ON CONFLICT (tenant_id) DO NOTHING
    """), {"id": TENANT_ID, "name": "ZeroQue Demo Co"})

    # ── Org units ────────────────────────────────────────────────────────────
    for oid, name, code in [
        (ORG_OPS,     "Operations",    "OPS"),
        (ORG_FINANCE, "Finance",       "FIN"),
        (ORG_PROCURE, "Procurement",   "PRO"),
    ]:
        session.execute(text("""
            INSERT INTO org_units (org_unit_id, tenant_id, name, code)
            VALUES (:id, :tid, :name, :code)
            ON CONFLICT (org_unit_id) DO NOTHING
        """), {"id": oid, "tid": TENANT_ID, "name": name, "code": code})

    # ── Users ────────────────────────────────────────────────────────────────
    for uid, name, email, org_id in [
        (USER_ALICE,   "Alice Admin",   "alice@demo.co",   ORG_PROCURE),
        (USER_BOB,     "Bob Buyer",     "bob@demo.co",     ORG_PROCURE),
        (USER_CHARLIE, "Charlie Staff", "charlie@demo.co", ORG_OPS),
        (USER_DIANA,   "Diana Finance", "diana@demo.co",   ORG_FINANCE),
    ]:
        session.execute(text("""
            INSERT INTO users (user_id, tenant_id, org_unit_id, name, email)
            VALUES (:id, :tid, :oid, :name, :email)
            ON CONFLICT (user_id) DO NOTHING
        """), {"id": uid, "tid": TENANT_ID, "oid": org_id, "name": name, "email": email})

    # ── Categories ───────────────────────────────────────────────────────────
    for cid, name in [(CAT_PPE,"PPE"), (CAT_CLEANING,"Cleaning"), (CAT_PACKAGING,"Packaging")]:
        session.execute(text("""
            INSERT INTO categories (category_id, tenant_id, name)
            VALUES (:id, :tid, :name) ON CONFLICT (category_id) DO NOTHING
        """), {"id": cid, "tid": TENANT_ID, "name": name})

    # ── Vendors ───────────────────────────────────────────────────────────────
    for vid, name in [
        (VENDOR_CLEANPRO, "CleanPro Supplies Ltd"),
        (VENDOR_SAFEKIT,  "SafeKit PPE Solutions"),
        (VENDOR_BULKMART, "BulkMart Packaging"),
    ]:
        session.execute(text("""
            INSERT INTO vendors (vendor_id, tenant_id, name)
            VALUES (:id, :tid, :name) ON CONFLICT (vendor_id) DO NOTHING
        """), {"id": vid, "tid": TENANT_ID, "name": name})

    # ── Products ─────────────────────────────────────────────────────────────
    for pid, name, sku, cat_id, unit, price, vid in PRODUCTS:
        session.execute(text("""
            INSERT INTO products (product_id, tenant_id, category_id, vendor_id, name, sku, unit_of_measure, unit_price_minor)
            VALUES (:id, :tid, :cat, :vid, :name, :sku, :unit, :price)
            ON CONFLICT (product_id) DO NOTHING
        """), {"id": pid, "tid": TENANT_ID, "cat": cat_id, "vid": vid,
               "name": name, "sku": sku, "unit": unit, "price": price})

    # ── Policy ────────────────────────────────────────────────────────────────
    session.execute(text("""
        INSERT INTO policies (policy_id, tenant_id, name, approval_required, auto_approve_threshold_minor)
        VALUES (:id, :tid, :name, TRUE, 5000000) ON CONFLICT (policy_id) DO NOTHING
    """), {"id": POLICY_ID, "tid": TENANT_ID, "name": "Standard Approval Policy"})

    # ── Budget ────────────────────────────────────────────────────────────────
    session.execute(text("""
        INSERT INTO budgets (budget_id, tenant_id, org_unit_id, allocated_minor, spent_minor, period_start, period_end)
        VALUES (:id, :tid, :oid, 5000000, 2300000, '2026-04-01', '2026-06-30')
        ON CONFLICT (budget_id) DO NOTHING
    """), {"id": BUDGET_ID, "tid": TENANT_ID, "oid": ORG_OPS})

    # ── Orders + order_items ─────────────────────────────────────────────────
    today = datetime.now(timezone.utc).date()
    order_data = [
        (VENDOR_SAFEKIT, USER_BOB, "delivered", 4500, -30, -20, -18, PRODUCTS[0]),
        (VENDOR_SAFEKIT, USER_BOB, "delivered", 3000, -25, -15, -13, PRODUCTS[1]),
        (VENDOR_CLEANPRO, USER_BOB, "delivered", 6600, -20, -10, -9, PRODUCTS[5]),
        (VENDOR_CLEANPRO, USER_CHARLIE, "delivered", 7000, -18, -8, -8, PRODUCTS[6]),
        (VENDOR_SAFEKIT, USER_BOB, "delivered", 3600, -15, -5, -6, PRODUCTS[3]),
        (VENDOR_BULKMART, USER_BOB, "pending", 9000, -10, 5, None, PRODUCTS[8]),
        (VENDOR_CLEANPRO, USER_CHARLIE, "delivered", 5400, -8, -2, -1, PRODUCTS[7]),
        (VENDOR_SAFEKIT, USER_BOB, "delivered", 1500, -5, 3, 4, PRODUCTS[2]),
        (VENDOR_BULKMART, USER_CHARLIE, "delivered", 5600, -60, -50, -48, PRODUCTS[9]),
        (VENDOR_CLEANPRO, USER_BOB, "delivered", 4400, -90, -80, -79, PRODUCTS[5]),
    ]
    for i, (vid, uid, status, amount, order_offset, exp_offset, act_offset, prod) in enumerate(order_data):
        oid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"order-{i}"))
        order_date = today + timedelta(days=order_offset)
        exp_date = today + timedelta(days=exp_offset)
        act_date = (today + timedelta(days=act_offset)) if act_offset is not None else None
        session.execute(text("""
            INSERT INTO orders (order_id, tenant_id, vendor_id, requester_id, status,
                                total_amount_minor, order_date, expected_delivery_date, actual_delivery_date)
            VALUES (:id, :tid, :vid, :uid, :status, :amount, :odate, :edate, :adate)
            ON CONFLICT (order_id) DO NOTHING
        """), {"id": oid, "tid": TENANT_ID, "vid": vid, "uid": uid, "status": status,
               "amount": amount, "odate": order_date, "edate": exp_date, "adate": act_date})
        # order_item
        item_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"item-{i}"))
        session.execute(text("""
            INSERT INTO order_items (item_id, order_id, product_id, quantity, unit_price)
            VALUES (:iid, :oid, :pid, 2, :price)
            ON CONFLICT (item_id) DO NOTHING
        """), {"iid": item_id, "oid": oid, "pid": prod[0], "price": prod[5] / 100.0})

    # ── Purchase requests ─────────────────────────────────────────────────────
    pr_data = [
        (USER_CHARLIE, "Monthly PPE restock", 7500, "approved"),
        (USER_CHARLIE, "Cleaning supplies Q2", 12000, "pending"),
        (USER_BOB,     "Packaging materials bulk", 22500, "approved"),
        (USER_DIANA,   "Safety equipment audit", 8000, "submitted"),
        (USER_CHARLIE, "Antibacterial products", 6600, "approved"),
        (USER_BOB,     "Hi-vis vests x10", 12000, "approved"),
        (USER_DIANA,   "Floor cleaner restock", 10500, "pending"),
        (USER_CHARLIE, "Eco cleaning wipes", 5400, "approved"),
        (USER_BOB,     "PPE budget Q3", 30000, "submitted"),
        (USER_CHARLIE, "Cardboard boxes monthly", 8400, "approved"),
    ]
    for i, (uid, title, amount, status) in enumerate(pr_data):
        rid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pr-{i}"))
        created = datetime.now(timezone.utc) - timedelta(days=i * 3)
        session.execute(text("""
            INSERT INTO purchase_requests (request_id, tenant_id, requester_id, title, total_amount_minor, status, created_at)
            VALUES (:id, :tid, :uid, :title, :amount, :status, :created)
            ON CONFLICT (request_id) DO NOTHING
        """), {"id": rid, "tid": TENANT_ID, "uid": uid, "title": title,
               "amount": amount, "status": status, "created": created})

    session.commit()
    session.close()
    print("✓ Postgres seeded")


# ---------------------------------------------------------------------------
# Neo4j seed
# ---------------------------------------------------------------------------

def seed_neo4j():
    from neo4j import GraphDatabase
    uri  = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd  = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    print("=== Seeding Neo4j ===")

    with driver.session() as s:
        # Tenant
        s.run("MERGE (t:Tenant {tenant_id: $id}) SET t.name = $name",
              id=TENANT_ID, name="ZeroQue Demo Co")

        # OrgUnits
        for oid, name, code in [
            (ORG_OPS,     "Operations",  "OPS"),
            (ORG_FINANCE, "Finance",     "FIN"),
            (ORG_PROCURE, "Procurement", "PRO"),
        ]:
            s.run("""
                MERGE (o:OrgUnit {org_unit_id: $id})
                SET o.name = $name, o.code = $code, o.status = 'active'
                WITH o
                MATCH (t:Tenant {tenant_id: $tid})
                MERGE (t)-[:HAS_ORG_UNIT]->(o)
            """, id=oid, name=name, code=code, tid=TENANT_ID)

        # Roles
        for rid, code, name in [
            (ROLE_ADMIN,     "admin",               "Administrator"),
            (ROLE_BUYER,     "buyer",                "Buyer"),
            (ROLE_REQUESTER, "requester",            "Requester"),
            (ROLE_FINANCE,   "finance_manager",      "Finance Manager"),
        ]:
            s.run("MERGE (r:Role {role_id: $id}) SET r.code = $code, r.name = $name, r.status = 'active'",
                  id=rid, code=code, name=name)

        # Permissions
        for pid, code in [
            (PERM_INTEL, "intelligence.query"),
            (PERM_BUY,   "purchase.create"),
            (PERM_VIEW,  "product.view"),
        ]:
            s.run("MERGE (p:Permission {perm_id: $id}) SET p.code = $code", id=pid, code=code)

        # Role → Permission links
        # Admin gets all
        for pcode in ["intelligence.query", "purchase.create", "product.view"]:
            s.run("""
                MATCH (r:Role {code: 'admin'}), (p:Permission {code: $code})
                MERGE (r)-[:GRANTS]->(p)
            """, code=pcode)
        # Buyer gets intel + purchase + view
        for pcode in ["intelligence.query", "purchase.create", "product.view"]:
            s.run("""
                MATCH (r:Role {code: 'buyer'}), (p:Permission {code: $code})
                MERGE (r)-[:GRANTS]->(p)
            """, code=pcode)
        # Requester gets view only
        for pcode in ["product.view"]:
            s.run("""
                MATCH (r:Role {code: 'requester'}), (p:Permission {code: $code})
                MERGE (r)-[:GRANTS]->(p)
            """, code=pcode)
        # Finance manager gets intel + view
        for pcode in ["intelligence.query", "product.view"]:
            s.run("""
                MATCH (r:Role {code: 'finance_manager'}), (p:Permission {code: $code})
                MERGE (r)-[:GRANTS]->(p)
            """, code=pcode)

        # Users
        for uid, name, email, org_id, role_id in [
            (USER_ALICE,   "Alice Admin",   "alice@demo.co",   ORG_PROCURE, ROLE_ADMIN),
            (USER_BOB,     "Bob Buyer",     "bob@demo.co",     ORG_PROCURE, ROLE_BUYER),
            (USER_CHARLIE, "Charlie Staff", "charlie@demo.co", ORG_OPS,     ROLE_REQUESTER),
            (USER_DIANA,   "Diana Finance", "diana@demo.co",   ORG_FINANCE, ROLE_FINANCE),
        ]:
            s.run("""
                MERGE (u:User {user_id: $uid})
                SET u.name = $name, u.email = $email, u.status = 'active'
                WITH u
                MATCH (o:OrgUnit {org_unit_id: $oid})
                MERGE (u)-[:BELONGS_TO]->(o)
                WITH u
                MATCH (r:Role {role_id: $rid})
                MERGE (u)-[:HAS_ROLE]->(r)
            """, uid=uid, name=name, email=email, oid=org_id, rid=role_id)

        # Vendors in graph
        for vid, name in [
            (VENDOR_CLEANPRO, "CleanPro Supplies Ltd"),
            (VENDOR_SAFEKIT,  "SafeKit PPE Solutions"),
            (VENDOR_BULKMART, "BulkMart Packaging"),
        ]:
            s.run("""
                MERGE (v:Vendor {vendor_id: $id})
                SET v.name = $name, v.status = 'active'
                WITH v MATCH (t:Tenant {tenant_id: $tid})
                MERGE (t)-[:HAS_VENDOR]->(v)
            """, id=vid, name=name, tid=TENANT_ID)

        # Categories in graph
        for cid, name in [(CAT_PPE,"PPE"), (CAT_CLEANING,"Cleaning"), (CAT_PACKAGING,"Packaging")]:
            s.run("""
                MERGE (c:Category {category_id: $id}) SET c.name = $name, c.status = 'active'
            """, id=cid, name=name)

        # Products in graph with category links
        for pid, name, sku, cat_id, unit, price, vid in PRODUCTS:
            s.run("""
                MERGE (p:Product {product_id: $pid})
                SET p.name = $name, p.sku = $sku, p.status = 'active', p.unit_of_measure = $unit
                WITH p
                MATCH (c:Category {category_id: $cat})
                MERGE (p)-[:IN_CATEGORY]->(c)
                WITH p
                MATCH (v:Vendor {vendor_id: $vid})
                MERGE (v)-[:SUPPLIES]->(p)
            """, pid=pid, name=name, sku=sku, unit=unit, cat=cat_id, vid=vid)

        # ApprovedRange — universal range covering all products
        s.run("""
            MERGE (ar:ApprovedRange {range_id: $id})
            SET ar.name = 'Standard Range', ar.status = 'active', ar.is_universal = true
            WITH ar
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_APPROVED_RANGE]->(ar)
        """, id=RANGE_ID, tid=TENANT_ID)

        # Link all PPE + Cleaning products to the approved range
        for pid, _, _, cat_id, _, _, _ in PRODUCTS:
            if cat_id in (CAT_PPE, CAT_CLEANING):
                s.run("""
                    MATCH (ar:ApprovedRange {range_id: $rid}), (p:Product {product_id: $pid})
                    MERGE (ar)-[:INCLUDES]->(p)
                """, rid=RANGE_ID, pid=pid)

        # CostCentre
        cc_id = "cccc9999-0000-0000-0000-000000000001"
        s.run("""
            MERGE (cc:CostCentre {cost_centre_id: $id})
            SET cc.name = 'Operations CC', cc.code = 'OPS-CC', cc.status = 'active'
            WITH cc
            MATCH (u:User {user_id: $uid})
            MERGE (u)-[:ASSIGNED_TO_CC]->(cc)
        """, id=cc_id, uid=USER_CHARLIE)

        # Policy node
        s.run("""
            MERGE (p:Policy {policy_id: $id})
            SET p.code = 'standard-approval', p.name = 'Standard Approval', p.status = 'active'
            WITH p
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (p)-[:ASSIGNED_TO]->(t)
        """, id=POLICY_ID, tid=TENANT_ID)

    driver.close()
    print("✓ Neo4j seeded")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting seed...")
    try:
        seed_postgres()
    except Exception as exc:
        print(f"✗ Postgres seed failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        seed_neo4j()
    except Exception as exc:
        print(f"✗ Neo4j seed failed: {exc}", file=sys.stderr)
        print("  Is Neo4j running? docker compose up -d neo4j")
        sys.exit(1)

    print("\n✓ Seed complete.")
    print(f"  Tenant ID:  {TENANT_ID}")
    print(f"  Users:      Alice (admin), Bob (buyer), Charlie (requester), Diana (finance)")
    print(f"  Products:   10 products across PPE, Cleaning, Packaging")
    print(f"  Test query: POST /intelligence/query")
    print(f'  Body: {{"question":"What are our top spending categories?","tenant_id":"{TENANT_ID}"}}')
