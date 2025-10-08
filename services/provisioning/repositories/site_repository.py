from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from services.provisioning.models import SiteV2
from services.provisioning.repositories.base_repository import BaseRepository
from services.provisioning.repositories.tenant_repository import TenantRepository
from services.provisioning.utils.custom_exceptions import ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# SITE REPOSITORY
# ============================================================================

class SiteRepository(BaseRepository):
    """Repository for Site operations"""

    def __init__(self):
        super().__init__(SiteV2)

    def get_by_tenant(self, db: Session, tenant_id: str) -> List[SiteV2]:
        """Get sites by tenant ID"""
        try:
            return db.query(SiteV2).filter(SiteV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting sites by tenant {tenant_id}: {e}")
            return []

    def create_site(self, db: Session, tenant_id: str, name: str, site_type: str = "retail",
                    geo: Optional[Dict] = None) -> SiteV2:
        """Create site with tenant validation"""
        # Validate tenant exists
        tenant_repo = TenantRepository()
        if not tenant_repo.get_by_id(db, tenant_id):
            raise ValidationError(f"Tenant {tenant_id} not found")

        return self.create(
            db,
            site_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            site_type=site_type,
            geo=geo
        )