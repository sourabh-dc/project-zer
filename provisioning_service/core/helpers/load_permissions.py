"""
Seed roles, permissions, and role→permission mappings on startup.

Replaces the CSV-based approach with a single code-defined source of truth
aligned to the ZeroQue Roles, Access and Approval v1.1 document.
"""
import uuid
from typing import List, Tuple

from provisioning_service.Models import Permission, Role, RolePermission, JobFunction
from provisioning_service.core.db_config import SessionLocal

# ═══════════════════════════════════════════════════════════════════
# Job function catalogue (12 categories)
# ═══════════════════════════════════════════════════════════════════
JOB_FUNCTIONS: List[Tuple[str, str, int]] = [
    ("procurement", "Procurement", 1),
    ("finance", "Finance", 2),
    ("engineering_maintenance", "Engineering and Maintenance", 3),
    ("warehouse_stores", "Warehouse and Stores", 4),
    ("operations_production", "Operations and Production", 5),
    ("quality_compliance", "Quality and Compliance", 6),
    ("health_safety", "Health and Safety", 7),
    ("facilities", "Facilities", 8),
    ("human_resources", "Human Resources", 9),
    ("it", "IT", 10),
    ("senior_management", "Senior Management", 11),
    ("other_custom", "Other / Custom", 12),
]

# ═══════════════════════════════════════════════════════════════════
# Master permission catalogue (42 permissions)
# ═══════════════════════════════════════════════════════════════════
ALL_PERMISSIONS: List[Tuple[str, str]] = [
    # ── Tenants & users ──────────────────────────────────────────
    ("tenants.create", "Create and manage tenants"),
    ("users.manage", "Invite and manage users"),
    ("users.password.reset", "Reset user passwords"),
    ("roles.assign", "Assign and remove roles for users"),
    # ── Sites & stores ───────────────────────────────────────────
    ("sites.manage", "Manage sites for a tenant"),
    ("stores.manage", "Manage stores for a site"),
    ("vendors.manage", "Manage vendors for a tenant"),
    # ── Organisational ───────────────────────────────────────────
    ("org_units.manage", "Manage organizational units"),
    ("org_units.assign", "Assign users to organizational units"),
    ("cost_centres.manage", "Manage cost centres"),
    # ── Catalog ──────────────────────────────────────────────────
    ("catalog.categories.manage", "Manage catalog categories"),
    ("catalog.products.manage", "Create and update catalog products"),
    ("catalog.products.view", "View catalog products"),
    ("catalog.variants.manage", "Manage catalog variants"),
    # ── Subscriptions & entitlements ─────────────────────────────
    ("subscriptions.plans.manage", "Manage subscription plans"),
    ("subscriptions.plans.view", "View subscription plans"),
    ("subscriptions.features.manage", "Manage subscription features"),
    ("subscriptions.features.view", "View subscription features"),
    ("subscriptions.tenant.manage", "Manage tenant subscriptions"),
    ("subscriptions.tenant.view", "View tenant subscription status"),
    ("entitlements.check", "Check entitlements for tenants"),
    ("entitlements.usage.record", "Record entitlement usage"),
    ("entitlements.usage.view", "View entitlement usage summary"),
    ("entitlements.usage.manage", "Reset entitlement usage records"),
    # ── Approvals ────────────────────────────────────────────────
    ("approvals.chains.manage", "Manage approval chains and steps"),
    ("approvals.requests.create", "Create approval requests"),
    ("approvals.requests.view", "View approval requests"),
    ("approvals.requests.respond", "Respond to approval requests"),
    # ── Budgets ──────────────────────────────────────────────────
    ("budget.approve", "Approve budget requests"),
    ("costcentre.manage", "Manage cost centre budgets"),
    ("budgets.manage", "Manage budgets — allocate and configure approver limits"),
    ("budgets.manage.subordinates", "Allocate budget to direct reports only"),
    ("budgets.instant.request", "Request instant budget top-ups"),
    ("budgets.instant.approve", "Approve instant budget requests"),
    # ── Admin ────────────────────────────────────────────────────
    ("admin.permissions.manage", "Manage permission catalog"),
    ("admin.roles.manage", "Manage roles and assignments"),
    ("admin.scopes.manage", "Manage role scopes"),
    # ── Audit & governance ───────────────────────────────────────
    ("audit.view", "View audit history"),
    ("audit.export", "Export authorised audit evidence"),
    ("sod.configure", "Configure Segregation of Duties rules"),
    ("delegation.create", "Create delegated authority"),
    ("delegation.manage", "Manage delegated authority records"),
    ("delegation.view", "View delegation records"),
]

