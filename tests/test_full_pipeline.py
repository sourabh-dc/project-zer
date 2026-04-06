#!/usr/bin/env python3
"""
tests/test_full_pipeline.py
----------------------------
Full end-to-end pipeline test:

  signup → auth → Postgres → outbox → publisher → Service Bus → consumer → Neo4j

Requires Docker: docker compose up -d postgres neo4j

Usage:
    AUTH_MODE=local python3 tests/test_full_pipeline.py
"""
import sys
import os
import asyncio
import uuid
import json

os.environ["AUTH_MODE"] = "local"
os.environ["TRANSPORT_MODE"] = "local"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy import text

from shared.db import engine, SessionFactory, get_session
from shared.models import Base as SharedBase
from onboarding_service.models import Base as OnboardingBase
from onboarding_service.routes import router as onboarding_router, set_session_factory
from auth_service.routes import router as auth_router
from auth_service import local_store
from graph_service.neo4j_client import get_driver, init_constraints, run_cypher, close_driver
from graph_service.handlers import dispatch
from event_service.publisher import publish_pending_events
from event_service.transport import LocalTransport

# ── Test app ─────────────────────────────────────────────────────────

test_app = FastAPI(title="Full Pipeline Test")
test_app.include_router(onboarding_router)
test_app.include_router(auth_router)

passed = 0
failed = 0


