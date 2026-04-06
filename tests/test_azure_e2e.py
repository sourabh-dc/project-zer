#!/usr/bin/env python3
"""
tests/test_azure_e2e.py
------------------------
Full end-to-end test against real Azure infrastructure:

  Signup (API) → Postgres → Outbox → Publisher → Azure Service Bus
                                      → Consumer → Azure Neo4j

Components:
  - Postgres:     Local Docker (port 5433)
  - Service Bus:  Azure (zeroque-servicebus)
  - Neo4j:        Azure ACI (zeroque-neo4j.uksouth.azurecontainer.io:7687)
  - Auth:         Local mode (bcrypt + JWT)

Usage:
    docker compose up -d postgres
    python3 tests/test_azure_e2e.py
"""
import sys
import os
import asyncio
import json

os.environ["AUTH_MODE"] = "local"
os.environ["TRANSPORT_MODE"] = "servicebus"
os.environ["NEO4J_URI"] = "bolt://zeroque-neo4j.uksouth.azurecontainer.io:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "zeroque_neo4j_prod_2026"

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
from event_service.transport import ServiceBusTransport
from shared.config import SERVICE_BUS_CONNECTION

test_app = FastAPI(title="Azure E2E Test")
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
    """Reset Postgres + Neo4j."""
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

    # Drain leftover messages from Service Bus
    sb = ServiceBusTransport(SERVICE_BUS_CONNECTION)
    for topic, sub in [("tenant", "tenant-consumer"), ("user", "user-consumer")]:
        receiver = sb._client.get_subscription_receiver(
            topic_name=topic, subscription_name=sub, max_wait_time=5,
        )
        msgs = receiver.receive_messages(max_message_count=50, max_wait_time=5)
        for m in msgs:
            receiver.complete_message(m)
        receiver.close()
        if msgs:
            print(f"  Drained {len(msgs)} leftover messages from {topic}/{sub}")
    sb._client.close()

    print("  Setup: Postgres + Azure Neo4j + Service Bus reset")


setup()


