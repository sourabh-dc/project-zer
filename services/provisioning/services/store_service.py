import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException

from services.provisioning.core.recording_service import record_provisioning_metric
from ..repositories.site_repository import SiteRepository
from ..repositories.store_repository import StoreRepository

import logging

logger = logging.getLogger(__name__)

class StoreService:
    def __init__(self):
        self.repo = StoreRepository()
        self.site_repo = SiteRepository()

    async def upsert_store_v2(self, store_id: str, payload, site_id: str, db: Session):
        # Convert string IDs to UUIDs if needed
        try:
            store_uuid = uuid.UUID(store_id)
        except ValueError:
            store_uuid = uuid.uuid4()

        try:
            site_uuid = uuid.UUID(site_id)
        except ValueError:
            site_uuid = uuid.uuid4()

        # Validate site exists
        if not self.site_repo.get_site_by_id(db, site_uuid):
            record_provisioning_metric("create_store", "site_not_found", site_id)
            raise HTTPException(status_code=400, detail="Site not found")

        store = self.repo.get_by_id(db, store_uuid)
        if store:
            store = self.repo.update_store(db, store, payload.name, payload.store_type, payload.geo)
            logger.info("store_updated", extra={"store_id": str(store_uuid)})
            return {"store_id": str(store.store_id), "name": store.name, "store_type": store.store_type, "geo": store.geo, "updated": True}
        store = self.repo.create_store(db, store_id, site_id, payload.name, payload.store_type, payload.geo)
        logger.info("store_created", extra={"store_id": str(store_uuid)})
        return {"store_id": str(store.store_id), "name": store.name, "store_type": store.store_type, "geo": store.geo, "created": True}

    async def upsert_site_store_v2(self, payload, db: Session):
        """Link a Site to a Store (V2 architecture)."""
        # Validate site and store exist
        if not self.site_repo.get_by_id(db, payload.site_id):
            raise HTTPException(status_code=400, detail="Site not found")
        if not self.repo.get_by_id(db, payload.store_id):
            raise HTTPException(status_code=400, detail="Store not found")

        # Check if link already exists
        existing = self.repo.get_link(db, payload.site_id, payload.store_id)
        if existing:
            logger.info("site_store_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        # Create new link
        link_id = self.repo.create_link(db, payload.site_id, payload.store_id)
        logger.info("site_store_created", extra={"id": link_id})
        return {"id": link_id, "created": True}