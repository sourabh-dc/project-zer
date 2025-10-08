from typing import Optional, List

from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from services.provisioning.models import VendorV2
from services.provisioning.repositories.base_repository import BaseRepository
from services.provisioning.repositories.tenant_repository import TenantRepository
from services.provisioning.utils.custom_exceptions import ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# VENDOR REPOSITORY
# ============================================================================

class VendorRepository(BaseRepository):
    """Repository for Vendor operations"""

    def __init__(self):
        super().__init__(VendorV2)

    def get_by_tenant(self, db: Session, tenant_id: str) -> List[VendorV2]:
        """Get vendors by tenant ID"""
        try:
            return db.query(VendorV2).filter(VendorV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting vendors by tenant {tenant_id}: {e}")
            return []

    def create_vendor(self, db: Session, tenant_id: str, name: str, description: Optional[str] = None,
                      rating: Optional[float] = None) -> VendorV2:
        """Create vendor with tenant validation"""
        # Validate tenant exists
        tenant_repo = TenantRepository()
        if not tenant_repo.get_by_id(db, tenant_id):
            raise ValidationError(f"Tenant {tenant_id} not found")

        return self.create(
            db,
            vendor_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            rating=rating
        )