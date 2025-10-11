from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from .base_repository import BaseRepository
from ..utils.custom_exceptions import DuplicateError
from ..models import TenantV2

logger = logging.getLogger(__name__)

# ============================================================================
# TENANT REPOSITORY
# ============================================================================

class TenantRepository(BaseRepository):
    """Repository for Tenant operations"""

    def __init__(self):
        super().__init__(TenantV2)

    def get_tenant_by_id(self, db: Session, tenant_id):
        """Get tenant by ID"""
        return db.query(TenantV2).filter(TenantV2.tenant_id == tenant_id).one_or_none()

    def get_by_name(self, db: Session, name: str) -> Optional[TenantV2]:
        """Get tenant by name"""
        try:
            return db.query(TenantV2).filter(TenantV2.name == name).first()
        except Exception as e:
            logger.error(f"Error getting tenant by name {name}: {e}")
            return None

    def get_by_type(self, db: Session, tenant_type: str, limit: int = 100) -> List[TenantV2]:
        """Get tenants by type"""
        try:
            return db.query(TenantV2).filter(TenantV2.type == tenant_type).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting tenants by type {tenant_type}: {e}")
            return []

    def create_tenant(self, db: Session, tenant_id, name: str, tenant_type: str = "customer",
                      scenario_id: Optional[str] = None) -> TenantV2:
        """Create tenant with validation"""
        # Check if name already exists
        existing = self.get_by_name(db, name)
        if existing:
            raise DuplicateError(f"Tenant with name '{name}' already exists")

        return self.create(
            db,
            tenant_id=tenant_id,
            name=name,
            type=tenant_type,
            scenario_id=scenario_id
        )

    def check_relationship(self, db: Session, parent_tenant_id, child_tenant_id, relationship) -> Optional[List]:
        """Check if a link between store and vendor exists"""
        existing = db.execute(text("""
                                   SELECT id
                                   FROM tenant_links_new
                                   WHERE parent_tenant_id = :p
                                     AND child_tenant_id = :c
                                     AND relationship = :r
                                   """), {"p": parent_tenant_id, "c": child_tenant_id,
                                          "r": relationship}).first()
        return existing if existing else None

    def create_relationship(self, db: Session, parent_tenant_id, child_tenant_id, relationship) -> str:
        """Create link between parent and child tenant"""
        link_id = str(uuid4())
        try:
            db.execute(text("""
                            INSERT INTO tenant_links_new(id, parent_tenant_id, child_tenant_id, relationship)
                            VALUES (:id, :p, :c, :r)
                            """), {"id": link_id, "p": parent_tenant_id,
                                   "c": child_tenant_id, "r": relationship})
            db.commit()
            return link_id
        except Exception as e:
            logger.error(f"Error creating link between parent tenant {parent_tenant_id} and child tenant {child_tenant_id}: {e}")
            db.rollback()
            raise e