def check(condition, msg=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  \u2713 {msg}")
    else:
        failed += 1
        print(f"  \u2717 FAIL: {msg}")


def setup():
    """Reset Postgres tables and Neo4j graph."""
    OnboardingBase.metadata.drop_all(engine)
    SharedBase.metadata.drop_all(engine)
    SharedBase.metadata.create_all(engine)
    OnboardingBase.metadata.create_all(engine)
    set_session_factory(SessionFactory)
    local_store.reset_store()

    driver = get_driver()
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    init_constraints()
    print("  Setup: Postgres tables + Neo4j graph reset")


setup()


async def run_tests():
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # ── PHASE 1: Tenant Signup ────────────────────────────────
        print("\n" + "="*60)
        print("PHASE 1: TENANT SIGNUP")
        print("="*60)

        print("\n[1.1] Create tenant — Acme Corp")
        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "Acme Corp",
            "type": "customer",
            "email": "info@acmecorp.com",
            "admin_email": "admin@acmecorp.com",
            "admin_firstname": "John",
            "admin_lastname": "Doe",
            "industry": "technology",
            "default_currency": "GBP",
        })
        check(r.status_code == 201, f"Signup returns 201 (got {r.status_code})")
        acme = r.json()
        acme_tenant_id = acme["tenant_id"]
        acme_org_id = acme["org_id"]
        acme_user_id = acme["admin_user_id"]
        check(acme["role"] == "tenant_admin", "Admin role = tenant_admin")
        check(acme["status"] == "provisioned", "Status = provisioned")
        print(f"    tenant_id={acme_tenant_id}")
        print(f"    org_id={acme_org_id}")
        print(f"    admin_user_id={acme_user_id}")

        print("\n[1.2] Create second tenant — Globex Corp")
        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "Globex Corp",
            "type": "retailer",
            "email": "info@globex.com",
            "admin_email": "eve@globex.com",
            "admin_firstname": "Eve",
            "admin_lastname": "Smith",
            "industry": "retail",
        })
        check(r.status_code == 201, f"Globex signup returns 201 (got {r.status_code})")
        globex = r.json()
        globex_tenant_id = globex["tenant_id"]

        # ── PHASE 2: Verify Postgres ──────────────────────────────
        print("\n" + "="*60)
        print("PHASE 2: VERIFY POSTGRES")
        print("="*60)

        print("\n[2.1] Tenants")
        with get_session() as db:
            tenants = db.execute(text("SELECT tenant_id, tenant_name, org_id FROM tenants")).fetchall()
            check(len(tenants) == 2, f"2 tenants in DB (got {len(tenants)})")
            for t in tenants:
                print(f"    {t.tenant_name} (org_id={t.org_id})")

        print("\n[2.2] Users")
        with get_session() as db:
            users = db.execute(text("SELECT email, status, auth0_user_id IS NOT NULL as has_ad_id FROM users")).fetchall()
            check(len(users) == 2, f"2 users in DB (got {len(users)})")
            for u in users:
                print(f"    {u.email} (status={u.status}, azure_ad={u.has_ad_id})")

        print("\n[2.3] Outbox events")
        with get_session() as db:
            events = db.execute(
                text("SELECT event_type, status, topic FROM outbox_events ORDER BY created_at")
            ).fetchall()
            check(len(events) == 4, f"4 events in outbox (got {len(events)})")
            for e in events:
                print(f"    {e.event_type} → topic={e.topic} (status={e.status})")
            pending = [e for e in events if e.status == "pending"]
            check(len(pending) == 4, f"All 4 events are pending (got {len(pending)})")

        # ── PHASE 3: Publisher → Local Transport ──────────────────
        print("\n" + "="*60)
        print("PHASE 3: PUBLISHER → LOCAL TRANSPORT")
        print("="*60)

        local_transport = LocalTransport()
        tenant_events = []
        user_events = []

        local_transport._get_queue("tenant", "graph-consumer")
        local_transport._get_queue("user", "graph-consumer")

        print("\n[3.1] Publish pending events")
        with get_session() as db:
            count = await publish_pending_events(db, local_transport, 100)
            check(count == 4, f"Published {count} events (expected 4)")

        print("\n[3.2] Verify events marked as published")
        with get_session() as db:
            events = db.execute(text("SELECT event_type, status FROM outbox_events")).fetchall()
            all_published = all(e.status == "published" for e in events)
            check(all_published, "All events status = 'published'")

        # ── PHASE 4: Consumer → Neo4j Graph Projection ───────────
        print("\n" + "="*60)
        print("PHASE 4: CONSUMER → NEO4J GRAPH PROJECTION")
        print("="*60)

        print("\n[4.1] Consume tenant events → Neo4j")
        q = local_transport._get_queue("tenant", "graph-consumer")
        tenant_count = 0
        while not q.empty():
            event = await q.get()
            handled = dispatch(event)
            check(handled, f"tenant event dispatched: {event.get('event_type')}")
            tenant_count += 1
        check(tenant_count == 2, f"2 tenant events consumed (got {tenant_count})")

        print("\n[4.2] Consume user events → Neo4j")
        q = local_transport._get_queue("user", "graph-consumer")
        user_count = 0
        while not q.empty():
            event = await q.get()
            handled = dispatch(event)
            check(handled, f"user event dispatched: {event.get('event_type')}")
            user_count += 1
        check(user_count == 2, f"2 user events consumed (got {user_count})")

        # ── PHASE 5: Verify Neo4j Graph ──────────────────────────
        print("\n" + "="*60)
        print("PHASE 5: VERIFY NEO4J GRAPH")
        print("="*60)

        print("\n[5.1] Tenant nodes")
        result = run_cypher("MATCH (t:Tenant) RETURN t.tenant_id AS tid, t.name AS name, t.type AS type ORDER BY t.name")
        check(len(result) == 2, f"2 Tenant nodes (got {len(result)})")
        for r in result:
            print(f"    Tenant: {r['name']} (type={r['type']}, id={r['tid']})")

        print("\n[5.2] User nodes")
        result = run_cypher("MATCH (u:User) RETURN u.user_id AS uid, u.email AS email, u.name AS name ORDER BY u.email")
        check(len(result) == 2, f"2 User nodes (got {len(result)})")
        for r in result:
            print(f"    User: {r['email']} ({r['name']}, id={r['uid']})")

        print("\n[5.3] Role nodes")
        result = run_cypher("MATCH (r:Role) RETURN r.code AS code ORDER BY r.code")
        check(len(result) >= 1, f"At least 1 Role node (got {len(result)})")
        for r in result:
            print(f"    Role: {r['code']}")

        print("\n[5.4] Relationships: (Tenant)-[:HAS_USER]->(User)")
        result = run_cypher("""
            MATCH (t:Tenant)-[:HAS_USER]->(u:User)
            RETURN t.name AS tenant, u.email AS user
            ORDER BY t.name, u.email
        """)
        check(len(result) == 2, f"2 HAS_USER relationships (got {len(result)})")
        for r in result:
            print(f"    {r['tenant']} → {r['user']}")

        print("\n[5.5] Relationships: (User)-[:HAS_ROLE]->(Role)")
        result = run_cypher("""
            MATCH (u:User)-[:HAS_ROLE]->(r:Role)
            RETURN u.email AS user, r.code AS role
            ORDER BY u.email
        """)
        check(len(result) == 2, f"2 HAS_ROLE relationships (got {len(result)})")
        for r in result:
            print(f"    {r['user']} → {r['role']}")

        print("\n[5.6] Full graph topology for Acme")
        result = run_cypher("""
            MATCH (t:Tenant {tenant_id: $tid})-[:HAS_USER]->(u:User)-[:HAS_ROLE]->(r:Role)
            RETURN t.name AS tenant, u.email AS user, r.code AS role
        """, {"tid": acme_tenant_id})
        check(len(result) == 1, f"Acme topology: 1 user with 1 role (got {len(result)})")
        if result:
            print(f"    {result[0]['tenant']} → {result[0]['user']} → {result[0]['role']}")

        # ── PHASE 6: Auth — Login + JWT ──────────────────────────
        print("\n" + "="*60)
        print("PHASE 6: AUTH — LOGIN + JWT")
        print("="*60)

        import bcrypt
        test_password = "TestPass123!"
        admin_data = local_store._users.get("email:admin@acmecorp.com")
        if admin_data:
            admin_data["password_hash"] = bcrypt.hashpw(
                test_password.encode(), bcrypt.gensalt(10)
            ).decode()

        print("\n[6.1] Login as Acme admin")
        r = await client.post("/auth/login", json={
            "email": "admin@acmecorp.com",
            "password": test_password,
            "org_id": acme_org_id,
        })
        check(r.status_code == 200, f"Login returns 200 (got {r.status_code})")
        token = r.json()["access_token"]

        print("\n[6.2] /auth/me — verify JWT")
        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        check(r.status_code == 200, f"/auth/me returns 200 (got {r.status_code})")
        me = r.json()
        check(me["email"] == "admin@acmecorp.com", "Email correct in JWT")
        check(me["org_id"] == acme_org_id, "org_id correct in JWT")
        check("org_admin" in me["roles"], "org_admin role in JWT")
        check(me["is_admin"] is True, "is_admin = true")

        print("\n[6.3] Forgot password")
        r = await client.post("/auth/forgot-password", json={"email": "admin@acmecorp.com"})
        check(r.status_code == 200, "Forgot password returns 200")

        print("\n[6.4] Unauthenticated access → 401")
        r = await client.get("/auth/me")
        check(r.status_code == 401, f"No token → 401 (got {r.status_code})")

        # ── PHASE 7: Service Bus (real Azure) ─────────────────────
        print("\n" + "="*60)
        print("PHASE 7: AZURE SERVICE BUS (real)")
        print("="*60)

        from shared.config import SERVICE_BUS_CONNECTION
        if SERVICE_BUS_CONNECTION and "servicebus.windows.net" in SERVICE_BUS_CONNECTION:
            print("\n[7.1] Publish to Azure Service Bus")
            # Reset outbox to pending so we can re-publish to Azure SB
            with get_session() as db:
                db.execute(text("UPDATE outbox_events SET status = 'pending', published_at = NULL"))

            from event_service.transport import ServiceBusTransport
            sb_transport = ServiceBusTransport(SERVICE_BUS_CONNECTION)
            with get_session() as db:
                count = await publish_pending_events(db, sb_transport, 100)
                check(count == 4, f"Published {count} events to Azure Service Bus")
            await sb_transport.close()

            print("\n[7.2] Consume from Azure Service Bus → Neo4j")
            driver = get_driver()
            with driver.session() as s:
                s.run("MATCH (n) DETACH DELETE n")
            print("    Neo4j cleared for consumer verification")

            sb_transport = ServiceBusTransport(SERVICE_BUS_CONNECTION)
            consumed = 0
            for topic, sub in [("tenant", "tenant-consumer"), ("user", "user-consumer")]:
                receiver = sb_transport._client.get_subscription_receiver(
                    topic_name=topic, subscription_name=sub, max_wait_time=10,
                )
                messages = receiver.receive_messages(max_message_count=20, max_wait_time=10)
                for msg in messages:
                    event = json.loads(str(msg))
                    handled = dispatch(event)
                    receiver.complete_message(msg)
                    consumed += 1
                    print(f"    Consumed: {event.get('event_type')} → {'PROJECTED' if handled else 'SKIPPED'}")
                receiver.close()
            await sb_transport.close()
            check(consumed >= 4, f"Consumed {consumed} events from Service Bus (expected >= 4)")

            print("\n[7.3] Verify Neo4j after Service Bus consumer")
            result = run_cypher("MATCH (t:Tenant) RETURN count(t) AS c")
            check(result[0]["c"] >= 2, f"At least 2 Tenant nodes after SB consumer (got {result[0]['c']})")

            result = run_cypher("MATCH (u:User) RETURN count(u) AS c")
            check(result[0]["c"] >= 2, f"At least 2 User nodes after SB consumer (got {result[0]['c']})")

            result = run_cypher("MATCH (t:Tenant)-[:HAS_USER]->(u:User)-[:HAS_ROLE]->(r:Role) RETURN count(*) AS c")
            check(result[0]["c"] >= 2, f"At least 2 full paths (Tenant→User→Role) (got {result[0]['c']})")
        else:
            print("  (skipped — SERVICE_BUS_CONNECTION not set)")

    close_driver()


asyncio.run(run_tests())

print(f"\n{'='*60}")
if failed == 0:
    print(f"  ALL {passed} ASSERTIONS PASSED")
else:
    print(f"  PASSED: {passed}  FAILED: {failed}")
print(f"{'='*60}")

sys.exit(1 if failed > 0 else 0)