# ═══════════════════════════════════════════════════════════════════
# Master role catalogue (12 roles) with preset permission codes
# ═══════════════════════════════════════════════════════════════════
ROLES: List[Tuple[str, str, List[str]]] = [
    # ── General ──────────────────────────────────────────────────
    ("tenant_admin", "Super admin for tenant — full control", [
        "*",  # wildcard — tenant_admin gets everything
    ]),
    ("administrator", "Administrator — user, org, commercial & technical admin", [
        "users.manage", "users.password.reset", "roles.assign",
        "sites.manage", "stores.manage", "vendors.manage",
        "org_units.manage", "org_units.assign", "cost_centres.manage",
        "catalog.categories.manage", "catalog.products.manage",
        "subscriptions.tenant.view", "entitlements.check", "entitlements.usage.view",
        "approvals.chains.manage", "budgets.manage",
        "audit.view", "audit.export", "sod.configure",
        "delegation.create", "delegation.manage", "delegation.view",
    ]),
    ("site_manager", "Site Manager — operational oversight for assigned sites", [
        "sites.manage", "stores.manage",
        "users.manage", "roles.assign",
        "org_units.manage", "org_units.assign",
        "catalog.products.view",
        "approvals.requests.view", "approvals.requests.respond",
        "budgets.manage.subordinates", "costcentre.manage",
        "audit.view",
    ]),
    ("requester", "Requester — create and manage own purchase requests", [
        "catalog.products.view",
        "approvals.requests.create", "approvals.requests.view",
    ]),
    ("approver", "Approver — review and respond to requests in assigned scope", [
        "catalog.products.view",
        "approvals.requests.view", "approvals.requests.respond",
    ]),
    ("auditor", "Auditor — read-only compliance and audit access", [
        "catalog.products.view",
        "approvals.requests.view",
        "subscriptions.tenant.view", "entitlements.usage.view",
        "audit.view", "audit.export",
    ]),
    # ── Procurement ──────────────────────────────────────────────
    ("procurement_manager", "Procurement Manager — configure, govern & approve procurement", [
        "catalog.categories.manage", "catalog.products.manage", "catalog.variants.manage",
        "catalog.products.view",
        "approvals.requests.create", "approvals.requests.view", "approvals.requests.respond",
        "approvals.chains.manage",
        "budget.approve", "budgets.manage.subordinates",
        "vendors.manage",
        "audit.view",
    ]),
    ("procurement_user", "Procurement User — day-to-day procurement activity", [
        "catalog.products.view",
        "approvals.requests.create", "approvals.requests.view",
    ]),
    # ── Warehouse ────────────────────────────────────────────────
    ("warehouse_user", "Warehouse User — goods-in and receipting", [
        "catalog.products.view",
        "approvals.requests.view",
    ]),
    # ── Finance ──────────────────────────────────────────────────
    ("finance_manager", "Finance Manager — budgets, cost centres & financial reporting", [
        "budgets.manage", "budgets.manage.subordinates", "budget.approve",
        "budgets.instant.request", "budgets.instant.approve",
        "costcentre.manage", "cost_centres.manage",
        "approvals.requests.view", "approvals.requests.respond",
        "catalog.products.view",
        "subscriptions.tenant.view", "entitlements.check", "entitlements.usage.view",
        "audit.view", "audit.export",
    ]),
    ("finance_user", "Finance User — view budgets, spend & financial reports", [
        "catalog.products.view",
        "approvals.requests.view",
        "subscriptions.tenant.view", "entitlements.usage.view",
    ]),
    # ── Human Resources ──────────────────────────────────────────
    ("hr_manager", "HR Manager — manage HR-related procurement & user access", [
        "users.manage", "roles.assign",
        "org_units.manage", "org_units.assign",
        "catalog.products.view",
        "approvals.requests.create", "approvals.requests.view",
        "budgets.manage.subordinates",
        "audit.view",
    ]),
    ("hr_user", "HR User — day-to-day HR procurement activity", [
        "catalog.products.view",
        "approvals.requests.create", "approvals.requests.view",
    ]),
]