async def run_tests():
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # ── 1. SIGNUP ─────────────────────────────────────────────
        print("\n" + "="*60)
        print("1. TENANT SIGNUP")
        print("="*60)

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
        check(r.status_code == 201, f"Acme signup 201 (got {r.status_code})")
        acme = r.json()
        print(f"    tenant_id={acme['tenant_id']}, org_id={acme['org_id']}")
        print(f"    admin={acme['admin_email']}, role={acme['role']}")
        check(acme["role"] == "tenant_admin", "Role = tenant_admin")

        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "Globex Corp",
            "type": "retailer",
            "email": "info@globex.com",
            "admin_email": "eve@globex.com",
            "admin_firstname": "Eve",
            "admin_lastname": "Smith",
            "industry": "retail",
        })
        check(r.status_code == 201, "Globex signup 201")
        globex = r.json()
        print(f"    tenant_id={globex['tenant_id']}, org_id={globex['org_id']}")

        # ── 2. POSTGRES VERIFICATION ─────────────────────────────
        print("\n" + "="*60)
        print("2. POSTGRES — Records Created")
        print("="*60)

        with get_session() as db:
            tenants = db.execute(text("SELECT tenant_name, org_id, status FROM tenants")).fetchall()
            check(len(tenants) == 2, f"2 tenants (got {len(tenants)})")

            users = db.execute(text("SELECT email, status FROM users")).fetchall()
            check(len(users) == 2, f"2 users (got {len(users)})")

            events = db.execute(text(
                "SELECT event_type, status, topic FROM outbox_events ORDER BY created_at"
            )).fetchall()
            check(len(events) == 4, f"4 outbox events (got {len(events)})")
            for e in events:
                print(f"    {e.event_type} → topic={e.topic} ({e.status})")

        # ── 3. AUTH — Login + JWT ─────────────────────────────────
        print("\n" + "="*60)
        print("3. AUTH — Login + JWT")
        print("="*60)

        import bcrypt
        test_pw = "TestPass123!"
        admin_data = local_store._users.get("email:admin@acmecorp.com")
        if admin_data:
            admin_data["password_hash"] = bcrypt.hashpw(test_pw.encode(), bcrypt.gensalt(10)).decode()

        r = await client.post("/auth/login", json={
            "email": "admin@acmecorp.com",
            "password": test_pw,
            "org_id": acme["org_id"],
        })
        check(r.status_code == 200, "Login 200")
        token = r.json()["access_token"]

        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        check(r.status_code == 200, "/auth/me 200")
        me = r.json()
        check(me["email"] == "admin@acmecorp.com", "JWT email correct")
        check(me["org_id"] == acme["org_id"], "JWT org_id correct")
        check("org_admin" in me["roles"], "JWT has org_admin role")
        check(me["is_admin"] is True, "is_admin = true")
        print(f"    JWT: user_id={me['user_id']}, email={me['email']}, roles={me['roles']}")

        r = await client.post("/auth/forgot-password", json={"email": "admin@acmecorp.com"})
        check(r.status_code == 200, "Forgot password 200")

        r = await client.get("/auth/me")
        check(r.status_code == 401, "Unauthenticated → 401")

        # ── 4. PUBLISHER → Azure Service Bus ──────────────────────
        print("\n" + "="*60)
        print("4. PUBLISHER → Azure Service Bus")
        print("="*60)

        sb_transport = ServiceBusTransport(SERVICE_BUS_CONNECTION)
        with get_session() as db:
            count = await publish_pending_events(db, sb_transport, 100)
            check(count == 4, f"Published {count} events to Service Bus")
        await sb_transport.close()

        with get_session() as db:
            published = db.execute(text(
                "SELECT COUNT(*) as c FROM outbox_events WHERE status = 'published'"
            )).fetchone()
            check(published.c == 4, f"All 4 events published (got {published.c})")
            print(f"    {published.c} events published to Azure Service Bus")

        # ── 5. CONSUMER — Service Bus → Neo4j ────────────────────
        print("\n" + "="*60)
        print("5. CONSUMER — Azure Service Bus → Azure Neo4j")
        print("="*60)

        # The Azure Function consumer may have already consumed the messages.
        # Try local consume first; if 0, the Azure Function beat us — verify via Neo4j.
        sb_transport = ServiceBusTransport(SERVICE_BUS_CONNECTION)
        consumed = 0
        for topic, sub in [("tenant", "tenant-consumer"), ("user", "user-consumer")]:
            receiver = sb_transport._client.get_subscription_receiver(
                topic_name=topic, subscription_name=sub, max_wait_time=10,
            )
            messages = receiver.receive_messages(max_message_count=10, max_wait_time=10)
            for msg in messages:
                event = json.loads(str(msg))
                handled = dispatch(event)
                receiver.complete_message(msg)
                consumed += 1
                status = "PROJECTED" if handled else "SKIPPED"
                print(f"    [{sub}] {status}: {event.get('event_type')} (tenant={event.get('tenant_id','?')[:8]}...)")
            receiver.close()
        await sb_transport.close()

        if consumed == 0:
            print("    Azure Function consumer already processed all messages!")
            print("    Verifying via Neo4j graph (populated by Azure Function)...")
            tenant_count = run_cypher("MATCH (t:Tenant) RETURN count(t) AS c")[0]["c"]
            check(tenant_count >= 2, f"Azure Function projected {tenant_count} tenants to Neo4j")
        else:
            check(consumed == 4, f"Consumed {consumed} events from Service Bus")

        # ── 6. NEO4J VERIFICATION ─────────────────────────────────
        print("\n" + "="*60)
        print("6. NEO4J — Graph Verification (Azure)")
        print("="*60)

        print("\n  Tenants:")
        result = run_cypher("MATCH (t:Tenant) RETURN t.tenant_id AS id, t.name AS name, t.type AS type ORDER BY t.name")
        check(len(result) == 2, f"2 Tenant nodes (got {len(result)})")
        for r in result:
            print(f"    {r['name']} (type={r['type']})")

        print("\n  Users:")
        result = run_cypher("MATCH (u:User) RETURN u.email AS email, u.name AS name ORDER BY u.email")
        check(len(result) == 2, f"2 User nodes (got {len(result)})")
        for r in result:
            print(f"    {r['email']} ({r['name']})")

        print("\n  Roles:")
        result = run_cypher("MATCH (r:Role) RETURN r.code AS code")
        check(len(result) >= 1, f"At least 1 Role node (got {len(result)})")
        for r in result:
            print(f"    {r['code']}")

        print("\n  Relationships: (Tenant)-[:HAS_USER]->(User)")
        result = run_cypher("""
            MATCH (t:Tenant)-[:HAS_USER]->(u:User)
            RETURN t.name AS tenant, u.email AS user ORDER BY t.name
        """)
        check(len(result) == 2, f"2 HAS_USER rels (got {len(result)})")
        for r in result:
            print(f"    {r['tenant']} → {r['user']}")

        print("\n  Relationships: (User)-[:HAS_ROLE]->(Role)")
        result = run_cypher("""
            MATCH (u:User)-[:HAS_ROLE]->(r:Role)
            RETURN u.email AS user, r.code AS role ORDER BY u.email
        """)
        check(len(result) == 2, f"2 HAS_ROLE rels (got {len(result)})")
        for r in result:
            print(f"    {r['user']} → {r['role']}")

        print("\n  Full path: (Tenant)-[:HAS_USER]->(User)-[:HAS_ROLE]->(Role)")
        result = run_cypher("""
            MATCH (t:Tenant)-[:HAS_USER]->(u:User)-[:HAS_ROLE]->(r:Role)
            RETURN t.name AS tenant, u.email AS user, r.code AS role
            ORDER BY t.name
        """)
        check(len(result) == 2, f"2 full paths (got {len(result)})")
        for r in result:
            print(f"    {r['tenant']} → {r['user']} → {r['role']}")

    close_driver()


asyncio.run(run_tests())

print(f"\n{'='*60}")
if failed == 0:
    print(f"  ALL {passed} ASSERTIONS PASSED  ✓")
    print(f"")
    print(f"  Infrastructure:")
    print(f"    Postgres:    localhost:5433 (Docker)")
    print(f"    Service Bus: zeroque-servicebus.servicebus.windows.net")
    print(f"    Neo4j:       zeroque-neo4j.uksouth.azurecontainer.io:7687")
    print(f"    Functions:   zeroque-functions.azurewebsites.net")
else:
    print(f"  PASSED: {passed}  FAILED: {failed}")
print(f"{'='*60}")

sys.exit(1 if failed > 0 else 0)
