import uuid
from typing import Dict
from fastapi import HTTPException
import time
from sqlalchemy.orm import Session

from services.provisioning.repositories.bulk_user_saga import BulkUserSaga
from services.provisioning.repositories.site_saga import SiteSaga
from services.provisioning.repositories.store_saga import StoreSaga
from services.provisioning.repositories.tenant_saga import TenantSaga
from services.provisioning.repositories.user_saga import UserSaga
from services.provisioning.schemas import TenantRequest, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, \
    RoleRequest, VendorRequest, CostCentreRequest
from services.provisioning.utils.user_auth import check_permission
from ..repositories.cost_centre_saga import CostCentreSaga
from ..repositories.role_saga import RoleSaga
from ..repositories.vendor_saga import VendorSaga
from ..utils.provisioning_logger import logger
from ..utils.metrics import req_total, req_duration


async def create_tenant(req: TenantRequest, db: Session):
    start = time.time()
    try:
        req_total.labels(op="create_tenant", status="start").inc()
        saga = TenantSaga(db)
        print(27)
        res = await saga.exec(req)
        req_total.labels(op="create_tenant", status="ok").inc()
        req_duration.labels(op="create_tenant").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_tenant", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_tenant", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_tenants(db: Session):
    try:
        return TenantSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def create_site(site_id: str, req: SiteRequest, tenant_id: str, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_site", status="start").inc()
        saga = SiteSaga(db)
        res = await saga.exec(uuid.UUID(site_id), uuid.UUID(tenant_id), req, uctx)
        req_total.labels(op="create_site", status="ok").inc()
        req_duration.labels(op="create_site").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_site", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_site", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_sites(db: Session):
    try:
        return SiteSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def create_store(store_id: str, req: StoreRequest, site_id: str, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_store", status="start").inc()
        saga = StoreSaga(db)
        res = await saga.exec(uuid.UUID(store_id), uuid.UUID(site_id), req, uctx)
        req_total.labels(op="create_store", status="ok").inc()
        req_duration.labels(op="create_store").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_store", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_store", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_stores(db: Session):
    try:
        return StoreSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def create_user(user_id: str, req: UserRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_user", status="start").inc()
        saga = UserSaga(db)
        res = await saga.exec(uuid.UUID(user_id), req, uctx)
        req_total.labels(op="create_user", status="ok").inc()
        req_duration.labels(op="create_user").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_user", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_user", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_users(db: Session):
    try:
        return UserSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def bulk_import_users(req: BulkUserRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="bulk_import_users", status="start").inc()

        # Check entitlement for bulk user import feature
        check_permission(uctx, "provisioning.bulk_import")

        saga = BulkUserSaga(db)
        res = await saga.exec(
            tenant_id=req.tenant_id,
            users_data=req.users,
            uctx=uctx,
            auto_generate_api_keys=req.auto_generate_api_keys
        )
        req_total.labels(op="bulk_import_users", status="ok").inc()
        req_duration.labels(op="bulk_import_users").observe(time.time() - start)

        logger.info(f"Bulk user import completed: {res['success_count']}/{res['total_requested']} succeeded")
        return res

    except ValueError as e:
        req_total.labels(op="bulk_import_users", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="bulk_import_users", status="fail").inc()
        logger.error(f"Bulk user import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def create_role(role_id: str, req: RoleRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_role", status="start").inc()
        saga = RoleSaga(db)
        res = await saga.exec(uuid.UUID(role_id), req, uctx)
        req_total.labels(op="create_role", status="ok").inc()
        req_duration.labels(op="create_role").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_role", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_role", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_roles(db: Session):
    try:
        return RoleSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def create_vendor(vendor_id: str, req: VendorRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_vendor", status="start").inc()
        saga = VendorSaga(db)
        res = await saga.exec(uuid.UUID(vendor_id), req, uctx)
        req_total.labels(op="create_vendor", status="ok").inc()
        req_duration.labels(op="create_vendor").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_vendor", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_vendor", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_vendors(db: Session):
    try:
        return VendorSaga(db).getall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def create_cc(req: CostCentreRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        req_total.labels(op="create_cost_centre", status="start").inc()
        saga = CostCentreSaga(db)
        res = await saga.exec(req, uctx)
        req_total.labels(op="create_cost_centre", status="ok").inc()
        req_duration.labels(op="create_cost_centre").observe(time.time() - start)
        return res
    except ValueError as e:
        req_total.labels(op="create_cost_centre", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        req_total.labels(op="create_cost_centre", status="fail").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def get_cc(db: Session, tenant_id: str = None):
    try:
        return CostCentreSaga(db).getall(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))