# ═══════════════════════════════════════════════════════════════════
# Seeding functions
# ═══════════════════════════════════════════════════════════════════

def _seed_permissions(session):
    """Insert any permissions from ALL_PERMISSIONS that don't yet exist."""
    existing = {p.code for p in session.query(Permission).all()}
    added = 0
    for code, desc in ALL_PERMISSIONS:
        if code not in existing:
            session.add(Permission(permission_id=uuid.uuid4(), code=code, description=desc))
            existing.add(code)
            added += 1
    if added:
        session.flush()
        print(f"  ✅ Seeded {added} new permissions ({len(existing)} total)")


def _seed_roles(session):
    """Insert any roles from ROLES that don't yet exist."""
    existing = {r.code for r in session.query(Role).all()}
    added = 0
    for code, desc, _ in ROLES:
        if code not in existing:
            session.add(Role(role_id=uuid.uuid4(), code=code, description=desc))
            existing.add(code)
            added += 1
    if added:
        session.flush()
        print(f"  ✅ Seeded {added} new roles ({len(existing)} total)")


def _seed_role_permissions(session):
    """Ensure every role→permission mapping from ROLES exists.

    Skips the ``*`` wildcard — tenant_admin's wildcard is granted at
    JWT-issue time in auth_routes.py, not stored as a DB permission row.
    """
    existing_pairs = {
        (rp.role_code, rp.permission_code)
        for rp in session.query(RolePermission).all()
    }
    added = 0
    for role_code, _, perm_codes in ROLES:
        for perm_code in perm_codes:
            if perm_code == "*":
                continue  # wildcard handled in auth, not in DB
            if (role_code, perm_code) not in existing_pairs:
                session.add(RolePermission(role_code=role_code, permission_code=perm_code))
                existing_pairs.add((role_code, perm_code))
                added += 1
    if added:
        session.flush()
        print(f"  ✅ Seeded {added} new role→permission mappings")


def seed_roles_and_permissions():
    """Master seed: permissions → roles → role_permissions. Idempotent."""
    session = SessionLocal()
    try:
        _seed_permissions(session)
        _seed_roles(session)
        _seed_role_permissions(session)
        session.commit()
        print("✅ All roles and permissions seeded successfully.")
    except Exception as e:
        session.rollback()
        print(f"❌ Error seeding roles/permissions: {e}")
        raise
    finally:
        session.close()


def seed_job_functions():
    """Seed the 12 standard job functions. Idempotent."""
    session = SessionLocal()
    try:
        existing = {jf.code for jf in session.query(JobFunction).all()}
        added = 0
        for code, desc, sort in JOB_FUNCTIONS:
            if code not in existing:
                session.add(JobFunction(code=code, description=desc, sort_order=sort))
                existing.add(code)
                added += 1
        session.commit()
        if added:
            print(f"  ✅ Seeded {added} new job functions ({len(existing)} total)")
    except Exception as e:
        session.rollback()
        print(f"❌ Error seeding job functions: {e}")
        raise
    finally:
        session.close()
