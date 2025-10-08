from typing import Optional, List, Dict
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

    def create_store(self, db: Session, site_id: str, name: str, store_type: str = "cashierless",
                     geo: Optional[Dict] = None) -> StoreV2:
        """Create store with site validation"""
        # Validate site exists
        site_repo = SiteRepository()
        if not site_repo.get_by_id(db, site_id):
            raise ValidationError(f"Site {site_id} not found")

        return self.create(
            db,
            store_id=str(uuid4()),
            site_id=site_id,
            name=name,
            store_type=store_type,
            geo=geo
        )