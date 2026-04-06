"""
onboarding_service.routes
--------------------------
Tenant onboarding API.

Flow:
  1. Admin calls POST /onboarding/tenant-signup
  2. Azure AD group created (tenant isolation) + Azure AD user created
  3. Tenant + User records created in Postgres
  4. tenant_admin role assigned with full permissions
  5. Events emitted: tenant.created → topic "tenant", user.created → topic "user"
  6. Admin logs in via /auth/login → gets JWT → can access the platform
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth_service.config import AUTH_MODE
from onboarding_service.models import Tenant
from onboarding_service.schemas import TenantSignupRequest
from onboarding_service.worker import provision_admin

logger = logging.getLogger("onboarding_service.routes")

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

_session_factory = None


def set_session_factory(factory):
    global _session_factory
    _session_factory = factory


def get_db():
    if _session_factory is None:
        raise RuntimeError("Database session factory not configured")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _emit(db, tenant_id, event_type, payload):
    """Emit event into the outbox — topic derived from event_type prefix."""
    try:
        from event_service.emitter import emit
        emit(db, tenant_id, event_type, payload)
    except Exception as exc:
        logger.warning(f"Event emission skipped ({event_type}): {exc}")


@router.post("/tenant-signup", status_code=201)
async def create_tenant(req: TenantSignupRequest, db: Session = Depends(get_db)):
    """Full tenant onboarding:
    1. Create Azure AD Group (tenant) + Azure AD User (admin)
    2. Create Tenant + User records in Postgres
    3. Assign tenant_admin role with all permissions
    4. Emit tenant.created and user.created events to outbox
    """
    existing = db.query(Tenant).filter(Tenant.email == req.email).first()
    if existing:
        raise HTTPException(409, "Tenant email already exists")

    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt

        org = await mgmt.create_organization(
            req.tenant_name, req.tenant_name,
            metadata={"industry": req.industry} if req.industry else None,
        )
        temp_password = f"Zq!{uuid.uuid4().hex[:12]}"
        ad_user = await mgmt.create_user(
            req.admin_email, temp_password,
            f"{req.admin_firstname} {req.admin_lastname}",
        )
        await mgmt.add_member(org["id"], ad_user["id"])

        org_id = org["id"]
        azure_ad_user_id = ad_user["id"]
        initial_password = temp_password
    else:
        from auth_service import local_store as store

        org = store.create_organization(req.tenant_name, req.tenant_name)
        temp_password = f"Zq!{uuid.uuid4().hex[:12]}"
        ad_user = store.create_user(
            req.admin_email, temp_password,
            f"{req.admin_firstname} {req.admin_lastname}",
        )
        store.add_member(org["id"], ad_user["user_id"], ["org_admin"])

        org_id = org["id"]
        azure_ad_user_id = ad_user["user_id"]
        initial_password = temp_password

    tenant_id = uuid.uuid4()
    tenant = Tenant(
        tenant_id=tenant_id,
        org_id=org_id,
        tenant_name=req.tenant_name,
        tenant_type=req.type,
        email=req.email,
        registration_number=req.registration_number,
        phone=req.phone,
        billing_email=req.billing_email,
        default_currency=req.default_currency,
        timezone=req.timezone,
        locale=req.locale,
        industry=req.industry,
        primary_domain=req.primary_domain,
    )
    db.add(tenant)
    db.flush()

    _emit(db, str(tenant_id), "tenant.created", {
        "tenant_id": str(tenant_id),
        "org_id": org_id,
        "tenant_name": req.tenant_name,
        "type": req.type,
        "email": req.email,
        "admin_email": req.admin_email,
    })

    admin_result = provision_admin(
        db,
        tenant_id=str(tenant_id),
        admin_email=req.admin_email,
        admin_firstname=req.admin_firstname,
        admin_lastname=req.admin_lastname,
        auth0_user_id=azure_ad_user_id,
        emit_fn=_emit,
    )

    return {
        "tenant_id": str(tenant_id),
        "org_id": org_id,
        "admin_user_id": admin_result["user_id"],
        "azure_ad_user_id": azure_ad_user_id,
        "admin_email": req.admin_email,
        "role": admin_result["role_code"],
        "permissions": admin_result["permissions"],
        "status": "provisioned",
    }


@router.get("/health")
def health():
    return {"status": "ok", "service": "onboarding_service"}
