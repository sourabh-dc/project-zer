from typing import Optional, List, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from services.provisioning.models import StoreV2
from services.provisioning.repositories.base_repository import BaseRepository
from services.provisioning.repositories.site_repository import SiteRepository
from services.provisioning.utils.custom_exceptions import ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# STORE REPOSITORY
# ============================================================================

class StoreRepository(BaseRepository):
    """Repository for Store operations"""

    def __init__(self):
        super().__init__(StoreV2)

    def get_by_site(self, db: Session, site_id: str) -> List[StoreV2]:
        """Get stores by site ID"""
        try:
            return db.query(StoreV2).filter(StoreV2.site_id == site_id).all()
        except Exception as e:
            logger.error(f"Error getting stores by site {site_id}: {e}")
            return []

    def create_store(self, db: Session, store_id:str, site_id: str, name: str, store_type: str = "cashierless",
                     geo: Optional[Dict] = None) -> StoreV2:
        """Create store with site validation"""
        # Validate site exists
        site_repo = SiteRepository()
        if not site_repo.get_by_id(db, site_id):
            raise ValidationError(f"Site {site_id} not found")

        return self.create(
            db,
            store_id=store_id,
            site_id=site_id,
            name=name,
            store_type=store_type,
            geo=geo
        )

    def get_by_id(self, db: Session, store_id) -> Optional[StoreV2]:
        """Get a store by its ID"""
        try:
            return db.query(StoreV2).filter(StoreV2.store_id == store_id).one_or_none()
        except Exception as e:
            logger.error(f"Error getting store by id {store_id}: {e}")
            return None

    def update_store(self, db: Session, store, name: Optional[str] = None, store_type: Optional[str] = None, geo: Optional[Dict] = None) -> Optional[StoreV2]:
        """Update store fields by store_id"""
        if name is not None:
            store.name = name
        if store_type is not None:
            store.store_type = store_type
        if geo is not None:
            store.geo = geo
        try:
            db.commit()
            db.refresh(store)
            return store
        except Exception as e:
            logger.error(f"Error updating store {store.id}: {e}")
            db.rollback()
            return None

    def get_link(self, db: Session, site_id: str, store_id: str) -> Optional[str]:
        """Get link ID between site and store if exists"""
        try:
            result = db.execute(text("""
                                       SELECT id
                                       FROM site_stores
                                       WHERE site_id = :s
                                         AND store_id = :st
                                       """), {"s": site_id, "st": store_id}).first()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting link between site {site_id} and store {store_id}: {e}")
            return None

    def create_link(self, db: Session, site_id: str, store_id: str) -> str:
        """Create link between site and store"""
        link_id = str(uuid4())
        try:
            db.execute(text("""
                            INSERT INTO site_stores(id, site_id, store_id)
                            VALUES (:id, :s, :st)
                            """), {"id": link_id, "s": site_id, "st": store_id})
            db.commit()
            return link_id
        except Exception as e:
            logger.error(f"Error creating link between site {site_id} and store {store_id}: {e}")
            db.rollback()
            raise ValidationError("Failed to create link between site and store")
