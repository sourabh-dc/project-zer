"""
Sites API — site CRUD + site↔tenant links.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, Site, Store, SiteTenant
from provisioning_service.Schemas import UserContext, SiteRequest, SiteUpdateRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage
from provisioning_service.core.helpers.resource_loaders import site_quota_resource
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total

router = APIRouter(prefix="/provisioning", tags=["Sites"])


@router.post("/sites", status_code=201)
async def create_site(
        req: SiteRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("sites.manage")),
        policy=Depends(require_policy("site.create", resource_loader=site_quota_resource)),
):
    """Create a new site and associate it with a tenant"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create a site (no tenant_id here)

        site = Site(
            site_id=uuid.uuid4(),
            name=req.name,
            site_type=req.type,
            active=bool(getattr(req, "active", True)),
            currency=getattr(req, "currency", None),
            timezone=getattr(req, "timezone", None),
            language=getattr(req, "language", None),
            phone=getattr(req, "phone", None),
            fax=getattr(req, "fax", None),
            email=getattr(req, "email", None),
            url=getattr(req, "url", None),
            logo_url=getattr(req, "logo_url", None),
            primary_billing_address=getattr(req, "primary_billing_address", None),
            primary_shipping_address=getattr(req, "primary_shipping_address", None),
            shipping_addresses=getattr(req, "shipping_addresses", None),
            geo=getattr(req, "geo", None),
            external_id=getattr(req, "external_id", None),
            is_headquarter=bool(getattr(req, "is_headquarter", False))
        )

        db.add(site)
        db.flush()  # Get site_id

        # Create a site-tenant relationship
        site_tenant = SiteTenant(
            id=uuid.uuid4(),
            site_id=site.site_id,
            tenant_id=uuid.UUID(req.tenant_id)
        )
        db.add(site_tenant)
        db.commit()
        db.refresh(site)

        # Record feature usage
        record_feature_usage(db, req.tenant_id, "multi.site", count=1)

        logger.info(f"Created site: {site.site_id} ({site.name}) for tenant: {req.tenant_id}")

        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "created_at": site.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_site", status="error").inc()
        raise
    except IntegrityError as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"Site creation IntegrityError: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid tenant reference: {str(e)}")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"Site creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/sites/{site_id}/tenants/{tenant_id}", status_code=201)
async def add_tenant_to_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    user = Depends(check_user_authorization('tenant.admin')),
    policy=Depends(require_policy("site.assign_tenant", resource_from="none")),
):
    """Allow a site to be managed by an additional tenant"""
    try:
        # Verify site exists
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Check if the association already exists
        existing = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if existing:
            raise HTTPException(status_code=409, detail="Site is already associated with this tenant")

        # Create association
        site_tenant = SiteTenant(
            id=uuid.uuid4(),
            site_id=uuid.UUID(site_id),
            tenant_id=uuid.UUID(tenant_id)
        )
        db.add(site_tenant)
        db.commit()

        logger.info(f"✅ Added tenant {tenant_id} to site {site_id}")

        return {
            "site_id": site_id,
            "tenant_id": tenant_id,
            "associated": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Add tenant to site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/sites/{site_id}/tenants")
async def list_site_tenants(
    site_id: str,
    db: Session = Depends(get_db),
    user = Depends(check_user_authorization('tenant.admin'))):
    """List all tenants associated with a site"""
    try:
        # Verify site exists and is accessible by the user's tenant
        site_access = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == user["tenant_id"]
        ).first()

        if not site_access:
            raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")

        # Get all tenants for the site
        tenants = db.query(Tenant).join(
            SiteTenant, Tenant.tenant_id == SiteTenant.tenant_id
        ).filter(
            SiteTenant.site_id == uuid.UUID(site_id)
        ).all()

        return {
            "site_id": site_id,
            "tenants": [
                {
                    "tenant_id": str(t.tenant_id),
                    "name": t.tenant_name,
                    "type": t.tenant_type,
                    "created_at": t.created_at.isoformat()
                }
                for t in tenants
            ],
            "total": len(tenants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List site tenants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/sites/{site_id}/tenants/{tenant_id}", status_code=204)
async def remove_tenant_from_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("site.remove_tenant", resource_from="none")),
):
    """Remove a tenant from a site"""
    try:
        # Find the association
        site_tenant = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not site_tenant:
            raise HTTPException(status_code=404, detail="Site-tenant association not found")

        # Prevent removing the last tenant
        tenant_count = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id)
        ).count()

        if tenant_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the only tenant from a site")

        db.delete(site_tenant)
        db.commit()

        logger.info(f"✅ Removed tenant {tenant_id} from site {site_id}")

        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID or tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Remove tenant from site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/sites")
async def list_sites(
        tenant_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin'))
):
    """List sites with optional tenant filtering"""
    try:
        # Start with SiteTenant join to support many-to-many
        q = db.query(Site).join(SiteTenant, Site.site_id == SiteTenant.site_id)

        # If tenant_id provided, filter by it; otherwise filter by user's tenant
        # ctx can be a dict from check_user_authorization; support both
        ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
        if tenant_id:
            q = q.filter(SiteTenant.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(SiteTenant.tenant_id == ctx_tenant)

        total = q.count()
        sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "sites": [
                {
                    "site_id": str(s.site_id),
                    "name": s.name,
                    "site_type": s.site_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in sites
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List sites failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sites/{site_id}")
async def get_site(site_id: str, db: Session = Depends(get_db)):
    """Get a single site by ID"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "active": site.active,
            "currency": site.currency,
            "timezone": site.timezone,
            "language": site.language,
            "phone": site.phone,
            "fax": site.fax,
            "email": site.email,
            "url": site.url,
            "logo_url": site.logo_url,
            "primary_billing_address": site.primary_billing_address,
            "primary_shipping_address": site.primary_shipping_address,
            "geo": site.geo,
            "external_id": site.external_id,
            "is_headquarter": site.is_headquarter,
            "created_at": site.created_at.isoformat(),
            "updated_at": site.updated_at.isoformat() if site.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/sites/{site_id}")
async def update_site(
    site_id: str,
    req: SiteUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("sites.manage")),
    policy=Depends(require_policy("site.update")),
):
    """Update an existing site"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        # Map schema field → model field
        field_map = {"site_type": "site_type"}
        for key, value in update_data.items():
            model_key = field_map.get(key, key)
            setattr(site, model_key, value)

        site.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(site)

        # Outbox audit event
        try:
            _st = db.query(SiteTenant).filter(SiteTenant.site_id == site.site_id).first()
            _tid = _st.tenant_id if _st else uuid.uuid4()
            create_outbox_event(
                db, _tid, "site.updated",
                {"site_id": str(site.site_id), "name": site.name, "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for site.updated: {_oe}")

        logger.info(f"✅ Updated site: {site.site_id}")
        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "active": site.active,
            "updated_at": site.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/sites/{site_id}", status_code=204)
async def delete_site(
    site_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("sites.manage")),
    policy=Depends(require_policy("site.delete", resource_from="none")),
):
    """Soft-delete a site (deactivate it)"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        # Check if stores are still linked
        store_count = db.query(Store).filter(Store.site_id == site.site_id, Store.active == True).count()
        if store_count > 0:
            raise HTTPException(status_code=400, detail=f"Cannot delete site — {store_count} active store(s) still linked")

        site.active = False
        site.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            _st = db.query(SiteTenant).filter(SiteTenant.site_id == site.site_id).first()
            _tid = _st.tenant_id if _st else uuid.uuid4()
            create_outbox_event(db, _tid, "site.deleted", {"site_id": site_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for site.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted site: {site_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
