"""
Roles & Responsibilities API — Phase 2

Exposes the 12-role catalogue and the responsibility → permission mapping
so the frontend can render the 6-step user setup journey:
    Person → Role → Responsibilities → Scope → Controls → Confirmation

All responsibility labels use business language — customers never see
permission codes like ``approvals.requests.respond``.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.core.db_config import get_db
from provisioning_service.core.helpers.load_permissions import ROLES
from provisioning_service.Models import Role, JobFunction, Site, CostCentre, OrgUnit

router = APIRouter(prefix="/roles", tags=["roles"])

# ═══════════════════════════════════════════════════════════════════
# Response models
# ═══════════════════════════════════════════════════════════════════


class RoleItem(BaseModel):
    """A single role in the catalogue."""
    code: str
    description: str
    category: str  # General | Procurement | Warehouse | Finance | Human Resources


class RoleListResponse(BaseModel):
    roles: List[RoleItem] = Field(default_factory=list)


class ResponsibilityItem(BaseModel):
    """One responsibility tick-box in business language."""
    label: str                          # e.g. "Approve or reject requests"
    group: str                          # e.g. "Requests and purchasing"
    permission_code: str                # underlying code e.g. "approvals.requests.respond"
    preselected: bool = False           # whether this role preselects it
    requires_controls: bool = False     # whether this responsibility needs limits/controls


class ResponsibilityGroup(BaseModel):
    """A group of related responsibilities."""
    group_name: str                     # e.g. "Requests and purchasing"
    sort_order: int = 0
    items: List[ResponsibilityItem] = Field(default_factory=list)


class RoleResponsibilitiesResponse(BaseModel):
    role_code: str
    role_description: str
    groups: List[ResponsibilityGroup] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Master responsibility catalogue (business language)
#
# Each entry maps a permission_code → (group, label, requires_controls)
# Groups are displayed in the order they appear.
# ═══════════════════════════════════════════════════════════════════

_RESPONSIBILITY_CATALOGUE: dict[str, tuple[str, str, bool]] = {
    # ── Requests and purchasing ───────────────────────────────────
    "approvals.requests.create":    ("Requests and purchasing", "Request products", False),
    "approvals.requests.view":      ("Requests and purchasing", "View requests within assigned scope", False),
    "approvals.requests.respond":   ("Requests and purchasing", "Approve or reject requests", True),
    # ── Products and suppliers ────────────────────────────────────
    "catalog.products.view":        ("Products and suppliers", "View product catalogues", False),
    "catalog.products.manage":      ("Products and suppliers", "Create and update products", False),
    "catalog.categories.manage":    ("Products and suppliers", "Manage product categories", False),
    "catalog.variants.manage":      ("Products and suppliers", "Manage product variants", False),
    "vendors.manage":               ("Products and suppliers", "Create and manage suppliers", False),
    # ── Goods receiving ───────────────────────────────────────────
    # (permissions not yet in catalogue — placeholder for future)
    # ── Finance and budgets ───────────────────────────────────────
    "budgets.manage":               ("Finance and budgets", "Manage budgets and cost centres", False),
    "budgets.manage.subordinates":  ("Finance and budgets", "Allocate budget to team members", False),
    "budget.approve":               ("Finance and budgets", "Approve budget requests", True),
    "budgets.instant.request":      ("Finance and budgets", "Request instant budget top-ups", False),
    "budgets.instant.approve":      ("Finance and budgets", "Approve instant budget requests", True),
    "costcentre.manage":            ("Finance and budgets", "Manage cost centre budgets", False),
    "cost_centres.manage":          ("Finance and budgets", "Create and edit cost centres", False),
    # ── Approvals & governance ────────────────────────────────────
    "approvals.chains.manage":      ("Approvals and governance", "Configure approval chains", False),
    "sod.configure":                ("Approvals and governance", "Configure Segregation of Duties rules", False),
    "delegation.create":            ("Approvals and governance", "Create delegated authority", False),
    "delegation.manage":            ("Approvals and governance", "Manage delegation records", False),
    "delegation.view":              ("Approvals and governance", "View delegation records", False),
    # ── Users and administration ──────────────────────────────────
    "users.manage":                 ("Users and administration", "Invite and manage users", False),
    "users.password.reset":         ("Users and administration", "Reset user passwords", False),
    "roles.assign":                 ("Users and administration", "Assign and remove roles for users", False),
    "sites.manage":                 ("Users and administration", "Manage sites", False),
    "stores.manage":                ("Users and administration", "Manage stores", False),
    "org_units.manage":             ("Users and administration", "Manage organisational units", False),
    "org_units.assign":             ("Users and administration", "Assign users to departments", False),
    "tenants.create":               ("Users and administration", "Create and manage tenants", False),
    # ── Subscriptions ─────────────────────────────────────────────
    "subscriptions.plans.manage":   ("Subscriptions and billing", "Manage subscription plans", False),
    "subscriptions.plans.view":     ("Subscriptions and billing", "View subscription plans", False),
    "subscriptions.features.manage":("Subscriptions and billing", "Manage subscription features", False),
    "subscriptions.features.view":  ("Subscriptions and billing", "View subscription features", False),
    "subscriptions.tenant.manage":  ("Subscriptions and billing", "Manage tenant subscriptions", False),
    "subscriptions.tenant.view":    ("Subscriptions and billing", "View tenant subscription status", False),
    "entitlements.check":           ("Subscriptions and billing", "Check entitlements for tenants", False),
    "entitlements.usage.record":    ("Subscriptions and billing", "Record entitlement usage", False),
    "entitlements.usage.view":      ("Subscriptions and billing", "View entitlement usage summary", False),
    "entitlements.usage.manage":    ("Subscriptions and billing", "Manage entitlement usage records", False),
    # ── Audit & reporting ─────────────────────────────────────────
    "audit.view":                   ("Audit and reporting", "View audit history", False),
    "audit.export":                 ("Audit and reporting", "Export authorised audit evidence", False),
    # ── Administration (sensitive) ────────────────────────────────
    "admin.permissions.manage":     ("Administration", "Manage permission catalogue", False),
    "admin.roles.manage":           ("Administration", "Manage roles and assignments", False),
    "admin.scopes.manage":          ("Administration", "Manage role scopes", False),
}

# Group display order
_GROUP_ORDER = [
    "Requests and purchasing",
    "Products and suppliers",
    "Goods receiving",
    "Finance and budgets",
    "Approvals and governance",
    "Users and administration",
    "Subscriptions and billing",
    "Audit and reporting",
    "Administration",
]


def _role_category(code: str) -> str:
    """Map a role code to its display category."""
    general = {"administrator", "site_manager", "requester", "approver", "auditor"}
    if code in general:
        return "General"
    if code.startswith("procurement"):
        return "Procurement"
    if code.startswith("warehouse"):
        return "Warehouse"
    if code.startswith("finance"):
        return "Finance"
    if code.startswith("hr"):
        return "Human Resources"
    return "Other"


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════


@router.get("", response_model=RoleListResponse)
async def list_roles(db: Session = Depends(get_db)):
    """
    Return the 12 standard ZeroQue roles with categories.

    Used by the frontend Step 2 (Role selection) to render the role picker.
    """
    db_roles = {r.code: r for r in db.query(Role).all()}

    items: List[RoleItem] = []
    for code, desc, _ in ROLES:
        # Use DB description if available (overrides code-defined), else fall back
        display_desc = db_roles[code].description if code in db_roles else desc
        items.append(RoleItem(
            code=code,
            description=display_desc,
            category=_role_category(code),
        ))

    return RoleListResponse(roles=items)


@router.get("/{role_code}/responsibilities", response_model=RoleResponsibilitiesResponse)
async def get_role_responsibilities(role_code: str):
    """
    Return business-language responsibilities for a role, grouped by category.

    Each responsibility is marked as preselected if the role's default
    permissions include it, and whether it needs additional controls (e.g.
    approval limits).

    Used by the frontend Step 3 (Responsibilities) to render tick-boxes.
    """
    # Find the role in the master catalogue
    role_def = None
    for code, desc, perms in ROLES:
        if code == role_code:
            role_def = (code, desc, perms)
            break

    if role_def is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_code}' not found")

    _, role_desc, preset_perms = role_def
    preset_set = set(preset_perms)

    # Build groups
    groups_map: dict[str, List[ResponsibilityItem]] = {}
    for perm_code, (group, label, needs_controls) in _RESPONSIBILITY_CATALOGUE.items():
        if group not in groups_map:
            groups_map[group] = []
        groups_map[group].append(ResponsibilityItem(
            label=label,
            group=group,
            permission_code=perm_code,
            preselected=perm_code in preset_set or "*" in preset_set,
            requires_controls=needs_controls,
        ))

    # Order groups by _GROUP_ORDER, then alphabetically for any not listed
    ordered: List[ResponsibilityGroup] = []
    for gname in _GROUP_ORDER:
        if gname in groups_map:
            ordered.append(ResponsibilityGroup(
                group_name=gname,
                sort_order=_GROUP_ORDER.index(gname),
                items=groups_map.pop(gname),
            ))
    # Any remaining groups (future additions)
    for gname, items in sorted(groups_map.items()):
        ordered.append(ResponsibilityGroup(
            group_name=gname,
            sort_order=len(ordered),
            items=items,
        ))

    return RoleResponsibilitiesResponse(
        role_code=role_code,
        role_description=role_desc,
        groups=ordered,
    )


# ═══════════════════════════════════════════════════════════════════
# Job Functions
# ═══════════════════════════════════════════════════════════════════


class JobFunctionItem(BaseModel):
    code: str
    description: str


class JobFunctionListResponse(BaseModel):
    job_functions: List[JobFunctionItem] = Field(default_factory=list)


@router.get("/job-functions", response_model=JobFunctionListResponse)
async def list_job_functions(db: Session = Depends(get_db)):
    """Return the 12 standard job functions (Procurement, Finance, etc.)."""
    items = [
        JobFunctionItem(code=jf.code, description=jf.description)
        for jf in db.query(JobFunction)
        .filter(JobFunction.is_active == True)
        .order_by(JobFunction.sort_order)
        .all()
    ]
    return JobFunctionListResponse(job_functions=items)


# ═══════════════════════════════════════════════════════════════════
# Scopes — available scope targets for user setup
# ═══════════════════════════════════════════════════════════════════


class ScopeOption(BaseModel):
    scope_type: str         # organisation | site | cost_centre | department
    scope_id: str           # UUID of the target (or "all" for organisation)
    label: str              # display name
    parent_label: Optional[str] = None  # e.g. site name for a cost centre


class ScopeListResponse(BaseModel):
    scopes: List[ScopeOption] = Field(default_factory=list)


@router.get("/scopes", response_model=ScopeListResponse)
async def list_scopes(
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
):
    """
    Return all available scope targets for a tenant.

    Used by the frontend Step 4 (Scope selection) to populate dropdowns.
    Returns organisation, sites, cost centres, and departments.
    """
    scopes: List[ScopeOption] = []

    # ── Organisation (always available) ───────────────────────────
    scopes.append(ScopeOption(
        scope_type="organisation",
        scope_id="all",
        label="Entire organisation",
    ))

    # ── Sites ─────────────────────────────────────────────────────
    sites = db.query(Site).filter(
        Site.active == True,
    ).all()
    for s in sites:
        scopes.append(ScopeOption(
            scope_type="site",
            scope_id=str(s.site_id),
            label=s.name,
        ))

    # ── Cost Centres ──────────────────────────────────────────────
    cost_centres = db.query(CostCentre).filter(
        CostCentre.tenant_id == tenant_id,
        CostCentre.is_active == True,
    ).all()
    for cc in cost_centres:
        scopes.append(ScopeOption(
            scope_type="cost_centre",
            scope_id=str(cc.cost_centre_id),
            label=f"{cc.name} ({cc.code})",
        ))

    # ── Departments / Org Units ───────────────────────────────────
    org_units = db.query(OrgUnit).filter(
        OrgUnit.tenant_id == tenant_id,
        OrgUnit.status == "active",
    ).order_by(OrgUnit.name).all()
    for ou in org_units:
        scopes.append(ScopeOption(
            scope_type="department",
            scope_id=str(ou.org_unit_id),
            label=ou.name,
        ))

    return ScopeListResponse(scopes=scopes)
