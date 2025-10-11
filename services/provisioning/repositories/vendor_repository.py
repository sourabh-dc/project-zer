from datetime import datetime
from typing import Optional, List

from sqlalchemy import text
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

    def get_by_id(self, db: Session, vendor_id) -> Optional[VendorV2]:
        """Get a vendor by its ID"""
        try:
            return db.query(VendorV2).filter(VendorV2.vendor_id == vendor_id).one_or_none()
        except Exception as e:
            logger.error(f"Error getting vendor by id {vendor_id}: {e}")
            return None

    def get_by_tenant(self, db: Session, tenant_id: str) -> List[VendorV2]:
        """Get vendors by tenant ID"""
        try:
            return db.query(VendorV2).filter(VendorV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting vendors by tenant {tenant_id}: {e}")
            return []

    def create_vendor(self, db: Session, vendor_id:str, tenant_id: str, name: str, description: Optional[str] = None,
                      rating: Optional[float] = None) -> VendorV2:
        """Create vendor with tenant validation"""
        # Validate tenant exists
        tenant_repo = TenantRepository()
        if not tenant_repo.get_by_id(db, tenant_id):
            raise ValidationError(f"Tenant {tenant_id} not found")

        return self.create(
            db,
            vendor_id=vendor_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            rating=rating
        )

    def update_vendor(self, db: Session, vendor, tenant_id: Optional[str] = None, name: Optional[str] = None,
                      description: Optional[str] = None, rating: Optional[float] = None) -> Optional[VendorV2]:
        """Update vendor fields by vendor_id"""
        if tenant_id is not None:
            vendor.tenant_id = tenant_id
        if name is not None:
            vendor.name = name
        if description is not None:
            vendor.description = description
        if rating is not None:
            vendor.rating = rating
        vendor.updated_at = datetime.utcnow()
        db.commit()
        return vendor

    def check_link(self, db: Session, store_id: str, vendor_id: str):
        """Check if a link between store and vendor exists"""
        try:
            link = db.execute(text("""
                                   SELECT id
                                   FROM store_vendors
                                   WHERE store_id = :s
                                     AND vendor_id = :v
                                   """), {"s": store_id, "v": vendor_id}).first()
            return link if link else False
        except Exception as e:
            logger.error(f"Error checking link between store {store_id} and vendor {vendor_id}: {e}")
            return False

    def create_link(self, db: Session, store_id: str, vendor_id: str) -> str:
        """Create a link between a store and a vendor"""
        link_id = str(uuid4())
        try:
            db.execute(text("""
                            INSERT INTO store_vendors (id, store_id, vendor_id)
                            VALUES (:id, :s, :v)
                            """), {"id": link_id, "s": store_id, "v": vendor_id})
            db.commit()
            return link_id
        except Exception as e:
            logger.error(f"Error creating link between store {store_id} and vendor {vendor_id}: {e}")
            db.rollback()
            raise ValidationError("Failed to create store-vendor link")