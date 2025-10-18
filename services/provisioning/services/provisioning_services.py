import uuid
from typing import Dict

from fastapi import HTTPException
import time

from prometheus_client import Counter, Histogram
from sqlalchemy.orm import Session

from services.provisioning.repositories.site_saga import SiteSaga
from services.provisioning.repositories.store_saga import StoreSaga
from services.provisioning.repositories.tenant_saga import TenantSaga
from services.provisioning.repositories.user_saga import UserSaga
from services.provisioning.schemas import TenantRequest, SiteRequest, StoreRequest, UserRequest

req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])

async def create_tenant(req: TenantRequest, db: Session):
    start = time.time()
    try:
        req_total.labels(op="create_tenant", status="start").inc()
        saga = TenantSaga(db)
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