#!/usr/bin/env python3
"""
tests/test_onboarding.py
-------------------------
E2E test suite for the onboarding service.
Runs against real Docker Postgres (docker compose up -d postgres).

Tests with AUTH_MODE=local (no Azure AD required).
When Azure AD consent is granted, switch to AUTH_MODE=azure_ad to test full flow.

Usage:
    docker compose up -d postgres
    python3 -m shared.init_db
    AUTH_MODE=local python3 tests/test_onboarding.py
"""
import sys
import os
import asyncio
import uuid

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

# ── Build test app with both routers ─────────────────────────────────

test_app = FastAPI(title="Test App")
test_app.include_router(onboarding_router)
test_app.include_router(auth_router)

# ── Setup ─────────────────────────────────────────────────────────────

def setup():
    OnboardingBase.metadata.drop_all(engine)
    SharedBase.metadata.drop_all(engine)
    SharedBase.metadata.create_all(engine)
    OnboardingBase.metadata.create_all(engine)
    set_session_factory(SessionFactory)
    local_store.reset_store()

setup()

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


async def run_tests():
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # ── 1. Health ─────────────────────────────────────────────
        print("\n[1] Health check")
        r = await client.get("/onboarding/health")
        check(r.status_code == 200, "Health endpoint returns 200")

        # ── 2. Tenant signup ──────────────────────────────────────
        print("\n[2] Tenant signup — Acme Corp")
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
        data = r.json()
        check("tenant_id" in data, "Response has tenant_id")
        check("org_id" in data, "Response has org_id")
        check("azure_ad_user_id" in data, "Response has azure_ad_user_id")
        check(data["admin_email"] == "admin@acmecorp.com", "Admin email correct")
        check(data["role"] == "tenant_admin", "Admin role = tenant_admin")
        check(len(data["permissions"]) == 8, f"8 permissions assigned (got {len(data['permissions'])})")
        check(data["status"] == "provisioned", "Status = provisioned")

        acme_tenant_id = data["tenant_id"]
        acme_org_id = data["org_id"]

        # ── 3. Verify DB records ──────────────────────────────────
        print("\n[3] Verify database records")
        with get_session() as db:
            t = db.execute(
                text("SELECT tenant_name, org_id, status, industry FROM tenants WHERE tenant_id = :tid"),
                {"tid": uuid.UUID(acme_tenant_id)},
            ).fetchone()
            check(t is not None, "Tenant exists in DB")
            check(t.tenant_name == "Acme Corp", "Tenant name = Acme Corp")
            check(t.org_id == acme_org_id, "org_id linked correctly")
            check(t.industry == "technology", "Industry = technology")

            u = db.execute(
                text("SELECT email, first_name, last_name, auth0_user_id, status FROM users WHERE tenant_id = :tid"),
                {"tid": uuid.UUID(acme_tenant_id)},
            ).fetchone()
            check(u is not None, "User exists in DB")
            check(u.email == "admin@acmecorp.com", "User email correct")
            check(u.first_name == "John", "First name = John")
            check(u.auth0_user_id is not None, "Azure AD user_id linked")
            check(u.status == "active", "User status = active")

            role = db.execute(text("SELECT code FROM roles WHERE code = 'tenant_admin'")).fetchone()
            check(role is not None, "tenant_admin role exists")

            perms = db.execute(text("SELECT COUNT(*) as c FROM permissions")).fetchone()
            check(perms.c == 8, f"8 permissions created (got {perms.c})")

            rp = db.execute(text("SELECT COUNT(*) as c FROM role_permissions")).fetchone()
            check(rp.c == 8, f"8 role-permission mappings (got {rp.c})")

            ur = db.execute(
                text("SELECT COUNT(*) as c FROM user_roles WHERE tenant_id = :tid"),
                {"tid": uuid.UUID(acme_tenant_id)},
            ).fetchone()
            check(ur.c == 1, "UserRole assignment exists")

        # ── 4. Verify outbox events ──────────────────────────────
        print("\n[4] Verify outbox events")
        with get_session() as db:
            events = db.execute(
                text("SELECT event_type, status, topic FROM outbox_events ORDER BY created_at"),
            ).fetchall()
            check(len(events) >= 2, f"At least 2 events in outbox (got {len(events)})")

            types = [e.event_type for e in events]
            check("tenant.created" in types, "tenant.created event exists")
            check("user.created" in types, "user.created event exists")

            for e in events:
                check(e.status == "pending", f"Event '{e.event_type}' status = pending")

            topic_map = {e.event_type: e.topic for e in events}
            check(topic_map.get("tenant.created") == "tenant", "tenant.created → topic 'tenant'")
            check(topic_map.get("user.created") == "user", "user.created → topic 'user'")

        # ── 5. Duplicate signup → 409 ────────────────────────────
        print("\n[5] Duplicate tenant email → 409")
        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "Another Corp",
            "type": "customer",
            "email": "info@acmecorp.com",
            "admin_email": "admin2@acmecorp.com",
            "admin_firstname": "Jane",
            "admin_lastname": "Doe",
        })
        check(r.status_code == 409, f"Duplicate email returns 409 (got {r.status_code})")

        # ── 6. Publisher picks up events ─────────────────────────
        print("\n[6] Publisher processes pending events")
        from event_service.publisher import publish_pending_events
        from event_service.transport import LocalTransport

        local_transport = LocalTransport()
        local_transport._get_queue("tenant", "test-sub")
        local_transport._get_queue("user", "test-sub")

        with get_session() as db:
            count = await publish_pending_events(db, local_transport, 100)
            check(count >= 2, f"Published {count} events")

        with get_session() as db:
            events = db.execute(
                text("SELECT event_type, status, published_at FROM outbox_events"),
            ).fetchall()
            all_published = all(e.status == "published" for e in events)
            check(all_published, "All events marked as 'published'")
            all_have_timestamp = all(e.published_at is not None for e in events)
            check(all_have_timestamp, "All events have published_at timestamp")

        # ── 7. Admin login → JWT → /auth/me ──────────────────────
        print("\n[7] Admin login → JWT → /auth/me")
        admin_email = "admin@acmecorp.com"
        test_password = "TestPass123!"

        import bcrypt
        user_data = local_store._users.get(f"email:{admin_email}")
        check(user_data is not None, "Admin user exists in auth local_store")
        if user_data:
            user_data["password_hash"] = bcrypt.hashpw(
                test_password.encode(), bcrypt.gensalt(10)
            ).decode()

        r = await client.post("/auth/login", json={
            "email": admin_email,
            "password": test_password,
            "org_id": acme_org_id,
        })
        check(r.status_code == 200, f"Login returns 200 (got {r.status_code})")
        token_data = r.json()
        check("access_token" in token_data, "JWT received")

        token = token_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = await client.get("/auth/me", headers=headers)
        check(r.status_code == 200, f"/auth/me returns 200 (got {r.status_code})")
        me = r.json()
        check(me["email"] == admin_email, "Token decodes to correct email")
        check(me["org_id"] == acme_org_id, "Token has correct org_id")
        check("org_admin" in me["roles"], "Token has org_admin role")

        # ── 8. Second tenant — isolation ──────────────────────────
        print("\n[8] Second tenant — Globex Corp (tenant isolation)")
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
        globex_data = r.json()
        globex_tenant_id = globex_data["tenant_id"]
        globex_org_id = globex_data["org_id"]
        check(globex_tenant_id != acme_tenant_id, "Different tenant_id from Acme")
        check(globex_org_id != acme_org_id, "Different org_id from Acme")

        with get_session() as db:
            tenant_count = db.execute(text("SELECT COUNT(*) as c FROM tenants")).fetchone()
            check(tenant_count.c == 2, f"2 tenants in DB (got {tenant_count.c})")

            user_count = db.execute(text("SELECT COUNT(*) as c FROM users")).fetchone()
            check(user_count.c == 2, f"2 users in DB (got {user_count.c})")

            event_count = db.execute(text("SELECT COUNT(*) as c FROM outbox_events")).fetchone()
            check(event_count.c == 4, f"4 events total (got {event_count.c})")

        # Globex admin login
        eve_email = "eve@globex.com"
        eve_user = local_store._users.get(f"email:{eve_email}")
        if eve_user:
            eve_user["password_hash"] = bcrypt.hashpw(
                test_password.encode(), bcrypt.gensalt(10)
            ).decode()

        r = await client.post("/auth/login", json={
            "email": eve_email,
            "password": test_password,
            "org_id": globex_org_id,
        })
        check(r.status_code == 200, "Eve login returns 200")
        eve_token = r.json()["access_token"]

        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {eve_token}"})
        check(r.status_code == 200, "Eve /auth/me returns 200")
        eve_me = r.json()
        check(eve_me["org_id"] == globex_org_id, "Eve's org_id = Globex")
        check(eve_me["org_id"] != acme_org_id, "Eve's org_id ≠ Acme (tenant isolation)")

        # ── 9. Service Bus publisher (real Azure Service Bus) ─────
        print("\n[9] Publisher → Azure Service Bus (pending Globex events)")
        from shared.config import SERVICE_BUS_CONNECTION
        if SERVICE_BUS_CONNECTION:
            from event_service.transport import create_transport
            sb_transport = create_transport("servicebus")
            with get_session() as db:
                count = await publish_pending_events(db, sb_transport, 100)
                check(count >= 2, f"Published {count} events to Azure Service Bus")
            await sb_transport.close()

            with get_session() as db:
                pending = db.execute(
                    text("SELECT COUNT(*) as c FROM outbox_events WHERE status = 'pending'"),
                ).fetchone()
                check(pending.c == 0, f"0 pending events remain (got {pending.c})")
        else:
            print("  (skipped — SERVICE_BUS_CONNECTION not set)")

        # ── 10. Validation tests ──────────────────────────────────
        print("\n[10] Validation — bad requests")
        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "X",
            "type": "customer",
            "email": "x@x.com",
            "admin_email": "a@a.com",
            "admin_firstname": "A",
            "admin_lastname": "B",
        })
        check(r.status_code == 422, f"Short tenant_name → 422 (got {r.status_code})")

        r = await client.post("/onboarding/tenant-signup", json={
            "tenant_name": "Valid Name",
            "type": "invalid_type",
            "email": "test@test.com",
            "admin_email": "admin@test.com",
            "admin_firstname": "A",
            "admin_lastname": "B",
        })
        check(r.status_code == 422, f"Invalid type → 422 (got {r.status_code})")

        # ── 11. Unauthenticated access → 401 ─────────────────────
        print("\n[11] Unauthenticated access → 401")
        r = await client.get("/auth/me")
        check(r.status_code == 401, f"/auth/me without token → 401 (got {r.status_code})")

        r = await client.get("/auth/org/members")
        check(r.status_code == 401, f"/auth/org/members without token → 401 (got {r.status_code})")

        # ── 12. Forgot password endpoint ──────────────────────────
        print("\n[12] Forgot password")
        r = await client.post("/auth/forgot-password", json={"email": "admin@acmecorp.com"})
        check(r.status_code == 200, "Forgot password returns 200")
        check("ok" in r.json().get("status", ""), "Status = ok")


asyncio.run(run_tests())

print(f"\n{'='*60}")
if failed == 0:
    print(f"  ALL {passed} ASSERTIONS PASSED")
else:
    print(f"  PASSED: {passed}  FAILED: {failed}")
print(f"{'='*60}")

sys.exit(1 if failed > 0 else 0)
